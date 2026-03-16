import sqlite3
import os
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent / "data" / "payment_check.db")

def migrate():
    print(f"Connecting to {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # カラム存在チェック
            cursor.execute("PRAGMA table_info(vendors)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if "gemini_flag" in columns:
                print("Column 'gemini_flag' already exists. Skipping.")
            else:
                print("Adding column 'gemini_flag'...")
                cursor.execute("ALTER TABLE vendors ADD COLUMN gemini_flag TEXT")
                conn.commit()
                print("Migration successful.")
                
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
