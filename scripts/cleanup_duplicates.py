
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"

def cleanup_duplicates():
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Cleaning up duplicates in 'cumulative' table ---")
    
    try:
        # 重複レコードのIDを特定（idが大きい＝最新を残す）
        # GROUP BY business keys
        sql_keep = """
            SELECT MAX(id)
            FROM cumulative
            GROUP BY yyyymm, base_invoice_no, vendor_code, dept_code
        """
        
        # 重複削除実行
        # id NOT IN (...) を削除
        # SQLiteのDELETE ... WHERE id NOT IN (...) は重いかもしれないが、
        # record数が数千~数万なら許容範囲
        
        # まず件数確認
        cursor.execute("SELECT COUNT(*) FROM cumulative")
        before_count = cursor.fetchone()[0]
        print(f"Before count: {before_count}")
        
        print("Executing DELETE...")
        cursor.execute(f"DELETE FROM cumulative WHERE id NOT IN ({sql_keep})")
        deleted_count = cursor.rowcount
        
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM cumulative")
        after_count = cursor.fetchone()[0]
        print(f"After count: {after_count}")
        print(f"Deleted {deleted_count} duplicate rows.")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    cleanup_duplicates()
