import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "data", "app.db")
# Adjust path if necessary. Based on previous context, the db is likely at e:\python\conda\B2B\app.db or similar. 
# Let's check config or just assume standard location relative to script.
# Actually, let's try to locate the DB first or use the path from config.
# But for a simple script, I will try the default location.
# Wait, let's check where `get_db` gets it.
# It imports `SessionLocal` from `app.core.database`.
# Let's assume it's `app.db` in the root or `app/data`.
# I'll try to find it. But usually it's `sql_app.db` or `app.db`.

# Let's check `app/core/config.py` or `app/core/database.py` if I could.
# But to be safe, I will just use the path I found in previous turns or assume it.
# In `endpoints.py`, it uses `app.core.database`.
# Let's assume `app.db` is in the root directory `E:\python\conda\B2B`.

DB_PATH = r"E:\python\conda\B2B\data\btb_v2.db"

def migrate():
    print(f"Connecting to database at {DB_PATH}...")
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("Adding dynamic_profile_snapshot column to character_versions table...")
        cursor.execute("ALTER TABLE character_versions ADD COLUMN dynamic_profile_snapshot TEXT") # JSON is stored as TEXT in SQLite usually, or we can just use JSON type if supported, but TEXT is safe.
        conn.commit()
        print("Migration successful!")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("Column already exists. Skipping.")
        else:
            print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
