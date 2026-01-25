import sqlite3
import os

def fix_db():
    db_path = 'btb.db'
    print(f"Checking DB at: {os.path.abspath(db_path)}")
    
    if not os.path.exists(db_path):
        print("Error: btb.db not found!")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # List tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("Tables:", [t[0] for t in tables])
        
        if 'character_events' in [t[0] for t in tables]:
            # Check columns
            cursor.execute("PRAGMA table_info(character_events)")
            columns = [info[1] for info in cursor.fetchall()]
            print("Columns in character_events:", columns)
            
            if 'event_time' not in columns:
                print("Adding event_time column...")
                cursor.execute("ALTER TABLE character_events ADD COLUMN event_time TEXT")
                conn.commit()
                print("Done.")
            else:
                print("Column event_time already exists.")
        else:
            print("Table character_events does not exist. It might need to be created by the app.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_db()
