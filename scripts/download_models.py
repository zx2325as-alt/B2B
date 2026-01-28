import os
import shutil
import yaml
import warnings
from pathlib import Path
from app.core.config import settings
from app.utils.logger import logger

# Suppress warnings
warnings.filterwarnings("ignore")

def download_whisper():
    """Download Faster Whisper model if not exists."""
    model_size = settings.AUDIO_STT_MODEL_SIZE
    output_dir = settings.AUDIO_STT_MODEL_PATH
    
    logger.info(f"Checking Whisper model ({model_size})...")
    if output_dir.exists() and any(output_dir.iterdir()):
        logger.info(f"✅ Whisper model found at: {output_dir}")
        return

    logger.info(f"⬇️ Downloading Whisper model to: {output_dir}")
    try:
        from faster_whisper import download_model
        # download_model returns the path to the model
        downloaded_path = download_model(model_size, output_dir=str(output_dir))
        logger.info(f"✅ Whisper model downloaded successfully to: {downloaded_path}")
    except Exception as e:
        logger.error(f"❌ Failed to download Whisper model: {e}")

def download_ser():
    """Download SER model if not exists."""
    model_id = settings.AUDIO_SER_MODEL
    output_dir = settings.AUDIO_SER_MODEL_PATH
    
    logger.info(f"Checking SER model ({model_id})...")
    if output_dir.exists() and (output_dir / "config.json").exists():
        logger.info(f"✅ SER model found at: {output_dir}")
        return

    logger.info(f"⬇️ Downloading SER model to: {output_dir}")
    try:
        from transformers import AutoModelForAudioClassification, AutoFeatureExtractor
        
        # Download and save
        model = AutoModelForAudioClassification.from_pretrained(model_id)
        feature_extractor = AutoFeatureExtractor.from_pretrained(model_id)
        
        model.save_pretrained(output_dir)
        feature_extractor.save_pretrained(output_dir)
        logger.info(f"✅ SER model downloaded successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to download SER model: {e}")
        # Fallback to snapshot_download
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=model_id, local_dir=output_dir)
            logger.info(f"✅ SER model downloaded via snapshot.")
        except Exception as e2:
            logger.error(f"❌ Snapshot download failed: {e2}")

def download_pyannote():
    """Download Pyannote models (Diarization, Segmentation, Embedding) if not exists."""
    # Define models and target directories
    models = {
        "diarization": {
            "repo_id": "pyannote/speaker-diarization-3.1",
            "local_dir": settings.PYANNOTE_DIR
        },
        "segmentation": {
            "repo_id": "pyannote/segmentation-3.0",
            "local_dir": settings.PYANNOTE_SEGMENTATION_DIR
        },
        "embedding": {
            "repo_id": "pyannote/wespeaker-voxceleb-resnet34-LM",
            "local_dir": settings.PYANNOTE_EMBEDDING_DIR
        }
    }
    
    from huggingface_hub import snapshot_download
    token = os.environ.get("HF_TOKEN")
    
    for name, info in models.items():
        local_dir = info["local_dir"]
        logger.info(f"Checking Pyannote {name} model...")
        
        if local_dir.exists() and (local_dir / "config.yaml").exists():
            logger.info(f"✅ Pyannote {name} model found at: {local_dir}")
            continue
            
        logger.info(f"⬇️ Downloading Pyannote {name} model to: {local_dir}")
        try:
            snapshot_download(
                repo_id=info["repo_id"],
                local_dir=local_dir,
                token=token,
                ignore_patterns=["*.msgpack", "*.safetensors"] if name == "diarization" else [] # filter optional
            )
            logger.info(f"✅ Pyannote {name} downloaded.")
        except Exception as e:
            logger.error(f"❌ Failed to download Pyannote {name}: {e}")
            if "401" in str(e):
                logger.warning("⚠️ Authentication failed. Please set HF_TOKEN environment variable for Pyannote models.")

    # Patch Diarization Config to point to local Segmentation/Embedding
    patch_pyannote_config()

def patch_pyannote_config():
    """Update Pyannote Diarization config.yaml to point to local models."""
    diarization_dir = settings.MODEL_DIR / "pyannote_diarization"
    config_path = diarization_dir / "config.yaml"
    
    if not config_path.exists():
        logger.warning("⚠️ Pyannote diarization config not found, skipping patch.")
        return
        
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            
        # Update pipeline params with absolute paths
        # We use forward slashes for compatibility
        seg_path = (settings.MODEL_DIR / "pyannote_segmentation" / "config.yaml").as_posix()
        emb_path = (settings.MODEL_DIR / "pyannote_embedding" / "config.yaml").as_posix()
        
        if "pipeline" in config and "params" in config["pipeline"]:
            config["pipeline"]["params"]["segmentation"] = seg_path
            config["pipeline"]["params"]["embedding"] = emb_path
            
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
            
        logger.info(f"✅ Patched Pyannote config with local paths: {config_path}")
        
    except Exception as e:
        logger.error(f"❌ Failed to patch Pyannote config: {e}")

if __name__ == "__main__":
    logger.info("🚀 Starting Model Verification & Download...")
    logger.info(f"📂 Model Directory: {settings.MODEL_DIR}")
    
    # Ensure HF Mirror
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    
    download_whisper()
    download_ser()
    download_pyannote()
    
    logger.info("✨ Model setup complete.")
