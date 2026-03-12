
import sqlite3
import sys
from pathlib import Path

# DBパス設定
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"

def migrate():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Database not found. Please run apply_schema.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. masters_assign_dept_override に dept_name カラムを追加
    try:
        # カラム存在チェック
        cursor.execute("PRAGMA table_info(masters_assign_dept_override)")
        columns = [info[1] for info in cursor.fetchall()]
        if "dept_name" not in columns:
            print("Adding dept_name column to masters_assign_dept_override...")
            cursor.execute("ALTER TABLE masters_assign_dept_override ADD COLUMN dept_name TEXT")
        else:
            print("dept_name column already exists in masters_assign_dept_override.")
    except Exception as e:
        print(f"Error migrating masters_assign_dept_override: {e}")

    # 2. masters_assign_vendor に vendor_name カラムを追加
    try:
        # カラム存在チェック
        cursor.execute("PRAGMA table_info(masters_assign_vendor)")
        columns = [info[1] for info in cursor.fetchall()]
        if "vendor_name" not in columns:
            print("Adding vendor_name column to masters_assign_vendor...")
            cursor.execute("ALTER TABLE masters_assign_vendor ADD COLUMN vendor_name TEXT")
        else:
            print("vendor_name column already exists in masters_assign_vendor.")
    except Exception as e:
        print(f"Error migrating masters_assign_vendor: {e}")

    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
