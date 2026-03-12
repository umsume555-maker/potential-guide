
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "payment_check.db"

def auto_register_depts():
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Auto-registering missing departments ---")
    
    try:
        # Find departments in output_summary that are NOT in masters_department
        sql = """
            SELECT DISTINCT s.dept_code, s.dept_name
            FROM output_summary s
            LEFT JOIN masters_department m ON s.dept_code = m.dept_code
            WHERE m.dept_code IS NULL
              AND s.dept_code IS NOT NULL AND s.dept_code != ''
        """
        cursor.execute(sql)
        missing_rows = cursor.fetchall()
        
        if not missing_rows:
            print("No missing departments found.")
        else:
            print(f"Found {len(missing_rows)} missing departments.")
            
            # Insert with default type 'SGA'
            insert_sql = """
                INSERT INTO masters_department (dept_code, dept_name, dept_type, updated_at)
                VALUES (?, ?, 'SGA', datetime('now', 'localtime'))
            """
            
            count = 0
            for r in missing_rows:
                dept_code = r[0]
                dept_name = r[1] or f"Dept-{dept_code}" # Fallback name
                cursor.execute(insert_sql, (dept_code, dept_name))
                count += 1
                
            conn.commit()
            print(f"Registered {count} departments as 'SGA'.")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    auto_register_depts()
