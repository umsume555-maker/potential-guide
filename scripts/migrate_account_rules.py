
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"

def migrate_schema():
    print(f"Migrating DB at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. Check if table exists and backup/drop
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='rule_account_master'")
        if cursor.fetchone()[0] > 0:
            print("Dropping existing rule_account_master...")
            cursor.execute("DROP TABLE rule_account_master")
            
        # 2. Create new table
        print("Creating new rule_account_master...")
        sql = """
            CREATE TABLE rule_account_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_code TEXT NOT NULL,
                scope_type TEXT NOT NULL, -- 'DEPT' / 'DEPT_TYPE' / 'ANY'
                scope_key TEXT,           -- dept_code / 'SGA'|'COST' / ''
                expected_account TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                UNIQUE(vendor_code, scope_type, scope_key)
            )
        """
        cursor.execute(sql)
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_schema()
