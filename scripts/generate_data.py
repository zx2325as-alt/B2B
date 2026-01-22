import random
import uuid
import time
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.models.sql_models import DialogueLog, Scenario

# Ensure tables exist
Base.metadata.create_all(bind=engine)

def generate_mock_data():
    db = SessionLocal()
    print("Generating mock data...")
    
    scenarios = db.query(Scenario).all()
    scenario_ids = [s.id for s in scenarios] + [None]
    
    users = [f"user_{i}" for i in range(1, 51)]
    
    intents = ["ask_policy", "chitchat", "complaint", "check_status"]
    
    # Generate 1000 logs
    logs = []
    for i in range(1000):
        latency = random.uniform(100, 2000) # 100ms to 2s
        rating = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.05, 0.2, 0.4, 0.3])[0]
        
        log = DialogueLog(
            session_id=str(uuid.uuid4()),
            user_id=random.choice(users),
            user_input=f"Mock question {i}",
            scenario_id=random.choice(scenario_ids),
            bot_response=f"Mock response {i}",
            nlu_result={"intent": random.choice(intents), "confidence": 0.9},
            reasoning_content=f"Mock reasoning step 1... step 2...",
            latency_ms=latency,
            rating=rating,
            tokens_used=random.randint(50, 500)
        )
        logs.append(log)
        
        if i % 100 == 0:
            print(f"Generated {i} logs...")
            
    db.bulk_save_objects(logs)
    db.commit()
    print("Successfully added 1000 mock logs.")
    db.close()

if __name__ == "__main__":
    generate_mock_data()
