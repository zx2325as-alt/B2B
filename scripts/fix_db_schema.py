import sqlite3
import os

DB_PATH = "e:/python/conda/B2B/data/btb_v2.db"

def check_schema():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(conversation_segments)")
        columns = cursor.fetchall()
        if not columns:
            print("Table 'conversation_segments' does not exist.")
        else:
            print("Columns in 'conversation_segments':")
            col_names = [col[1] for col in columns]
            print(col_names)
            
            # Check for missing columns
            missing = []
            for needed in ['analysis', 'rating', 'feedback']:
                if needed not in col_names:
                    missing.append(needed)
            
            if missing:
                print(f"Missing columns: {missing}")
                for col in missing:
                    print(f"Adding column: {col}")
                    if col == 'analysis':
                        cursor.execute(f"ALTER TABLE conversation_segments ADD COLUMN {col} JSON DEFAULT '{{}}'")
                    elif col == 'rating':
                        cursor.execute(f"ALTER TABLE conversation_segments ADD COLUMN {col} INTEGER DEFAULT 0")
                    elif col == 'feedback':
                        cursor.execute(f"ALTER TABLE conversation_segments ADD COLUMN {col} TEXT")
                conn.commit()
                print("Columns added successfully.")
            else:
                print("All columns present.")
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_schema()
