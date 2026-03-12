# scripts/migrate_invoice_ocr.py
import sys
import os
import sqlite3

# プロジェクトルートをパスに追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.database import DB_PATH

def migrate():
    print(f"Applying migration to: {DB_PATH}")
    
    with sqlite3.connect(DB_PATH) as conn:
        # テーブル作成
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoice_ocr_results (
                run_id TEXT,
                approval_no TEXT,
                file_name TEXT,
                
                -- OCR抽出結果
                detected_amount INTEGER,             -- 抽出された金額
                detected_invoice_no TEXT,            -- 抽出されたインボイス番号
                has_reduced_tax INTEGER DEFAULT 0,   -- 軽減税率有無 (0/1)
                confidence REAL,                     -- 信頼度スコア (0.0-1.0)
                ocr_method TEXT,                     -- 使用手法 (text_layer/pyocr/ai_ocr)
                
                -- 突合結果
                match_status TEXT,                   -- OK/NG/WARNING/UNCHECKED
                amount_diff INTEGER,                 -- 金額差分 (detected - actual)
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                
                PRIMARY KEY (run_id, approval_no, file_name)
            );
        """)
        # output_summary カラム追加 (存在しない場合のみ)
        try:
            conn.execute("ALTER TABLE output_summary ADD COLUMN decision_no TEXT")
            print("Migration: Added decision_no column to output_summary")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("Migration: decision_no column already exists in output_summary")
            else:
                raise

        conn.commit()
        print("Migration completed: invoice_ocr_results table created / schema updated.")

if __name__ == "__main__":
    migrate()
