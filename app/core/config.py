import os
import yaml
from pathlib import Path
from typing import Any, Dict

class Settings:
    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent.parent
        self.CONFIG_PATH = self.BASE_DIR / "config" / "config.yaml"
        self.PROMPTS_PATH = self.BASE_DIR / "config" / "prompts.yaml"
        self.DATA_DIR = self.BASE_DIR / "data"
        
        self._config = self._load_config()
        self.PROMPTS = self._load_prompts()
        
        # App
        app_config = self._config.get("app") or {}
        self.APP_NAME = app_config.get("name", "BtB System")
        self.APP_VERSION = app_config.get("version", "1.0.0")
        self.APP_DESCRIPTION = app_config.get("description", "BtB System")
        self.DEBUG = app_config.get("debug", True)
        self.DEFAULT_SCENARIO = app_config.get("default_scenario", None) # Default Scenario Name
        
        # Server
        server_config = self._config.get("server") or {}
        self.HOST = server_config.get("host", "127.0.0.1")
        self.BACKEND_PORT = server_config.get("backend_port", 8000)
        self.ADMIN_PORT = server_config.get("admin_port", 8501)
        self.CHAT_PORT = server_config.get("chat_port", 8502)
        
        # API URL (Constructed)
        self.API_URL = f"http://{self.HOST}:{self.BACKEND_PORT}/api/v1"

        # LLM
        llm_config = self._config.get("llm") or {}
        self.LLM_API_KEY = llm_config.get("api_key", "") or os.getenv("LLM_API_KEY", "")
        self.LLM_BASE_URL = llm_config.get("base_url", "https://api.openai.com/v1")
        self.LLM_MODEL = llm_config.get("model", "gpt-3.5-turbo")
        self.LLM_TIMEOUT = llm_config.get("timeout", 60.0)
        self.HTTP_PROXY = llm_config.get("proxy", "") or os.getenv("HTTP_PROXY", "")

        # RAG
        rag_config = self._config.get("rag") or {}
        self.RAG_SIMILARITY_TOP_K = rag_config.get("similarity_top_k", 3)
        self.RAG_CHUNK_SIZE = rag_config.get("chunk_size", 512)

        # Audio
        audio_config = self._config.get("audio") or {}
        self.AUDIO_STT_MODEL_SIZE = audio_config.get("stt_model_size", "medium")
        self.AUDIO_STT_DEVICE = audio_config.get("stt_device", "cpu")
        self.AUDIO_STT_COMPUTE_TYPE = audio_config.get("stt_compute_type", "int8")
        self.AUDIO_TTS_ENABLED = audio_config.get("tts_enabled", True)
        self.AUDIO_TTS_VOICE = audio_config.get("tts_voice", "zh-CN-XiaoxiaoNeural")
        self.AUDIO_SER_ENABLED = audio_config.get("ser_enabled", True)
        self.AUDIO_SER_MODEL = audio_config.get("ser_model", "superb/wav2vec2-base-superb-er")

        # Database
        db_config = self._config.get("database") or {}
        self.DATABASE_URL = db_config.get("url") or f"sqlite:///{self.DATA_DIR}/btb.db"

        # Redis
        redis_config = self._config.get("redis") or {}
        self.REDIS_URL = redis_config.get("url", "redis://localhost:6379/0")
        
        # User
        user_config = self._config.get("user") or {}
        self.USER_DEFAULT_PROFILE_ID = user_config.get("default_profile_id", "guest")

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
