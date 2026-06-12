"""
支払予定日チェック
取引先マスターの支払パターンから期待日を計算し、完全一致のみOK
休日判定: 土日＋祝日＋年末年始(12/31～1/3)
"""
from datetime import date, timedelta
from typing import Optional, Set
from dateutil.relativedelta import relativedelta


def is_holiday(
    check_date: date,
    holidays: Set[str]
) -> bool:
    """
    休日かどうか判定
    - 土曜・日曜
    - 祝日（holidaysセット）
    - 年末年始（12/31～1/3）
    """
    # 土日
    if check_date.weekday() >= 5:
        return True
    
    # 祝日
    date_str = check_date.strftime("%Y-%m-%d")
    if date_str in holidays:
        return True
    
    # 年末年始
    month_day = (check_date.month, check_date.day)
    if month_day in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        return True
    
    return False


def adjust_for_holiday(
    target_date: date,
    holidays: Set[str],
    before: bool = True,
    no_month_crossing: bool = False
) -> date:
    """
    休日の場合に営業日へ調整
    
    Args:
        target_date: 調整対象日
        holidays: 祝日セット
        before: True=休日前（前倒し）, False=休日後（後ろ倒し）
        no_month_crossing: True=月跨ぎ不可（後ろ倒しで翌月になる場合は前倒し）
    
    Returns:
        調整後の日付
    """
    original_month = target_date.month
    adjusted = target_date
    delta = timedelta(days=-1 if before else 1)
    
    while is_holiday(adjusted, holidays):
        adjusted += delta
        
        # 月跨ぎ不可で翌月に入った場合は前倒しに切り替え
        if no_month_crossing and not before and adjusted.month != original_month:
            # 戻って前倒しで再計算
            adjusted = target_date
            delta = timedelta(days=-1)
            while is_holiday(adjusted, holidays):
                adjusted += delta
            break
    
    return adjusted


def get_last_day_of_month(year: int, month: int) -> date:
    """月末日を取得"""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return next_month - timedelta(days=1)


def get_closing_date(transaction_date: date, closing_day: int) -> date:
    """
    取引日が属する締め期間の締日を返す。

    Args:
        transaction_date: 取引日付
        closing_day: 締日（0=末日, 1-31）

    Returns:
        その取引が属する締め期間の締日

    Examples:
        closing_day=20 の場合:
          - 取引日 10/10 → 10/20 締め（10月分）
          - 取引日 10/25 → 11/20 締め（11月分）
        closing_day=0（末日）の場合:
          - 取引日 10/10 → 10/31 締め
          - 取引日 10/31 → 10/31 締め
    """
    y, m, d = transaction_date.year, transaction_date.month, transaction_date.day

    if closing_day == 0 or closing_day == 99:
        # 末日締め: 取引月の末日が締日
        return get_last_day_of_month(y, m)

    # 取引日 <= 締日 → 同月の締日
    # 取引日 >  締日 → 翌月の締日
    if d <= closing_day:
        # 同月の closing_day 日（月末を超えないようにクランプ）
        last = get_last_day_of_month(y, m)
        actual_day = min(closing_day, last.day)
        return date(y, m, actual_day)
    else:
        # 翌月の closing_day 日
        next_month = date(y, m, 1) + relativedelta(months=1)
        last = get_last_day_of_month(next_month.year, next_month.month)
        actual_day = min(closing_day, last.day)
        return date(next_month.year, next_month.month, actual_day)


def calculate_expected_payment_date(
    transaction_date: date,
    closing_day: int,
    payment_month_offset: int,
    payment_day: int,
    holiday_handling: str,
    holidays: Set[str],
    no_month_crossing: bool = False
) -> date:
    """
    期待支払日を計算

    Args:
        transaction_date: 取引日付
        closing_day: 締日（99=末日, 1-31）
        payment_month_offset: 締日基準の支払月数（0=締日当月, 1=締日翌月, 2=締日翌々月）
        payment_day: 支払日（99=末日, 1-31）
        holiday_handling: 休日考慮区分（"1"=休日前倒し, "2"=休日後倒し）
        holidays: 祝日セット（YYYY-MM-DD 文字列）
        no_month_crossing: True=後倒しで翌月になる場合は前倒しに切り替え

    Returns:
        期待支払日（休日調整済み）

    Notes:
        修正前は closing_day を無視して取引日をそのまま基準にしていた。
        正しくは: 取引日 → 属する締め期間の締日 → +offset ヶ月 → payment_day
    """
    # 1. 取引日が属する締め期間の締日を求める
    closing_date = get_closing_date(transaction_date, closing_day)

    # 2. 締日から payment_month_offset ヶ月後の月を支払月とする
    payment_month_date = closing_date + relativedelta(months=payment_month_offset)

    # 3. 支払日を決定
    if payment_day == 0 or payment_day == 99:
        # 末日払い
        expected = get_last_day_of_month(
            payment_month_date.year,
            payment_month_date.month
        )
    else:
        last = get_last_day_of_month(payment_month_date.year, payment_month_date.month)
        expected = date(
            payment_month_date.year,
            payment_month_date.month,
            min(payment_day, last.day)
        )

    # 4. 休日調整
    before = (holiday_handling == "1")
    expected = adjust_for_holiday(expected, holidays, before, no_month_crossing)

    return expected


def check_payment_date(
    applied_date: str,
    expected_date: str
) -> tuple[str, str]:
    """
    支払予定日チェック（完全一致のみOK）
    
    Args:
        applied_date: 申請の支払予定日 (YYYY-MM-DD)
        expected_date: 期待支払日 (YYYY-MM-DD)
    
    Returns:
        (判定結果, 理由)
    """
    if not applied_date:
        return ("NG", "支払予定日が空欄")
    
    if not expected_date:
        return ("-", "期待日を計算できません")
    
    if applied_date == expected_date:
        return ("OK", "")
    
    return (
        "NG",
        f"申請: {applied_date}, 期待: {expected_date}"
    )


def load_holidays_from_db(conn) -> Set[str]:
    """DBから祝日セットを読み込む"""
    cursor = conn.execute("SELECT holiday_date FROM holidays")
    return {row["holiday_date"] for row in cursor}


if __name__ == "__main__":
    # テスト
    holidays = {"2025-11-03", "2025-11-23", "2025-12-23"}
    
    # 翌月末休日前
    tx_date = date(2025, 10, 15)
    expected = calculate_expected_payment_date(
        tx_date,
        closing_day=0,
        payment_month_offset=1,
        payment_day=0,
        holiday_handling="1",
        holidays=holidays
    )
    print(f"取引日: {tx_date} → 支払日: {expected}")
    
    # 翌月27日休日後
    expected2 = calculate_expected_payment_date(
        tx_date,
        closing_day=0,
        payment_month_offset=1,
        payment_day=27,
        holiday_handling="2",
        holidays=holidays
    )
    print(f"取引日: {tx_date} → 支払日(27日): {expected2}")
