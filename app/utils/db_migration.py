import sqlite3
from app.core.config import settings

def migrate():
    print("Checking database migrations...")
    db_url = settings.DATABASE_URL
    if "sqlite" not in db_url:
        print("Skipping migration for non-SQLite database.")
        return

    # Extract path from sqlite:///./sql_app.db
    db_path = db_url.replace("sqlite:///", "")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if 'rating' column exists in 'conversation_segments'
        cursor.execute("PRAGMA table_info(conversation_segments)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "rating" not in columns:
            print("Adding 'rating' column to conversation_segments...")
            cursor.execute("ALTER TABLE conversation_segments ADD COLUMN rating INTEGER DEFAULT 0")
        
        if "feedback" not in columns:
            print("Adding 'feedback' column to conversation_segments...")
            cursor.execute("ALTER TABLE conversation_segments ADD COLUMN feedback TEXT")
            
        conn.commit()
        conn.close()
        print("Migration complete.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
