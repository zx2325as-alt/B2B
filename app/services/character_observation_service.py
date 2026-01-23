from sqlalchemy.orm import Session
from app.models.sql_models import CharacterObservation, Character
from typing import List, Dict, Any
import json
from app.services.character_service import character_service

class CharacterObservationService:
    """
    Service for managing active character observations (suggestions).
    """

    def add_observations(self, db: Session, session_id: str, observations: List[Dict[str, Any]]):
        """
        Batch add observations from dialogue analysis.
        """
        created_objs = []
        for obs in observations:
            char_name = obs.get("character_name")
            if not char_name:
                continue
            
            # Find character by name
            character = db.query(Character).filter(Character.name == char_name).first()
            if not character:
                continue

            new_obs = CharacterObservation(
                character_id=character.id,
                session_id=session_id,
                content=obs, # Store the full observation JSON
                confidence=0.8, # Default confidence, could come from LLM
                status="pending"
            )
            db.add(new_obs)
            created_objs.append(new_obs)
        
        db.commit()
        return created_objs

    def get_pending_observations(self, db: Session, character_id: int = None):
        """
        Get pending observations, optionally filtered by character.
        """
        query = db.query(CharacterObservation).filter(CharacterObservation.status == "pending")
        if character_id:
            query = query.filter(CharacterObservation.character_id == character_id)
        return query.order_by(CharacterObservation.created_at.desc()).all()

    def approve_observation(self, db: Session, observation_id: int):
        """
        Approve an observation and merge it into the character's dynamic profile.
        """
        obs = db.query(CharacterObservation).filter(CharacterObservation.id == observation_id).first()
        if not obs:
            return False

        character = db.query(Character).filter(Character.id == obs.character_id).first()
        if not character:
            return False

        # Merge logic
        # For now, we append to a list or update keys in dynamic_profile
        # Assuming dynamic_profile has a "observations" list or similar structure
        profile = dict(character.dynamic_profile or {})
        
        # 1. Update Core Traits if category matches
        category = obs.content.get("category")
        observation_text = obs.content.get("observation")
        
        # Add to a structured "collected_observations" list in profile
        if "collected_observations" not in profile:
            profile["collected_observations"] = []
        
        profile["collected_observations"].append({
            "category": category,
            "text": observation_text,
            "source_session": obs.session_id,
            "date": str(obs.created_at)
        })

        # Update character profile
        character.dynamic_profile = profile
        
        # Mark observation as approved
        obs.status = "approved"
        
        # Versioning handled by direct update here, or we should use character_service.update_character
        # But for simplicity, we do direct commit here, maybe trigger version bump later if needed
        character.version += 1
        
        db.commit()
        return True

    def reject_observation(self, db: Session, observation_id: int):
        """
        Reject an observation.
        """
        obs = db.query(CharacterObservation).filter(CharacterObservation.id == observation_id).first()
        if not obs:
            return False
        
        obs.status = "rejected"
        db.commit()
        return True

character_observation_service = CharacterObservationService()
