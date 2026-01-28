from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Body
from fastapi.responses import FileResponse, JSONResponse
from app.services.audio_service import audio_service
from app.utils.logger import logger
from pydantic import BaseModel
import shutil
import os
import uuid
from pathlib import Path

router = APIRouter()

class SpeakerUpdate(BaseModel):
    name: str = None
    character_name: str = None

@router.get("/audio/profiles", summary="Get all voice profiles")
def get_voice_profiles():
    return audio_service.voice_profile_service.get_all_speakers()

@router.put("/audio/profiles/{speaker_id}", summary="Update voice profile")
def update_voice_profile(speaker_id: str, update: SpeakerUpdate):
    success = False
    if update.character_name:
        success = audio_service.voice_profile_service.bind_character(speaker_id, update.character_name)
    elif update.name:
        success = audio_service.voice_profile_service.update_speaker_name(speaker_id, update.name)
        
    if not success:
        raise HTTPException(status_code=404, detail="Speaker not found or update failed")
    return {"status": "success", "id": speaker_id}

@router.delete("/audio/profiles/{speaker_id}", summary="Delete voice profile")
def delete_voice_profile(speaker_id: str):
    if audio_service.voice_profile_service.delete_speaker(speaker_id):
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Speaker not found")

@router.post("/audio/transcribe", summary="语音转文字 (STT)")
async def transcribe_audio(
    file: UploadFile = File(...),
):
    """
    上传音频文件，进行语音识别和情感分析。
    """
    try:
        # Save temp file
        file_ext = Path(file.filename).suffix
        if not file_ext:
            file_ext = ".wav" # Default
            
        temp_filename = f"upload_{uuid.uuid4()}{file_ext}"
        temp_path = audio_service.audio_dir / temp_filename
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process
        result = audio_service.transcribe(str(temp_path))
        
        # Cleanup (Optional: Keep for debugging or delete)
        # os.remove(temp_path)
        
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
             
        return result
        
    except Exception as e:
        logger.error(f"STT Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/audio/synthesize", summary="文字转语音 (TTS)")
async def synthesize_text(
    text: str = Form(...),
    voice: str = Form(None)
):
    """
    将文本转换为语音文件。
    """
    try:
        output_path = await audio_service.synthesize(text, voice=voice)
        
        if not output_path or not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="TTS generation failed")
            
        # Return file
        return FileResponse(
            output_path, 
            media_type="audio/mpeg", 
            filename=os.path.basename(output_path)
        )
        
    except Exception as e:
        logger.error(f"TTS Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
