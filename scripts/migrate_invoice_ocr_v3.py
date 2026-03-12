import sqlite3
import sys
import os

# プロジェクトルートをパスに追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.database import DB_PATH

def migrate():
    print(f"Migrating database v3: {DB_PATH}")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # 既存のカラムを確認
        cursor.execute("PRAGMA table_info(invoice_ocr_results)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # status 追加
        if "status" not in columns:
            print("Adding status column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN status TEXT")
            
        # detected_date 追加 (発行日)
        if "detected_date" not in columns:
            print("Adding detected_date column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN detected_date TEXT")

        # has_ringi 追加 (稟議書有無)
        if "has_ringi" not in columns:
            print("Adding has_ringi column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN has_ringi INTEGER DEFAULT 0")
        
        conn.commit()
    
    print("Migration v3 completed.")

if __name__ == "__main__":
    migrate()
