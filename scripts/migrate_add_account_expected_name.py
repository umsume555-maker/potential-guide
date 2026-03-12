from pathlib import Path
import sqlite3
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.database import get_db, DB_PATH

def migrate():
    print(f"Applying migration to {DB_PATH}...")
    
    with get_db() as conn:
        try:
            # check if column exists
            cursor = conn.execute("PRAGMA table_info(output_summary)")
            columns = [row["name"] for row in cursor]
            
            if "account_expected_name" in columns:
                print("Column `account_expected_name` already exists. Skipping.")
                return

            print("Adding `account_expected_name` column to `output_summary`...")
            conn.execute("ALTER TABLE output_summary ADD COLUMN account_expected_name TEXT")
            print("Migration successful.")
                
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
