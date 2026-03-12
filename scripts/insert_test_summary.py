# scripts/insert_test_summary.py
import sys
import os
import sqlite3
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from infra.database import DB_PATH

def insert_test_data():
    # 新しいRUN_IDを生成
    run_id = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    print(f"Creating test data with Run ID: {run_id}")

    # 現在のrun_logにエントリを追加（最新として認識させるため）
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO run_log (run_id, status, started_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (run_id, "COMPLETED"))
        
        # テスト用データの挿入
        # 1. ZSN25120500000000236: 14,000 OKパターン
        conn.execute("""
            INSERT INTO output_summary (
                run_id, base_invoice_no, decision_no, 
                dept_code, payment_amount,
                vendor_code, vendor_name, status,
                overall_result
            ) VALUES (
                ?, ?, ?, 
                '99999', 14000,
                'V001', 'Test Vendor 1', '承認済',
                'OK'
            )
        """, (run_id, "TEST-INV-001", "ZSN25120500000000236"))

        # 2. ZSN25122600000000014: 3,487,500 OKパターン
        conn.execute("""
            INSERT INTO output_summary (
                run_id, base_invoice_no, decision_no, 
                dept_code, payment_amount,
                vendor_code, vendor_name, status,
                overall_result
            ) VALUES (
                ?, ?, ?, 
                '99999', 3487500,
                'V002', 'Test Vendor 2', '承認済',
                'OK'
            )
        """, (run_id, "TEST-INV-002", "ZSN25122600000000014"))
        
        # 3. ZSN25122600000000005: 存在するが金額不一致パターン（OCR失敗時など）
        # 仮に 10,000円として登録しておく
        conn.execute("""
            INSERT INTO output_summary (
                run_id, base_invoice_no, decision_no, 
                dept_code, payment_amount,
                vendor_code, vendor_name, status,
                overall_result
            ) VALUES (
                ?, ?, ?, 
                '99999', 10000,
                'V003', 'Test Vendor 3', '承認済',
                'OK'
            )
        """, (run_id, "TEST-INV-003", "ZSN25122600000000005"))

        conn.commit()
    
    print("Test data inserted successfully.")

if __name__ == "__main__":
    insert_test_data()
