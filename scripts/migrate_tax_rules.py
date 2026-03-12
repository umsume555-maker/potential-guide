import sqlite3
import os
from pathlib import Path

# パス設定
db_path = Path(os.getenv('LOCALAPPDATA')) / 'PayCheckTool' / 'app.db'

def migrate():
    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    
    try:
        # テーブル作成
        print("Creating table rule_tax_rules...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rule_tax_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_code TEXT NOT NULL,
                scope_type TEXT NOT NULL,       -- 'DEPT_TYPE', 'DEPT', 'ANY'
                scope_key TEXT,                 -- 'COST', 'SGA', 部門コード
                expected_tax TEXT NOT NULL,     -- 税区分
                reason TEXT,
                updated_by TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(vendor_code, scope_type, scope_key)
            )
        """)
        
        # インデックス
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rule_tax_rules_vendor ON rule_tax_rules(vendor_code)")
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
