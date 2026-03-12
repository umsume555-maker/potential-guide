"""
チェックサービス
CSV取込 → 判定 → 出力の一連の処理を管理
"""
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass

from infra.database import get_db, init_database
from infra.csv_loader import (
    load_csv, aggregate_by_base_invoice, 
    InvoiceSummary, get_yyyymm
)
from infra.excel_writer import write_excel
from domain.validators import (
    check_vendor_payee, check_tax_category, check_account,
    check_payment_date, calculate_expected_payment_date,
    check_anomaly, determine_monthly_flag, overall_judgment
)
from domain.validators.vendor_check import load_allowed_payees_from_db
from domain.validators.tax_category_check import get_expected_tax_from_rule
from domain.validators.account_check import get_expected_account_from_rule
from domain.validators.payment_date_check import load_holidays_from_db
from domain.validators.anomaly_check import (
    get_monthly_counts_from_cumulative, create_synthetic_row, MonthlyCount
)


@dataclass
class CheckResult:
    """チェック結果"""
    run_id: str
    base_month: str
    started_at: str
    ended_at: str
    status: str
    input_rows: int
    output_rows: int
    ng_count: int
    hold_count: int
    dash_count: int
    excel_path: Optional[Path] = None
    excel_path: Optional[Path] = None
    error_message: Optional[str] = None
    # 正マスター情報
    rule_total: int = 0
    rule_updated: Optional[str] = None
    rule_db_path: Optional[str] = None


