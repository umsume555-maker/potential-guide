# scoring.py
"""
スコアリングモジュール
- OCR結果の総合スコア算出
- AI OCR切り替え判定
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import yaml


@dataclass
class ScoringResult:
    """スコアリング結果"""
    total_score: float  # 総合スコア (0.0-1.0)
    amount_score: float  # 金額スコア
    invoice_score: float  # インボイス番号スコア
    reduced_tax_score: float  # 軽減税率スコア
    plausibility_score: float  # 妥当性スコア
    text_quality_score: float  # テキスト品質スコア
    needs_ai_ocr: bool  # AI OCRが必要か


def load_config(config_path: Optional[Path] = None) -> dict:
    """設定ファイルを読み込む"""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def calculate_score(
    amount: Optional[int],
    amount_confidence: float,
    invoice_number: Optional[str],
    has_reduced_tax: bool,
    text_quality: float,
    config: Optional[dict] = None
) -> ScoringResult:
    """
    総合スコアを算出
    
    Args:
        amount: 抽出された金額
        amount_confidence: 金額抽出の信頼度
        invoice_number: インボイス番号
        has_reduced_tax: 軽減税率有無
        text_quality: OCRテキスト品質スコア
        config: 設定辞書
    
    Returns:
        ScoringResult
    """
    if config is None:
        config = load_config()
    
    # 重み設定
    weights = config.get("scoring", {})
    w_amount = weights.get("amount", 0.35)
    w_invoice = weights.get("invoice", 0.25)
    w_reduced = weights.get("reduced_tax", 0.10)
    w_plausibility = weights.get("plausibility", 0.15)
    w_quality = weights.get("text_quality", 0.15)
    
    # 閾値
    threshold = config.get("ocr", {}).get("confidence_threshold", 0.72)
    
    # 各スコア計算
    # 1. 金額スコア
    if amount is not None:
        amount_score = amount_confidence
    else:
        amount_score = 0.0
    
    # 2. インボイス番号スコア
    invoice_score = 1.0 if invoice_number else 0.0
    
    # 3. 軽減税率スコア（判定できたら1.0）
    reduced_tax_score = 1.0 if has_reduced_tax else 0.5  # 無しでも問題ないので0.5
    
    # 4. 妥当性スコア
    plausibility_score = 0.5  # ベース
    if amount is not None:
        # 金額の妥当性（極端な値でなければ加点）
        if 1000 <= amount <= 100_000_000:
            plausibility_score = 0.8
        if 10000 <= amount <= 10_000_000:
            plausibility_score = 1.0
    
    # 5. テキスト品質スコア
    text_quality_score = text_quality
    
    # 総合スコア計算
    total_score = (
        w_amount * amount_score +
        w_invoice * invoice_score +
        w_reduced * reduced_tax_score +
        w_plausibility * plausibility_score +
        w_quality * text_quality_score
    )
    
    # AI OCR必要判定
    needs_ai_ocr = total_score < threshold
    
    return ScoringResult(
        total_score=min(1.0, total_score),
        amount_score=amount_score,
        invoice_score=invoice_score,
        reduced_tax_score=reduced_tax_score,
        plausibility_score=plausibility_score,
        text_quality_score=text_quality_score,
        needs_ai_ocr=needs_ai_ocr
    )


if __name__ == "__main__":
    # テスト
    result = calculate_score(
        amount=1234567,
        amount_confidence=0.85,
        invoice_number="T1234567890123",
        has_reduced_tax=True,
        text_quality=0.75
    )
    
    print("=== スコアリング結果 ===")
    print(f"総合スコア: {result.total_score:.2f}")
    print(f"  金額: {result.amount_score:.2f}")
    print(f"  インボイス: {result.invoice_score:.2f}")
    print(f"  軽減税率: {result.reduced_tax_score:.2f}")
    print(f"  妥当性: {result.plausibility_score:.2f}")
    print(f"  テキスト品質: {result.text_quality_score:.2f}")
    print(f"AI OCR必要: {'はい' if result.needs_ai_ocr else 'いいえ'}")
