from pathlib import Path
import sqlite3
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.database import get_db, DB_PATH

def migrate():
    print(f"Applying migration to {DB_PATH}...")
    
    schema_sql = """
    CREATE TABLE IF NOT EXISTS masters_account (
        account_code TEXT PRIMARY KEY,
        account_name TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    with get_db() as conn:
        try:
            conn.executescript(schema_sql)
            print("Migration successful: Created `masters_account` table.")
            
            # Verify
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='masters_account'")
            if cursor.fetchone():
                print("Verification OK: Table exists.")
            else:
                print("Verification FAILED: Table not found.")
                
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
