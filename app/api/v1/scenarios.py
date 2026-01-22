from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.domain_schemas import ScenarioCreate, ScenarioUpdate, ScenarioResponse
from app.services.scenario_service import scenario_service

router = APIRouter()

@router.post("/", response_model=ScenarioResponse)
def create_scenario(scenario: ScenarioCreate, db: Session = Depends(get_db)):
    return scenario_service.create_scenario(db=db, scenario=scenario)

@router.get("/", response_model=List[ScenarioResponse])
def read_scenarios(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return scenario_service.get_scenarios(db, skip=skip, limit=limit)

@router.get("/{scenario_id}", response_model=ScenarioResponse)
def read_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db_scenario = scenario_service.get_scenario(db, scenario_id=scenario_id)
    if db_scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return db_scenario

@router.put("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(scenario_id: int, scenario: ScenarioUpdate, db: Session = Depends(get_db)):
    db_scenario = scenario_service.update_scenario(db, scenario_id=scenario_id, scenario=scenario)
    if db_scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return db_scenario
