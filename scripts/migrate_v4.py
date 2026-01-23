import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "btb_v2.db")

def migrate():
    print(f"Migrating database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(character_feedback)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "log_id" not in columns:
            print("Adding log_id column to character_feedback table...")
            cursor.execute("ALTER TABLE character_feedback ADD COLUMN log_id INTEGER")
        else:
            print("log_id column already exists in character_feedback table.")
            
        conn.commit()
        print("Migration successful!")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
