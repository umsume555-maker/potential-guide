
import sqlite3
import sys
from pathlib import Path

# プロジェクトルートディレクトリ
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"

def seed_departments():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # データ定義
        departments = [
            ("1001", "管理部", "SGA"),     # 販管費
            ("2001", "製造部", "COST"),    # 原価
            ("2002", "工場庶務", "COST"),  # 原価
            ("3001", "営業部", "SGA"),     # 販管費
            ("9000", "共通部門", "SGA"),   # 販管費
        ]

        print("Seeding masters_department...")
        
        # 既存データの確認 (オプション: 重複を避けるか、DELETEするか)
        # 今回は一旦DELETEして初期化
        cursor.execute("DELETE FROM masters_department")
        
        cursor.executemany(
            "INSERT INTO masters_department (dept_code, dept_name, dept_type) VALUES (?, ?, ?)",
            departments
        )
        
        conn.commit()
        print(f"Success: Inserted {len(departments)} departments.")
        
        # 確認
        cursor.execute("SELECT * FROM masters_department")
        rows = cursor.fetchall()
        for row in rows:
            print(row)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    seed_departments()
