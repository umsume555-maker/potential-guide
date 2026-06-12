"""
総合判定
各判定結果から総合判定を算出
"""
from typing import List


def overall_judgment(results: List[str]) -> str:
    """
    総合判定
    
    Args:
        results: 各判定結果のリスト ["OK", "NG", "-", ...]
    
    Returns:
        総合判定結果
        - NG: 1つでもNGがあれば
        - -: NGがなく、-が1つでもあれば
        - OK: 全部OK
    """
    if "NG" in results:
        return "NG"
    if "-" in results:
        return "-"
    return "OK"
