import sqlite3
from typing import Dict, List, Tuple
from infra.database import get_db
from datetime import datetime

class MasterRepository:
    """
    既存DBからマスタデータを参照するリポジトリ
    """
    def __init__(self):
        pass

    def get_vendor_master(self) -> Dict[str, str]:
        """
        取引先マスタを取得
        Returns: {vendor_code: vendor_name}
        """
        with get_db() as conn:
            cursor = conn.execute("SELECT vendor_code, vendor_name FROM masters_vendor")
            return {row["vendor_code"]: row["vendor_name"] for row in cursor}

    def get_department_master(self) -> Dict[str, str]:
        """
        事業所（部門）マスタを取得
        Returns: {dept_code: dept_name}
        Note: masters_department と masters_assign_dept_override の両方を考慮する？
        まずは自動補完された masters_assign_dept_override が実態に近い可能性があるため、そちらを優先しつつ
        masters_department も見る（存在すれば）。
        今回はシンプルに、実績がある cumulative から取得するのが一番確実かもしれないが、
        正規のマスタとして登録されているものを使うべき。
        Schemaを見る限り masters_department はまだ作成途中(Phase 2.5)かもしれない。
        既存の masters_assign_dept_override (部門例外) を使うのが無難か。
        """
        depts = {}
        with get_db() as conn:
            # 1. masters_assign_dept_override (部門名マスタとして代用されているケースが多い)
            cursor = conn.execute("SELECT dept_code, dept_name FROM masters_assign_dept_override")
            for row in cursor:
                if row["dept_code"] and row["dept_name"]:
                    depts[row["dept_code"]] = row["dept_name"]
            
            # 2. masters_department (もしあれば)
            try:
                cursor = conn.execute("SELECT dept_code, dept_name FROM masters_department")
                for row in cursor:
                    if row["dept_code"] and row["dept_name"]:
                        depts[row["dept_code"]] = row["dept_name"]
            except sqlite3.OperationalError:
                pass # テーブルがない場合は無視
                
        return depts

    def get_cumulative_data(self, base_month: str, vendor_codes: List[str]) -> List[dict]:
        """
        指定月・取引先の実績データを取得（集計前）
        """
        if not vendor_codes:
            return []
            
        placeholders = ",".join(["?"] * len(vendor_codes))
        sql = f"""
            SELECT vendor_code, dept_code, dept_name, payment_amount, transaction_date, base_invoice_no
            FROM cumulative
            WHERE yyyymm = ?
              AND vendor_code IN ({placeholders})
        """
        params = [base_month] + vendor_codes
        
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


    def get_cumulative_data_all(self, base_month: str, exclude_vendor_codes: List[str] = None) -> List[dict]:
        """
        指定月の全取引先の実績データを取得（除外リスト指定可）
        「毎月あるのに今月なし」の全取引先チェックに使用
        """
        if exclude_vendor_codes:
            placeholders = ",".join(["?"] * len(exclude_vendor_codes))
            sql = f"""
                SELECT vendor_code, vendor_name, dept_code, dept_name, payment_amount, transaction_date
                FROM cumulative
                WHERE yyyymm = ?
                  AND vendor_code NOT IN ({placeholders})
                  AND payment_amount > 0
            """
            params = [base_month] + exclude_vendor_codes
        else:
            sql = """
                SELECT vendor_code, vendor_name, dept_code, dept_name, payment_amount, transaction_date
                FROM cumulative
                WHERE yyyymm = ?
                  AND payment_amount > 0
            """
            params = [base_month]
        
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_all_vendor_names(self) -> Dict[str, str]:
        """
        全取引先マスタを取得
        Returns: {vendor_code: vendor_name}
        """
        with get_db() as conn:
            cursor = conn.execute("SELECT vendor_code, vendor_name FROM masters_vendor")
            return {row["vendor_code"]: row["vendor_name"] for row in cursor}

    def get_target_vendors(self) -> List[str]:
        """
        請求対象取引先（Target Vendors）のリストを取得
        """
        with get_db() as conn:
            try:
                cursor = conn.execute("SELECT vendor_code FROM vendor_reconciliation_target")
                return [row["vendor_code"] for row in cursor]
            except sqlite3.OperationalError:
                return []

    def get_excluded_vendors(self) -> List[str]:
        """
        除外取引先（Excluded Vendors）のリストを取得
        """
        with get_db() as conn:
            try:
                cursor = conn.execute("SELECT vendor_code FROM masters_exclude")
                return [row["vendor_code"] for row in cursor]
            except sqlite3.OperationalError:
                return []

    def get_vendor_departments(self, vendor_code: str) -> List[dict]:
        """
        指定取引先の過去実績のある事業所リストを取得
        """
        with get_db() as conn:
            # output_summary から dept_code, dept_name を取得
            # 名前は最新のものを使いたいが、MAXで代用
            sql = """
                SELECT dept_code, MAX(dept_name) as dept_name
                FROM output_summary
                WHERE vendor_code = ?
                  AND dept_code IS NOT NULL AND dept_code != ''
                GROUP BY dept_code
                ORDER BY dept_code
            """
            cursor = conn.execute(sql, (vendor_code,))
            return [dict(row) for row in cursor.fetchall()]


