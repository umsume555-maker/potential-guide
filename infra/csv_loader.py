"""
CSV取込モジュール
E2出力のCSVを読み込み、正規化してDBに格納
"""
import csv
import re
from pathlib import Path
from typing import Iterator, Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime


def normalize_dept_code(code: str) -> str:
    """部門コードを8桁ゼロ埋めに正規化する。数値のみの場合は先頭をゼロ埋め。"""
    if not code:
        return code
    s = str(code).strip()
    # ".0" 付き浮動小数点文字列を整数文字列に変換 (例: "3101010.0" → "3101010")
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.isdigit() and len(s) < 8:
        s = s.zfill(8)
    return s


@dataclass
class InputRow:
    """入力CSV1行分のデータ"""
    invoice_no: str              # 伝票番号（枝番付き）
    base_invoice_no: str         # ベース伝票番号
    decision_no: str             # 決裁番号 (ZSN...) [NEW]
    branch_no: str               # 枝番
    dept_code: str               # 申請部門表示コード
    dept_name: str               # 申請部門名
    status: str                  # 状況区分
    transaction_date: str        # 取引日付 (YYYY-MM-DD)
    payment_date: str            # 支払予定日付 (YYYY-MM-DD)
    vendor_code: str             # 取引先コード
    vendor_name: str             # 取引先名
    payee_code: str              # 支払先コード
    payee_name: str              # 支払先名
    account_code: str            # 費用科目コード
    account_name: str            # 費用科目名
    payment_amount: int          # 支払金額
    tax_category: str            # 消費税区分
    tax_category_name: str       # 消費税区分名


@dataclass
class InvoiceSummary:
    """ベース伝票番号単位のサマリ"""
    base_invoice_no: str
    decision_no: str             # [NEW]
    dept_code: str
    dept_name: str
    vendor_code: str
    vendor_name: str
    payee_code: str
    payee_name: str
    status: str
    transaction_date: str
    payment_date: str
    payment_amount: int          # 合計金額
    tax_category: str            # 最小枝番の税区分
    tax_category_name: str
    account_code: str            # 最小枝番の科目
    account_name: str
    detail_count: int            # 明細数
    detail_count: int            # 明細数
    assignee: str = ""           # 担当
    details: list = field(default_factory=list)


