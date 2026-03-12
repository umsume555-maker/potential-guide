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
        closing_day: 締日（0=末日, 1-31）
        payment_month_offset: 期日指定月数（1=翌月, 2=翌々月）
        payment_day: 期日指定日（0=末日, 1-31）
        holiday_handling: 休日考慮区分（"1"=休日前, "2"=休日後）
        holidays: 祝日セット
        no_month_crossing: 月跨ぎ不可
    
    Returns:
        期待支払日
    """
    # 基準月を計算（取引日から支払月を算出）
    base_date = transaction_date
    
    # 支払月を計算
    payment_month_date = base_date + relativedelta(months=payment_month_offset)
    
    # 支払日を設定
    if payment_day == 0:
        # 末日
        expected = get_last_day_of_month(
            payment_month_date.year, 
            payment_month_date.month
        )
    else:
        try:
            expected = date(
                payment_month_date.year,
                payment_month_date.month,
                min(payment_day, get_last_day_of_month(
                    payment_month_date.year, 
                    payment_month_date.month
                ).day)
            )
        except ValueError:
            # 日付が無効な場合は末日
            expected = get_last_day_of_month(
                payment_month_date.year, 
                payment_month_date.month
            )
    
    # 休日調整
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
