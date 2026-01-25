import pytest
from app.services.character_service import character_service
from app.models.domain_schemas import CharacterCreate, CharacterUpdate

def test_create_character(db_session):
    character_in = CharacterCreate(
        name="Test Character",
        attributes={"role": "test", "age": 20},
        traits=["brave", "smart"],
        dynamic_profile={"mood": "happy"}
    )
    character = character_service.create_character(db_session, character_in)
    
    assert character.name == "Test Character"
    assert character.attributes["role"] == "test"
    assert character.id is not None

def test_get_character(db_session):
    character_in = CharacterCreate(name="Alice", attributes={}, traits=[], dynamic_profile={})
    created = character_service.create_character(db_session, character_in)
    
    fetched = character_service.get_character(db_session, created.id)
    assert fetched.name == "Alice"
    assert fetched.id == created.id

def test_update_character(db_session):
    character_in = CharacterCreate(name="Bob", attributes={}, traits=[], dynamic_profile={})
    created = character_service.create_character(db_session, character_in)
    
    update_data = CharacterUpdate(name="Bobby")
    updated = character_service.update_character(db_session, created.id, update_data)
    
    assert updated.name == "Bobby"
    assert updated.id == created.id
