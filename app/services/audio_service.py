import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
from app.utils.logger import logger
from app.core.config import settings
from app.services.voice_profile import VoiceProfileService

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    logger.warning("faster-whisper not installed. STT will be disabled.")

try:
    import edge_tts
    import asyncio
    HAS_TTS = True
except ImportError:
    HAS_TTS = False
    logger.warning("edge-tts not installed. TTS will be disabled.")

try:
    from transformers import pipeline
    HAS_SER = True
except ImportError:
    HAS_SER = False
    logger.warning("transformers not installed. SER will be disabled.")

class AudioService:
    """
    Audio Service for Multi-modal Interaction.
    Supports:
    1. STT (Speech-to-Text): Using local faster-whisper.
    2. TTS (Text-to-Speech): Using edge-tts (online/free) or local fallback.
    3. SER (Speech Emotion Recognition): Using local transformers (wav2vec2).
    """
    
    def __init__(self):
        # Load config from settings
        self.model_size = settings.AUDIO_STT_MODEL_SIZE
        self.device = settings.AUDIO_STT_DEVICE
        self.compute_type = settings.AUDIO_STT_COMPUTE_TYPE
        
        self._stt_model = None
        self._ser_pipeline = None
        
        # Output dirs
        self.audio_dir = settings.DATA_DIR / "audio_cache"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Voice Profile Service
        self.voice_profile_service = VoiceProfileService()

        # Check ffmpeg availability
        import shutil
        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg not found in system PATH. Audio processing (pydub) may fail or fallback to defaults.")

    def _load_stt_model(self):
        if not HAS_WHISPER:
            logger.warning("Whisper STT not available.")
            return None
        
        if self._stt_model is None:
            # Map 'gpu' to 'cuda' for faster-whisper compatibility
            device = self.device
            if device.lower() == 'gpu':
                device = 'cuda'

            # Use local model path if available
            model_path_or_size = str(settings.AUDIO_STT_MODEL_PATH)
            if not settings.AUDIO_STT_MODEL_PATH.exists():
                 logger.warning(f"Local Whisper model not found at {model_path_or_size}, falling back to size '{self.model_size}' (will download)")
                 model_path_or_size = self.model_size

            try:
                logger.info(f"Loading Whisper model ({model_path_or_size}) on {device}...")
                self._stt_model = WhisperModel(
                    model_path_or_size, 
                    device=device, 
                    compute_type=self.compute_type
                )
                logger.info("Whisper model loaded successfully.")
            except Exception as e:
                logger.warning(f"Failed to load Whisper model on {device}: {e}")
                if device != 'cpu':
                    logger.info("Retrying with device='cpu'...")
                    try:
                        self._stt_model = WhisperModel(
                            model_path_or_size, 
                            device='cpu', 
                            compute_type="int8"  # Fallback to int8 for CPU
                        )
                        logger.info("Whisper model loaded successfully on CPU.")
                    except Exception as e_cpu:
                        logger.error(f"Failed to load Whisper model on CPU: {e_cpu}")
                        return None
                else:
                    return None
        return self._stt_model

    def _load_ser_model(self):
        if not HAS_SER or not settings.AUDIO_SER_ENABLED:
            return None
            
        if self._ser_pipeline is None:
            try:
                # Use local model path if available
                model_path = str(settings.AUDIO_SER_MODEL_PATH)
                if settings.AUDIO_SER_MODEL_PATH.exists():
                     logger.info(f"Loading SER model from local path: {model_path}")
                     model_to_load = model_path
                else:
                     logger.warning(f"Local SER model not found at {model_path}, falling back to huggingface ID '{settings.AUDIO_SER_MODEL}'")
                     model_to_load = settings.AUDIO_SER_MODEL

                # Use device=0 for GPU if available and requested
                device = 0 if settings.AUDIO_STT_DEVICE in ["cuda", "gpu"] else -1
                self._ser_pipeline = pipeline("audio-classification", model=model_to_load, device=device)
                logger.info(f"SER model loaded successfully on device {device}.")
            except Exception as e:
                logger.error(f"Failed to load SER model: {e}")
                # Disable SER to prevent future timeouts
                self._ser_pipeline = None
                return None
        return self._ser_pipeline

    def separate_vocals(self, audio_path: str) -> str:
        """
        Use Demucs to separate vocals from background music.
        Returns the path to the separated vocals file.
        If separation fails or is skipped, returns the original path.
        """
        try:
            import subprocess
            import shutil
            
            # Check if demucs is installed
            if not shutil.which("demucs") and not shutil.which("demucs.exe"):
                # Try python -m demucs
                cmd_base = ["python", "-m", "demucs"]
            else:
                cmd_base = ["demucs"]

            output_dir = self.audio_dir / "separated"
            output_dir.mkdir(exist_ok=True)
            
            logger.info(f"Starting vocal separation for: {audio_path}")
            
            # Run Demucs
            # -n htdemucs_ft : High quality model
            # --two-stems=vocals : Only separate vocals and others
            cmd = cmd_base + ["-n", "htdemucs_ft", "--two-stems=vocals", "-o", str(output_dir), audio_path]
            
            # Use subprocess to run
            process = subprocess.run(cmd, capture_output=True, text=True)
            
            if process.returncode != 0:
                logger.error(f"Demucs separation failed: {process.stderr}")
                return audio_path
                
            # Construct expected output path
            # Demucs structure: output_dir / model_name / track_name / vocals.wav
            filename = Path(audio_path).stem
            model_name = "htdemucs_ft"
            vocals_path = output_dir / model_name / filename / "vocals.wav"
            
            if vocals_path.exists():
                logger.info(f"Vocal separation successful: {vocals_path}")
                return str(vocals_path)
            else:
                logger.warning(f"Expected separated file not found: {vocals_path}")
                return audio_path
                
        except Exception as e:
            logger.error(f"Error during vocal separation: {e}")
            return audio_path

    def detect_emotion(self, audio_path: str) -> Dict[str, float]:
        """
        Detect emotion from audio file using local model.
        """
        if not HAS_SER:
            return {}
            
        pipe = self._load_ser_model()
        if not pipe:
            return {}
            
        try:
            # Force load with librosa/soundfile first to bypass pipeline's internal ffmpeg dependency
            # This is robust for Windows where ffmpeg binary might not be in PATH for python-ffmpeg
            try:
                import librosa
                # Load as numpy array, sampling rate must match model usually (16k is safe default for most)
                # But pipeline usually handles resampling. Let's try raw bytes or just ensure soundfile is used.
                # Actually, transformers pipeline accepts numpy array.
                y, sr = librosa.load(audio_path, sr=16000)
                results = pipe(y, top_k=3)
            except Exception as load_err:
                logger.warning(f"Librosa load failed, falling back to path: {load_err}")
                # Fallback to path
                results = pipe(audio_path, top_k=3)
            
            # results is like [{'label': 'neutral', 'score': 0.9}, ...]
            # Note: pipeline output format might differ for array input (list of dicts) vs file
            if isinstance(results, list) and isinstance(results[0], list):
                 # For batch processing or some models, it might be nested
                 results = results[0]
                 
            return {res['label']: res['score'] for res in results}
        except Exception as e:
            logger.error(f"SER error: {e}")
            return {}

    def extract_paralinguistic_features(self, audio_path: str) -> Dict[str, Any]:
        """
        Extract paralinguistic features (Pitch, Energy, Speed).
        """
        try:
            import librosa
            import numpy as np
            
            y, sr = librosa.load(audio_path, sr=None)
            
            # 1. Energy (RMS)
            rms = librosa.feature.rms(y=y)
            energy = float(np.mean(rms))
            
            # 2. Pitch (F0)
            # Use piptrack or similar
            pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
            # Select pitches with high magnitude
            pitch_values = []
            for t in range(pitches.shape[1]):
                index = magnitudes[:, t].argmax()
                pitch = pitches[index, t]
                if pitch > 0:
                    pitch_values.append(pitch)
            
            avg_pitch = float(np.mean(pitch_values)) if pitch_values else 0.0
            
            # 3. Speed (Syllables estimation)
            duration = librosa.get_duration(y=y, sr=sr)
            # Estimate syllables using peak detection on envelope (approx 4-5Hz for speech)
            # This is a rough heuristic
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            peaks = librosa.util.peak_pick(onset_env, pre_max=3, post_max=3, pre_avg=3, post_avg=5, delta=0.5, wait=10)
            syllable_count = len(peaks)
            speed = syllable_count / duration if duration > 0 else 0
            
            return {
                "energy": energy,
                "pitch": avg_pitch,
                "duration": duration,
                "speed": speed,
                "syllable_count": syllable_count
            }
        except ImportError:
            logger.warning("Librosa not installed, skipping paralinguistics.")
            return {}
        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return {}

    def get_voice_fingerprint(self, audio_path: str = None, y_data: Any = None, sr_rate: int = None) -> Optional[list]:
        """
        Get voice fingerprint for speaker ID.
        Uses MFCC + Delta + Delta-Delta (39-dim vector).
        Can accept either audio_path or (y_data, sr_rate).
        """
        try:
            import librosa
            import numpy as np
            
            if y_data is not None and sr_rate is not None:
                y, sr = y_data, sr_rate
            elif audio_path:
                y, sr = librosa.load(audio_path, sr=None)
            else:
                return None
            
            # Ensure minimum length for MFCC (at least 2048 samples usually)
            if len(y) < 2048:
                return None

            # 1. MFCC
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            
            # 2. Delta & Delta-Delta
            mfcc_delta = librosa.feature.delta(mfcc)
            mfcc_delta2 = librosa.feature.delta(mfcc, order=2)
            
            # 3. Stack and Mean
            # Shape: (39, T)
            combined = np.vstack([mfcc, mfcc_delta, mfcc_delta2])
            
            # Mean across time -> (39,)
            fingerprint = np.mean(combined, axis=1).tolist()
            return fingerprint
        except Exception as e:
            # logger.error(f"Fingerprint error: {e}") # Reduce log spam for short segments
            return None

    def transcribe_with_diarization(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe audio with speaker diarization (segment-level identification).
        Returns a structured transcript with speaker labels.
        Uses Clustering to improve consistency within the session.
        """
        if not HAS_WHISPER:
            return {"text": "", "error": "STT module not installed"}

        model = self._load_stt_model()
        if not model:
            return {"text": "", "error": "Model failed to load"}
            
        try:
            import librosa
            import numpy as np
            from sklearn.cluster import AgglomerativeClustering
            from sklearn.metrics.pairwise import cosine_distances

            # Load full audio once for slicing
            y_full, sr = librosa.load(audio_path, sr=None)
            duration_total = librosa.get_duration(y=y_full, sr=sr)
        except Exception as e:
            return {"text": "", "error": f"Audio load failed: {e}"}

        try:
            # Transcribe
            # Force Simplified Chinese output
            # Enable VAD filter to prevent hallucinations on silent audio
            # Disable condition_on_previous_text to prevent repetitive loops
            segments, info = model.transcribe(
                audio_path, 
                beam_size=settings.AUDIO_BEAM_SIZE, 
                language="zh", 
                initial_prompt=settings.AUDIO_INITIAL_PROMPT,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            # 1. Collect Segments & Fingerprints
            temp_segments = [] # List of dicts
            fingerprints = []
            valid_indices = [] # Indices in temp_segments that have fingerprints
            
            # Known Hallucination Phrases to filter
            HALLUCINATION_PHRASES = ["请不吝点赞", "订阅", "转发", "打赏支持", "明镜与点点", "字幕", "Amara.org"]

            for i, segment in enumerate(segments):
                # Hallucination Filter
                if any(phrase in segment.text for phrase in HALLUCINATION_PHRASES):
                    # logger.warning(f"Filtered hallucination: {segment.text}")
                    continue

                # Calculate start/end samples
                start_sample = int(segment.start * sr)
                end_sample = int(segment.end * sr)
                
                # Slice audio
                y_seg = y_full[start_sample:end_sample]
                
                # Get Fingerprint
                fp = self.get_voice_fingerprint(y_data=y_seg, sr_rate=sr)
                
                seg_data = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "speaker_id": "unknown",
                    "speaker_name": "Unknown"
                }
                
                temp_segments.append(seg_data)
                
                if fp is not None:
                    fingerprints.append(fp)
                    valid_indices.append(i)
            
            detected_speakers = set()
            
            # 2. Clustering Logic
            if len(fingerprints) > 0:
                X = np.array(fingerprints)
                
                # If very few segments, just match directly
                if len(fingerprints) < 2:
                    labels = [0]
                    n_clusters = 1
                else:
                    # Clustering
                    # Distance threshold 0.5 roughly corresponds to cosine sim 0.5
                    # But for speaker ID, usually 0.2-0.3 distance (0.8-0.7 sim) is a cut-off.
                    # VoiceProfile uses 0.85 sim => 0.15 distance.
                    # Let's use a slightly looser clustering threshold (e.g. 0.3) to group same speaker
                    try:
                        clustering = AgglomerativeClustering(
                            n_clusters=None,
                            metric='cosine', 
                            linkage='average',
                            distance_threshold=0.3  # Cosine distance
                        ).fit(X)
                        labels = clustering.labels_
                        n_clusters = clustering.n_clusters_
                    except Exception as cluster_err:
                        logger.warning(f"Clustering failed: {cluster_err}, falling back to single cluster")
                        labels = [0] * len(fingerprints)
                        n_clusters = 1
                
                # 3. Process Clusters
                cluster_map = {} # cluster_id -> (speaker_id, speaker_name)
                
                for k in range(n_clusters):
                    # Get all fingerprints in this cluster
                    cluster_indices = [idx for idx, label in enumerate(labels) if label == k]
                    cluster_fps = X[cluster_indices]
                    
                    # Compute centroid (mean)
                    centroid = np.mean(cluster_fps, axis=0).tolist()
                    
                    # Match against DB
                    match = self.voice_profile_service.match_speaker(centroid, threshold=0.80)
                    
                    if match:
                        s_id, s_name, _ = match
                    else:
                        # Create new profile for this cluster
                        s_id, s_name = self.voice_profile_service.create_profile(centroid)
                        
                    cluster_map[k] = (s_id, s_name)
                    detected_speakers.add((s_id, s_name))
                
                # 4. Assign back to segments
                for idx, label in zip(valid_indices, labels):
                    s_id, s_name = cluster_map[label]
                    temp_segments[idx]["speaker_id"] = s_id
                    temp_segments[idx]["speaker_name"] = s_name
            
            # Construct full formatted text
            full_formatted_text = ""
            for seg in temp_segments:
                full_formatted_text += f"【{seg['speaker_name']}】: {seg['text']}\n"
            
            return {
                "text": full_formatted_text, 
                "raw_segments": temp_segments,
                "detected_speakers": [{"id": s[0], "name": s[1]} for s in list(detected_speakers)],
                "language": info.language,
                "duration": duration_total
            }

        except Exception as e:
            error_str = str(e)
            logger.error(f"Diarization error: {e}")
            
            # Automatic Fallback for CUDA/DLL errors
            if ("dll" in error_str.lower() or "library" in error_str.lower() or "cuda" in error_str.lower()) and self.device != "cpu":
                logger.warning(f"CUDA/DLL error detected ({e}). Switching to CPU mode and retrying...")
                self.device = "cpu"
                self.compute_type = "int8"
                self._stt_model = None # Force reload
                return self.transcribe_with_diarization(audio_path) # Recursive retry
                
            return {"text": "", "error": str(e)}

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe audio file to text with emotion and feature detection.
        """
        if not HAS_WHISPER:
            return {"text": "", "error": "STT module not installed"}
            
        model = self._load_stt_model()
        if not model:
            return {"text": "", "error": "Model failed to load"}

        try:
            start_time = time.time()
            # Force Simplified Chinese output with initial_prompt
            segments, info = model.transcribe(
                audio_path, 
                beam_size=5, 
                language="zh", 
                initial_prompt="以下是简体中文的对话。"
            )
            
            text_segments = []
            for segment in segments:
                text_segments.append(segment.text)
            
            full_text = " ".join(text_segments).strip()
            duration = time.time() - start_time
            
            # Detect emotion
            emotions = self.detect_emotion(audio_path)
            top_emotion = max(emotions, key=emotions.get) if emotions else "neutral"
            
            # Extract features
            features = self.extract_paralinguistic_features(audio_path)
            
            # Fingerprint
            fingerprint = self.get_voice_fingerprint(audio_path)
            
            # Identify Speaker
            speaker_id, speaker_name, is_new = "unknown", "Unknown", False
            if fingerprint:
                speaker_id, speaker_name, is_new = self.voice_profile_service.identify_speaker(fingerprint)

            return {
                "text": full_text,
                "language": info.language,
                "duration": duration,
                "confidence": info.language_probability,
                "emotions": emotions,
                "top_emotion": top_emotion,
                "features": features,
                "fingerprint": fingerprint,
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
                "is_new_speaker": is_new
            }
        except Exception as e:
            error_str = str(e)
            logger.error(f"Transcription error: {e}")
            
            # Automatic Fallback for CUDA/DLL errors
            if ("dll" in error_str.lower() or "library" in error_str.lower() or "cuda" in error_str.lower()) and self.device != "cpu":
                logger.warning(f"CUDA/DLL error detected ({e}). Switching to CPU mode and retrying...")
                self.device = "cpu"
                self.compute_type = "int8"
                self._stt_model = None # Force reload
                return self.transcribe(audio_path) # Recursive retry
            
            return {"text": "", "error": str(e)}

    async def synthesize(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural", output_file: str = "output.mp3") -> Optional[str]:
        """
        Synthesize text to audio file.
        """
        if not HAS_TTS:
            logger.warning("TTS module not installed")
            return None
            
        output_path = self.audio_dir / output_file
        
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
            return str(output_path)
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return None

    def get_available_voices(self) -> list:
        if settings.AUDIO_TTS_VOICES:
            return settings.AUDIO_TTS_VOICES
            
        # Common EdgeTTS voices fallback
        return [
            {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao (Female, Warm)", "lang": "zh-CN"},
            {"id": "zh-CN-YunxiNeural", "name": "Yunxi (Male, Calm)", "lang": "zh-CN"},
            {"id": "en-US-JennyNeural", "name": "Jenny (Female, US)", "lang": "en-US"},
            {"id": "en-US-GuyNeural", "name": "Guy (Male, US)", "lang": "en-US"}
        ]

audio_service = AudioService()
