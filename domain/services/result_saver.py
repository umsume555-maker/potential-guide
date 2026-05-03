"""
チェック結果 DB 保存モジュール
check_service.py から分離した保存専用ロジック
"""
from typing import List, Dict
from infra.csv_loader import normalize_dept_code


def save_results(conn, run_id: str, summaries: List[Dict], details: List[Dict]) -> None:
    """
    チェック結果を output_summary / output_detail に保存する。

    Args:
        conn: SQLite 接続（呼び出し元でコミット管理）
        run_id: 実行 ID
        summaries: サマリ行リスト
        details: 明細行リスト
    """
    _save_summaries(conn, run_id, summaries)
    _save_details(conn, run_id, details)


def _calc_ocr_match_status(ocr_amount, payment_amount) -> str:
    """OCR金額と支払金額を比較して OK / NG / - を返す"""
    ocr_val = str(ocr_amount or "").replace(",", "").strip()
    pay_val = str(payment_amount or "").strip()

    if not ocr_val:
        return "-"
    try:
        return "OK" if float(ocr_val) == float(pay_val) else "NG"
    except (ValueError, TypeError):
        return "OK" if ocr_val == pay_val else "NG"


def _save_summaries(conn, run_id: str, summaries: List[Dict]) -> None:
    for s in summaries:
        ocr_match_status = _calc_ocr_match_status(
            s.get("ocr_amount"), s["payment_amount"]
        )
        conn.execute(
            """
            INSERT INTO output_summary (
                run_id, base_invoice_no, decision_no, dept_code, dept_name,
                vendor_code, vendor_name, payee_code, payee_name,
                payment_amount, tax_category,
                account_code, account_name,
                payment_date, transaction_date, status,
                bank_account_info,
                ocr_amount, ocr_file_link, ocr_match_status,
                vendor_payee_result, tax_result, tax_expected,
                account_result, account_expected, account_expected_name,
                payment_date_result, payment_date_expected,
                anomaly_result, anomaly_type, is_monthly, overall_result,
                assigned_confirmed, assigned_proposed,
                amount_3m_ago, count_3m_ago,
                amount_2m_ago, count_2m_ago,
                amount_1m_ago, count_1m_ago,
                amount_current, count_current,
                amount_next, count_next
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                run_id,
                s["base_invoice_no"],
                s.get("decision_no", ""),
                normalize_dept_code(s["dept_code"]),
                s["dept_name"],
                s["vendor_code"],
                s["vendor_name"],
                s["payee_code"],
                s.get("payee_name", ""),
                s["payment_amount"],
                s["tax_category"],
                s["account_code"],
                s.get("account_name", ""),
                s["payment_date"],
                s["transaction_date"],
                s["status"],
                s.get("bank_account_info", ""),
                s.get("ocr_amount", ""),
                s.get("ocr_file_link", ""),
                ocr_match_status,
                s["vendor_payee_result"],
                s["tax_result"],
                s["tax_expected"],
                s["account_result"],
                s["account_expected"],
                s.get("account_expected_name", ""),
                s["payment_date_result"],
                s["payment_date_expected"],
                s["anomaly_result"],
                s["anomaly_type"],
                s["is_monthly"],
                s["overall_result"],
                "",
                s["assignee"],
                s.get("amount_3m_ago", 0),
                s.get("count_3m_ago", 0),
                s.get("amount_2m_ago", 0),
                s.get("count_2m_ago", 0),
                s.get("amount_1m_ago", 0),
                s.get("count_1m_ago", 0),
                s.get("amount_current", 0),
                s.get("count_current", 0),
                s.get("amount_next", 0),
                s.get("count_next", 0),
            ),
        )


def _save_details(conn, run_id: str, details: List[Dict]) -> None:
    for d in details:
        conn.execute(
            """
            INSERT INTO output_detail (
                run_id, invoice_no, base_invoice_no, branch_no,
                dept_code, dept_name, vendor_code, vendor_name,
                payee_code, payee_name, account_code, account_name,
                payment_amount, tax_category, tax_category_name,
                payment_date, transaction_date, status
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                run_id,
                d["invoice_no"],
                d["base_invoice_no"],
                d["branch_no"],
                normalize_dept_code(d["dept_code"]),
                d["dept_name"],
                d["vendor_code"],
                d["vendor_name"],
                d["payee_code"],
                d.get("payee_name", ""),
                d["account_code"],
                d.get("account_name", ""),
                d["payment_amount"],
                d["tax_category"],
                d.get("tax_category_name", ""),
                d["payment_date"],
                d["transaction_date"],
                d["status"],
            ),
        )
