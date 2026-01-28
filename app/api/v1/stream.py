from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.sql_models import ConversationSegment
from app.services.realtime_audio_service import RealtimeAudioService
from app.utils.logger import logger
import asyncio
from typing import Optional, List

router = APIRouter()
try:
    service = RealtimeAudioService()
except ImportError as e:
    logger.error(f"Failed to initialize RealtimeAudioService: {e}")
    service = None

@router.websocket("/ws/audio/{session_id}")
async def audio_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if service is None:
        await websocket.send_text("Error: Realtime service is unavailable (missing dependencies).")
        await websocket.close()
        return
    logger.info(f"WebSocket connected: {session_id}")
    
    async def process_and_send(sid, seg_bytes):
        try:
             result = await service.process_segment_async(sid, seg_bytes)
             if result:
                 # result is {"segments": [...]}
                 from starlette.websockets import WebSocketState
                 if websocket.client_state == WebSocketState.CONNECTED:
                     await websocket.send_json(result)
                 else:
                     logger.warning(f"WebSocket closed for session {sid}, skipping send.")
        except Exception as e:
             logger.error(f"Async processing error: {e}")

    try:
        while True:
            data = await websocket.receive_bytes()
            # Process chunk - returns bytes if segment ready
            segment_bytes = await service.process_audio_stream(session_id, data)
            if segment_bytes:
                # Spawn background task for heavy processing
                asyncio.create_task(process_and_send(session_id, segment_bytes))
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass

@router.put("/segments/{segment_id}/speaker")
async def update_speaker(segment_id: int, speaker_name: str = Body(..., embed=True)):
    """
    Update the speaker name for a segment.
    This effectively 'binds' the voice profile to a person and triggers RE-ANALYSIS.
    """
    if service is None:
        raise HTTPException(status_code=503, detail="Realtime service is unavailable.")
        
    success, msg = await service.update_segment_speaker_and_reanalyze(segment_id, speaker_name)
    if not success:
         raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "message": msg}

@router.post("/segments/{segment_id}/rate")
async def rate_segment(
    segment_id: int, 
    rating: int, 
    feedback: str = None,
    db: Session = Depends(get_db)
):
    """
    Rate a realtime conversation segment.
    """
    seg = db.query(ConversationSegment).filter(ConversationSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    seg.rating = rating
    if feedback:
        seg.feedback = feedback
    
    db.commit()
    return {"status": "success", "segment_id": segment_id}

@router.get("/segments", summary="Get Realtime Segments")
def get_segments(
    limit: int = 50,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(ConversationSegment)
    if session_id:
        query = query.filter(ConversationSegment.session_id == session_id)
        
    # Order by newest first
    segments = query.order_by(ConversationSegment.created_at.desc()).limit(limit).all()
    return segments
