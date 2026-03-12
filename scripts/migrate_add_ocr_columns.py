
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "payment_check.db"

def migrate():
    print(f"Migrating database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute("PRAGMA table_info(output_summary)")
    columns = {row[1] for row in cursor.fetchall()}
    
    try:
        if "ocr_amount" not in columns:
            print("Adding ocr_amount column...")
            cursor.execute("ALTER TABLE output_summary ADD COLUMN ocr_amount TEXT")
        
        if "ocr_file_link" not in columns:
            print("Adding ocr_file_link column...")
            cursor.execute("ALTER TABLE output_summary ADD COLUMN ocr_file_link TEXT")
            
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
