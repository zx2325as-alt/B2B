import sqlite3
import os
from pathlib import Path

DB_PATH = Path("e:/python/conda/B2B/data/btb_v2.db")

def migrate_db():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. Check current columns
        cursor.execute("PRAGMA table_info(character_events)")
        columns_info = cursor.fetchall()
        column_names = [col[1] for col in columns_info]
        print(f"Current columns: {column_names}")

        # 2. Add 'event_time' if missing
        if "event_time" not in column_names:
            print("Adding 'event_time' column...")
            cursor.execute("ALTER TABLE character_events ADD COLUMN event_time VARCHAR")
            # Migrate data if event_date exists
            if "event_date" in column_names:
                cursor.execute("UPDATE character_events SET event_time = event_date")

        # 3. Add 'description' if missing
        if "description" not in column_names:
            print("Adding 'description' column...")
            cursor.execute("ALTER TABLE character_events ADD COLUMN description TEXT")
            # Migrate data if summary exists
            if "summary" in column_names:
                cursor.execute("UPDATE character_events SET description = summary")

        # 4. Add 'source_log_id' if missing
        if "source_log_id" not in column_names:
            print("Adding 'source_log_id' column...")
            cursor.execute("ALTER TABLE character_events ADD COLUMN source_log_id INTEGER")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
