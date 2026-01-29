from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from app.core.database import get_db
from app.services.feedback_service import feedback_service
from app.utils.logger import logger

router = APIRouter()

class FeedbackCreate(BaseModel):
    session_id: str
    user_input: str
    model_output: str
    rating: int # 1-5
    comment: Optional[str] = None

class CharacterEventCreate(BaseModel):
    summary: str
    intent: Optional[str] = None
    strategy: Optional[str] = None
    session_id: Optional[str] = None
    event_date: Optional[str] = None

@router.post("/feedback", summary="提交用户反馈")
async def create_feedback(
    feedback: FeedbackCreate, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    接收用户反馈。如果是差评，后台触发复盘分析。
    """
    try:
        log = feedback_service.save_feedback(
            db, 
            feedback.session_id, 
            feedback.user_input, 
            feedback.model_output, 
            feedback.rating, 
            feedback.comment
        )
        
        # 触发后台复盘任务
        background_tasks.add_task(feedback_service.trigger_evolution_if_needed, db, log)
        
        return {"status": "success", "id": log.id}
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/characters/{character_id}/events", summary="添加角色时间线事件")
def add_event(
    character_id: int,
    event: CharacterEventCreate,
    db: Session = Depends(get_db)
):
    try:
        new_event = feedback_service.add_character_event(
            db, 
            character_id, 
            event.summary, 
            event.intent, 
            event.strategy, 
            event.session_id,
            event.event_date
        )
        return {"status": "success", "id": new_event.id}
    except Exception as e:
        logger.error(f"Add event error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/characters/{character_id}/timeline", summary="获取角色时间线")
def get_timeline(
    character_id: int,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    events = feedback_service.get_character_timeline(db, character_id, limit)
    return events
