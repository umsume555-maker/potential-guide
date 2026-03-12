
import sqlite3
import os
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

# Add root to path
sys.path.append(os.getcwd())
from infra.database import get_db

def populate_targets(base_month="2026-01"):
    """
    Populate vendor_reconciliation_target based on "Recurring Missing" logic.
    Logic: Count distinct months with payments in the past 4 months (relative to base_month).
           If count >= 3, add to target.
    """
    print(f"Starting population of target vendors. Base Month: {base_month}")
    
    # Calculate past 4 months
    dt = datetime.strptime(base_month + "-01", "%Y-%m-%d")
    past_months = []
    for i in range(1, 5):
        pm = (dt - relativedelta(months=i)).strftime("%Y-%m")
        past_months.append(pm)
    
    print(f"Checking months: {past_months}")
    
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        
        # 1. Get all vendors with payments in these months
        placeholders = ",".join(["?"] * len(past_months))
        sql = f"""
            SELECT vendor_code, vendor_name, yyyymm
            FROM cumulative
            WHERE yyyymm IN ({placeholders})
              AND payment_amount > 0
        """
        rows = conn.execute(sql, past_months).fetchall()
        
        # 2. Count distinct months per vendor
        vendor_stats = {}
        vendor_names = {}
        
        for r in rows:
            v_code = r["vendor_code"]
            v_name = r["vendor_name"]
            month = r["yyyymm"]
            
            if v_code not in vendor_stats:
                vendor_stats[v_code] = set()
                vendor_names[v_code] = v_name
            
            vendor_stats[v_code].add(month)
            
        # 3. Identify targets (Count >= 3)
        targets = []
        for v_code, months in vendor_stats.items():
            if len(months) >= 3:
                targets.append((v_code, vendor_names[v_code]))
                
        print(f"Found {len(targets)} vendors meeting criteria (>= 3 months in past 4).")
        
        # 4. Insert into DB
        added_count = 0
        existing_count = 0
        
        # Create table if not exists (Lazy migration)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                vendor_code TEXT PRIMARY KEY,
                vendor_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        for v_code, v_name in targets:
            try:
                # Check exist
                cur = conn.execute("SELECT 1 FROM vendor_reconciliation_target WHERE vendor_code = ?", (v_code,))
                if cur.fetchone():
                    existing_count += 1
                    continue
                
                conn.execute("INSERT INTO vendor_reconciliation_target (vendor_code, vendor_name) VALUES (?, ?)", (v_code, v_name))
                added_count += 1
                print(f"  Added: {v_code} {v_name}")
                
            except Exception as e:
                print(f"  Error adding {v_code}: {e}")
        
        conn.commit()
        print(f"Done. Added: {added_count}, Already Existed: {existing_count}")

if __name__ == "__main__":
    populate_targets()
