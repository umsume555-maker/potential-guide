# scripts/run_invoice_matching.py
import sys
import os
import asyncio
from pathlib import Path

# プロジェクトルートを追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.database import DB_PATH
from domain.services.invoice_match_service import InvoiceMatchService
import sqlite3

def get_latest_run_id():
    """最新の実行IDを取得"""
    with sqlite3.connect(DB_PATH) as conn:
        # まずTESTデータがあればそれを優先（デバッグ用）
        cursor = conn.execute("SELECT run_id, started_at FROM run_log WHERE run_id LIKE 'TEST_%' ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"Found TEST Run ID: {row[0]} (started_at: {row[1]})")
            return row[0]

        # なければ通常データの最新
        cursor = conn.execute("SELECT run_id, started_at FROM run_log ORDER BY started_at DESC, rowid DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"Found Run ID: {row[0]} (started_at: {row[1]})")
            return row[0]
            
        return None

async def main():
    print("=== 請求書OCR突合処理 ===")
    
    # Run ID 取得
    run_id = get_latest_run_id()
    if not run_id:
        print("[ERROR] 実行履歴が見つかりません。先にチェックツールを実行してください。")
        return
    
    print(f"Target Run ID: {run_id}")
    
    # ZIP展開先
    zip_out_path = Path("invoice_ocr/ZIP_FILE_OUT")
    if not zip_out_path.exists():
        print(f"[ERROR] 展開先フォルダが見つかりません: {zip_out_path}")
        return
    
    # サービス実行
    service = InvoiceMatchService(DB_PATH)
    result = await service.process_and_match(run_id, zip_out_path)
    
    print("\n--- 実行結果 ---")
    print(f"処理ファイル数: {result['processed_files']}")
    print(f"一致 (OK)     : {result['match_ok']}")
    print(f"不一致 (NG)   : {result['match_ng']}")
    print("完了しました。")

if __name__ == "__main__":
    asyncio.run(main())
