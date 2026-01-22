from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.sql_models import FeedbackLog, EvolutionCase, CharacterEvent, Character
from app.core.config import settings
from app.services.llm import llm_service
from app.utils.logger import logger
import json
import re

class FeedbackService:
    """
    Manages user feedback, triggering evolution (review analysis),
    and character timeline events.
    """

    def save_feedback(self, db: Session, session_id: str, user_input: str, model_output: str, rating: int, comment: str = None) -> FeedbackLog:
        """
        Save user feedback log.
        """
        log = FeedbackLog(
            session_id=session_id,
            user_input=user_input,
            model_output=model_output,
            rating=rating,
            comment=comment
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    async def trigger_evolution_if_needed(self, db: Session, feedback_log: FeedbackLog):
        """
        If rating is low (e.g., <= 2), trigger 'Review Analysis'.
        """
        if feedback_log.rating > 2:
            return None
        
        # Trigger Review
        logger.info(f"Triggering Evolution for Feedback ID {feedback_log.id} (Rating: {feedback_log.rating})")
        
        config = settings.PROMPTS.get("deep_analysis", {}).get("review_analysis", {})
        prompt_template = config.get("prompt", "")
        temperature = config.get("temperature", 0.5)
        
        if not prompt_template:
            logger.warning("No review_analysis prompt defined.")
            return None
            
        prompt = prompt_template.format(
            original_input=feedback_log.user_input,
            original_output=feedback_log.model_output,
            user_feedback=feedback_log.comment or "No specific comment, just low rating."
        )
        
        response = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"}
        )
        
        try:
            result = json.loads(response)
            diagnosis = result.get("diagnosis", "")
            improved_report = result.get("improved_report_markdown", "")
            
            # Save Evolution Case
            case = EvolutionCase(
                feedback_id=feedback_log.id,
                original_input=feedback_log.user_input,
                bad_output=feedback_log.model_output,
                improved_output=improved_report,
                diagnosis=diagnosis
            )
            db.add(case)
            db.commit()
            logger.info(f"Evolution Case saved for Feedback ID {feedback_log.id}")
            return case
        except Exception as e:
            logger.error(f"Evolution analysis failed: {e}")
            return None

    def add_character_event(self, db: Session, character_id: int, summary: str, intent: str = None, strategy: str = None, session_id: str = None) -> CharacterEvent:
        """
        Add a timeline event for a character.
        """
        event = CharacterEvent(
            character_id=character_id,
            summary=summary,
            intent=intent,
            strategy=strategy,
            source_session_id=session_id
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    
    def get_character_timeline(self, db: Session, character_id: int, limit: int = 50) -> list[CharacterEvent]:
        """
        Get events for a character, ordered by date desc.
        """
        return db.query(CharacterEvent).filter(CharacterEvent.character_id == character_id).order_by(CharacterEvent.event_date.desc()).limit(limit).all()

feedback_service = FeedbackService()
