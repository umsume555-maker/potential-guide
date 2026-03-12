
import sqlite3
from pathlib import Path

DB_PATH = Path("data/payment_check.db")

def check_status():
    if not DB_PATH.exists():
        print("Database not found.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        
        # Recent 5 run logs
        cursor = conn.execute("SELECT * FROM run_log ORDER BY started_at DESC LIMIT 5")
        runs = cursor.fetchall()
        
        if not runs:
            print("No run log found.")
            return

        print(f"{'Run ID':<20} | {'Status':<10} | {'Started':<20} | {'OCR Rows'}")
        print("-" * 60)
        
        for run in runs:
            r_id = run["run_id"]
            status = run["status"]
            started = run["started_at"]
            
            # Count results
            cursor = conn.execute("SELECT COUNT(*) FROM invoice_ocr_results WHERE run_id = ?", (r_id,))
            count = cursor.fetchone()[0]
            print(f"{r_id:<20} | {status:<10} | {started:<20} | {count}")

        print("-" * 60)
        # Total count
        cursor = conn.execute("SELECT COUNT(*) FROM invoice_ocr_results")
        total = cursor.fetchone()[0]
        print(f"Total rows in invoice_ocr_results: {total}")


if __name__ == "__main__":
    check_status()
