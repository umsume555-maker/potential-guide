import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.database import DB_PATH

def migrate():
    print(f"Migrating database: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    
    # 1. Add table vendor_reconciliation_target
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                vendor_code TEXT PRIMARY KEY,
                vendor_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("Created table: vendor_reconciliation_target")
    except Exception as e:
        print(f"Error creating table: {e}")

    # 2. Add column is_monthly to output_summary
    try:
        # Check if column exists
        cursor = conn.execute("PRAGMA table_info(output_summary)")
        columns = [row[1] for row in cursor.fetchall()]
        if "is_monthly" not in columns:
            conn.execute("ALTER TABLE output_summary ADD COLUMN is_monthly TEXT")
            print("Added column: is_monthly to output_summary")
        else:
            print("Column is_monthly already exists")
    except Exception as e:
        print(f"Error adding column: {e}")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
