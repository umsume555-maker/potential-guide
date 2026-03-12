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


def count_judgments(results: List[str]) -> dict:
    """
    判定結果を集計
    
    Args:
        results: 各行の総合判定結果リスト
    
    Returns:
        {"OK": n, "NG": n, "-": n}
    """
    counts = {"OK": 0, "NG": 0, "-": 0}
    for r in results:
        if r in counts:
            counts[r] += 1
    return counts


if __name__ == "__main__":
    # テスト
    print(overall_judgment(["OK", "OK", "OK"]))  # OK
    print(overall_judgment(["OK", "NG", "OK"]))  # NG
    print(overall_judgment(["OK", "-", "OK"]))   # -
    print(overall_judgment(["NG", "-", "OK"]))   # NG