class CheckService:
    """チェック処理サービス"""
    
    def __init__(self):
        self.run_id = ""
        self.base_month = ""
        self.holidays: Set[str] = set()
        self.allowed_payees: Set[tuple] = set()
        self.excluded_vendors: Set[str] = set()
        self.vendor_masters: Dict[str, dict] = {}
        self.assign_rules: List[tuple] = []
        self.assign_overrides: Dict[str, str] = {}
        self.assign_vendors: Dict[str, str] = {}
        self.account_masters: Dict[str, str] = {}
    
    def _load_masters(self, conn) -> None:
        """マスターデータを読み込む"""
        # 許容支払先
        self.allowed_payees = load_allowed_payees_from_db(conn)
        
        # 祝日
        self.holidays = load_holidays_from_db(conn)
        
        # 除外取引先
        cursor = conn.execute("SELECT vendor_code FROM masters_exclude")
        self.excluded_vendors = {row["vendor_code"] for row in cursor}
        
        # 取引先マスター
        cursor = conn.execute("""
            SELECT vendor_code, vendor_name, payment_condition_code,
                   holiday_handling, payment_cycle_type, payment_month_offset,
                   payment_day, closing_day, bank_code, bank_name,
                   branch_code, branch_name, account_type, account_number,
                   account_holder, date_tolerance, no_month_crossing
            FROM masters_vendor
        """)
        self.vendor_masters = {
            row["vendor_code"]: dict(row) for row in cursor
        }
        
        # 担当割当（部門範囲ルール）
        cursor = conn.execute("""
            SELECT dept_code_start, dept_code_end, assignee, priority
            FROM masters_assign_dept_rule
            ORDER BY priority DESC
        """)
        self.assign_rules = [(row["dept_code_start"], row["dept_code_end"], 
                              row["assignee"]) for row in cursor]
        
        # 担当割当（部門例外）
        cursor = conn.execute("SELECT dept_code, assignee FROM masters_assign_dept_override")
        self.assign_overrides = {row["dept_code"]: row["assignee"] for row in cursor}
        
        # 担当割当（取引先別）
        cursor = conn.execute("SELECT vendor_code, assignee FROM masters_assign_vendor")
        self.assign_vendors = {row["vendor_code"]: row["assignee"] for row in cursor}
        
        # 科目マスタ
        cursor = conn.execute("SELECT account_code, account_name FROM masters_account")
        self.account_masters = {row["account_code"]: row["account_name"] for row in cursor}
    
    def _get_assignee(self, vendor_code: str, dept_code: str) -> str:
        """担当を取得（取引先別 > 部門例外 > 部門範囲ルール）"""
        # 1. 取引先別（優先度高）
        if vendor_code in self.assign_vendors:
            val = self.assign_vendors[vendor_code]
            if val: return val
            
        # 2. 部門例外
        if dept_code in self.assign_overrides:
            val = self.assign_overrides[dept_code]
            if val: return val
        
        # 3. 部門範囲ルール（現在は使われていないがロジック維持）
        for start, end, assignee in self.assign_rules:
            if start <= dept_code <= end:
                return assignee
        
        return ""
    
    def _get_past_amounts(
        self, 
        conn, 
        vendor_code: str, 
        dept_code: str, 
        base_month: str
    ) -> Dict[str, Any]:
        """過去金額・個数を取得（3ヶ月前〜1ヶ月前）"""
        from dateutil.relativedelta import relativedelta
        
        base_date = datetime.strptime(base_month + "-01", "%Y-%m-%d")
        result = {}
        
        # 3ヶ月前〜1ヶ月前
        offsets = [
            ("3m_ago", -3), ("2m_ago", -2), ("1m_ago", -1)
        ]
        
        for suffix, offset in offsets:
            target_month = (base_date + relativedelta(months=offset)).strftime("%Y-%m")
            
            cursor = conn.execute("""
                SELECT 
                    COALESCE(SUM(payment_amount), 0) as total_amount,
                    COALESCE(SUM(CASE WHEN payment_amount >= 0 THEN 1 ELSE -1 END), 0) as count
                FROM cumulative
                WHERE vendor_code = ? AND dept_code = ? AND yyyymm = ?
            """, (vendor_code, dept_code, target_month))
            
            row = cursor.fetchone()
            result[f"amount_{suffix}"] = row["total_amount"] if row else 0
            result[f"count_{suffix}"] = row["count"] if row else 0
        
        return result
    
    
    def _sync_assignment_masters(self, conn, rows: List):
        """Inputデータから担当割当マスタを自動更新"""
        cursor = conn.cursor()
        
        # 部門
        dept_map = {}
        for r in rows:
            if r.dept_code and r.dept_code.strip():
                dept_map[r.dept_code] = r.dept_name
        
        for code, name in dept_map.items():
            if code in self.assign_overrides:
                # Update Name
                cursor.execute("UPDATE masters_assign_dept_override SET dept_name = ? WHERE dept_code = ?", (name, code))
            else:
                # Insert New
                cursor.execute("INSERT INTO masters_assign_dept_override (dept_code, dept_name, assignee) VALUES (?, ?, '')", (code, name))
                self.assign_overrides[code] = ""

        # 取引先
        vendor_map = {}
        for r in rows:
            if r.vendor_code and r.vendor_code.strip():
                vendor_map[r.vendor_code] = r.vendor_name
        
        for code, name in vendor_map.items():
            if code in self.assign_vendors:
                cursor.execute("UPDATE masters_assign_vendor SET vendor_name = ? WHERE vendor_code = ?", (name, code))
            else:
                cursor.execute("INSERT INTO masters_assign_vendor (vendor_code, vendor_name, assignee) VALUES (?, ?, '')", (code, name))
                self.assign_vendors[code] = ""
        
        conn.commit()

    def run_check(
        self,
        csv_path: Path,
        base_month: str,
        output_dir: Path
    ) -> CheckResult:
        """
        チェック処理を実行
        
        Args:
            csv_path: 入力CSVパス
            base_month: 基準月 (YYYY-MM)
            output_dir: 出力ディレクトリ
        
        Returns:
            CheckResult: チェック結果
        """
        self.run_id = str(uuid.uuid4())[:8].upper()
        self.base_month = base_month
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # DB初期化
            init_database()
            
            with get_db() as conn:
                # マスター読み込み
                self._load_masters(conn)
                
                # OCR結果読み込み (最新)
                ocr_results = self._load_latest_ocr_results(conn)
                
                # 祝日チェック
                if not self.holidays:
                    # 祝日データがない場合は警告（エラー停止にしない）
                    print("警告: 祝日データがありません。支払予定日チェックが正確でない可能性があります。")
                
                # CSV取込
                rows = list(load_csv(csv_path))
                input_rows = len(rows)
                
                # 申請部門名または部門コードが空のデータをフィルタ（完全除外）
                # (load_csvでstrip済だが、念のため再チェック)
                initial_count = len(rows)
                rows = [r for r in rows if r.dept_name and r.dept_name.strip() and r.dept_code and r.dept_code.strip()]
                filtered_count = len(rows)
                if initial_count != filtered_count:
                    print(f"部門情報欠損により {initial_count - filtered_count} 行を除外しました。")
                
                # 除外取引先をフィルタ
                rows = [r for r in rows if r.vendor_code not in self.excluded_vendors]
                
                # 自動マスタ同期 (Inputデータから部門・取引先を登録)
                self._sync_assignment_masters(conn, rows)
                
                # ベース伝票単位で集約
                summaries = aggregate_by_base_invoice(iter(rows))
                
                # Inputデータから統計情報集計（当月・翌月用）
                # ユーザー指摘により、明細単位ではなく「伝票単位」で集計する
                from collections import defaultdict
                # amount, count, amounts
                stats_map = defaultdict(lambda: {"amount": 0, "count": 0, "raw_count": 0, "amounts": []})
                
                for inv_no, s in summaries.items():
                    if s.transaction_date and len(s.transaction_date) >= 7:
                        try:
                            # YYYY-MM
                            ym = s.transaction_date[:7]
                            key = (str(s.dept_code), str(s.vendor_code), ym)
                            stats_map[key]["amount"] += s.payment_amount
                            stats_map[key]["amounts"].append(s.payment_amount)
                            # 伝票合計金額が正なら+1、負なら-1
                            stats_map[key]["count"] += (1 if s.payment_amount >= 0 else -1)
                            stats_map[key]["raw_count"] += 1
                        except:
                            pass

                # 除外取引先リスト
                excluded_list = [
                    {"vendor_code": vc, "vendor_name": "", "reason": "除外マスター登録"}
                    for vc in self.excluded_vendors
                ]
                
                # 判定処理
                summary_data = []
                detail_data = []
                ng_count = 0
                dash_count = 0
                hold_count = 0
                
                # 翌月を計算
                from dateutil.relativedelta import relativedelta
                base_date = datetime.strptime(base_month + "-01", "%Y-%m-%d")
                next_month = (base_date + relativedelta(months=1)).strftime("%Y-%m")
                
                # 毎月判定用のデータを収集
                vendor_dept_pairs = set()
                for inv_no, summary in summaries.items():
                    vendor_dept_pairs.add((summary.vendor_code, summary.dept_code))
                
                # 各ベース伝票を処理
                for inv_no, summary in summaries.items():
                    # 取引日付の月
                    tx_month = get_yyyymm(summary.transaction_date)
                    
                    # --- 判定処理 ---
                    
                    # 1. 支払先相違
                    vp_result, vp_reason = check_vendor_payee(
                        summary.vendor_code, summary.payee_code, self.allowed_payees
                    )
                    
                    # 2. 税区分
                    expected_tax = get_expected_tax_from_rule(
                        conn, summary.vendor_code, summary.dept_code
                    )
                    tax_result, tax_reason = check_tax_category(
                        summary.tax_category, expected_tax
                    )
                    
                    # 3. 科目
                    expected_account = get_expected_account_from_rule(
                        conn, summary.vendor_code, summary.dept_code
                    )
                    acc_result, acc_reason = check_account(
                        summary.account_code, expected_account
                    )
                    
                    # 4. 支払予定日
                    vendor_master = self.vendor_masters.get(summary.vendor_code, {})
                    expected_payment_date = ""
                    
                    if vendor_master and summary.transaction_date:
                        try:
                            tx_date = datetime.strptime(
                                summary.transaction_date, "%Y-%m-%d"
                            ).date()
                            expected_date = calculate_expected_payment_date(
                                tx_date,
                                closing_day=vendor_master.get("closing_day", 0) or 0,
                                payment_month_offset=vendor_master.get("payment_month_offset", 1) or 1,
                                payment_day=vendor_master.get("payment_day", 0) or 0,
                                holiday_handling=vendor_master.get("holiday_handling", "1") or "1",
                                holidays=self.holidays,
                                no_month_crossing=bool(vendor_master.get("no_month_crossing", 0))
                            )
                            expected_payment_date = expected_date.strftime("%Y-%m-%d")
                        except Exception:
                            expected_payment_date = ""
                    
                    pd_result, pd_reason = check_payment_date(
                        summary.payment_date, expected_payment_date
                    )
                    
                    # 5. ズレモレ二重
                    monthly_counts = get_monthly_counts_from_cumulative(
                        conn, summary.vendor_code, summary.dept_code, base_month
                    )
                    is_monthly = determine_monthly_flag(monthly_counts)
                    
                    # 当月データ存在確認 (Cumulative OR Input)
                    cursor = conn.execute("""
                        SELECT COUNT(*) as cnt FROM cumulative
                        WHERE vendor_code = ? AND dept_code = ? AND yyyymm = ?
                    """, (summary.vendor_code, summary.dept_code, base_month))
                    has_current_db = cursor.fetchone()["cnt"] > 0
                    
                    # Inputからの集計値を取得
                    key_current = (str(summary.dept_code), str(summary.vendor_code), base_month)
                    key_next = (str(summary.dept_code), str(summary.vendor_code), next_month)
                    
                    current_stats = stats_map[key_current]
                    next_stats = stats_map[key_next]
                    
                    has_current = has_current_db or (current_stats["raw_count"] > 0)
                    
                    # 個数取得 (CumulativeからM-3~M-1を取得)
                    past_amounts = self._get_past_amounts(
                        conn, summary.vendor_code, summary.dept_code, base_month
                    )
                    
                    # 今月・翌月分をInput集計値で上書き
                    past_amounts["amount_current"] = current_stats["amount"]
                    past_amounts["count_current"] = current_stats["count"]
                    past_amounts["amount_next"] = next_stats["amount"]
                    past_amounts["count_next"] = next_stats["count"]
                    
                    date_tolerance = vendor_master.get("date_tolerance", 0) or 0
                    
                    anomaly_result, anomaly_type, anomaly_reason = check_anomaly(
                        is_monthly=is_monthly,
                        base_month=base_month,
                        transaction_month=tx_month,
                        date_tolerance=date_tolerance,
                        count_1m_ago=past_amounts.get("count_1m_ago", 0),
                        count_current=past_amounts.get("count_current", 0),
                        has_current_month_data=has_current or tx_month == base_month,
                        current_amounts=current_stats["amounts"]
                    )
                    
                    # 6. 総合判定
                    all_results = [vp_result, tax_result, acc_result, pd_result, anomaly_result]
                    overall = overall_judgment(all_results)
                    
                    # 担当取得
                    assignee = self._get_assignee(summary.vendor_code, summary.dept_code)
                    
                    # 口座情報
                    bank_info = ""
                    if vendor_master:
                        bank_info = f"{vendor_master.get('bank_name', '')} {vendor_master.get('branch_name', '')} {vendor_master.get('account_number', '')}"
                    
                    # --- OCRデータ結合 ---
                    ocr_amount = ""
                    ocr_file_link = ""
                    
                    key = (str(summary.dept_code), str(summary.vendor_code))
                    if key in ocr_results:
                        candidates = ocr_results[key]
                        matched_ocr = None
                        
                        if len(candidates) == 1:
                            matched_ocr = candidates[0]
                        else:
                            # 複数候補がある場合、金額一致で突合
                            # Excel上の金額は整数または浮動小数点だが、OCRはデータ型が不明確な場合も。
                            # ここでは単純比較 (abs差分が小さいもの)
                            target_amount = summary.payment_amount
                            best_match = None
                            min_diff = float('inf')
                            
                            for c in candidates:
                                try:
                                    det_amt = c["detected_amount"]
                                    if det_amt is None: continue
                                    diff = abs(float(det_amt) - float(target_amount))
                                    if diff < min_diff:
                                        min_diff = diff
                                        best_match = c
                                except Exception:
                                    continue
                            
                            # 差分が0（完全一致）のみ採用、あるいは最も近いものを採用？
                            # 要望: 「OUTPUTの「支払金額」と請求書突合のエクセルデータの「当月請求額」も突合して結合先を決定してください。」
                            # 差分0なら採用、そうでなければ...今回は最も近いものを採用しつつ、差分が大きい場合は警告？
                            # いったん「最も近いもの」を採用する（ただし閾値を設けるべきかも）
                            if best_match: # and min_diff == 0: # 必要なら厳格化
                                matched_ocr = best_match
                        
                        if matched_ocr:
                            ocr_amount = matched_ocr["detected_amount"]
                            fname = matched_ocr["file_name"]
                            # ハイパーリンク生成
                            # サーバーのAPIエンドポイントへのリンク、またはファイルパス
                            # Excel上でクリックして開くには httpリンクが一番扱いやすい
                            # "http://localhost:8000/api/ocr/files/{fname}"
                            ocr_file_link = f'=HYPERLINK("http://localhost:8000/api/ocr/files/{fname}", "リンク")'


                    # サマリ行
                    summary_row = {
                        "overall_result": overall,
                        "ocr_amount": ocr_amount,
                        "ocr_file_link": ocr_file_link,
                        "dept_code": summary.dept_code,
                        "dept_name": summary.dept_name,
                        "vendor_code": summary.vendor_code,
                        "vendor_name": summary.vendor_name,
                        "vendor_payee_result": vp_result,
                        "assignee": assignee,
                        "base_invoice_no": summary.base_invoice_no,
                        "transaction_date": summary.transaction_date,
                        "payee_code": summary.payee_code,
                        "vendor_payee_result": vp_result,
                        "payment_amount": summary.payment_amount,
                        "payment_date": summary.payment_date,
                        "payment_date_result": pd_result,
                        "payment_date_expected": expected_payment_date,
                        "tax_category": summary.tax_category,
                        "tax_result": tax_result,
                        "tax_expected": expected_tax or "",
                        "account_code": summary.account_code,
                        "account_name": self.account_masters.get(summary.account_code, ""),
                        "account_result": acc_result,
                        "account_expected": expected_account or "",
                        "account_expected_name": self.account_masters.get(expected_account, "") if expected_account else "",
                        "anomaly_result": anomaly_result,
                        "anomaly_type": anomaly_type,
                        "is_monthly": "毎月" if is_monthly else "",
                        "status": summary.status,
                        "bank_account_info": bank_info,
                        **past_amounts
                    }
                    summary_data.append(summary_row)
                    
                    # 統計
                    if overall == "NG":
                        ng_count += 1
                    elif overall == "-":
                        dash_count += 1
                    
                    # 明細行
                    for detail in summary.details:
                        detail_row = {
                            "invoice_no": detail.invoice_no,
                            "base_invoice_no": detail.base_invoice_no,
                            "branch_no": detail.branch_no,
                            "dept_code": detail.dept_code,
                            "dept_name": detail.dept_name,
                            "vendor_code": detail.vendor_code,
                            "vendor_name": detail.vendor_name,
                            "payee_code": detail.payee_code,
                            "payee_name": detail.payee_name,
                            "account_code": detail.account_code,
                            "account_name": detail.account_name,
                            "payment_amount": detail.payment_amount,
                            "tax_category": detail.tax_category,
                            "tax_category_name": detail.tax_category_name,
                            "payment_date": detail.payment_date,
                            "transaction_date": detail.transaction_date,
                            "status": detail.status,
                        }
                        detail_data.append(detail_row)
                
                # モレの合成行を追加
                # （累積がある取引先×部門で当月データがない場合）
                # ユーザー要望により、ここ（共通処理）では追加せず、現場用シート出力時のみ追加する仕様に変更 (2026/01/29)

                
                # 5. 例外部門を除外（DB保存・Excel出力・スプレッドシート連携の全てから除外）
                cursor = conn.execute("SELECT dept_code FROM masters_exception_dept")
                exception_dept_codes = {r[0] for r in cursor.fetchall()}
                
                if exception_dept_codes:
                    # OUTPUTから除外
                    summary_data = [r for r in summary_data if r.get("dept_code") not in exception_dept_codes]
                    # DETAILからも除外（整合性のため）
                    detail_data = [r for r in detail_data if r.get("dept_code") not in exception_dept_codes]
                
                ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 実行ログ保存
                conn.execute("""
                    INSERT INTO run_log (run_id, base_month, started_at, ended_at, 
                                        status, input_rows, output_rows, ng_count,
                                        hold_count, dash_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (self.run_id, base_month, started_at, ended_at, "completed",
                      input_rows, len(summary_data), ng_count, hold_count, dash_count))
                
                # 結果保存 (output_summary/detail) - 修正
                self._save_results(conn, self.run_id, summary_data, detail_data)
                
                # Excel出力
                run_info = {
                    "run_id": self.run_id,
                    "base_month": base_month,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "input_rows": input_rows,
                    "output_rows": len(summary_data),
                    "ng_count": ng_count,
                    "hold_count": hold_count,
                    "hold_count": hold_count,
                    "dash_count": dash_count,
                }
                
                # 正マスター統計取得
                from infra.rule_repository import RuleRepository
                rule_repo = RuleRepository()
                try:
                    rule_stats = rule_repo.get_stats(conn)
                    run_info["rule_total"] = rule_stats["total_rules"]
                    run_info["rule_updated"] = rule_stats["last_updated"]
                except Exception:
                    run_info["rule_total"] = 0
                    run_info["rule_updated"] = ""
                
                # --- 追加: データ健全性診断メトリクス ---
                total_input = input_rows if input_rows > 0 else 1
                
                # 1. Null率計算
                def calc_null_rate(key_attr):
                    null_cnt = sum(1 for r in rows if not getattr(r, key_attr, ""))
                    return null_cnt / total_input
                
                run_info["null_rate_dept"] = calc_null_rate("dept_code")
                run_info["null_rate_vendor"] = calc_null_rate("vendor_code")
                run_info["null_rate_payee"] = calc_null_rate("payee_code")
                run_info["null_rate_payment_date"] = calc_null_rate("payment_date")
                run_info["null_rate_tax"] = calc_null_rate("tax_category")
                run_info["null_rate_account"] = calc_null_rate("account_code")
                
                # 2. 日付一致率 (payment_date == transaction_date)
                match_cnt = sum(1 for r in rows if r.payment_date and r.payment_date == r.transaction_date)
                run_info["date_match_rate"] = match_cnt / total_input
                
                # 3. 値分布 (Top 10)
                from collections import Counter
                def get_top_dist(key_attr, n=10):
                    counts = Counter(getattr(r, key_attr, "") for r in rows)
                    return counts.most_common(n)
                
                run_info["dist_tax"] = str(get_top_dist("tax_category"))
                run_info["dist_account"] = str(get_top_dist("account_code"))
                
                # 4. DBパス
                run_info["db_path"] = str(init_database.__globals__.get('DB_PATH', ''))
                
                
                excel_path = write_excel(
                    output_dir,
                    base_month,
                    summary_data,
                    detail_data,
                    excluded_list,
                    run_info
                )
                
                return CheckResult(
                    run_id=self.run_id,
                    base_month=base_month,
                    started_at=started_at,
                    ended_at=ended_at,
                    status="completed",
                    input_rows=input_rows,
                    output_rows=len(summary_data),
                    ng_count=ng_count,
                    hold_count=hold_count,
                    dash_count=dash_count,
                    excel_path=excel_path,
                    rule_total=run_info.get("rule_total", 0),
                    rule_updated=run_info.get("rule_updated"),
                    rule_db_path=run_info.get("db_path", "")
                )
        
        except Exception as e:
            ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_msg = str(e)
            
            # エラー時でも可能な限り診断情報を出力する
            run_info = {
                "run_id": self.run_id,
                "base_month": base_month,
                "started_at": started_at,
                "ended_at": ended_at,
                "status": "error",
                "error_message": error_msg,
                "db_path": str(init_database.__globals__.get('DB_PATH', ''))
            }
            
            excel_path = None
            try:
                # CSVファイルがあれば診断
                if csv_path.exists():
                    diag_info = self._diagnose_csv(csv_path)
                    run_info.update(diag_info)
                
                # エラー用Excel出力（データ行は空）
                excel_path = write_excel(
                    output_dir,
                    base_month,
                    [], # summary
                    [], # detail
                    [], # excluded
                    run_info
                )
            except Exception as e2:
                # 診断や出力ごときで落ちては元も子もないのでログのみ
                print(f"診断出力失敗: {e2}")
                
            return CheckResult(
                run_id=self.run_id,
                base_month=base_month,
                started_at=started_at,
                ended_at=ended_at,
                status="error",
                input_rows=run_info.get("input_rows", 0),
                output_rows=0,
                ng_count=0,
                hold_count=0,
                dash_count=0,
                error_message=error_msg,
                excel_path=excel_path
            )

    def _diagnose_csv(self, csv_path: Path) -> Dict[str, Any]:
        """エラー時にCSVを簡易解析して診断情報を返す"""
        import csv
        from collections import Counter
        
        info = {}
        try:
            with open(csv_path, encoding="cp932", errors="replace", newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                info["csv_headers"] = ", ".join(headers[:80])
                
                rows = list(reader)
                total = len(rows)
                info["input_rows"] = total
                
                if total > 0:
                    # null率計算
                    def calc_rate(col_name):
                        if col_name not in headers: return 0.0 # 列がない場合は欠損扱いはしない（別途ヘッダー不足エラーになるため）
                        cnt = sum(1 for r in rows if not r.get(col_name, "").strip())
                        return cnt / total

                    info["null_rate_dept"] = calc_rate("申請部門表示コード")
                    info["null_rate_vendor"] = calc_rate("取引先コード")
                    info["null_rate_payee"] = calc_rate("支払先コード")
                    info["null_rate_payment_date"] = calc_rate("支払予定日付")
                    info["null_rate_tax"] = calc_rate("消費税区分")
                    info["null_rate_account"] = calc_rate("費用科目コード")
                    
                    # 日付一致率
                    def parse_d(d): return d.replace("/", "-").replace(".", "-") # 簡易正規化
                    
                    match_cnt = 0
                    if "支払予定日付" in headers and "取引日付" in headers:
                        for r in rows:
                            pd = r.get("支払予定日付", "").strip()
                            td = r.get("取引日付", "").strip()
                            if pd and pd == td:
                                match_cnt += 1
                        info["date_match_rate"] = match_cnt / total
                    
                    # 分布
                    def get_dist(col_name):
                        if col_name not in headers: return ""
                        c = Counter(r.get(col_name, "").strip() for r in rows)
                        return str(c.most_common(10))
                        
                    info["dist_tax"] = get_dist("消費税区分")
                    info["dist_account"] = get_dist("費用科目コード")
                    
        except Exception as e:
            info["diagnose_error"] = str(e)
            
        return info

    def _load_latest_ocr_results(self, conn) -> Dict[tuple, List[dict]]:
        """最新のOCR結果を取得 (key: (dept_code, vendor_code)) => list of ocr rows"""
        # 最新のOCR run_idを取得 (OCR実行は run_log に記録されている前提)
        # run_log は現状共通だが、OCR実行かチェック実行かの区分がないかもしれない
        # OCR実行時は run_id を生成しているので、invoice_ocr_results にある最大の run_id を探す方が確実かもしれないが
        # ここでは invoice_ocr_results に存在する run_id の中で、run_log の started_at が最新のものを選ぶ
        
        # 最新の run_id を特定
        cursor = conn.execute("""
            SELECT r.run_id 
            FROM run_log r
            JOIN invoice_ocr_results i ON r.run_id = i.run_id
            ORDER BY r.started_at DESC 
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if not row:
            # run_logになくても invoice_ocr_results にあればそれを使う（バックアップ策）
            cursor = conn.execute("SELECT DISTINCT run_id FROM invoice_ocr_results ORDER BY run_id DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return {}

        run_id = row[0]
        
        # OCR結果取得
        # 注意: dept_code, vendor_code は空の場合がある
        cursor = conn.execute("""
            SELECT dept_code, vendor_code, detected_amount, file_name, confidence 
            FROM invoice_ocr_results 
            WHERE run_id = ?
        """, (run_id,))
        
        results = {}
        for row in cursor:
            # マッチングキーとなる情報がない場合はスキップ
            if not row["dept_code"] or not row["vendor_code"]:
                continue
                
            key = (str(row["dept_code"]), str(row["vendor_code"]))
            if key not in results:
                results[key] = []
            
            results[key].append({
                "detected_amount": row["detected_amount"],
                "file_name": row["file_name"],
                "confidence": row["confidence"]
            })
            
        return results


    def _save_results(self, conn, run_id: str, summaries: List[Dict], details: List[Dict]):
        """結果をDBに保存"""
        # Summary
        for s in summaries:
            # OCR判定計算
            ocr_val = str(s.get("ocr_amount") or "").replace(",", "").strip()
            pay_val = str(s["payment_amount"] or "").strip()
            ocr_match_status = "-"
            
            if not ocr_val:
                ocr_match_status = "-"
            else:
                try:
                    # 数値比較
                    if float(ocr_val) == float(pay_val):
                        ocr_match_status = "OK"
                    else:
                        ocr_match_status = "NG"
                except:
                    # 数値変換失敗時は文字列比較（完全一致かNGか）
                    if ocr_val == pay_val:
                        ocr_match_status = "OK"
                    else:
                        ocr_match_status = "NG"

            conn.execute("""
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
            """, (
                run_id, s["base_invoice_no"], s.get("decision_no", ""), s["dept_code"], s["dept_name"],
                s["vendor_code"], s["vendor_name"], s["payee_code"], s.get("payee_name", ""),
                s["payment_amount"], s["tax_category"],
                s["account_code"], s.get("account_name", ""),
                s["payment_date"], s["transaction_date"], s["status"],
                s.get("bank_account_info", ""),
                s.get("ocr_amount", ""), s.get("ocr_file_link", ""), ocr_match_status,
                s["vendor_payee_result"], s["tax_result"], s["tax_expected"],
                s["account_result"], s["account_expected"], s.get("account_expected_name", ""),
                s["payment_date_result"], s["payment_date_expected"],
                s["anomaly_result"], s["anomaly_type"], s["is_monthly"], s["overall_result"],
            "", s["assignee"],
            s.get("amount_3m_ago", 0), s.get("count_3m_ago", 0),
            s.get("amount_2m_ago", 0), s.get("count_2m_ago", 0),
            s.get("amount_1m_ago", 0), s.get("count_1m_ago", 0),
            s.get("amount_current", 0), s.get("count_current", 0),
            s.get("amount_next", 0), s.get("count_next", 0)
        ))
            
        # Detail
        for d in details:
            conn.execute("""
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
            """, (
                run_id, d["invoice_no"], d["base_invoice_no"], d["branch_no"],
                d["dept_code"], d["dept_name"], d["vendor_code"], d["vendor_name"],
                d["payee_code"], d.get("payee_name", ""), d["account_code"], d.get("account_name", ""),
                d["payment_amount"], d["tax_category"], d.get("tax_category_name", ""),
                d["payment_date"], d["transaction_date"], d["status"]
            ))

if __name__ == "__main__":
    # テスト実行
    from pathlib import Path
    
    base_dir = Path(__file__).parent.parent.parent
    csv_path = base_dir / "ui_mock" / "入力ﾃﾞｰﾀｻﾝﾌﾟﾙ.csv"
    output_dir = base_dir / "data"
    
    if csv_path.exists():
        service = CheckService()
        result = service.run_check(csv_path, "2025-11", output_dir)
        
        print(f"実行ID: {result.run_id}")
        print(f"ステータス: {result.status}")
        print(f"入力行数: {result.input_rows}")
        print(f"出力行数: {result.output_rows}")
        print(f"NG件数: {result.ng_count}")
        print(f"Excel出力: {result.excel_path}")
        
        if result.error_message:
            print(f"エラー: {result.error_message}")
    else:
        print(f"CSVファイルが見つかりません: {csv_path}")
