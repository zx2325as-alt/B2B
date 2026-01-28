import os
import shutil
import logging
import uuid
import json
import numpy as np
import scipy.io.wavfile as wavfile
import scipy.signal
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from app.core.config import settings
from app.services.audio_service import audio_service
from app.services.voice_profile import VoiceProfileService

logger = logging.getLogger(__name__)

# Lazy import for noisereduce
try:
    import noisereduce as nr
    HAS_NR = True
except ImportError:
    HAS_NR = False
    logger.warning("noisereduce not installed. Denoising will be skipped.")

# Lazy import for pyannote.audio
try:
    import torch
    import torchaudio
    from pyannote.audio import Pipeline
    HAS_PYANNOTE = True
    
    # Suppress warnings
    import warnings
    warnings.filterwarnings("ignore", module="torchaudio")
    warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
    
    # Fix for torchaudio backend warning on Windows
    if os.name == 'nt':
        try:
            torchaudio.set_audio_backend("soundfile")
        except:
            pass
            
except ImportError:
    HAS_PYANNOTE = False
    logger.warning("pyannote.audio not installed. Diarization will fallback to simple VAD+Clustering.")

class AdvancedAudioService:
    """
    Advanced Audio Service implementing the Multi-task Audio Recognition Optimization Scheme.
    1. Preprocessing (Denoise, Normalize)
    2. Speaker Diarization (Pyannote / Clustering)
    3. Transcription & Alignment
    """

    def __init__(self):
        self.audio_service = audio_service
        self.voice_profile_service = VoiceProfileService()
        self.temp_dir = settings.DATA_DIR / "temp_advanced_processing"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self._pyannote_pipeline = None

    def _load_pyannote_pipeline(self):
        if not HAS_PYANNOTE:
            return None
        
        if self._pyannote_pipeline is None:
            try:
                logger.info("Loading Pyannote Diarization Pipeline...")
                
                # Check for local offline model
                local_config = settings.PYANNOTE_CONFIG_PATH
                
                if local_config.exists():
                    logger.info(f"Loading local model from: {local_config}")
                    self._pyannote_pipeline = Pipeline.from_pretrained(str(local_config))
                else:
                    logger.info("Local model config not found. Attempting to download/load from HuggingFace...")
                    # Use HF Token if available, or try local/cache
                    use_auth_token = os.environ.get("HF_TOKEN") or True 
                    self._pyannote_pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=use_auth_token
                    )
                
                if self._pyannote_pipeline and torch.cuda.is_available():
                    self._pyannote_pipeline.to(torch.device("cuda"))
                
                logger.info("Pyannote Pipeline loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load Pyannote Pipeline: {e}")
                self._pyannote_pipeline = None
        
        return self._pyannote_pipeline

    def preprocess_audio(self, input_path: str) -> str:
        """
        Step 1: Audio Preprocessing
        - Denoise (noisereduce)
        - Normalize
        Returns path to processed wav file.
        """
        logger.info(f"Preprocessing audio: {input_path}")
        try:
            # Load audio
            rate, data = wavfile.read(input_path)
            
            # Convert to float32
            if data.dtype != np.float32:
                data = data.astype(np.float32) / 32768.0 if data.dtype == np.int16 else data.astype(np.float32)

            # 1. Denoise
            if HAS_NR:
                # Assume noise is stationary? Or use non-stationary?
                # Stationary is faster and safer for general background noise.
                logger.info("Applying Noisereduce...")
                data = nr.reduce_noise(y=data, sr=rate, stationary=True)
            
            # 2. Bandpass Filter (80-7000Hz)
            nyquist = 0.5 * rate
            low = 80 / nyquist
            high = min(7000, rate/2 - 1) / nyquist
            b, a = scipy.signal.butter(4, [low, high], btype='band')
            if len(data.shape) > 1: # Stereo
                 data = np.array([scipy.signal.lfilter(b, a, ch) for ch in data.T]).T
            else:
                 data = scipy.signal.lfilter(b, a, data)

            # 3. Normalize
            max_val = np.max(np.abs(data))
            if max_val > 0:
                data = data / max_val * 0.95
            
            # Save processed file
            processed_filename = f"processed_{uuid.uuid4()}.wav"
            output_path = self.temp_dir / processed_filename
            
            # Convert back to int16
            data_int16 = (data * 32767).astype(np.int16)
            wavfile.write(output_path, rate, data_int16)
            
            logger.info(f"Preprocessing complete: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Preprocessing failed: {e}")
            return input_path # Fallback to original

    def diarize_audio(self, audio_path: str, num_speakers: int = None) -> List[Dict]:
        """
        Step 2: Speaker Diarization
        Returns list of segments: [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
        """
        pipeline = self._load_pyannote_pipeline()
        
        if pipeline:
            try:
                logger.info("Running Pyannote Diarization...")
                # Apply pipeline
                diarization = pipeline(audio_path, num_speakers=num_speakers)
                
                segments = []
                for turn, _, speaker in diarization.itertracks(yield_label=True):
                    segments.append({
                        "start": turn.start,
                        "end": turn.end,
                        "speaker": speaker
                    })
                return segments
            except Exception as e:
                logger.error(f"Pyannote diarization failed: {e}. Falling back to simple VAD.")
        
        # Fallback: Use AudioService's simple VAD + Diarization (reusing existing logic but simulating segments)
        # Actually, AudioService.transcribe_with_diarization does everything (STT+Diarization).
        # But here we want Diarization ONLY first?
        # No, simpler to just use the existing method if Pyannote is missing.
        return []

    def process_full_pipeline(self, input_path: str, character_names: List[str] = None) -> Dict:
        """
        Run the full optimization scheme:
        1. Preprocess
        2. Diarize
        3. Transcribe & Align
        """
        import time
        import librosa
        
        start_time = time.time()
        
        # 1. Preprocess
        clean_audio_path = self.preprocess_audio(input_path)
        
        # Get duration
        try:
            duration = librosa.get_duration(path=clean_audio_path)
        except:
            duration = 0.0
            
        # 2. Diarize
        segments = self.diarize_audio(clean_audio_path)
        
        # 3. Transcribe & Align
        # If we have segments from Pyannote, we transcribe each segment
        final_segments = []
        full_text_parts = []
        detected_speakers = set()
        
        if segments:
            logger.info(f"Pyannote found {len(segments)} segments. Transcribing...")
            # Load Whisper model once
            model = self.audio_service._load_stt_model()
            
            rate, data = wavfile.read(clean_audio_path)
            
            for seg in segments:
                start_sample = int(seg["start"] * rate)
                end_sample = int(seg["end"] * rate)
                
                if end_sample - start_sample < rate * 0.5: # Skip < 0.5s
                    continue
                    
                chunk_data = data[start_sample:end_sample]
                
                # Save temp chunk
                chunk_path = self.temp_dir / f"chunk_{uuid.uuid4()}.wav"
                wavfile.write(chunk_path, rate, chunk_data)
                
                # Transcribe
                text = ""
                try:
                    # Use faster-whisper
                    segments_gen, _ = model.transcribe(
                        str(chunk_path), 
                        beam_size=5, 
                        language="zh",
                        initial_prompt="以下是简体中文的对话。"
                    )
                    text = "".join([s.text for s in segments_gen]).strip()
                except Exception as e:
                    logger.error(f"Transcription failed for chunk: {e}")
                
                # Cleanup chunk
                try:
                    os.remove(chunk_path)
                except:
                    pass
                
                if text:
                    # Map Pyannote speaker to a persistent one?
                    # Pyannote returns SPEAKER_00, SPEAKER_01 for the FILE.
                    # We might want to match these to known profiles?
                    # Ideally, extract embedding for this segment and match.
                    # For now, just pass SPEAKER_XX as name.
                    
                    speaker_label = seg["speaker"]
                    
                    # TODO: Implement Matching against VoiceProfileService DB using embedding
                    # But Pyannote pipeline doesn't easily expose embedding per segment unless we run the embedding model separately.
                    # For now, just use the label.
                    
                    final_segments.append({
                        "start": seg["start"],
                        "end": seg["end"],
                        "speaker_id": speaker_label,
                        "speaker_name": speaker_label,
                        "text": text
                    })
                    full_text_parts.append(f"【{speaker_label}】: {text}")
                    detected_speakers.add((speaker_label, speaker_label))
        else:
            # Fallback to existing AudioService logic (Whisper Native Diarization / Simple VAD)
            logger.warning("Using fallback simple diarization pipeline.")
            result = self.audio_service.transcribe_with_diarization(clean_audio_path)
            if result:
                final_segments = result.get("raw_segments", [])
                return result # Return directly as it has the structure
        
        # Cleanup clean audio
        # os.remove(clean_audio_path) 
        
        return {
            "text": "\n".join(full_text_parts),
            "raw_segments": final_segments,
            "detected_speakers": [{"id": s[0], "name": s[1]} for s in list(detected_speakers)],
            "language": "zh",
            "duration": duration
        }
