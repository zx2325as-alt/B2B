import sqlite3
import json
import os

# Database path (Adjusted to match config.yaml)
DB_PATH = r"e:\python\conda\PyTorch01\BtB\data\btb_v2.db"

def add_column_if_not_exists(cursor, table, column, definition):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added column '{column}' to table '{table}'.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Column '{column}' already exists in table '{table}'.")
        else:
            print(f"Error adding column '{column}' to '{table}': {e}")

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print(f"Updating database schema for: {DB_PATH}")

    # 1. Add dynamic_profile to characters table
    # Using JSON type (SQLite supports JSON text storage)
    add_column_if_not_exists(cursor, "characters", "dynamic_profile", "JSON DEFAULT '{}'")

    conn.commit()
    conn.close()
    print("Schema update completed.")

if __name__ == "__main__":
    main()
