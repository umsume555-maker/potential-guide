
import sqlite3
import os
from pathlib import Path

# DBパス設定
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"
SCHEMA_PATH = BASE_DIR / "infra" / "schema.sql"

def apply_schema():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Database not found. Creating new...")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        
    try:
        # スクリプトとして実行（複数ステートメント対応）
        conn.executescript(schema_sql)
        print("Schema applied successfully.")
        
        # テーブル確認
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("Tables in DB:", [t[0] for t in tables])
        
    except Exception as e:
        print(f"Error applying schema: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    apply_schema()
