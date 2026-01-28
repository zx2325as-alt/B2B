import os
import yaml
from pathlib import Path
from typing import Any, Dict

class Settings:
    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent.parent
        self.CONFIG_PATH = self.BASE_DIR / "config" / "smartlisten_config.yaml"  # Updated to new config
        if not self.CONFIG_PATH.exists():
             self.CONFIG_PATH = self.BASE_DIR / "config" / "config.yaml" # Fallback

        self.PROMPTS_PATH = self.BASE_DIR / "config" / "prompts.yaml"
        self.DATA_DIR = self.BASE_DIR / "data"
        
        self._config = self._load_config()
        self.PROMPTS = self._load_prompts()
        
        # System
        system_config = self._config.get("system") or self._config.get("app") or {}
        self.APP_NAME = system_config.get("name", "BtB System")
        self.APP_DESCRIPTION = system_config.get("description", "BtB 深度对话理解与个性化翻译系统")
        self.APP_VERSION = system_config.get("version", "1.0.0")
        self.APP_MODE = system_config.get("mode", "production")
        self.LOG_LEVEL = system_config.get("log_level", "INFO")
        self.DEBUG = self.LOG_LEVEL.upper() == "DEBUG"
        
        # Audio
        audio_config = self._config.get("audio") or {}
        self.AUDIO_INPUT_DEVICE = audio_config.get("input_device", "default")
        self.AUDIO_SAMPLE_RATE = audio_config.get("sample_rate", 16000)
        self.AUDIO_CHANNELS = audio_config.get("channels", 1)
        self.AUDIO_CHUNK_SIZE = audio_config.get("chunk_size", 1024)
        
        self.AUDIO_BEAM_SIZE = audio_config.get("beam_size", 5)
        self.AUDIO_INITIAL_PROMPT = audio_config.get("initial_prompt", "以下是简体中文的对话。")
        self.AUDIO_TTS_DEFAULT_VOICE = audio_config.get("default_voice", "zh-CN-XiaoxiaoNeural")
        self.AUDIO_TTS_VOICES = audio_config.get("available_voices", [])
        
        self.AUDIO_SER_ENABLED = audio_config.get("ser_enabled", True)
        self.AUDIO_SER_MODEL = audio_config.get("ser_model", "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition")
        
        # Models - ASR
        models_config = self._config.get("models") or {}
        
        # Global Model Directory
        self.MODEL_DIR = self.BASE_DIR / "model"
        self.MODEL_DIR.mkdir(parents=True, exist_ok=True)
        
        asr_config = models_config.get("asr") or {}
        self.AUDIO_STT_MODEL_SIZE = asr_config.get("model_size") or audio_config.get("stt_model_size", "base")
        self.AUDIO_STT_COMPUTE_TYPE = asr_config.get("compute_type") or audio_config.get("stt_compute_type", "int8")
        
        # Model Paths (Centralized)
        self.AUDIO_STT_MODEL_PATH = self.MODEL_DIR / f"faster-whisper-{self.AUDIO_STT_MODEL_SIZE}"
        self.AUDIO_SER_MODEL_PATH = self.MODEL_DIR / "ser_model"
        self.PYANNOTE_DIR = self.MODEL_DIR / "pyannote_diarization"
        self.PYANNOTE_SEGMENTATION_DIR = self.MODEL_DIR / "pyannote_segmentation"
        self.PYANNOTE_EMBEDDING_DIR = self.MODEL_DIR / "pyannote_embedding"
        self.PYANNOTE_CONFIG_PATH = self.PYANNOTE_DIR / "config.yaml"
        
        # GPU
        gpu_config = self._config.get("gpu") or {}
        self.GPU_ENABLED = gpu_config.get("enabled", True)
        self.AUDIO_STT_DEVICE = "cuda" if self.GPU_ENABLED else "cpu"
        # Override with old config key if present and new one is missing
        if "stt_device" in audio_config:
            self.AUDIO_STT_DEVICE = audio_config["stt_device"]
        
        # LLM
        llm_config = models_config.get("llm") or self._config.get("llm") or {}
        self.LLM_ENABLED = llm_config.get("enabled", True)
        
        # Mode Switching (online vs local)
        self.LLM_MODE = llm_config.get("mode", "online")
        
        # Select active config block
        active_config = llm_config.get(self.LLM_MODE, {})
        # Fallback to root level if active_config is empty (for backward compatibility)
        if not active_config:
            active_config = llm_config
            
        self.LLM_API_KEY = active_config.get("api_key", "") or os.getenv("LLM_API_KEY", "")
        self.LLM_BASE_URL = active_config.get("base_url") or active_config.get("ollama_host", "https://api.openai.com/v1")
        self.LLM_MODEL = active_config.get("model_name") or active_config.get("model", "gpt-3.5-turbo")
        self.LLM_TIMEOUT = active_config.get("timeout", 60.0)
        self.HTTP_PROXY = active_config.get("proxy", "") or os.getenv("HTTP_PROXY", "")

        # RAG
        rag_config = self._config.get("rag") or {}
        self.RAG_SIMILARITY_TOP_K = rag_config.get("similarity_top_k", 3)
        self.RAG_CHUNK_SIZE = rag_config.get("chunk_size", 512)

        # Database / Storage
        storage_config = self._config.get("storage") or {}
        db_config = self._config.get("database") or {}
        
        default_db_path = self.DATA_DIR / "btb.db"
        # Ensure directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        self.DATABASE_URL = storage_config.get("database_url") or db_config.get("url") or f"sqlite:///{default_db_path.as_posix()}"

        # Ensure database directory exists if using sqlite
        if self.DATABASE_URL.startswith("sqlite:///"):
            try:
                # Extract path from URL
                # Handle potential 4 slashes for Unix absolute paths, though rare in this context
                path_str = self.DATABASE_URL.split("sqlite:///")[-1]
                
                # Create Path object
                db_path = Path(path_str)
                
                # If path is relative, ensure we resolve it correctly to create directory
                # But mkdir works on relative paths too.
                if not db_path.exists():
                     db_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"Warning: Auto-creation of database directory failed: {e}")

        # Server / API
        api_config = self._config.get("api") or self._config.get("server") or {}
        self.HOST = api_config.get("host", "127.0.0.1")
        self.BACKEND_PORT = api_config.get("port") or api_config.get("backend_port", 8000)
        self.ADMIN_PORT = api_config.get("admin_port", 8501)
        self.CHAT_PORT = api_config.get("chat_port", 8502)
        self.API_URL = f"http://{self.HOST}:{self.BACKEND_PORT}/api/v1"
        
        # User Defaults
        user_config = self._config.get("user") or {}
        self.USER_DEFAULT_PROFILE_ID = user_config.get("default_profile_id", "guest")

        # Cache / Redis
        cache_config = self._config.get("cache") or self._config.get("redis") or {}
        self.REDIS_URL = cache_config.get("url") or cache_config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379/0")

    def _load_config(self) -> Dict[str, Any]:
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Error loading config.yaml: {e}")
                return {}
        return {}

    def _load_prompts(self) -> Dict[str, Any]:
        if self.PROMPTS_PATH.exists():
            try:
                with open(self.PROMPTS_PATH, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Error loading prompts.yaml: {e}")
                return {}
        return {}

settings = Settings()
