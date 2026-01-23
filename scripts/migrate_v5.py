import sqlite3
import os

# Adjust path to point to the correct database file location
# Assuming the script is run from project root or scripts/ folder
# and data/ is in project root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "btb_v2.db")

def migrate():
    print(f"Migrating database at {DB_PATH}...")
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(character_feedback)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "context_data" not in columns:
            print("Adding context_data column to character_feedback table...")
            # SQLite doesn't have a native JSON type, it uses TEXT
            cursor.execute("ALTER TABLE character_feedback ADD COLUMN context_data TEXT")
        else:
            print("context_data column already exists in character_feedback table.")
            
        conn.commit()
        print("Migration successful!")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
