"""
科目チェック
累積のテンプレ採用=1の直近値を「正」として比較
"""
from typing import Optional


def check_account(
    applied_account: str,
    expected_account: Optional[str]
) -> tuple[str, str]:
    """
    科目チェック
    
    Args:
        applied_account: 申請の科目コード
        expected_account: 累積から取得した「正」の科目コード
    
    Returns:
        (判定結果, 理由)
        - OK: 一致
        - NG: 不一致
        - -: 正が存在しない（累積データなし）
    """
    # 正が存在しない場合
    if expected_account is None:
        return ("-", "累積データなし（初回取引）")
    
    # 一致判定
    if applied_account == expected_account:
        return ("OK", "")
    
    # 不一致
    return (
        "NG",
        f"申請: {applied_account or '(空欄)'}, 正: {expected_account or '(空欄)'}"
    )


from infra.rule_repository import RuleRepository

def get_expected_account_from_rule(
    conn,
    vendor_code: str,
    dept_code: str = ""
) -> Optional[str]:
    """
    正マスターから科目コードを取得 (Resolve)
    """
    repo = RuleRepository()
    return repo.resolve_account(conn, vendor_code, dept_code)


if __name__ == "__main__":
    # テスト
    result, reason = check_account("82870", "82870")
    print(f"一致: {result} {reason}")
    
    result, reason = check_account("82870", "82750")
    print(f"不一致: {result} {reason}")
    
    result, reason = check_account("82870", None)
    print(f"累積なし: {result} {reason}")
