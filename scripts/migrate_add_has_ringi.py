"""
マイグレーション: invoice_ocr_results テーブルに has_ringi カラムを追加

実行方法:
    python scripts/migrate_add_has_ringi.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "app.db"

def migrate():
    print("[INFO] Starting migration: Add has_ringi column to invoice_ocr_results")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # カラムが既に存在するか確認
        cursor.execute("PRAGMA table_info(invoice_ocr_results)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "has_ringi" in columns:
            print("[INFO] Column 'has_ringi' already exists. Skipping migration.")
            return
        
        # カラムを追加
        print("[INFO] Adding 'has_ringi' column...")
        cursor.execute("""
            ALTER TABLE invoice_ocr_results 
            ADD COLUMN has_ringi INTEGER DEFAULT 0
        """)
        
        conn.commit()
        print("[SUCCESS] Migration completed successfully!")

if __name__ == "__main__":
    migrate()
