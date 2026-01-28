import os
import time
import uuid
import json
import wave
import asyncio
import numpy as np
import scipy.signal
try:
    import webrtcvad
except ImportError:
    webrtcvad = None
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.sql_models import ConversationSegment, Character
from app.services.audio_service import AudioService
from app.services.voice_profile import VoiceProfileService
from app.services.extraction_service import ExtractionService
from app.utils.logger import logger

class RealtimeAudioService:
    def __init__(self):
        if webrtcvad is None:
            raise ImportError("Module 'webrtcvad' is required but not found. Please install it using 'pip install webrtcvad-wheels'.")
        self.vad = webrtcvad.Vad(3) # Increase to 3 (Very Aggressive) for better noise rejection in multi-speaker env
        self.audio_service = AudioService()
        self.voice_profile_service = VoiceProfileService()
        self.extraction_service = ExtractionService()
        # Removed internal executor in favor of loop.run_in_executor
        
        # Buffer state: session_id -> {buffer: bytearray, silence_frames: int, is_speech: bool}
        self.sessions = {}
        
        self.sample_rate = 16000
        self.frame_duration_ms = 30
        self.frame_size = int(self.sample_rate * self.frame_duration_ms / 1000 * 2) # 16bit = 2 bytes

    def _get_session_state(self, session_id: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "buffer": bytearray(),
                "speech_buffer": bytearray(),
                "silence_frames": 0,
                "is_speaking": False,
                "last_active": time.time()
            }
        return self.sessions[session_id]

    def _preprocess_audio(self, audio_data: bytes) -> bytes:
        """
        Apply Bandpass Filter and Normalization to raw PCM audio.
        Target: Human Voice (80Hz - 8000Hz).
        """
        try:
            # 1. Convert to numpy array (int16)
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            
            if len(audio_np) == 0:
                return audio_data

            # 2. Bandpass Filter (80Hz - 8000Hz)
            # Nyquist frequency = sample_rate / 2 = 8000Hz
            # So 8000Hz is high, we might set highcut slightly lower like 7000Hz or just Highpass > 80Hz
            nyquist = 0.5 * self.sample_rate
            low = 80 / nyquist
            high = 7000 / nyquist
            b, a = scipy.signal.butter(4, [low, high], btype='band')
            filtered_audio = scipy.signal.lfilter(b, a, audio_np)
            
            # 3. Normalization (Target -3dB or similar, but here we just maximize range without clipping)
            max_val = np.max(np.abs(filtered_audio))
            if max_val > 0:
                # Normalize to near int16 max (32767), with some headroom (0.9)
                target_max = 32767 * 0.9
                gain = target_max / max_val
                # Clamp gain to avoid amplifying noise too much (e.g. max 5x gain)
                gain = min(gain, 5.0) 
                normalized_audio = filtered_audio * gain
            else:
                normalized_audio = filtered_audio

            # 4. Convert back to int16
            processed_bytes = normalized_audio.astype(np.int16).tobytes()
            return processed_bytes
        except Exception as e:
            logger.error(f"Audio preprocessing error: {e}")
            return audio_data

    async def process_audio_stream(self, session_id: str, audio_chunk: bytes) -> Optional[bytes]:
        """
        Process incoming raw PCM 16-bit 16kHz mono chunk.
        Returns the audio segment bytes if a speech segment is completed, else None.
        """
        # Preprocess chunk (Filtering/Normalization)
        # Note: Filtering chunk-by-chunk can introduce artifacts at boundaries, 
        # but for VAD/STT it's often acceptable or we should maintain filter state.
        # For simplicity in this iteration, we process chunks directly.
        # Ideally, normalization should happen on the accumulated buffer, but we do it here for VAD.
        
        # processed_chunk = self._preprocess_audio(audio_chunk) 
        # CAUTION: Normalizing small chunks of silence amplifies noise!
        # BETTER STRATEGY: Only filter chunks, don't normalize until we have a speech segment.
        
        state = self._get_session_state(session_id)
        state["last_active"] = time.time()
        
        # Append to raw buffer
        state["buffer"].extend(audio_chunk)
        
        ready_segment = None
        
        # Process frames
        while len(state["buffer"]) >= self.frame_size:
            frame = state["buffer"][:self.frame_size]
            state["buffer"] = state["buffer"][self.frame_size:]
            
            is_speech = False
            try:
                is_speech = self.vad.is_speech(frame, self.sample_rate)
            except:
                pass
            
            if is_speech:
                if not state["is_speaking"]:
                    state["is_speaking"] = True
                    # logger.debug(f"[{session_id}] Speech started")
                state["silence_frames"] = 0
                state["speech_buffer"].extend(frame)
            else:
                if state["is_speaking"]:
                    state["speech_buffer"].extend(frame)
                    state["silence_frames"] += 1
                    
                    # Silence threshold: 500ms approx 16 frames
                    if state["silence_frames"] > 20: 
                        # Speech ended
                        segment_bytes = bytes(state["speech_buffer"])
                        
                        # Apply Preprocessing (Denoise/Normalize) to the FULL segment
                        # This is much safer than chunk-based normalization
                        processed_segment = self._preprocess_audio(segment_bytes)
                        
                        # Process if long enough (> 0.5s)
                        if len(processed_segment) > self.sample_rate * 0.5: # 0.5 sec
                             ready_segment = processed_segment
                        
                        # Reset
                        state["speech_buffer"] = bytearray()
                        state["is_speaking"] = False
                        state["silence_frames"] = 0
                        
                        # Return immediately if we found a segment (handle one at a time per chunk process)
                        # The loop might continue if there are more frames, but usually 1 chunk = few frames.
                        if ready_segment:
                            break
        
        return ready_segment

    async def process_segment_async(self, session_id: str, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Async wrapper for processing a complete speech segment.
        1. Save WAV (IO)
        2. STT (CPU/GPU)
        3. Deep Analyze (Async LLM)
        4. DB Save (IO)
        """
        loop = asyncio.get_running_loop()
        
        try:
            # 1. Save to temp WAV (Blocking I/O)
            temp_filename = f"{session_id}_{uuid.uuid4()}.wav"
            temp_path = self.audio_service.audio_dir / "realtime" / temp_filename
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            
            def save_wav():
                with wave.open(str(temp_path), 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(audio_bytes)
            
            await loop.run_in_executor(None, save_wav)
            
            # 2. STT & Diarization (Blocking CPU/GPU)
            # Use run_in_executor to avoid blocking the event loop
            stt_result = await loop.run_in_executor(
                None, 
                self.audio_service.transcribe_with_diarization, 
                str(temp_path)
            )
            
            if "error" in stt_result and stt_result["text"] == "":
                 logger.warning(f"STT failed: {stt_result['error']}")
                 return None

            raw_segments = stt_result.get("raw_segments", [])
            if not raw_segments:
                return None
            
            # 3. Emotion & Metrics (Blocking)
            emotion = await loop.run_in_executor(None, self.audio_service.detect_emotion, str(temp_path))
            metrics = await loop.run_in_executor(None, self.audio_service.extract_paralinguistic_features, str(temp_path))
            
            # 4. Process each segment
            db: Session = SessionLocal()
            saved_segments = []
            
            try:
                for seg in raw_segments:
                    speaker_id = seg["speaker_id"]
                    speaker_name = seg["speaker_name"]
                    text = seg["text"]
                    
                    # Resolve Character ID
                    character_id = None
                    if speaker_name != "Unknown":
                        char = db.query(Character).filter(Character.name == speaker_name).first()
                        if char:
                            character_id = char.id
                    
                    # 5. Deep Analysis (Async)
                    # Fetch minimal context (last 5 turns) for continuity
                    history_context = ""
                    last_segs = db.query(ConversationSegment).filter(
                        ConversationSegment.session_id == session_id
                    ).order_by(ConversationSegment.created_at.desc()).limit(5).all()
                    
                    if last_segs:
                        last_segs.reverse()
                        for s in last_segs:
                            history_context += f"{s.speaker_name}: {s.text}\n"
                    
                    analysis_result = await self.extraction_service.deep_analyze(
                        text=text,
                        character_names=[speaker_name] if speaker_name != "Unknown" else [],
                        history_context=history_context,
                        audio_features=metrics,
                        emotion_data=emotion,
                        speaker_info={"name": speaker_name, "id": speaker_id}
                    )
                    
                    analysis_data = analysis_result.get("structured_data", {})
                    markdown_report = analysis_result.get("markdown_report", "")
                    
                    # Save full analysis data including report if needed, 
                    # but here we store the JSON structured data in 'analysis' column
                    # and maybe the markdown in a separate place or inside JSON.
                    full_analysis_record = {
                        "structured": analysis_data,
                        "report": markdown_report
                    }

                    db_seg = ConversationSegment(
                        session_id=session_id,
                        text=text,
                        speaker_id=speaker_id,
                        speaker_name=speaker_name,
                        character_id=character_id,
                        emotion=emotion,
                        metrics=metrics,
                        analysis=full_analysis_record, # New Column
                        start_time=seg["start"],
                        end_time=seg["end"],
                        audio_path=str(temp_path) 
                    )
                    db.add(db_seg)
                    db.commit()
                    db.refresh(db_seg)
                    
                    saved_segments.append({
                        "id": db_seg.id,
                        "text": text,
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "emotion": emotion,
                        "analysis": full_analysis_record,
                        "timestamp": datetime.now().isoformat()
                    })
            finally:
                db.close()
            
            return {"segments": saved_segments}

        except Exception as e:
            logger.error(f"Error processing segment async: {e}")
            return None

    async def update_segment_speaker_and_reanalyze(self, segment_id: int, new_speaker_name: str):
        """
        Manually bind/update speaker -> Update DB -> Trigger Re-analysis.
        """
        db: Session = SessionLocal()
        try:
            seg = db.query(ConversationSegment).filter(ConversationSegment.id == segment_id).first()
            if not seg:
                return False, "Segment not found"
            
            old_speaker_id = seg.speaker_id
            
            # Update DB
            seg.speaker_name = new_speaker_name
            
            # Check if character exists
            char = db.query(Character).filter(Character.name == new_speaker_name).first()
            if char:
                seg.character_id = char.id
            else:
                seg.character_id = None
            
            # Update Voice Profile
            if old_speaker_id and "speaker_" in old_speaker_id:
                 self.voice_profile_service.update_speaker_name(old_speaker_id, new_speaker_name)
            
            # Trigger Re-analysis with new identity
            # Fetch context (previous 5 turns)
            history_context = ""
            try:
                # Get segments BEFORE the current one
                prev_segs = db.query(ConversationSegment).filter(
                    ConversationSegment.session_id == seg.session_id,
                    ConversationSegment.created_at < seg.created_at
                ).order_by(ConversationSegment.created_at.desc()).limit(5).all()
                
                if prev_segs:
                    prev_segs.reverse()
                    for s in prev_segs:
                        history_context += f"{s.speaker_name}: {s.text}\n"
            except Exception as ex:
                logger.warning(f"Failed to fetch context for re-analysis: {ex}")
            
            analysis_result = await self.extraction_service.deep_analyze(
                text=seg.text,
                character_names=[new_speaker_name],
                history_context=history_context,
                audio_features=seg.metrics,
                emotion_data=seg.emotion,
                speaker_info={"name": new_speaker_name, "id": seg.speaker_id}
            )
            
            full_analysis_record = {
                "structured": analysis_result.get("structured_data", {}),
                "report": analysis_result.get("markdown_report", "")
            }
            
            seg.analysis = full_analysis_record
            db.commit()
            
            return True, "Updated and Re-analyzed"
        except Exception as e:
            db.rollback()
            logger.error(f"Update speaker error: {e}")
            return False, str(e)
        finally:
            db.close()
