# extractor.py
"""
情報抽出モジュール
- 金額抽出（当月請求金額）
- インボイス番号抽出
- 軽減税率判定
- 稟議書判定
- 請求書判定
"""

from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
import re
import yaml


@dataclass
class AmountCandidate:
    """金額候補"""
    value: int  # 金額
    context: str  # 近傍テキスト
    score: float  # スコア (0.0-1.0)
    is_excluded: bool  # 除外対象か


@dataclass
class ExtractionResult:
    """抽出結果"""
    amount: Optional[int]  # 当月請求金額
    invoice_number: Optional[str]  # インボイス番号
    date: Optional[str]    # 発行日 (YYYY-MM-DD)
    has_reduced_tax: bool  # 軽減税率有無
    has_ringisyo: bool  # 稟議書有無
    is_invoice: bool  # 請求書判定
    confidence: float  # 総合信頼度



def load_config(config_path: Optional[Path] = None) -> dict:
    """設定ファイルを読み込む"""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_text(text: str) -> str:
    """
    テキスト正規化
    - 全角数字→半角
    - カンマ除去
    """
    # 全角→半角変換テーブル
    zen_to_han = str.maketrans(
        "０１２３４５６７８９，、．",
        "0123456789,,."
    )
    return text.translate(zen_to_han)


def extract_amounts(text: str, config: Optional[dict] = None) -> List[AmountCandidate]:
    """
    テキストから金額候補を抽出
    
    Args:
        text: OCRテキスト
        config: 設定辞書
    
    Returns:
        金額候補のリスト（スコア降順）
    """
    if config is None:
        config = load_config()
    
    # 正規化
    normalized = normalize_text(text)
    
    # 設定読み込み
    amount_config = config.get("amount_extraction", {})
    exclude_labels = amount_config.get("exclude_labels", [])
    priority_labels = amount_config.get("priority_labels", [])
    window_chars = amount_config.get("window_chars", 30)
    
    # 金額パターン（円付き、カンマ区切り対応）
    amount_patterns = [
        r"¥\s*([\d,]+)",  # ¥1,234
        r"([\d,]+)\s*円",  # 1,234円
        r"([\d,]+)\s*(?:税込|税抜|合計)",  # 1,234 税込
        r"金額[:\s]*([\d,]+)",  # 金額: 1,234
        r"請求[:\s]*([\d,]+)",  # 請求: 1,234
        r"合計[:\s]*([\d,]+)",  # 合計: 1,234
    ]
    
    candidates = []
    
    for pattern in amount_patterns:
        for match in re.finditer(pattern, normalized):
            amount_str = match.group(1).replace(",", "")
            try:
                amount = int(amount_str)
            except ValueError:
                continue
            
            # 妥当性チェック（100円未満、100億円以上は除外）
            if amount < 100 or amount > 10_000_000_000:
                continue
            
            # 近傍テキスト取得
            start = max(0, match.start() - window_chars)
            end = min(len(normalized), match.end() + window_chars)
            context = normalized[start:end]
            
            # 除外判定
            is_excluded = any(label in context for label in exclude_labels)
            
            # スコア計算
            score = 0.5  # ベーススコア
            
            # 優先ラベルがあればスコアアップ
            for label in priority_labels:
                if label in context:
                    score += 0.15
                    break
            
            # 除外ラベルがあればスコアダウン
            if is_excluded:
                score -= 0.4
            
            # 桁数による調整（大きすぎる・小さすぎる金額は減点）
            if 1000 <= amount <= 10_000_000:
                score += 0.1
            
            candidates.append(AmountCandidate(
                value=amount,
                context=context,
                score=max(0.0, min(1.0, score)),
                is_excluded=is_excluded
            ))
    
    # スコア降順でソート
    candidates.sort(key=lambda x: x.score, reverse=True)
    
    return candidates


def extract_best_amount(text: str, config: Optional[dict] = None) -> Tuple[Optional[int], float]:
    """
    最も可能性の高い金額を抽出
    
    Returns:
        (金額, 信頼度スコア)
    """
    candidates = extract_amounts(text, config)
    
    # 除外されていない最高スコアの候補を返す
    for cand in candidates:
        if not cand.is_excluded:
            return cand.value, cand.score
    
    return None, 0.0


def extract_invoice_number(text: str, config: Optional[dict] = None) -> Optional[str]:
    """
    インボイス番号を抽出
    
    パターン: T + 13桁数字
    
    Returns:
        インボイス番号（見つからない場合はNone）
    """
    if config is None:
        config = load_config()
    
    pattern = config.get("invoice_pattern", r"T\d{13}")
    
    # 全角→半角変換
    normalized = normalize_text(text)
    
    match = re.search(pattern, normalized)
    if match:
        return match.group(0)
    
    return None


