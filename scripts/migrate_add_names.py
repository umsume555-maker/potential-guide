"""
マイグレーション: invoice_ocr_results テーブルに dept_name, vendor_name カラムを追加

実行方法:
    python scripts/migrate_add_names.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "payment_check.db"

def migrate():
    print("[INFO] Starting migration: Add dept_name, vendor_name columns to invoice_ocr_results")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # カラムが既に存在するか確認
        cursor.execute("PRAGMA table_info(invoice_ocr_results)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # dept_name 追加
        if "dept_name" not in columns:
            print("[INFO] Adding 'dept_name' column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN dept_name TEXT")
        else:
            print("[INFO] Column 'dept_name' already exists. Skipping.")
            
        # vendor_name 追加
        if "vendor_name" not in columns:
            print("[INFO] Adding 'vendor_name' column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN vendor_name TEXT")
        else:
            print("[INFO] Column 'vendor_name' already exists. Skipping.")
        
        conn.commit()
        print("[SUCCESS] Migration completed successfully!")

if __name__ == "__main__":
    migrate()
