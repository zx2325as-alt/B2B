import json
from pathlib import Path
from typing import Dict, Any
from app.core.config import settings
from app.utils.logger import logger

class UserProfileService:
    def __init__(self):
        self.profiles_path = settings.DATA_DIR / "profiles.json"
        self._ensure_file()

    def _ensure_file(self):
        if not self.profiles_path.parent.exists():
            self.profiles_path.parent.mkdir(parents=True, exist_ok=True)
            
        if not self.profiles_path.exists():
            with open(self.profiles_path, 'w') as f:
                json.dump({}, f)

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        with open(self.profiles_path, 'r') as f:
            profiles = json.load(f)
        return profiles.get(user_id, {
            "preference": "neutral",
            "knowledge_level": "intermediate",
            "preferred_format": "text"
        })

    def update_profile(self, user_id: str, updates: Dict[str, Any]):
        with open(self.profiles_path, 'r') as f:
            profiles = json.load(f)
        
        current = profiles.get(user_id, {})
        current.update(updates)
        profiles[user_id] = current
        
        with open(self.profiles_path, 'w') as f:
            json.dump(profiles, f, indent=2)

user_service = UserProfileService()
