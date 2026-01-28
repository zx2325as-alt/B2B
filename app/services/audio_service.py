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

            try:
                logger.info(f"Loading Whisper model ({self.model_size}) on {device}...")
                self._stt_model = WhisperModel(
                    self.model_size, 
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
                            self.model_size, 
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
                model_name = settings.AUDIO_SER_MODEL
                
                # Check for local path first if model_name looks like a path or generic name
                local_path = settings.DATA_DIR / "models" / "ser" / model_name.replace("/", "_")
                if local_path.exists():
                    logger.info(f"Loading SER model from local path: {local_path}")
                    model_to_load = str(local_path)
                else:
                    logger.info(f"Loading SER model ({model_name})...")
                    model_to_load = model_name

                # Try loading with offline mode first if possible, but pipeline doesn't strictly enforce it via kwarg easily without model_kwargs
                # We'll just wrap it in try-except for connection errors
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
            # Force soundfile backend if available to avoid pydub/ffmpeg dependency for WAV
            try:
                import soundfile
            except ImportError:
                pass
            
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

    def get_voice_fingerprint(self, audio_path: str) -> Optional[list]:
        """
        Get voice fingerprint for speaker ID.
        Uses MFCC + Delta + Delta-Delta (39-dim vector) for better robustness.
        """
        try:
            import librosa
            import numpy as np
            y, sr = librosa.load(audio_path, sr=None)
            
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
            logger.error(f"Fingerprint error: {e}")
            return None

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
        # Common EdgeTTS voices
        return [
            {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao (Female, Warm)", "lang": "zh-CN"},
            {"id": "zh-CN-YunxiNeural", "name": "Yunxi (Male, Calm)", "lang": "zh-CN"},
            {"id": "en-US-JennyNeural", "name": "Jenny (Female, US)", "lang": "en-US"},
            {"id": "en-US-GuyNeural", "name": "Guy (Male, US)", "lang": "en-US"}
        ]

audio_service = AudioService()
