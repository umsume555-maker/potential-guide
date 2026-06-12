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

        優先順位:
          1. 基準月の最新チェック実行（output_summary）― 削除済み申請を含まない最新状態
          2. output_summaryがない場合のみ cumulative にフォールバック（過去月対応）
        """
        if not vendor_codes:
            return []

        placeholders = ",".join(["?"] * len(vendor_codes))

        with get_db() as conn:
            conn.row_factory = sqlite3.Row

            # 1. 基準月の最新チェック実行 run_id を取得（input_rows >= 100 の本番run）
            latest_run = conn.execute("""
                SELECT run_id FROM run_log
                WHERE base_month = ? AND input_rows >= 100
                ORDER BY started_at DESC LIMIT 1
            """, (base_month,)).fetchone()

            os_rows = []
            if latest_run:
                run_id = latest_run["run_id"]
                sql_os = f"""
                    SELECT o.vendor_code, o.dept_code, o.dept_name, o.payment_amount,
                           o.transaction_date, o.base_invoice_no
                    FROM output_summary o
                    WHERE o.run_id = ?
                      AND o.vendor_code IN ({placeholders})
                      AND o.payment_amount > 0
                """
                os_rows = [dict(r) for r in conn.execute(sql_os, [run_id] + vendor_codes).fetchall()]

            # 2. output_summary にデータがあればそれを返す（最新チェック実行が真実）
            if os_rows:
                return os_rows

            # 3. output_summary がない場合のみ cumulative にフォールバック（過去月等）
            sql_cum = f"""
                SELECT vendor_code, dept_code, dept_name, payment_amount,
                       transaction_date, base_invoice_no
                FROM cumulative
                WHERE yyyymm = ?
                  AND vendor_code IN ({placeholders})
            """
            return [dict(r) for r in conn.execute(sql_cum, [base_month] + vendor_codes).fetchall()]


    def get_cumulative_data_all(self, base_month: str, exclude_vendor_codes: List[str] = None) -> List[dict]:
        """
        指定月の全取引先の実績データを取得（除外リスト指定可）
        「毎月あるのに今月なし」の全取引先チェックに使用

        優先順位:
          1. 基準月の最新チェック実行（output_summary）
          2. output_summaryがない場合のみ cumulative にフォールバック
        """
        exclude_vendor_codes = exclude_vendor_codes or []

        with get_db() as conn:
            conn.row_factory = sqlite3.Row

            # 1. 基準月の最新チェック実行 run_id を取得
            latest_run = conn.execute("""
                SELECT run_id FROM run_log
                WHERE base_month = ? AND input_rows >= 100
                ORDER BY started_at DESC LIMIT 1
            """, (base_month,)).fetchone()

            if latest_run:
                run_id = latest_run["run_id"]
                if exclude_vendor_codes:
                    ex_ph = ",".join(["?"] * len(exclude_vendor_codes))
                    sql_os = f"""
                        SELECT o.vendor_code, o.vendor_name, o.dept_code, o.dept_name,
                               o.payment_amount, o.transaction_date
                        FROM output_summary o
                        WHERE o.run_id = ?
                          AND o.vendor_code NOT IN ({ex_ph})
                          AND o.payment_amount > 0
                    """
                    params_os = [run_id] + exclude_vendor_codes
                else:
                    sql_os = """
                        SELECT o.vendor_code, o.vendor_name, o.dept_code, o.dept_name,
                               o.payment_amount, o.transaction_date
                        FROM output_summary o
                        WHERE o.run_id = ?
                          AND o.payment_amount > 0
                    """
                    params_os = [run_id]

                os_rows = [dict(r) for r in conn.execute(sql_os, params_os).fetchall()]
                if os_rows:
                    return os_rows

            # 2. output_summary がない場合のみ cumulative にフォールバック
            if exclude_vendor_codes:
                ex_ph = ",".join(["?"] * len(exclude_vendor_codes))
                sql = f"""
                    SELECT vendor_code, vendor_name, dept_code, dept_name, payment_amount, transaction_date
                    FROM cumulative
                    WHERE yyyymm = ?
                      AND vendor_code NOT IN ({ex_ph})
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

            return [dict(row) for row in conn.execute(sql, params).fetchall()]

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