def parse_invoice_no(invoice_no: str) -> tuple[str, str]:
    """
    伝票番号を分解してベース伝票番号と枝番を返す
    例: PI2511000007-0001 -> ("PI2511000007", "0001")
    """
    if not invoice_no:
        return ("", "")
    
    # ハイフンで分割
    parts = invoice_no.rsplit("-", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (invoice_no, "0000")


def parse_date(date_str: str) -> str:
    """
    日付文字列をYYYY-MM-DD形式に変換
    入力形式: YYYYMMDD
    """
    if not date_str or len(date_str) != 8:
        return ""
    try:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except Exception:
        return ""


def get_yyyymm(date_str: str) -> str:
    """日付文字列からYYYY-MM形式を取得"""
    if len(date_str) >= 7:
        return date_str[:7]
    return ""


def load_csv(file_path: Path, encoding: str = "cp932") -> Iterator[InputRow]:
    """
    CSVファイルを読み込んでInputRowを生成
    
    Args:
        file_path: CSVファイルパス
        encoding: 文字エンコーディング（デフォルト: cp932）
    
    Yields:
        InputRow: 1行ずつのデータ
    """
@dataclass
class CsvDiagnostics:
    """CSV診断情報"""
    headers: List[str]
    total_rows: int
    missing_columns: List[str]
    null_rates: Dict[str, float]
    date_match_rate: float # payment_date == transaction_date の割合
    value_distributions: Dict[str, List[tuple]] # key -> [(value, count), ...] top 10

def validate_csv_content(rows: List[InputRow], total_rows: int) -> None:
    """
    CSVの内容健全性をチェックし、異常があればエラーを送出
    """
    if total_rows == 0:
        return

    # 1. dept_code null率 check
    null_dept = sum(1 for r in rows if not r.dept_code)
    null_rate_dept = null_dept / total_rows
    if null_rate_dept > 0.95:
        raise ValueError(f"異常検知: 申請部門コード(dept_code)の欠損率が95%を超えています ({null_rate_dept:.1%})。列ズレの可能性があります。")

    # 2. vendor_code null率 check (入力時点で空はスキップされるので、実質ここには来ないはずだが念のため)
    # load_csvでスキップ済みなので、ここではチェック対象外とするか、InputRow生成前の生データで見る必要がある
    # 現状のload_csv実装では vendor_code 空行は yield されないため、ここはスキップ

    # 3. payment_date == transaction_date check
    # 支払予定日が取引日付と同じ割合が非常に高い場合、列指定ミスの疑い
    match_count = sum(1 for r in rows if r.payment_date and r.payment_date == r.transaction_date)
    match_rate = match_count / total_rows
    if match_rate > 0.95:
        raise ValueError(f"異常検知: 支払予定日が取引日付と同じデータが95%を超えています ({match_rate:.1%})。支払予定日列が取引日付列を参照している可能性があります。")


def load_csv(file_path: Path, encoding: str = "cp932") -> Iterator[InputRow]:
    """
    CSVファイルを読み込んでInputRowを生成
    必須列不足やデータ崩れチェックを含む
    """
    REQUIRED_COLUMNS = {
        "申請部門表示コード", "取引先コード", "支払先コード", 
        "取引日付", "支払予定日付", "支払金額", 
        "消費税区分", "費用科目コード", "伝票番号"
    }

    # エンコーディング自動判別
    detected_enc = encoding
    encodings = ["utf-8-sig", "cp932", "utf-8", "shift_jis"]
    
    for enc in encodings:
        try:
            with open(file_path, encoding=enc, errors="strict", newline="") as f:
                # 先頭だけ読んで判定
                sample = f.read(4096)
                f.seek(0)
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                
                # 必須列がいくつか含まれていればOKとみなす
                if "支払金額" in headers or "取引先コード" in headers:
                    detected_enc = enc
                    break
        except UnicodeError:
            continue
        except Exception:
            continue

    print(f"Loading CSV with encoding: {detected_enc}")

    with open(file_path, encoding=detected_enc, errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        
        # 必須列チェック
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            # エラー詳細用に先頭80列ぐらいを表示
            header_preview = ", ".join(headers[:80])
            raise ValueError(f"必須列が不足しています: {missing}\n検出ヘッダー: {header_preview}")

        # 取引先名カラムの推定
        vendor_name_col = "取引先名（略）" # fallback
        for col in ["取引先名", "取引先名(略)", "取引先名（略）"]:
            if col in headers:
                vendor_name_col = col
                break

        # データ読み込みと診断用バッファリング
        # (generatorだと全件診断前に処理が進んでしまうため、一旦リストにするか、
        #  あるいはチェックサービス側で診断するか。
        #  要件は「停止」なので、ここでバッファリングして診断するのが確実)
        
        rows_buffer = []
        raw_rows_count = 0
        
        for row in reader:
            raw_rows_count += 1
            
            invoice_no = row.get("伝票番号", "").strip()
            decision_no = row.get("決裁番号", "").strip()
            
            # 伝票番号がない場合は決裁番号をフォールバックとして使用
            if not invoice_no:
                if decision_no:
                    invoice_no = decision_no
                else:
                    continue
            
            base_invoice_no, branch_no = parse_invoice_no(invoice_no)
            vendor_code = row.get("取引先コード", "").strip() # null check
            
            # 取引先コード欠損チェック用（load_csvのスキップロジックの前に数えたいが、
            # 既存ロジックを踏襲しつつ、スキップされた行数が多い場合を検知する方が良いか？
            # 今回はシンプルに「有効行」に対する診断を行う）
            
            if not vendor_code:
                continue
            
            try:
                payment_amount = int(row.get("支払金額", "0") or "0")
            except ValueError:
                payment_amount = 0
            
            obj = InputRow(
                invoice_no=invoice_no,
                base_invoice_no=base_invoice_no,
                decision_no=row.get("決裁番号", "").strip(),
                branch_no=branch_no,
                dept_code=normalize_dept_code(row.get("申請部門表示コード", "").strip()),
                dept_name=row.get("申請部門名", "").strip(),
                status=row.get("状況区分", "").strip(),
                transaction_date=parse_date(row.get("取引日付", "")),
                payment_date=parse_date(row.get("支払予定日付", "")),
                vendor_code=vendor_code,
                vendor_name=row.get(vendor_name_col, "").strip(),
                payee_code=row.get("支払先コード", "").strip(),
                payee_name=row.get("支払先名", "").strip(),
                account_code=row.get("費用科目コード", "").strip(),
                account_name=row.get("費用科目名", "").strip(),
                payment_amount=payment_amount,
                tax_category=row.get("消費税区分", "").strip(),
                tax_category_name=row.get("消費税区分名", "").strip(),
            )
            rows_buffer.append(obj)
            
        # コンテンツ診断
        validate_csv_content(rows_buffer, len(rows_buffer))
        
        # 診断OKならyield
        for r in rows_buffer:
            yield r


def aggregate_by_base_invoice(rows: Iterator[InputRow]) -> dict[str, InvoiceSummary]:
    """
    ベース伝票番号単位で集約
    - 支払金額: 合計
    - 税区分/科目: 最小枝番のものを採用
    - その他: 最初の行の値を採用
    """
    summaries: dict[str, InvoiceSummary] = {}
    
    for row in rows:
        key = row.base_invoice_no
        
        if key not in summaries:
            summaries[key] = InvoiceSummary(
                base_invoice_no=row.base_invoice_no,
                decision_no=row.decision_no,
                dept_code=row.dept_code,
                dept_name=row.dept_name,
                vendor_code=row.vendor_code,
                vendor_name=row.vendor_name,
                payee_code=row.payee_code,
                payee_name=row.payee_name,
                status=row.status,
                transaction_date=row.transaction_date,
                payment_date=row.payment_date,
                payment_amount=0,
                tax_category=row.tax_category,
                tax_category_name=row.tax_category_name,
                account_code=row.account_code,
                account_name=row.account_name,
                detail_count=0,
                details=[],
            )
        
        summary = summaries[key]
        summary.payment_amount += row.payment_amount
        summary.detail_count += 1
        summary.details.append(row)
        
        # 最小枝番の税区分・科目を採用
        if row.branch_no < summaries[key].details[0].branch_no:
            summary.tax_category = row.tax_category
            summary.tax_category_name = row.tax_category_name
            summary.account_code = row.account_code
            summary.account_name = row.account_name
    
    # 各サマリで最小枝番のデータを確定
    for key, summary in summaries.items():
        if summary.details:
            # 枝番でソートして最小を取得
            sorted_details = sorted(summary.details, key=lambda x: x.branch_no)
            first = sorted_details[0]
            summary.tax_category = first.tax_category
            summary.tax_category_name = first.tax_category_name
            summary.account_code = first.account_code
            summary.account_name = first.account_name
    
    return summaries


def load_vendor_master_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    取引先マスターCSVを読み込む
    
    Args:
        file_path: CSVファイルパス
        encoding: 文字エンコーディング（デフォルト: cp932）
    
    Yields:
        Dict[str, str]: DBカラム名と値の辞書
    """
    # 休日考慮区分の変換マップ
    HOLIDAY_MAP = {
        "1": "1", # 休日前
        "2": "2", # 休日後
    }
    
    # 期日サイクルから月数・日数を推定する簡易ロジック
    # TODO: 必要に応じて詳細なロジックを実装
    def get_payment_terms(cycle_code):
        # 仮実装: コードから推定（実際はマスタ値を見て調整が必要）
        offset = 1  # デフォルト翌月
        day = 0     # デフォルト末日
        
        if "20" in str(cycle_code): # 20日払い等
            day = 20
        
        if "翌々月" in str(cycle_code):
            offset = 2
        
        return offset, day

    with open(file_path, encoding=encoding, errors="replace", newline="") as f:
        # ヘッダーが多段の可能性があるが、通常のDictReaderで試行
        # E2出力は通常1行目がヘッダー
        reader = csv.reader(f)
        header = next(reader, None)
        
        if not header:
            return
        
        # カラムインデックスの特定（名前で検索）
        def get_idx(name_part):
            for i, h in enumerate(header):
                if name_part in h:
                    return i
            return -1
        
        idx_code = get_idx("取引先コード")
        idx_name = get_idx("取引先名")
        idx_cond_code = get_idx("支払決済条件コード")
        idx_cond_name = get_idx("支払決済条件名")
        idx_holiday = get_idx("休日考慮区分")
        idx_cycle = get_idx("期日サイクル区分")
        idx_closing = get_idx("支払締日")
        
        # 新規追加: Geminiフラグ
        idx_gemini = -1
        for k in ["Gemini", "ジェミニ", "AIフラグ", "AIモデル"]:
            i = get_idx(k)
            if i >= 0:
                idx_gemini = i
                break
        
        if idx_code == -1:
            print("エラー: '取引先コード' カラムが見つかりません。ヘッダー:", header)
            return

        print(f"CSV読み込み開始: 取引先コード列={idx_code}, ヘッダー列数={len(header)}")
        
        # 口座情報
        
        # 口座情報
        idx_bank_code = get_idx("金融機関コード")
        idx_bank_name = get_idx("金融機関名")
        idx_branch_code = get_idx("支店コード")
        idx_branch_name = get_idx("支店名")
        idx_acc_type = get_idx("預金種目")
        idx_acc_num = get_idx("口座番号")
        idx_acc_name = get_idx("口座名義")
        
        seen_codes = set()
        
        for row in reader:
            if len(row) <= idx_code:
                continue
                
            vendor_code = row[idx_code].strip()
            if not vendor_code:
                continue
            
            # 重複チェック（既に処理済みのコードはスキップ）
            if vendor_code in seen_codes:
                print(f"重複スキップ: {vendor_code}")
                continue
            seen_codes.add(vendor_code)
            
            # 期日サイクル
            cycle = row[idx_cycle].strip() if idx_cycle >= 0 else ""
            offset, day = get_payment_terms(cycle)
            
            # 口座種目
            acc_type_raw = row[idx_acc_type].strip() if idx_acc_type >= 0 else ""
            acc_type = "1" if "普通" in acc_type_raw else "2" if "当座" in acc_type_raw else ""
            
            gemini_flag = ""
            if idx_gemini >= 0 and len(row) > idx_gemini:
                gemini_val = row[idx_gemini].strip()
                gemini_flag = gemini_val.translate(str.maketrans("１２", "12"))
            
            yield {
                "vendor_code": vendor_code,
                "vendor_name": row[idx_name].strip() if idx_name >= 0 else "",
                "payment_condition_code": row[idx_cond_code].strip() if idx_cond_code >= 0 else "",
                "payment_condition_name": row[idx_cond_name].strip() if idx_cond_name >= 0 else "",
                "holiday_handling": HOLIDAY_MAP.get(row[idx_holiday].strip(), "1") if idx_holiday >= 0 else "1",
                "payment_cycle_type": cycle,
                "payment_month_offset": str(offset),
                "payment_day": str(day),
                "closing_day": row[idx_closing].strip() if idx_closing >= 0 else "0",
                "bank_code": row[idx_bank_code].strip() if idx_bank_code >= 0 else "",
                "bank_name": row[idx_bank_name].strip() if idx_bank_name >= 0 else "",
                "branch_code": row[idx_branch_code].strip() if idx_branch_code >= 0 else "",
                "branch_name": row[idx_branch_name].strip() if idx_branch_name >= 0 else "",
                "account_type": acc_type,
                "account_number": row[idx_acc_num].strip() if idx_acc_num >= 0 else "",
                "account_holder": row[idx_acc_name].strip() if idx_acc_name >= 0 else "",
                "gemini_flag": gemini_flag,
            }


def load_department_master_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    部門マスターCSVを読み込む
    - 11列目(idx=10): 部門コード (8桁のみ対象)
    - 14列目(idx=13): 部門名
    - 20列目(idx=19): 計上区分 ("直接部門" -> COST, その他 -> SGA)
    """
    
    # エンコーディング推定
    detected_enc = encoding
    encodings = ["cp932", "utf-8-sig", "utf-8", "shift_jis"]
    
    for enc in encodings:
        try:
            with open(file_path, encoding=enc, errors="strict", newline="") as f:
                # 最初の数行を読んでエラーが出ないか確認
                for _ in range(5):
                    next(f)
                detected_enc = enc
                break
        except Exception:
            continue
            
    print(f"Loading Department CSV with encoding: {detected_enc}")

    with open(file_path, encoding=detected_enc, errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader, None)
        except Exception:
            return

        if not header:
            return

        # インデックス定義 (デフォルト)
        IDX_CODE = 10
        IDX_NAME = 13
        IDX_TYPE = 19
        
        # ヘッダーから列位置を探す試み
        def find_idx(candidates):
            for cand in candidates:
                for i, h in enumerate(header):
                    if cand == h.strip(): return i # 完全一致優先
                for i, h in enumerate(header):
                    if cand in h: return i
            return -1
            
        # もしヘッダーらしき文字列があれば列位置を上書き
        if len(header) > 5 and any("コード" in h for h in header):
             c_idx = find_idx(["部門コード", "組織コード"])
             n_idx = find_idx(["部門名", "組織名"])
             # "計上区分" を "区分" より先に試す
             t_idx = find_idx(["計上区分", "区分"])
             
             # 見つかった場合のみ上書き
             if c_idx >= 0: IDX_CODE = c_idx
             if n_idx >= 0: IDX_NAME = n_idx
             if t_idx >= 0: IDX_TYPE = t_idx
             print(f"Header Detected: Code={IDX_CODE}, Name={IDX_NAME}, Type={IDX_TYPE}")

        seen_codes = set()
        
        for row in reader:
            if len(row) <= IDX_TYPE:
                continue
                
            code = row[IDX_CODE].strip()
            
            # 8桁以外はスキップ
            if len(code) != 8 or not code.isdigit():
                continue
                
            if code in seen_codes:
                continue
            seen_codes.add(code)
            
            dept_name = row[IDX_NAME].strip()
            kbn = row[IDX_TYPE].strip()
            
            # 区分判定 (文字化け対策も含めて "直接" を含むか、あるいは特定のコードかも考慮)
            # UTF-8/SJISの揺らぎや余分な空白を除去
            is_cost = "直接" in kbn
            
            dept_type = "COST" if is_cost else "SGA"
            
            yield {
                "dept_code": code,
                "dept_name": dept_name,
                "dept_type": dept_type
            }


def load_exception_dept_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    例外部門CSVを読み込む（出力対象外の部門を登録）
    
    想定カラム:
    - 1列目: 部門コード (必須)
    - 2列目: 部門名 (任意)
    - 3列目: 除外理由 (任意)
    
    Returns:
        各行から以下を生成:
        - dept_code: 部門コード
        - dept_name: 部門名
        - reason: 除外理由
    """
    with open(file_path, encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        if not header:
            return
        
        # ヘッダー推定
        def get_idx(candidates):
            for i, h in enumerate(header):
                h_norm = h.strip().replace("ｺｰﾄﾞ", "コード")
                for c in candidates:
                    if c in h_norm:
                        return i
            return -1
        
        idx_code = get_idx(["部門コード", "部門ｺｰﾄﾞ", "部門CD"])
        idx_name = get_idx(["部門名"])
        idx_reason = get_idx(["理由", "除外理由", "備考"])
        
        # ヘッダーが見つからない場合、位置で推定
        if idx_code < 0:
            idx_code = 0
        if idx_name < 0 and len(header) > 1:
            idx_name = 1
        if idx_reason < 0 and len(header) > 2:
            idx_reason = 2
        
        seen_codes = set()
        
        for row in reader:
            if len(row) < 1:
                continue
            
            dept_code = row[idx_code].strip()
            if not dept_code:
                continue
            
            if dept_code in seen_codes:
                continue
            seen_codes.add(dept_code)
            
            dept_name = row[idx_name].strip() if idx_name >= 0 and len(row) > idx_name else ""
            reason = row[idx_reason].strip() if idx_reason >= 0 and len(row) > idx_reason else ""
            
            yield {
                "dept_code": dept_code,
                "dept_name": dept_name,
                "reason": reason
            }


def load_account_rule_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    科目ルールCSVを読み込む
    想定カラム:
    - 取引先コード (必須)
    - 適用範囲/部門 (任意: 8桁数字->DEPT, 'SGA'/'COST'->DEPT_TYPE, 空欄->ANY)
    - 費用科目コード (必須)
    - 理由 (任意)
    """
    with open(file_path, encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        if not header:
            return

        # ヘッダー推定 (簡易ロジック)
        def get_idx(candidates):
            for i, h in enumerate(header):
                if any(c in h for c in candidates):
                    return i
            return -1
            
        idx_vendor = get_idx(["取引先コード", "VendorCode"])
        idx_scope = get_idx(["部門", "適用範囲", "Dept"])
        idx_account = get_idx(["科目", "Account", "費用科目"])
        idx_reason = get_idx(["理由", "Reason", "備考"])
        
        if idx_vendor == -1 or idx_account == -1:
            # 必須列なし
            print(f"必須列不足: header={header}")
            return
            
        for row in reader:
            if len(row) <= max(idx_vendor, idx_account):
                continue
                
            vendor_code = row[idx_vendor].strip()
            if not vendor_code:
                continue
                
            account_code = row[idx_account].strip()
            if not account_code:
                continue
                
            # Scope判定
            scope_raw = row[idx_scope].strip() if idx_scope >= 0 and len(row) > idx_scope else ""
            
            scope_type = "ANY"
            scope_key = ""
            
            if not scope_raw:
                scope_type = "ANY"
            elif scope_raw in ["SGA", "COST", "販管", "原価"]:
                scope_type = "DEPT_TYPE"
                # 日本語対応
                if scope_raw == "販管": scope_key = "SGA"
                elif scope_raw == "原価": scope_key = "COST"
                else: scope_key = scope_raw
            elif re.match(r"^\d{8}$", scope_raw):
                scope_type = "DEPT"
                scope_key = scope_raw
            else:
                # その他は一旦ANY扱いにするか、エラーにするか？
                # ここでは安全側に倒して「DEPT扱いだがマッチしない」または「ANY」だが、
                # ユーザー意図不明な文字列はANYにすると危険なので、
                # 8桁でなければ DEPT_TYPE とみなして登録してみる（SGA/COST以外も増える可能性）
                # あるいは文字列そのままで DEPT_TYPE に。
                scope_type = "DEPT_TYPE"
                scope_key = scope_raw
                
            reason = row[idx_reason].strip() if idx_reason >= 0 and len(row) > idx_reason else "CSV Import"
            
            yield {
                "vendor_code": vendor_code,
                "scope_type": scope_type,
                "scope_key": scope_key,
                "expected_account": account_code,
                "reason": reason
            }


def load_vendor_rule_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    取引先ルールCSVを読み込む（科目＋税区分を一度に登録）
    - エンコーディング自動判別（cp932 -> utf-8-sig）
    """
    
    def _read_with_enc(enc):
        try:
            with open(file_path, encoding=enc, errors="strict", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return None, None, None
                
                # ヘッダー推定
                def get_idx(candidates):
                    for i, h in enumerate(header):
                        h_lower = h.lower().replace(' ', '').replace('　', '')
                        if any(c.lower().replace(' ', '') in h_lower for c in candidates):
                            return i
                    return -1
                    
                idx_vendor = get_idx(["取引先コード", "取引先ｺｰﾄﾞ", "VendorCode"])
                
                # 取引先コードが見つからなければエンコーディング不一致とみなす（または単なる形式違い）
                if idx_vendor == -1:
                    return None, None, None
                    
                return reader, header, idx_vendor
        except UnicodeError:
            return None, None, None

    # 1. Try CP932 (Standard for Excel in Japan)
    # Using "replace" might hide mojibake headers, so we used "strict" in helper to fail fast? 
    # But usually we use "replace" outside. Here we want to detect structure.
    # Let's try "replace" but check if idx_vendor is found.
    
    selected_encoding = encoding
    reader = None
    header = None
    
    # helper for detection requires opening via helper? 
    # Cannot yield from closed file.
    
    # Strategy: Determine encoding first
    encodings = ["cp932", "utf-8-sig", "utf-8", "shift_jis"]
    detected_enc = None
    
    for enc in encodings:
        try:
            with open(file_path, encoding=enc, errors="replace", newline="") as f:
                r = csv.reader(f)
                h = next(r, None)
                if h:
                    # Check for "取引先" or "Vendor"
                    # Simple heuristic
                    h_str = "".join(h)
                    if "取引先" in h_str or "Vendor" in h_str:
                        detected_enc = enc
                        break
        except Exception:
            continue
    
    if not detected_enc:
        detected_enc = "cp932" # Fallback
    
    print(f"Loading Vendor Rule CSV with encoding: {detected_enc}")
    
    with open(file_path, encoding=detected_enc, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        if not header:
            return

        def get_idx(candidates):
            for i, h in enumerate(header):
                h_lower = h.lower().replace(' ', '').replace('　', '')
                if any(c.lower().replace(' ', '') in h_lower for c in candidates):
                    return i
            return -1
            
        idx_vendor = get_idx(["取引先コード", "取引先ｺｰﾄﾞ", "VendorCode", "Vendor"])
        idx_cost = get_idx(["cost科目", "cost科目コード", "cost科目ｺｰﾄﾞ", "原価科目", "cost"])
        idx_sga = get_idx(["sga科目", "sga科目コード", "sga科目ｺｰﾄﾞ", "販管科目", "sga"])
        idx_any = get_idx(["科目", "科目コード", "科目ｺｰﾄﾞ", "費用科目", "AccountCode", "Account"])
        idx_tax = get_idx(["税区分", "税区分コード", "税区分ｺｰﾄﾞ", "TaxCode", "Tax"])
        idx_gemini = get_idx(["AI", "Gemini", "ジェミニ", "AIフラグ"])
        
        print(f"Header detected: vendor={idx_vendor}, cost={idx_cost}, sga={idx_sga}, any={idx_any}, tax={idx_tax}, gemini={idx_gemini}")
        
        if idx_vendor == -1:
            print(f"必須列不足: 取引先コードが見つかりません。header={header}")
            return
            
        for row in reader:
            if len(row) <= idx_vendor:
                continue
                
            vendor_code = row[idx_vendor].strip()
            if not vendor_code:
                continue
            
            # ANY科目 (共通)
            if idx_any >= 0 and len(row) > idx_any:
                any_account = row[idx_any].strip()
                if any_account:
                     yield {
                        "type": "account",
                        "vendor_code": vendor_code,
                        "scope_type": "ANY",
                        "scope_key": "",
                        "expected_account": any_account,
                        "reason": "CSV Import"
                    }

            # COST科目
            if idx_cost >= 0 and len(row) > idx_cost:
                cost_account = row[idx_cost].strip()
                if cost_account:
                    yield {
                        "type": "account",
                        "vendor_code": vendor_code,
                        "scope_type": "DEPT_TYPE",
                        "scope_key": "COST",
                        "expected_account": cost_account,
                        "reason": "CSV Import"
                    }
            
            # SGA科目
            if idx_sga >= 0 and len(row) > idx_sga:
                sga_account = row[idx_sga].strip()
                if sga_account:
                    yield {
                        "type": "account",
                        "vendor_code": vendor_code,
                        "scope_type": "DEPT_TYPE",
                        "scope_key": "SGA",
                        "expected_account": sga_account,
                        "reason": "CSV Import"
                    }
            
            # 税区分
            if idx_tax >= 0 and len(row) > idx_tax:
                tax_code = row[idx_tax].strip()
                if tax_code:
                    yield {
                        "type": "tax",
                        "vendor_code": vendor_code,
                        "expected_tax": tax_code,
                        "reason": "CSV Import"
                    }

            # AI Flag
            if idx_gemini >= 0 and len(row) > idx_gemini:
                val = row[idx_gemini].strip()
                if val:
                    yield {
                        "type": "ai_setting",
                        "vendor_code": vendor_code,
                        "gemini_flag": val.translate(str.maketrans("１２", "12")),
                        "reason": "CSV Import"
                    }


def load_account_master_csv(file_path: Path, encoding: str = "cp932") -> Iterator[Dict[str, str]]:
    """
    科目マスタCSVを読み込む
    
    想定カラム:
    - 科目コード (必須)
    - 科目名 (必須)
    """
    with open(file_path, encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        if not header:
            return

        # ヘッダー推定
        def get_idx(candidates):
            for i, h in enumerate(header):
                h_lower = h.lower().replace(' ', '').replace('　', '')
                if any(c.lower().replace(' ', '') in h_lower for c in candidates):
                    return i
            return -1
            
        idx_code = get_idx(["科目コード", "科目ｺｰﾄﾞ", "AccountCode", "勘定科目コード"])
        idx_name = get_idx(["科目名", "勘定科目名", "AccountName"])
        
        print(f"Account Master Header: code={idx_code}, name={idx_name}, header={header}")
        
        if idx_code == -1 or idx_name == -1:
            print(f"必須列不足: 科目コード or 科目名が見つかりません")
            return
            
        for row in reader:
            if len(row) <= max(idx_code, idx_name):
                continue
                
            code = row[idx_code].strip()
            name = row[idx_name].strip()
            
            if not code or not name:
                continue
            
            yield {
                "account_code": code,
                "account_name": name
            }


if __name__ == "__main__":
    # テスト実行
    import sys
    
    test_path = Path(__file__).parent.parent / "ui_mock" / "入力ﾃﾞｰﾀｻﾝﾌﾟﾙ.csv"
    if test_path.exists():
        rows = list(load_csv(test_path))
        print(f"読み込み行数: {len(rows)}")
        
        summaries = aggregate_by_base_invoice(iter(rows))
        print(f"ベース伝票数: {len(summaries)}")
    
    # マスタテスト
    master_path = Path(__file__).parent.parent / "ui_mock" / "取引先(支払先出力).csv"
    if master_path.exists():
        vendors = list(load_vendor_master_csv(master_path))
        print(f"マスタ読み込み件数: {len(vendors)}")
        if vendors:
            print(f"例: {vendors[0]}")

