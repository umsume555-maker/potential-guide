
import sqlite3
from datetime import datetime
from pathlib import Path
import os

# DB Setup
APP_NAME = "PayCheckTool"
base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home()))
DATA_DIR = base_dir / APP_NAME
DB_PATH = DATA_DIR / "app.db"

def seed_from_history():
    print(f"Seeding rules from history in {DB_PATH}...")
    
    if not DB_PATH.exists():
        print("Database not found.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 1. Seed Account Rules (Scope: DEPT - safest approach)
        # Strategy: Pick the account used in the most recent month for each Vendor+Dept.
        # If multiple in same month (unlikely for cumulative summary?), pick one (MAX rowid or similar).
        
        print("Analyzing cumulative history for Account Rules...")
        
        # Get latest yyyymm for each vendor+dept
        cursor.execute("""
            SELECT vendor_code, dept_code, account_code
            FROM cumulative
            WHERE account_code IS NOT NULL AND account_code != ''
            GROUP BY vendor_code, dept_code
            HAVING yyyymm = MAX(yyyymm)
        """)
        
        rows = cursor.fetchall()
        print(f"Found {len(rows)} Vendor-Dept combinations.")
        
        count_acc = 0
        for r in rows:
            v_code = r["vendor_code"]
            d_code = r["dept_code"]
            acc = r["account_code"]
            
            # Insert Rule
            # Scope: DEPT
            try:
                cursor.execute("""
                    INSERT INTO rule_account_master (vendor_code, scope_type, scope_key, expected_account, updated_by, reason)
                    VALUES (?, 'DEPT', ?, ?, 'system_seed', 'Auto-generated from history')
                    ON CONFLICT(vendor_code, scope_type, scope_key) DO UPDATE SET
                        expected_account = excluded.expected_account,
                        updated_by = excluded.updated_by,
                        reason = excluded.reason
                """, (v_code, d_code, acc))
                count_acc += 1
            except sqlite3.Error as e:
                print(f"Error inserting account rule for {v_code}-{d_code}: {e}")

        # 2. Seed Tax Rules
        # Strategy: Pick latest tax category for Vendor (Global)
        # Tax usually depends on Vendor, not Dept.
        
        print("Analyzing cumulative history for Tax Rules...")
        
        cursor.execute("""
            SELECT vendor_code, tax_category
            FROM cumulative
            WHERE tax_category IS NOT NULL AND tax_category != ''
            GROUP BY vendor_code
            HAVING yyyymm = MAX(yyyymm)
        """)
        
        rows = cursor.fetchall()
        print(f"Found {len(rows)} Vendors for Tax Rules.")
        
        count_tax = 0
        for r in rows:
            v_code = r["vendor_code"]
            tax = r["tax_category"]
            
            try:
                cursor.execute("""
                    INSERT INTO rule_tax_master (vendor_code, expected_tax, updated_by, reason)
                    VALUES (?, ?, 'system_seed', 'Auto-generated from history')
                    ON CONFLICT(vendor_code) DO UPDATE SET
                        expected_tax = excluded.expected_tax,
                        updated_by = excluded.updated_by,
                        reason = excluded.reason
                """, (v_code, tax))
                count_tax += 1
            except sqlite3.Error as e:
                print(f"Error inserting tax rule for {v_code}: {e}")

        conn.commit()
        print(f"Seeding completed. Account Rules: {count_acc}, Tax Rules: {count_tax}")
        
    except Exception as e:
        conn.rollback()
        print(f"Seeding failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    seed_from_history()
