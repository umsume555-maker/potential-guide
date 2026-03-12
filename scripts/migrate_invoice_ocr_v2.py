import sqlite3
import sys
import os

# プロジェクトルートをパスに追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.database import DB_PATH

def migrate():
    print(f"Migrating database: {DB_PATH}")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # 既存のカラムを確認
        cursor.execute("PRAGMA table_info(invoice_ocr_results)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # dept_code 追加
        if "dept_code" not in columns:
            print("Adding dept_code column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN dept_code TEXT")
            
        # vendor_code 追加
        if "vendor_code" not in columns:
            print("Adding vendor_code column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN vendor_code TEXT")

        # target_decision_no 追加 (突合相手の決裁番号)
        if "target_decision_no" not in columns:
            print("Adding target_decision_no column...")
            cursor.execute("ALTER TABLE invoice_ocr_results ADD COLUMN target_decision_no TEXT")
        
        conn.commit()
    
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
