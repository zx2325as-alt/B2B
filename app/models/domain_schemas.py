from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime

# Scenario Schemas
class ScenarioBase(BaseModel):
    name: str
    description: Optional[str] = None
    domain: str
    rules: Dict[str, Any] = {}
    system_role: Optional[str] = None
    processing_steps: Union[Dict[str, Any], str, List[Any]] = {}
    prompt_template: Optional[str] = None
    eval_criteria: Dict[str, Any] = {}

class ScenarioCreate(ScenarioBase):
    pass

class ScenarioUpdate(ScenarioBase):
    name: Optional[str] = None
    domain: Optional[str] = None
    system_role: Optional[str] = None
    processing_steps: Optional[Union[Dict[str, Any], str, List[Any]]] = None
    prompt_template: Optional[str] = None

class ScenarioResponse(ScenarioBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Character Schemas
class CharacterBase(BaseModel):
    name: str
    attributes: Dict[str, Any] = {}
    traits: Dict[str, Any] = {}
    dynamic_profile: Dict[str, Any] = {}

class CharacterCreate(CharacterBase):
    pass

class CharacterUpdate(CharacterBase):
    name: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    traits: Optional[Dict[str, Any]] = None
    dynamic_profile: Optional[Dict[str, Any]] = None
    version_note: Optional[str] = None # Reason for update

class CharacterResponse(CharacterBase):
    id: int
    version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Relationship Schemas
class RelationshipBase(BaseModel):
    source_id: int
    target_id: int
    relation_type: str
    details: Dict[str, Any] = {}
    strength: Optional[int] = 5
    sentiment: Optional[int] = 0

class RelationshipCreate(RelationshipBase):
    pass

class RelationshipUpdate(BaseModel):
    relation_type: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    strength: Optional[int] = None
    sentiment: Optional[int] = None

class RelationshipResponse(RelationshipBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
