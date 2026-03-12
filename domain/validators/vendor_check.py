"""
支払先相違チェック
取引先コード == 支払先コード が原則
例外は許容支払先マスターで管理
"""
from typing import Optional


def check_vendor_payee(
    vendor_code: str,
    payee_code: str,
    allowed_payees: Optional[set[tuple[str, str]]] = None
) -> tuple[str, str]:
    """
    支払先相違チェック
    
    Args:
        vendor_code: 取引先コード
        payee_code: 支払先コード
        allowed_payees: 許容支払先のセット {(vendor_code, payee_code), ...}
    
    Returns:
        (判定結果, 理由)
        - OK: 一致または許容
        - NG: 不一致かつ未許容
    """
    if not vendor_code or not payee_code:
        # コードが空の場合はチェック対象外
        return ("OK", "")
    
    # 完全一致
    if vendor_code == payee_code:
        return ("OK", "")
    
    # 許容支払先マスターに登録されている場合
    if allowed_payees and (vendor_code, payee_code) in allowed_payees:
        return ("OK", f"許容支払先: {payee_code}")
    
    # 不一致かつ未許容 → NG
    return (
        "NG",
        f"取引先コード({vendor_code}) ≠ 支払先コード({payee_code})"
    )


def load_allowed_payees_from_db(conn) -> set[tuple[str, str]]:
    """
    DBから許容支払先マスターを読み込む
    
    Args:
        conn: SQLite接続
    
    Returns:
        許容支払先のセット
    """
    cursor = conn.execute(
        "SELECT vendor_code, allowed_payee_code FROM masters_allowed_payee"
    )
    return {(row["vendor_code"], row["allowed_payee_code"]) for row in cursor}


if __name__ == "__main__":
    # テスト
    allowed = {("10001", "20001"), ("10002", "20002")}
    
    # 一致 → OK
    result, reason = check_vendor_payee("10001", "10001", allowed)
    print(f"一致: {result} {reason}")
    
    # 許容 → OK
    result, reason = check_vendor_payee("10001", "20001", allowed)
    print(f"許容: {result} {reason}")
    
    # 不一致・未許容 → NG
    result, reason = check_vendor_payee("10001", "30001", allowed)
    print(f"不一致: {result} {reason}")
