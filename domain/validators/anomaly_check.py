"""
ズレ・モレ・二重判定
毎月判定を基に異常検知を行う
"""
from typing import Optional
from dataclasses import dataclass


@dataclass
class MonthlyCount:
    """月別の金額・個数"""
    yyyymm: str
    total_amount: int
    count: int  # 個数（マイナス金額は-1）

from collections import defaultdict



def determine_monthly_flag(
    counts_4_months: list[MonthlyCount]
) -> bool:
    """
    毎月判定
    直近4ヶ月の個数合計 >= 3 なら毎月
    
    Args:
        counts_4_months: 直近4ヶ月の個数データ
    
    Returns:
        True: 毎月, False: 毎月以外
    """
    total_count = sum(c.count for c in counts_4_months)
    return total_count >= 3


def check_anomaly(
    is_monthly: bool,
    base_month: str,
    transaction_month: str,
    date_tolerance: int,
    count_1m_ago: int,
    count_current: int,
    has_current_month_data: bool,
    current_amounts: Optional[list] = None
) -> tuple[str, str, str]:
    """
    ズレ・モレ・二重判定
    
    Args:
        is_monthly: 毎月フラグ
        base_month: 基準月 (YYYY-MM)
        transaction_month: 取引日付の月 (YYYY-MM)
        date_tolerance: 取引日付許容月ずれ (0 or 1)
        count_1m_ago: 1ヶ月前の個数
        count_current: 当月の個数
        has_current_month_data: 当月データが存在するか
        current_amounts: 当月の金額リスト（二重判定用）
    
    Returns:
        (判定結果, 種別, 理由)
        - 判定結果: OK/NG
        - 種別: モレ/月ズレ？/二重入力？/空欄
    """
    anomaly_type = ""
    reason = ""
    
    # 基準月の翌月を計算
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    
    base_date = datetime.strptime(base_month + "-01", "%Y-%m-%d")
    next_month = (base_date + relativedelta(months=1)).strftime("%Y-%m")
    
    # ズレ判定
    # 定義: 取引日付が翌月 かつ 当月個数が0
    if transaction_month == next_month:
        if count_current == 0:
            anomaly_type = "月ズレ？"
            reason = f"取引日付が翌月({transaction_month})、当月個数=0"
    
    # 毎月の場合のみモレ・二重を判定
    # ※既に「ズレ」が入っている場合はスキップ（ズレ優先）
    if is_monthly and not anomaly_type:
        # モレ判定（当月データが0件）
        if not has_current_month_data:
            # ここでは単一の判定のみ。全体スキャンは find_missing_vendors で行う
            anomaly_type = "毎月あるのに今月ない"
            reason = "毎月取引だが当月データなし"
        
        # 二重判定
        # 定義: 前月1個以下 かつ 当月2個以上 かつ 同一金額
        elif count_1m_ago <= 1 and count_current >= 2:
            # 金額チェック (Strict Mode)
            is_same_amount = False
            if current_amounts and len(current_amounts) >= 2:
                # 全ての金額が同一かチェック
                first_amt = current_amounts[0]
                is_same_amount = all(amt == first_amt for amt in current_amounts)
            
            if is_same_amount:
                anomaly_type = "二重入力？"
                reason = f"前月={count_1m_ago}, 当月={count_current}, 同一金額({current_amounts[0]})"
    
    # 種別の優先順位: モレ > ズレ > 二重
    # 既にズレが入っている場合はズレのまま
    
    # 判定結果
    if anomaly_type:
        return ("NG", anomaly_type, reason)
    return ("OK", "", "")


def get_monthly_counts_from_cumulative(
    conn,
    vendor_code: str,
    dept_code: str,
    base_month: str
) -> list[MonthlyCount]:
    """
    累積から直近4ヶ月の個数を取得
    
    Args:
        conn: SQLite接続
        vendor_code: 取引先コード
        dept_code: 申請部門コード
        base_month: 基準月 (YYYY-MM)
    
    Returns:
        直近4ヶ月の個数リスト（古い順）
    """
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    
    base_date = datetime.strptime(base_month + "-01", "%Y-%m-%d")
    months = []
    for i in range(4, 0, -1):
        m = (base_date - relativedelta(months=i)).strftime("%Y-%m")
        months.append(m)
    
    result = []
    for m in months:
        cursor = conn.execute(
            """
            SELECT 
                COALESCE(SUM(payment_amount), 0) as total_amount,
                COUNT(*) as count
            FROM cumulative
            WHERE vendor_code = ?
              AND dept_code = ?
              AND yyyymm = ?
            """,
            (vendor_code, dept_code, m)
        )
        row = cursor.fetchone()
        # マイナス金額の処理は別途必要
        result.append(MonthlyCount(
            yyyymm=m,
            total_amount=row["total_amount"] if row else 0,
            count=row["count"] if row else 0
        ))
    
    return result


