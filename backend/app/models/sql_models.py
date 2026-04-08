from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey,
    Boolean, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    avatar_color = Column(String(20), default="#00d4ff")
    role = Column(String(100))
    background = Column(Text)
    age = Column(Integer, nullable=True)
    personality_tags = Column(JSON, default=list)   # ["内敛","理性"]
    core_traits = Column(JSON, default=dict)         # {openness:0.8,...}
    weakness = Column(Text)
    motivation = Column(Text)
    speaking_style = Column(Text)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("CharacterEvent", back_populates="character", cascade="all, delete-orphan")
    observations = relationship("CharacterObservation", back_populates="character", cascade="all, delete-orphan")
    rel_from = relationship("Relationship", foreign_keys="Relationship.source_id", back_populates="source", cascade="all, delete-orphan")
    rel_to   = relationship("Relationship", foreign_keys="Relationship.target_id", back_populates="target")


class CharacterEvent(Base):
    __tablename__ = "character_events"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    event_date = Column(String(50))        # flexible date string
    emotion_label = Column(String(50))
    importance = Column(Integer, default=3)  # 1-5
    created_at = Column(DateTime, default=datetime.utcnow)

    character = relationship("Character", back_populates="events")


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    rel_type = Column(String(50), default="neutral")   # ally, rival, friend, family, romantic, neutral
    strength = Column(Float, default=0.5)              # 0.0 ~ 1.0
    sentiment = Column(Float, default=0.0)             # -1.0 ~ 1.0
    description = Column(Text)
    history = Column(JSON, default=list)               # [{date,strength,sentiment}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = relationship("Character", foreign_keys=[source_id], back_populates="rel_from")
    target = relationship("Character", foreign_keys=[target_id], back_populates="rel_to")


class CharacterObservation(Base):
    """AI 生成的角色更新建议，需要人工审核"""
    __tablename__ = "character_observations"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    field = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)
    reason = Column(Text)
    status = Column(String(20), default="pending")   # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    character = relationship("Character", back_populates="observations")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="新对话")
    scenario = Column(String(100), default="general")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("messages.id"), nullable=True)   # for branching
    branch_label = Column(String(50), nullable=True)

    role = Column(String(20), nullable=False)          # user / assistant / system
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    character_name = Column(String(100))
    content = Column(Text, nullable=False)

    # Analysis layer
    inner_monologue = Column(Text)
    emotion_label = Column(String(50))
    emotion_score = Column(Float)
    subtext = Column(Text)
    psychological_tag = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    children = relationship("Message", foreign_keys=[parent_id])
