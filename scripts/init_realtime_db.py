import sys
import os
sys.path.append(os.getcwd())

from app.core.database import engine, Base
from app.models.sql_models import ConversationSegment

def init_db():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

if __name__ == "__main__":
    init_db()
