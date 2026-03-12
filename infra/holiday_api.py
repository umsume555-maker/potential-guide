"""
祝日API
内閣府の祝日CSVから祝日データを取得
"""
import httpx
from datetime import datetime
from typing import List, Tuple
import csv
import io


HOLIDAY_CSV_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


async def fetch_holidays_from_api() -> List[Tuple[str, str]]:
    """
    内閣府APIから祝日データを取得
    
    Returns:
        [(日付, 祝日名), ...] のリスト
        日付は YYYY-MM-DD 形式
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(HOLIDAY_CSV_URL, timeout=30.0)
        response.raise_for_status()
        
        # Shift-JISでデコード
        content = response.content.decode("shift_jis")
        
        holidays = []
        reader = csv.reader(io.StringIO(content))
        
        for i, row in enumerate(reader):
            if i == 0:
                continue  # ヘッダー行をスキップ
            
            if len(row) >= 2:
                date_str = row[0].strip()
                name = row[1].strip()
                
                # 日付をYYYY-MM-DD形式に変換
                try:
                    # 形式: YYYY/M/D
                    dt = datetime.strptime(date_str, "%Y/%m/%d")
                    formatted_date = dt.strftime("%Y-%m-%d")
                    holidays.append((formatted_date, name))
                except ValueError:
                    continue
        
        return holidays


def fetch_holidays_sync() -> List[Tuple[str, str]]:
    """同期版の祝日取得"""
    import httpx
    
    response = httpx.get(HOLIDAY_CSV_URL, timeout=30.0)
    response.raise_for_status()
    
    content = response.content.decode("shift_jis")
    
    holidays = []
    reader = csv.reader(io.StringIO(content))
    
    for i, row in enumerate(reader):
        if i == 0:
            continue
        
        if len(row) >= 2:
            date_str = row[0].strip()
            name = row[1].strip()
            
            try:
                dt = datetime.strptime(date_str, "%Y/%m/%d")
                formatted_date = dt.strftime("%Y-%m-%d")
                holidays.append((formatted_date, name))
            except ValueError:
                continue
    
    return holidays


def save_holidays_to_db(conn, holidays: List[Tuple[str, str]]) -> int:
    """
    祝日データをDBに保存
    
    Args:
        conn: SQLite接続
        holidays: [(日付, 祝日名), ...]
    
    Returns:
        保存件数
    """
    cursor = conn.cursor()
    
    # 既存データを削除して再挿入
    cursor.execute("DELETE FROM holidays")
    
    cursor.executemany(
        "INSERT INTO holidays (holiday_date, holiday_name) VALUES (?, ?)",
        holidays
    )
    
    conn.commit()
    return len(holidays)


def check_holidays_coverage(conn, required_years: List[int]) -> Tuple[bool, List[int]]:
    """
    必要な年の祝日データが揃っているか確認
    
    Args:
        conn: SQLite接続
        required_years: 必要な年のリスト [2025, 2026, 2027]
    
    Returns:
        (揃っているか, 不足している年のリスト)
    """
    cursor = conn.execute(
        "SELECT DISTINCT substr(holiday_date, 1, 4) as year FROM holidays"
    )
    existing_years = {int(row["year"]) for row in cursor}
    
    missing = [y for y in required_years if y not in existing_years]
    
    return (len(missing) == 0, missing)


if __name__ == "__main__":
    # テスト実行
    holidays = fetch_holidays_sync()
    print(f"取得祝日数: {len(holidays)}")
    
    # 最初の10件を表示
    for date, name in holidays[:10]:
        print(f"  {date}: {name}")
