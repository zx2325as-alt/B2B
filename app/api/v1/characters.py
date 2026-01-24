from typing import List, Union, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.domain_schemas import (
    CharacterCreate, CharacterUpdate, CharacterResponse,
    RelationshipCreate, RelationshipUpdate, RelationshipResponse
)
from app.services.character_service import character_service

router = APIRouter()

@router.post("/", response_model=CharacterResponse)
def create_character(character: CharacterCreate, db: Session = Depends(get_db)):
    return character_service.create_character(db=db, character=character)

@router.get("/", response_model=List[CharacterResponse])
def read_characters(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return character_service.get_characters(db, skip=skip, limit=limit)

@router.get("/{character_id}", response_model=CharacterResponse)
def read_character(character_id: int, db: Session = Depends(get_db)):
    db_character = character_service.get_character(db, character_id=character_id)
    if db_character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return db_character

@router.put("/{character_id}", response_model=CharacterResponse)
def update_character(character_id: int, character: CharacterUpdate, db: Session = Depends(get_db)):
    db_character = character_service.update_character(db, character_id=character_id, character=character)
    if db_character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return db_character

@router.delete("/{character_id}", response_model=dict)
def delete_character(character_id: int, db: Session = Depends(get_db)):
    success = character_service.delete_character(db, character_id=character_id)
    if not success:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "success", "message": f"Character {character_id} deleted"}

@router.get("/relationships/all", response_model=List[RelationshipResponse])
def get_all_relationships(db: Session = Depends(get_db)):
    return character_service.get_all_relationships(db)

@router.post("/relationships", response_model=RelationshipResponse)
def create_relationship(relation: RelationshipCreate, db: Session = Depends(get_db)):
    # Verify source/target exist
    if not character_service.get_character(db, relation.source_id):
        raise HTTPException(status_code=404, detail="Source character not found")
    if not character_service.get_character(db, relation.target_id):
        raise HTTPException(status_code=404, detail="Target character not found")
    return character_service.create_relationship(db=db, relation=relation)

@router.put("/relationships/{relationship_id}", response_model=RelationshipResponse)
def update_relationship(relationship_id: int, relation: RelationshipUpdate, db: Session = Depends(get_db)):
    db_rel = character_service.update_relationship(
        db, 
        relationship_id=relationship_id, 
        details=relation.details, 
        relation_type=relation.relation_type,
        strength=relation.strength,
        sentiment=relation.sentiment
    )
    if not db_rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return db_rel

@router.delete("/relationships/{relationship_id}", response_model=dict)
def delete_relationship(relationship_id: int, db: Session = Depends(get_db)):
    success = character_service.delete_relationship(db, relationship_id=relationship_id)
    if not success:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return {"status": "success", "message": f"Relationship {relationship_id} deleted"}

@router.post("/import", summary="批量导入角色和关系")
def import_characters(data: Union[List[Dict[str, Any]], Dict[str, Any]], db: Session = Depends(get_db)):
    """
    批量导入角色和关系 (Batch Import)
    
    Accepts:
    1. A list of characters (legacy support).
    2. A dict with keys "characters" and "relationships".
    """
    return character_service.import_data(db, data)

@router.get("/{character_id}/relationships", response_model=List[RelationshipResponse])
def get_character_relationships(character_id: int, db: Session = Depends(get_db)):
    return character_service.get_relationships(db, character_id=character_id)
