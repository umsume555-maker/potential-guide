"""
累積データ管理サービス
"""
from typing import Optional, List
from datetime import datetime
from dateutil.relativedelta import relativedelta
from infra.database import get_db

class CumulativeService:
    """累積データの更新・参照を行うサービス"""

    def __init__(self):
        pass

    def update_monthly(self, run_id: str, base_month: str) -> int:
        """
        月次更新を実行
        1. 指定された実行結果(run_id)からOKデータを抽出し、累積に追加
        2. 14ヶ月より古いデータを削除
        
        Args:
            run_id: チェック実行ID
            base_month: 基準月 (YYYY-MM)
            
        Returns:
            int: 追加された件数
        """
        with get_db() as conn:
            # 1. 既存データの削除（重複防止）
            # 同じ run_id に含まれる伝票番号・取引先・年月を持つレコードを削除
            delete_existing_sql = """
                DELETE FROM cumulative 
                WHERE EXISTS (
                    SELECT 1 FROM output_summary s 
                    WHERE s.run_id = ? 
                      AND cumulative.yyyymm = substr(s.transaction_date, 1, 7)
                      AND cumulative.vendor_code = s.vendor_code 
                      AND cumulative.base_invoice_no = s.base_invoice_no
                )
            """
            conn.execute(delete_existing_sql, (run_id,))

            # 2. 追加処理
            # output_summary から OK/NG 問わずレコードを取得して cumulative に挿入
            # 判断結果がOKなら template_use=1 とする
            
            insert_sql_revised = """
                INSERT INTO cumulative (
                    yyyymm, base_invoice_no, dept_code, dept_name,
                    vendor_code, payee_code, payment_amount,
                    tax_category, tax_category_name,
                    account_code, account_name,
                    payment_date, transaction_date, status,
                    template_use, overall_result
                )
                SELECT
                    ? as yyyymm,
                    base_invoice_no, dept_code, dept_name,
                    vendor_code, payee_code, payment_amount,
                    tax_category, tax_category_name,
                    account_code, account_name,
                    payment_date, transaction_date, status,
                    1 as template_use,
                    overall_result
                FROM output_summary
                WHERE run_id = ?
                  AND overall_result = 'OK'
            """
            
            # 基準月を yyyymm として登録（通常は transaction_date の年月を使うべきだが、
            # 累積の管理上、どの「チェック月」で確定したかをベースにするのが安全か？
            # いや、cumulative.yyyymm は「取引年月」を意味するはず（tax_check参照）。
            # output_summary に yyyymm はないが、transaction_date はある。
            # ここでは transaction_date から yyyymm を抽出して入れるべき。
            
            # 再考: insert_sql を変更して transaction_date から yyyymm を生成する
            insert_sql_revised = """
                INSERT INTO cumulative (
                    yyyymm, base_invoice_no, dept_code, dept_name,
                    vendor_code, payee_code, payment_amount,
                    tax_category, tax_category_name,
                    account_code, account_name,
                    payment_date, transaction_date, status,
                    template_use, overall_result
                )
                SELECT
                    substr(transaction_date, 1, 7) as yyyymm,
                    base_invoice_no, dept_code, dept_name,
                    vendor_code, payee_code, payment_amount,
                    tax_category, tax_category_name,
                    account_code, account_name,
                    payment_date, transaction_date, status,
                    CASE WHEN overall_result = 'OK' THEN 1 ELSE 0 END as template_use,
                    overall_result
                FROM output_summary
                WHERE run_id = ?
            """
            
            conn.execute(insert_sql_revised, (run_id,))
            
            # 追加件数取得（直前のINSERT件数はrowcountで取れるはずだが、簡単のためSELECT countでも良い）
            # executeの戻り値 cursor.rowcount を確認
            cursor = conn.execute("SELECT changes()")
            added_count = cursor.fetchone()[0]
            
            # 2. 削除処理（ローテーション）
            # 基準月の14ヶ月前以前のデータを削除
            # 例: 基準月 2024-11 -> 2023-09以前を削除 (14ヶ月保持: 2023-10 ~ 2024-11)
            
            dt_base = datetime.strptime(base_month, "%Y-%m")
            dt_limit = dt_base - relativedelta(months=14)
            limit_yyyymm = dt_limit.strftime("%Y-%m")
            
            delete_sql = "DELETE FROM cumulative WHERE yyyymm < ?"
            conn.execute(delete_sql, (limit_yyyymm,))
            
            return added_count
