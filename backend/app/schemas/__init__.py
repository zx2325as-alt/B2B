from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


# ─── Character ────────────────────────────────────────────────────────────────

class CharacterCreate(BaseModel):
    name: str
    role: str = ""
    background: str = ""
    age: Optional[int] = None
    avatar_color: str = "#00d4ff"
    personality_tags: list[str] = []
    weakness: str = ""
    motivation: str = ""
    speaking_style: str = ""

class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    background: Optional[str] = None
    age: Optional[int] = None
    avatar_color: Optional[str] = None
    personality_tags: Optional[list[str]] = None
    core_traits: Optional[dict] = None
    weakness: Optional[str] = None
    motivation: Optional[str] = None
    speaking_style: Optional[str] = None

class CharacterOut(BaseModel):
    id: int
    name: str
    role: str
    background: str
    age: Optional[int]
    avatar_color: str
    personality_tags: list[str]
    core_traits: dict
    weakness: str
    motivation: str
    speaking_style: str
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Event ────────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    character_id: int
    title: str
    description: str = ""
    event_date: str = ""
    emotion_label: str = ""
    importance: int = 3

class EventOut(BaseModel):
    id: int
    character_id: int
    title: str
    description: str
    event_date: str
    emotion_label: str
    importance: int
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Relationship ─────────────────────────────────────────────────────────────

class RelationshipCreate(BaseModel):
    source_id: int
    target_id: int
    rel_type: str = "neutral"
    strength: float = 0.5
    sentiment: float = 0.0
    description: str = ""

class RelationshipUpdate(BaseModel):
    rel_type: Optional[str] = None
    strength: Optional[float] = None
    sentiment: Optional[float] = None
    description: Optional[str] = None

class RelationshipOut(BaseModel):
    id: int
    source_id: int
    target_id: int
    rel_type: str
    strength: float
    sentiment: float
    description: str
    history: list
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Observation ─────────────────────────────────────────────────────────────

class ObservationReview(BaseModel):
    status: str  # approved / rejected

class ObservationOut(BaseModel):
    id: int
    character_id: int
    field: str
    old_value: str
    new_value: str
    reason: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Chat ────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    conversation_id: int
    speaker: str
    content: str
    character_id: Optional[int] = None
    scenario: str = "general"

class ConversationCreate(BaseModel):
    title: str = "新对话"
    scenario: str = "general"

class MessageOut(BaseModel):
    id: int
    conversation_id: int
    parent_id: Optional[int]
    role: str
    character_name: Optional[str]
    content: str
    inner_monologue: Optional[str]
    emotion_label: Optional[str]
    emotion_score: Optional[float]
    subtext: Optional[str]
    psychological_tag: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