def create_synthetic_row(
    vendor_code: str,
    dept_code: str,
    dept_name: str,
    vendor_name: str,
    base_month: str
) -> dict:
    """
    モレの合成行を作成
    
    Returns:
        合成行データ（辞書形式）
    """
    row = {
        "vendor_code": vendor_code,
        "dept_code": dept_code,
        "dept_name": dept_name,
        "vendor_name": vendor_name,
        "base_invoice_no": "-",
        "payee_code": "",
        "payee_name": "",
        "payment_amount": "",
        "tax_category": "",
        "tax_category_name": "",
        "account_code": "",
        "account_name": "",
        "payment_date": "",
        "transaction_date": "",
        "anomaly_result": "NG",
        "anomaly_type": "毎月あるのに今月ない",
        "is_synthetic": 1,
    }
    
    # 統計情報の初期値（モレなので当月などは0）
    row.update({
        "overall_result": "NG",
        "vendor_payee_result": "OK",
        "payment_date_result": "OK",
        "tax_result": "OK",
        "account_result": "OK",
        "is_monthly": "毎月",
        "status": "未申請",
        "amount_3m_ago": 0, "count_3m_ago": 0,
        "amount_2m_ago": 0, "count_2m_ago": 0,
        "amount_1m_ago": 0, "count_1m_ago": 0,
        "amount_current": 0, "count_current": 0,
        "amount_next": 0, "count_next": 0
    })
    return row


