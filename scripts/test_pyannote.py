
import os
import torch
from pyannote.audio import Pipeline

# Mock settings
class Settings:
    PYANNOTE_CONFIG_PATH = r"e:\python\conda\B2B\model\pyannote_diarization\config.yaml"

settings = Settings()

try:
    print(f"Loading pipeline from {settings.PYANNOTE_CONFIG_PATH}")
    pipeline = Pipeline.from_pretrained(settings.PYANNOTE_CONFIG_PATH)
    print("✅ Pipeline loaded successfully!")
except Exception as e:
    print(f"❌ Pipeline load failed: {e}")
