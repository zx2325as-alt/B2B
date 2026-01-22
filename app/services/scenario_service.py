from sqlalchemy.orm import Session
from app.models.sql_models import Scenario
from app.models.domain_schemas import ScenarioCreate, ScenarioUpdate
import yaml
import time
from pathlib import Path
from app.core.config import settings
from app.utils.logger import logger

class ScenarioService:
    def sync_scenarios_from_yaml(self, db: Session):
        """
        Syncs scenarios defined in 'prompts.yaml' (under 'scenarios' key) 
        and 'scenarios/' directory YAML files to the database.
        This allows 'Configuration over Code'.
        """
        all_scenarios = []

        # 1. Load from prompts.yaml (Centralized Config)
        config_scenarios = settings.PROMPTS.get("scenarios", [])
        if config_scenarios:
            logger.info(f"Found {len(config_scenarios)} scenarios in prompts.yaml")
            all_scenarios.extend(config_scenarios)

        # 2. Load from scenarios/ directory (Legacy / External files)
        scenarios_dir = settings.BASE_DIR / "scenarios"
        if scenarios_dir.exists():
            for yaml_file in scenarios_dir.glob("*.yaml"):
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data and "name" in data:
                        all_scenarios.append(data)
                except Exception as e:
                    logger.error(f"Failed to load scenario from {yaml_file}: {e}")

        # 3. Sync to DB
        for data in all_scenarios:
            try:
                if "name" not in data:
                    continue
                
                # Check if exists
                existing = db.query(Scenario).filter(Scenario.name == data["name"]).first()
                if existing:
                    # Update only if changed
                    changed = False
                    fields_map = {
                        "domain": data.get("domain", existing.domain),
                        "description": data.get("description", existing.description),
                        "rules": data.get("rules", existing.rules),
                        "system_role": data.get("system_role", existing.system_role),
                        "processing_steps": data.get("processing_steps", existing.processing_steps),
                        "prompt_template": data.get("prompt_template", existing.prompt_template),
                        "eval_criteria": data.get("eval_criteria", existing.eval_criteria)
                    }

                    for attr, new_value in fields_map.items():
                        current_value = getattr(existing, attr)
                        if current_value != new_value:
                            setattr(existing, attr, new_value)
                            changed = True
                    
                    if changed:
                        logger.info(f"Updated scenario: {data['name']}")
                else:
                    # Create
                    new_scenario = Scenario(
                        name=data["name"],
                        domain=data.get("domain", "General"),
                        description=data.get("description", ""),
                        rules=data.get("rules", {}),
                        system_role=data.get("system_role", ""),
                        processing_steps=data.get("processing_steps", {}),
                        prompt_template=data.get("prompt_template", ""),
                        eval_criteria=data.get("eval_criteria", {})
                    )
                    db.add(new_scenario)
                    logger.info(f"Created scenario: {data['name']}")
            except Exception as e:
                logger.error(f"Failed to sync scenario {data.get('name')}: {e}")
                db.rollback() 
        
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to commit scenarios: {e}")
            db.rollback()

    def get_scenario(self, db: Session, scenario_id: int):
        return db.query(Scenario).filter(Scenario.id == scenario_id).first()

    def get_scenarios(self, db: Session, skip: int = 0, limit: int = 100):
        start = time.time()
        try:
            results = db.query(Scenario).offset(skip).limit(limit).all()
            duration = time.time() - start
            if duration > 0.5:
                logger.warning(f"Slow DB Query (get_scenarios): {duration:.4f}s")
            return results
        except Exception as e:
            logger.error(f"DB Query Failed (get_scenarios): {e}")
            raise e

    def create_scenario(self, db: Session, scenario: ScenarioCreate):
        db_scenario = Scenario(**scenario.dict())
        db.add(db_scenario)
        db.commit()
        db.refresh(db_scenario)
        return db_scenario

    def update_scenario(self, db: Session, scenario_id: int, scenario: ScenarioUpdate):
        db_scenario = self.get_scenario(db, scenario_id)
        if not db_scenario:
            return None
        
        update_data = scenario.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_scenario, key, value)
        
        db.commit()
        db.refresh(db_scenario)
        return db_scenario

    def delete_scenario(self, db: Session, scenario_id: int):
        db_scenario = self.get_scenario(db, scenario_id)
        if db_scenario:
            db.delete(db_scenario)
            db.commit()
        return db_scenario

scenario_service = ScenarioService()