def find_missing_vendors(
    conn,
    base_month: str,
    current_pairs: set[tuple[str, str]]
) -> list[dict]:
    """
    毎月あるのに今月ないデータを検出
    
    Args:
        conn: SQLite接続
        base_month: 基準月
        current_pairs: 当月存在する (vendor_code, dept_code) のセット
        
    Returns:
        合成行リスト
    """
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    
    # 1. 前月を計算
    base_date = datetime.strptime(base_month + "-01", "%Y-%m-%d")
    prev_month = (base_date - relativedelta(months=1)).strftime("%Y-%m")
    next_month = (base_date + relativedelta(months=1)).strftime("%Y-%m")
    
    # 2. 前月に取引があったペアを取得（マスタから名前を取得）
    # 部門名はcumulativeから直接取得（マスタにない場合があるため）
    cursor = conn.execute("""
        SELECT DISTINCT c.vendor_code, c.dept_code, 
               COALESCE(mv.vendor_name, c.vendor_name, '') as vendor_name, 
               COALESCE(c.dept_name, '') as dept_name
        FROM cumulative c
        LEFT JOIN masters_vendor mv ON c.vendor_code = mv.vendor_code
        WHERE c.yyyymm = ?
          AND c.dept_code IS NOT NULL AND c.dept_code != ''
    """, (prev_month,))
    candidates = cursor.fetchall()
    
    print(f"[INFO] モレ検知候補ペア数: {len(candidates)} (前月: {prev_month})")
    if not candidates:
        return []

    # 3. 直近4ヶ月 (M-4 ~ M-1) のデータを一括取得 (N+1回避)
    target_months = []
    for i in range(4, 0, -1):
        m = (base_date - relativedelta(months=i)).strftime("%Y-%m")
        target_months.append(m)
    
    placeholders = ",".join(["?"] * len(target_months))
    sql = f"""
        SELECT vendor_code, dept_code, yyyymm, SUM(payment_amount) as total_amount, COUNT(*) as count
        FROM cumulative
        WHERE yyyymm IN ({placeholders})
        GROUP BY vendor_code, dept_code, yyyymm
    """
    rows = conn.execute(sql, target_months).fetchall()
    print(f"[INFO] 過去データ一括取得: {len(rows)} 件")

    # マップ化: (vendor, dept) -> { yyyymm: MonthlyCount }
    # SELECT順序: vendor_code(0), dept_code(1), yyyymm(2), total_amount(3), count(4)
    data_map = defaultdict(dict)
    for r in rows:
        key = (r[0], r[1])
        data_map[key][r[2]] = MonthlyCount(r[2], r[3], r[4])

    missing_rows = []
    
    # 例外部門と除外取引先を取得
    exception_depts = set()
    excluded_vendors = set()
    try:
        cursor_exc = conn.execute("SELECT dept_code FROM masters_exception_dept")
        exception_depts = {r[0] for r in cursor_exc.fetchall()}
        print(f"[INFO] 例外部門数: {len(exception_depts)}")
        
        cursor_exv = conn.execute("SELECT vendor_code FROM masters_exclude")
        excluded_vendors = {r[0] for r in cursor_exv.fetchall()}
        print(f"[INFO] 除外取引先数: {len(excluded_vendors)}")
    except Exception as e:
        print(f"[WARN] 除外リスト取得エラー: {e}")
    
    # SELECT順序: vendor_code(0), dept_code(1), vendor_name(2), dept_name(3)
    for row in candidates:
        v_code = row[0]
        d_code = row[1]
        
        # 除外チェック: 例外部門または除外取引先に該当する場合はスキップ
        if d_code in exception_depts:
            continue
        if v_code in excluded_vendors:
            continue
        
        # 4. 当月データがあるか確認
        if (v_code, d_code) in current_pairs:
            continue
            
        # 5. 直近4ヶ月データ構築
        counts = []
        for m in target_months:
            counts.append(data_map.get((v_code, d_code), {}).get(m, MonthlyCount(m, 0, 0)))
        
        if determine_monthly_flag(counts):
            # 6. Gap要件チェック
            # 「ズレ」として検出されるケース（翌月データがある）はモレとしない
            # output_summary を検索して翌月データがあるか確認
            # Note: output_summaryはRunごとに作られるので、現在のRunに含まれる翌月日付のトランザクションを探す
            # 呼び出し元のconnは現在処理中のDB接続
            
            # TODO: date_tolerance=0 は固定と仮定 (ズレ定義より)
            # transaction_dateのフォーマットは YYYY-MM-DD
            
            has_gap_data = False
            try:
                # 日付比較 (LIKE 'YYYY-MM%')
                gap_cursor = conn.execute("""
                    SELECT 1 FROM output_summary 
                    WHERE vendor_code = ? 
                      AND dept_code = ?
                      AND transaction_date LIKE ?
                      LIMIT 1
                """, (v_code, d_code, f"{next_month}%"))
                if gap_cursor.fetchone():
                    has_gap_data = True
            except Exception as e:
                # テーブルがない場合など
                pass
            
            if has_gap_data:
                # ズレとして扱われるため、モレにはしない
                continue

            # 7. モレ確定 -> 合成行作成
            # row: vendor_code(0), dept_code(1), vendor_name(2), dept_name(3)
            synthetic_row = create_synthetic_row(
                v_code, d_code, row[3], row[2], base_month
            )
            # 統計データ補完
            # counts は [M-4, M-3, M-2, M-1]
            if len(counts) >= 4:
                synthetic_row["amount_3m_ago"] = counts[1].total_amount
                synthetic_row["count_3m_ago"] = counts[1].count
                synthetic_row["amount_2m_ago"] = counts[2].total_amount
                synthetic_row["count_2m_ago"] = counts[2].count
                synthetic_row["amount_1m_ago"] = counts[3].total_amount
                synthetic_row["count_1m_ago"] = counts[3].count
                
            missing_rows.append(synthetic_row)
            
    return missing_rows


if __name__ == "__main__":
    # テスト
    counts = [
        MonthlyCount("2025-06", 100000, 1),
        MonthlyCount("2025-07", 100000, 1),
        MonthlyCount("2025-08", 100000, 1),
        MonthlyCount("2025-09", 100000, 1),
    ]
    
    is_monthly = determine_monthly_flag(counts)
    print(f"毎月判定: {is_monthly}")
    
    # 二重
    result, atype, reason = check_anomaly(
        is_monthly=True,
        base_month="2025-10",
        transaction_month="2025-10",
        date_tolerance=0,
        count_1m_ago=1,
        count_current=2,
        has_current_month_data=True
    )
    print(f"二重: {result}, 種別={atype}, {reason}")
    
    # ズレ
    result, atype, reason = check_anomaly(
        is_monthly=False,
        base_month="2025-10",
        transaction_month="2025-11",
        date_tolerance=0,
        count_1m_ago=0,
        count_current=1,
        has_current_month_data=True
    )
    print(f"ズレ: {result}, 種別={atype}, {reason}")