def check_reduced_tax(text: str) -> bool:
    """
    軽減税率の有無を判定
    
    条件: 「8%」または「軽減税率」が存在し、近傍に金額がある
    """
    normalized = normalize_text(text)
    
    # 軽減税率キーワード
    patterns = [
        r"軽減税率",
        r"8\s*%",
        r"8\s*％",
        r"軽減\s*8",
    ]
    
    for pattern in patterns:
        if re.search(pattern, normalized):
            # 近傍に金額があるか確認
            if re.search(r"[\d,]+\s*円", normalized):
                return True
    
    return False


def check_ringisyo(text: str, config: Optional[dict] = None) -> bool:
    """
    稟議書の有無を判定
    
    キーワードリストに部分一致すれば稟議書あり
    """
    if config is None:
        config = load_config()
    
    keywords = config.get("ringisyo_keywords", [])
    
    for keyword in keywords:
        if keyword in text:
            return True
    
    return False


def check_is_invoice(text: str, config: Optional[dict] = None) -> bool:
    """
    請求書かどうかを判定
    
    条件:
    - 請求書キーワードが含まれる
    - または インボイス番号が見つかる
    """
    if config is None:
        config = load_config()
    
    keywords = config.get("invoice_keywords", ["請求書", "御請求", "請求金額", "ご請求"])
    
    for keyword in keywords:
        if keyword in text:
            return True
    
    # インボイス番号があれば請求書と判定
    if extract_invoice_number(text, config):
        return True
    
    return False


def extract_date(text: str, config: Optional[dict] = None) -> Optional[str]:
    """
    日付を抽出 (YYYY-MM-DD形式)
    
    優先順位:
    1. 「請求日」「発行日」の近くの日付
    2. その他、妥当な日付
    """
    normalized = normalize_text(text)
    
    # 日付パターン (YYYY/MM/DD, YYYY-MM-DD, YYYY年MM月DD日, YYYY.MM.DD)
    pattern = r"(\d{4})[\/\-\.年](\d{1,2})[\/\-\.月](\d{1,2})日?"
    
    matches = []
    for match in re.finditer(pattern, normalized):
        try:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if 2000 <= y <= 2030 and 1 <= m <= 12 and 1 <= d <= 31:
                matches.append({
                    "date": f"{y:04d}-{m:02d}-{d:02d}",
                    "start": match.start(),
                    "end": match.end()
                })
        except ValueError:
            continue
            
    if not matches:
        return None
        
    # キーワード近傍優先
    keywords = ["請求日", "発行日"]
    best_match = None
    min_dist = float('inf')
    
    for match in matches:
        start_scope = max(0, match["start"] - 50)
        context = normalized[start_scope:match["start"]]
        
        for kw in keywords:
            if kw in context:
                dist = match["start"] - (start_scope + context.rfind(kw))
                if dist < min_dist:
                    min_dist = dist
                    best_match = match["date"]
    
    if best_match:
        return best_match
        
    return matches[0]["date"]


def extract_all(text: str, config: Optional[dict] = None) -> ExtractionResult:
    """
    全情報を抽出
    """
    if config is None:
        config = load_config()
    
    amount, amount_conf = extract_best_amount(text, config)
    invoice_number = extract_invoice_number(text, config)
    date = extract_date(text, config)
    has_reduced_tax = check_reduced_tax(text)
    has_ringisyo = check_ringisyo(text, config)
    is_invoice = check_is_invoice(text, config)
    
    confidence = 0.0
    if amount:
        confidence += 0.35 * amount_conf
    if invoice_number:
        confidence += 0.25
    if date:
        confidence += 0.10
    if has_reduced_tax:
        confidence += 0.05
    if is_invoice:
        confidence += 0.15
    
    return ExtractionResult(
        amount=amount,
        invoice_number=invoice_number,
        date=date,
        has_reduced_tax=has_reduced_tax,
        has_ringisyo=has_ringisyo,
        is_invoice=is_invoice,
        confidence=min(1.0, confidence)
    )



if __name__ == "__main__":
    # テスト
    test_text = """
    御請求書
    
    株式会社テスト 御中
    
    下記の通りご請求申し上げます。
    
    ご請求金額: ¥1,234,567（税込）
    
    内訳:
    商品A    ¥500,000
    商品B    ¥600,000
    消費税   ¥134,567
    
    軽減税率(8%) ¥50,000
    
    お支払期限: 2026年2月28日
    
    登録番号: T1234567890123
    """
    
    result = extract_all(test_text)
    print("=== 抽出結果 ===")
    print(f"金額: {result.amount:,}円" if result.amount else "金額: 未検出")
    print(f"インボイス番号: {result.invoice_number or '未検出'}")
    print(f"軽減税率: {'有' if result.has_reduced_tax else '無'}")
    print(f"稟議書: {'有' if result.has_ringisyo else '無'}")
    print(f"請求書判定: {'請求書' if result.is_invoice else '非請求書'}")
    print(f"信頼度: {result.confidence:.2f}")
