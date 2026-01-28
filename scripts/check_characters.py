import sqlite3
import os

DB_PATH = "e:/python/conda/B2B/data/btb_v2.db"

def list_characters():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, name FROM characters")
        rows = cursor.fetchall()
        if not rows:
            print("No characters found in database.")
        else:
            print(f"Found {len(rows)} characters:")
            for row in rows:
                print(f"ID: {row[0]}, Name: {row[1]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    list_characters()
