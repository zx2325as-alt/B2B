import sqlite3
import os
import sys

# Try to find the database file relative to this script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "btb_v2.db")

def add_column_if_not_exists(cursor, table, column, definition):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added column '{column}' to table '{table}'.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Column '{column}' already exists in table '{table}'.")
        else:
            print(f"Error adding column '{column}' to '{table}': {e}")

def create_table_if_not_exists(cursor, table_name, create_sql):
    try:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            print(f"Table '{table_name}' already exists.")
        else:
            cursor.execute(create_sql)
            print(f"Created table '{table_name}'.")
    except Exception as e:
        print(f"Error creating table '{table_name}': {e}")

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"Updating database schema for: {DB_PATH}")

    # 1. Update Relationships Table
    add_column_if_not_exists(cursor, "relationships", "strength", "INTEGER DEFAULT 5")
    add_column_if_not_exists(cursor, "relationships", "sentiment", "INTEGER DEFAULT 0")
    add_column_if_not_exists(cursor, "relationships", "last_updated", "TIMESTAMP")

    # 2. Create CharacterObservation Table
    create_table_if_not_exists(cursor, "character_observations", """
        CREATE TABLE character_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER,
            session_id VARCHAR,
            content JSON,
            confidence FLOAT DEFAULT 0.0,
            status VARCHAR DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(character_id) REFERENCES characters(id)
        )
    """)
    # Add indices if needed (basic ones usually created with table, but explicit is good)
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_character_observations_session_id ON character_observations (session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_character_observations_id ON character_observations (id)")
    except Exception as e:
        print(f"Index creation error: {e}")

    # 3. Create CharacterFeedback Table
    create_table_if_not_exists(cursor, "character_feedback", """
        CREATE TABLE character_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER,
            session_id VARCHAR,
            is_accurate INTEGER,
            reason_category VARCHAR,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(character_id) REFERENCES characters(id)
        )
    """)
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_character_feedback_session_id ON character_feedback (session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_character_feedback_id ON character_feedback (id)")
    except Exception as e:
        print(f"Index creation error: {e}")

    conn.commit()
    conn.close()
    print("Migration V3 completed.")

if __name__ == "__main__":
    main()
