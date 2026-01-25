import json
import os
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from app.utils.logger import logger

class VoiceProfileService:
    """
    Service for managing voice profiles (Speaker ID).
    Stores voice fingerprints (MFCC means) in a JSON file.
    """
    
    def __init__(self, data_path: str = "data/voice_profiles.json"):
        self.data_path = Path(data_path)
        self.profiles: Dict[str, Dict] = {}  # { "uuid": { "name": "User", "fingerprint": [0.1, ...] } }
        self._load_profiles()

    def _load_profiles(self):
        """Load profiles from JSON file."""
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_profiles()  # Create empty file
            return

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.profiles = json.load(f)
            logger.info(f"Loaded {len(self.profiles)} voice profiles.")
        except Exception as e:
            logger.error(f"Failed to load voice profiles: {e}")
            self.profiles = {}

    def _save_profiles(self):
        """Save profiles to JSON file."""
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save voice profiles: {e}")

    def identify_speaker(self, fingerprint: List[float], threshold: float = 0.85) -> Tuple[str, str, bool]:
        """
        Identify speaker from fingerprint.
        Returns: (speaker_id, speaker_name, is_new)
        """
        if not fingerprint or len(fingerprint) == 0:
            return "unknown", "Unknown", False

        query_vec = np.array(fingerprint)
        best_score = -1.0
        best_id = None
        
        # 1. Compare with existing profiles (Cosine Similarity)
        for pid, data in self.profiles.items():
            stored_vec = np.array(data["fingerprint"])
            if stored_vec.shape != query_vec.shape:
                continue
                
            # Cosine Similarity: (A . B) / (||A|| * ||B||)
            norm_q = np.linalg.norm(query_vec)
            norm_s = np.linalg.norm(stored_vec)
            if norm_q == 0 or norm_s == 0:
                continue
                
            score = np.dot(query_vec, stored_vec) / (norm_q * norm_s)
            
            if score > best_score:
                best_score = score
                best_id = pid

        # 2. Check threshold
        if best_score >= threshold and best_id:
            logger.info(f"Identified speaker: {self.profiles[best_id]['name']} (Score: {best_score:.2f})")
            return best_id, self.profiles[best_id]["name"], False
        
        # 3. If no match, create new profile
        new_id = f"speaker_{len(self.profiles) + 1}"
        new_name = f"Unknown Speaker {len(self.profiles) + 1}"
        
        self.profiles[new_id] = {
            "name": new_name,
            "fingerprint": fingerprint,
            "created_at": time.time()
        }
        self._save_profiles()
        logger.info(f"Created new voice profile: {new_name}")
        
        return new_id, new_name, True

    def update_speaker_name(self, speaker_id: str, new_name: str) -> bool:
        """Update the name of a speaker."""
        if speaker_id in self.profiles:
            self.profiles[speaker_id]["name"] = new_name
            self._save_profiles()
            return True
        return False

    def delete_speaker(self, speaker_id: str) -> bool:
        """Delete a speaker profile."""
        if speaker_id in self.profiles:
            del self.profiles[speaker_id]
            self._save_profiles()
            return True
        return False

    def get_all_speakers(self) -> List[Dict]:
        """Get list of all speakers."""
        return [{"id": k, **v} for k, v in self.profiles.items()]

import time
