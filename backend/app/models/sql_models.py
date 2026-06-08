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
    evidence_spans = relationship("EvidenceSpan", back_populates="character", cascade="all, delete-orphan")
    memory_items = relationship("MemoryItem", back_populates="character", cascade="all, delete-orphan")
    personality_snapshots = relationship("PersonalitySnapshot", back_populates="character", cascade="all, delete-orphan")
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


class EvidenceSpan(Base):
    """可追溯证据片段：所有人格/关系/记忆判断都应尽量绑定到这里"""
    __tablename__ = "evidence_spans"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True, index=True)
    source_type = Column(String(50), default="unknown")  # chat / import / profile / manual
    source_id = Column(Integer, nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    import_file_id = Column(Integer, ForeignKey("import_files.id"), nullable=True)
    interaction_unit_id = Column(Integer, ForeignKey("interaction_units.id"), nullable=True)
    character_event_id = Column(Integer, ForeignKey("character_events.id"), nullable=True)
    relationship_id = Column(Integer, ForeignKey("relationships.id"), nullable=True)
    observation_id = Column(Integer, ForeignKey("character_observations.id"), nullable=True)
    supports_type = Column(String(50), default="memory")  # trait / relationship / event / emotion / strategy / memory
    supports_id = Column(Integer, nullable=True)
    polarity = Column(String(20), default="supports")  # supports / contradicts / context
    quote = Column(Text, default="")
    interpretation = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    character = relationship("Character", back_populates="evidence_spans")


class MemoryItem(Base):
    """长期记忆条目：从证据中沉淀出的事实、情绪、语用和关系模式"""
    __tablename__ = "memory_items"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    memory_type = Column(String(50), default="fact")  # fact / emotion / pragmatics / relationship / diagnosis
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=0.0)
    evidence_ids = Column(JSON, default=list)
    source = Column(String(100), default="")
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    character = relationship("Character", back_populates="memory_items")


class PersonalitySnapshot(Base):
    """人格画像版本快照：用于后续长上下文复盘、diff 和回滚"""
    __tablename__ = "personality_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    version = Column(Integer, default=1)
    profile_json = Column(JSON, default=dict)
    supporting_evidence = Column(JSON, default=list)
    conflicting_evidence = Column(JSON, default=list)
    critic_result = Column(JSON, default=dict)
    source = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    character = relationship("Character", back_populates="personality_snapshots")


class AgentRun(Base):
    """Agent/工作流运行记录：第二阶段先用于可观测性，后续接 LangGraph trace"""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_name = Column(String(100), nullable=False)
    input_hash = Column(String(100), default="")
    status = Column(String(30), default="started")
    model_used = Column(String(100), default="")
    trace_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RetrievalTrace(Base):
    """混合检索追踪：记录一次证据包构建的候选来源、得分和最终证据"""
    __tablename__ = "retrieval_traces"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    speaker_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    listener_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    query_text = Column(Text, default="")
    strategy = Column(JSON, default=dict)
    evidence_pack = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class StructuredDiagnosis(Base):
    """结构化诊断报告：绑定证据、反证、替代解释和 Critic 复核结果"""
    __tablename__ = "structured_diagnoses"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    analysis_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    speaker_id = Column(Integer, ForeignKey("characters.id"), nullable=True, index=True)
    listener_id = Column(Integer, ForeignKey("characters.id"), nullable=True, index=True)
    diagnosis_type = Column(String(50), default="subtext")
    status = Column(String(30), default="draft")  # approved / downgraded / insufficient / failed
    confidence = Column(Float, default=0.0)
    result_json = Column(JSON, default=dict)
    critic_json = Column(JSON, default=dict)
    evidence_ids = Column(JSON, default=list)
    conflicting_evidence_ids = Column(JSON, default=list)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImportFile(Base):
    __tablename__ = "import_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    content_type = Column(String(100), default="")
    status = Column(String(30), default="previewed")
    version = Column(Integer, default=1)
    model_used = Column(String(100), default="ai-harness")
    summary = Column(Text)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    interaction_units = relationship("InteractionUnit", back_populates="import_file", cascade="all, delete-orphan")


class InteractionUnit(Base):
    __tablename__ = "interaction_units"

    id = Column(Integer, primary_key=True, index=True)
    import_file_id = Column(Integer, ForeignKey("import_files.id"), nullable=False)
    source_line_index = Column(Integer, default=0)
    source_text_snippet = Column(Text, default="")
    speaker = Column(String(100), default="")
    receiver = Column(String(100), default="")
    receiver_confidence = Column(Float, default=0.0)
    receiver_state = Column(String(20), default="inferred")
    content = Column(Text, default="")
    intent = Column(String(200), default="")
    intent_confidence = Column(Float, default=0.0)
    intent_state = Column(String(20), default="inferred")
    strategy = Column(String(200), default="")
    strategy_confidence = Column(Float, default=0.0)
    strategy_state = Column(String(20), default="inferred")
    emotion = Column(String(200), default="")
    emotion_confidence = Column(Float, default=0.0)
    emotion_state = Column(String(20), default="inferred")
    interaction_type = Column(String(100), default="")
    interaction_confidence = Column(Float, default=0.0)
    interaction_state = Column(String(20), default="inferred")
    psychological_label = Column(String(200), default="")
    context_window = Column(JSON, default=list)
    analysis = Column(JSON, default=dict)
    event_payload = Column(JSON, default=dict)
    relationship_payload = Column(JSON, default=dict)
    conversation_message_id = Column(Integer, nullable=True)
    character_event_id = Column(Integer, nullable=True)
    relationship_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    import_file = relationship("ImportFile", back_populates="interaction_units")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="新对话")
    scenario = Column(String(100), default="general")
    is_readonly = Column(Boolean, default=False)
    source_import_file_id = Column(Integer, ForeignKey("import_files.id"), nullable=True)
    active_branch_id = Column(String(80), nullable=True)
    active_branch_point_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("messages.id"), nullable=True)   # for branching
    branch_label = Column(String(50), nullable=True)
    branch_id = Column(String(80), nullable=True)

    role = Column(String(20), nullable=False)          # user / assistant / system
    message_index = Column(Integer, default=0)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    character_name = Column(String(100))
    receiver_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    receiver_name = Column(String(100))
    content = Column(Text, nullable=False)
    intent = Column(String(200))
    strategy = Column(String(200))
    emotion = Column(String(200))
    source_type = Column(String(20), default="chat")
    readonly = Column(Boolean, default=False)

    # Analysis layer
    inner_monologue = Column(Text)
    emotion_label = Column(String(50))
    emotion_score = Column(Float)
    subtext = Column(Text)
    psychological_tag = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    children = relationship("Message", foreign_keys=[parent_id])

    @property
    def message_id(self):
        return self.id

    @property
    def speaker_id(self):
        return self.character_id

    @property
    def speaker_name(self):
        return self.character_name

    @property
    def timestamp(self):
        return self.created_at
