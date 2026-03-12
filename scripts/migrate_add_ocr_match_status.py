
import sys
import os
import sqlite3
sys.path.append(os.getcwd())
from infra.database import DB_PATH

def migrate():
    print(f"Migrating database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(output_summary)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "ocr_match_status" not in columns:
            print("Adding ocr_match_status column...")
            cursor.execute("ALTER TABLE output_summary ADD COLUMN ocr_match_status TEXT")
            print("Column added.")
        else:
            print("ocr_match_status column already exists.")
            
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
