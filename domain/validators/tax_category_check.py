"""
税区分チェック
累積のテンプレ採用=1の直近値を「正」として比較
"""
from typing import Optional


def check_tax_category(
    applied_tax: str,
    expected_tax: Optional[str]
) -> tuple[str, str]:
    """
    税区分チェック
    
    Args:
        applied_tax: 申請の税区分
        expected_tax: 累積から取得した「正」の税区分
    
    Returns:
        (判定結果, 理由)
        - OK: 一致
        - NG: 不一致
        - -: 正が存在しない（累積データなし）
    """
    # 正が存在しない場合
    if expected_tax is None:
        return ("-", "累積データなし（初回取引）")
    
    # 一致判定（空文字同士も一致とみなす）
    if applied_tax == expected_tax:
        return ("OK", "")
    
    # 不一致
    return (
        "NG",
        f"申請: {applied_tax or '(空欄)'}, 正: {expected_tax or '(空欄)'}"
    )


from infra.rule_repository import RuleRepository

def get_expected_tax_from_rule(
    conn,
    vendor_code: str,
    dept_code: str = ""
) -> Optional[str]:
    """
    正マスターから税区分を取得 (Resolve)
    """
    repo = RuleRepository()
    return repo.resolve_tax(conn, vendor_code, dept_code)


if __name__ == "__main__":
    # テスト
    # 正がある場合
    result, reason = check_tax_category("45", "45")
    print(f"一致: {result} {reason}")
    
    result, reason = check_tax_category("45", "99")
    print(f"不一致: {result} {reason}")
    
    # 正がない場合
    result, reason = check_tax_category("45", None)
    print(f"累積なし: {result} {reason}")
