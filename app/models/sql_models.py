from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(Text, nullable=True)
    domain = Column(String, index=True) # e.g., "Medical", "CustomerService"
    rules = Column(JSON, default={}) # Dialogue flow rules
    
    # Advanced LLM Config
    system_role = Column(Text, nullable=True) # "Who am I"
    processing_steps = Column(JSON, default={}) # "How to think" (CoT steps)
    prompt_template = Column(Text, nullable=True) # Full prompt template
    
    eval_criteria = Column(JSON, default={}) # Scoring criteria
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(String, primary_key=True, index=True) # UUID
    user_id = Column(String, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    
    # Session state/context
    is_active = Column(Integer, default=1)
    summary = Column(Text, nullable=True) # Running summary of conversation
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    character = relationship("Character")
    scenario = relationship("Scenario")

class DialogueLog(Base):
    """
    Log for every dialogue turn, used for evaluation and analytics.
    """
    __tablename__ = "dialogue_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    user_id = Column(String, index=True)
    
    # Inputs
    user_input = Column(Text)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    
    # Outputs
    bot_response = Column(Text)
    nlu_result = Column(JSON) # Intent, etc.
    reasoning_content = Column(Text, nullable=True) # CoT content
    
    # Metrics
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    
    # Evaluation (Human or Auto)
    rating = Column(Integer, nullable=True) # 1-5
    feedback_text = Column(Text, nullable=True)
    is_archived_for_tuning = Column(Integer, default=0) # 0=No, 1=Yes
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AnalysisLog(Base):
    """
    Log for Long Conversation Analysis (replacing local JSON file).
    """
    __tablename__ = "analysis_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=True) # Optional link to a session
    
    # Content
    text_content = Column(Text) # The raw input text
    character_names = Column(JSON, default=[]) # List of involved characters
    
    # Results
    summary = Column(Text, nullable=True) # Short summary
    markdown_report = Column(Text, nullable=True) # Full Markdown report
    structured_data = Column(JSON, default={}) # The JSON output from LLM
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ConversationSegment(Base):
    """
    Real-time conversation segments.
    """
    __tablename__ = "conversation_segments"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True) # Group segments into a session
    
    text = Column(Text)
    speaker_id = Column(String, index=True) # Voice Profile ID
    speaker_name = Column(String) # Display Name
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True) # Mapped Character
    
    emotion = Column(JSON, default={}) # {label: score}
    metrics = Column(JSON, default={}) # Pitch, energy, etc.
    analysis = Column(JSON, default={}) # Deep analysis (Inner OS, Subtext)
    
    # Rating & Feedback
    rating = Column(Integer, default=0) # 1-5
    feedback = Column(Text, nullable=True)
    
    start_time = Column(Float, nullable=True) # Relative time in session
    end_time = Column(Float, nullable=True)
    
    audio_path = Column(String, nullable=True) # Path to saved wav segment
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    # Basic attributes: age, gender, occupation, etc.
    attributes = Column(JSON, default={}) 
    # Behavioral traits: personality, speaking style, etc.
    traits = Column(JSON, default={})
    # Dynamic profile: System's core memory of the character, updated by analysis engine
    dynamic_profile = Column(JSON, default={})
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    relationships_as_source = relationship("Relationship", foreign_keys="[Relationship.source_id]", back_populates="source")
    relationships_as_target = relationship("Relationship", foreign_keys="[Relationship.target_id]", back_populates="target")

class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("characters.id"))
    target_id = Column(Integer, ForeignKey("characters.id"))
    relation_type = Column(String, index=True) # e.g., "Friend", "Doctor-Patient"
    details = Column(JSON, default={}) # Interaction history summary or specific notes
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("Character", foreign_keys=[source_id], back_populates="relationships_as_source")
    target = relationship("Character", foreign_keys=[target_id], back_populates="relationships_as_target")

    # New fields for Dynamic Relationships
    strength = Column(Integer, default=5) # 1-10
    sentiment = Column(Integer, default=0) # -5 to +5
    last_updated = Column(DateTime(timezone=True), onupdate=func.now())

class CharacterObservation(Base):
    """
    Stores pending observations extracted from dialogue analysis.
    Needs user approval to be merged into Character.dynamic_profile.
    """
    __tablename__ = "character_observations"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"))
    session_id = Column(String, index=True)
    
    content = Column(JSON) # The observation content (e.g., {"trait": "Impatient", "evidence": "..."})
    confidence = Column(Float, default=0.0)
    
    status = Column(String, default="pending") # pending, approved, rejected, merged
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    character = relationship("Character")

class CharacterFeedback(Base):
    """
    Stores specific feedback on character accuracy.
    """
    __tablename__ = "character_feedback"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"))
    session_id = Column(String, index=True)
    log_id = Column(Integer, nullable=True)
    
    is_accurate = Column(Integer) # 1=Yes, 0=No
    reason_category = Column(String, nullable=True) # e.g., "Wrong Emotion", "Missed Intent"
    comment = Column(Text, nullable=True)
    context_data = Column(JSON, nullable=True) # Snapshot of context & analysis
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    character = relationship("Character")

class CharacterVersion(Base):
    """To track history of character changes"""
    __tablename__ = "character_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"))
    version = Column(Integer)
    attributes_snapshot = Column(JSON)
    traits_snapshot = Column(JSON)
    dynamic_profile_snapshot = Column(JSON) # Snapshot of dynamic profile
    change_reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FeedbackLog(Base):
    """
    Stores user feedback (thumbs up/down or 1-5 stars) for analysis reports.
    Used for RLHF/SFT data collection.
    """
    __tablename__ = "feedback_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    
    # Context
    user_input = Column(Text) # The original text analyzed
    model_output = Column(Text) # The report generated
    
    # Feedback
    rating = Column(Integer) # 1=ThumbDown, 5=ThumbUp (or 1-5 scale)
    comment = Column(Text, nullable=True) # User's specific complaint
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class EvolutionCase(Base):
    """
    Stores 'Golden Triples' (Input, Bad Output, Improved Output) for model fine-tuning.
    """
    __tablename__ = "evolution_cases"

    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(Integer, ForeignKey("feedback_logs.id"))
    
    original_input = Column(Text)
    bad_output = Column(Text)
    improved_output = Column(Text) # Generated by "Review Analysis"
    
    diagnosis = Column(Text) # LLM's explanation of what went wrong
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CharacterEvent(Base):
    """
    Auto-generated events from analysis for timeline.
    """
    __tablename__ = "character_events"
    
    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"))
    
    event_time = Column(String) # YYYY-MM-DD
    description = Column(Text)
    source_log_id = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
