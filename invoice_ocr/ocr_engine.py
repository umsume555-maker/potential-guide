# ocr_engine.py
"""
OCRエンジンモジュール
- pyocr (Tesseract) ラッパー
- 依存関係チェック
- 読取精度スコア算出
"""

from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class OCRResult:
    """OCR結果"""
    text: str  # 抽出テキスト
    confidence: float  # 信頼度 (0.0-1.0)
    method: str  # 使用した方式 ("pyocr", "ai_ocr", "text_layer")
    page_count: int  # ページ数


def check_dependencies() -> dict[str, bool]:
    """
    依存関係の確認
    
    Returns:
        {"pyocr": True/False, "tesseract": True/False}
    """
    result = {
        "pyocr": False,
        "tesseract": False,
        "tesseract_jpn": False
    }
    
    try:
        import pyocr
        result["pyocr"] = True
        
        tools = pyocr.get_available_tools()
        if tools:
            result["tesseract"] = True
            
            # 日本語対応確認
            langs = tools[0].get_available_languages()
            if "jpn" in langs:
                result["tesseract_jpn"] = True
    except ImportError:
        pass
    
    return result


def get_tesseract_tool():
    """Tesseractツールを取得"""
    try:
        import pyocr
        tools = pyocr.get_available_tools()
        if tools:
            return tools[0]
    except ImportError:
        pass
    return None


def ocr_image(image, lang: str = "jpn+eng") -> Tuple[str, float]:
    """
    画像からテキストを抽出
    
    Args:
        image: PIL Image
        lang: 言語設定（デフォルト: jpn+eng）
    
    Returns:
        (抽出テキスト, 信頼度スコア)
    """
    try:
        import pyocr
        import pyocr.builders
    except ImportError:
        print("[ERROR] pyocr がインストールされていません: pip install pyocr")
        return "", 0.0
    
    tool = get_tesseract_tool()
    if tool is None:
        print("[ERROR] Tesseract が見つかりません")
        print("       Tesseract をインストールして PATH を通してください")
        return "", 0.0
    
    try:
        # OCR実行
        text = tool.image_to_string(
            image,
            lang=lang,
            builder=pyocr.builders.TextBuilder()
        )
        
        # 信頼度スコア算出
        confidence = calculate_text_quality(text)
        
        return text, confidence
    except Exception as e:
        print(f"[ERROR] OCR実行エラー: {e}")
        return "", 0.0


def calculate_text_quality(text: str) -> float:
    """
    OCRテキストの品質スコアを算出 (0.0-1.0)
    
    評価項目:
    - 文字数
    - 日本語比率
    - 不可視文字比率
    - 金額パターン検出
    """
    if not text:
        return 0.0
    
    score = 0.0
    text_len = len(text)
    
    # 1. 文字数評価 (最大0.2)
    if text_len > 500:
        score += 0.2
    elif text_len > 100:
        score += 0.15
    elif text_len > 50:
        score += 0.1
    elif text_len > 20:
        score += 0.05
    
    # 2. 日本語比率 (最大0.3)
    import unicodedata
    jp_chars = sum(1 for c in text if unicodedata.name(c, "").startswith(("CJK", "HIRAGANA", "KATAKANA")))
    jp_ratio = jp_chars / text_len if text_len > 0 else 0
    score += min(0.3, jp_ratio * 0.5)
    
    # 3. 不可視文字・特殊文字の少なさ (最大0.2)
    visible_chars = sum(1 for c in text if c.isprintable() and not c.isspace())
    visible_ratio = visible_chars / text_len if text_len > 0 else 0
    score += visible_ratio * 0.2
    
    # 4. 数字の存在（金額がありそう） (最大0.15)
    digit_chars = sum(1 for c in text if c.isdigit())
    if digit_chars > 10:
        score += 0.15
    elif digit_chars > 5:
        score += 0.1
    elif digit_chars > 0:
        score += 0.05
    
    # 5. キーワード検出 (最大0.15)
    keywords = ["請求", "合計", "金額", "円", "税", "インボイス"]
    keyword_count = sum(1 for kw in keywords if kw in text)
    score += min(0.15, keyword_count * 0.03)
    
    return min(1.0, score)


def ocr_pdf(pdf_path: Path, config: Optional[dict] = None, db_path: Optional[str] = None, force_model: Optional[str] = None) -> OCRResult:
    """
    PDFをOCRして結果を返す
    force_model: 設定されている場合、Tesseractの結果に関わらずこのモデルでGeminiを実行
    """
    from .pdf_tools import extract_text_from_pdf, pdf_to_images, is_text_pdf
    from .preprocess import preprocess_image
    
    lang = config.get("ocr", {}).get("tesseract_lang", "jpn+eng") if config else "jpn+eng"
    confidence_threshold = config.get("ocr", {}).get("confidence_threshold", 0.80) if config else 0.80
    
    # 強制モードならモデル決定
    target_model = None
    if force_model == "1":
        target_model = config.get("ai_ocr", {}).get("model_a", "gemini-2.0-flash") if config else "gemini-2.0-flash"
        print(f"[INFO] Force Gemini Model A: {target_model}")
    elif force_model == "2":
        target_model = config.get("ai_ocr", {}).get("model_b", "gemini-2.0-flash") if config else "gemini-2.0-flash"
        print(f"[INFO] Force Gemini Model B: {target_model}")

    # 1. テキスト層抽出 (強制モードならスキップ...したいが、テキスト層の方が正確な場合もある。
    # しかし「強制的にモデルを使う」要望なら、画像解析(AI)を優先すべきか？
    # AIもテキスト層を読むわけではない（画像として読む）。
    # ここでは、テキスト層があってもAI強制ならAIを実行するロジックにする。
    
    extracted_text_result = None
    
    if not target_model and is_text_pdf(pdf_path, min_chars=100):
        text = extract_text_from_pdf(pdf_path)
        if text:
            confidence = calculate_text_quality(text)
            if confidence >= confidence_threshold:
                extracted_text_result = OCRResult(
                    text=text,
                    confidence=confidence,
                    method="text_layer",
                    page_count=1
                )
                return extracted_text_result

    # 2. 画像変換してOCR (Tesseract)
    # 強制モードでも、Tesseractの結果を一応取っておくか、あるいはスキップしてGemini直行か。
    # スキップした方が高速だが、前処理（pdf_to_images）は共通で必要。
    
    images = pdf_to_images(pdf_path)
    if not images:
        return OCRResult(text="", confidence=0.0, method="pyocr", page_count=0)
    
    all_texts = []
    total_confidence = 0.0
    
    # Tesseract実行 (強制モードでない場合、または比較用)
    # ここでは強制モードならTesseractをスキップして高速化する
    if not target_model:
        for i, img in enumerate(images):
            processed = preprocess_image(img, do_rotate=True, do_deskew=True)
            text, conf = ocr_image(processed, lang=lang)
            all_texts.append(text)
            total_confidence += conf
        
        combined_text = "\n".join(all_texts)
        avg_confidence = total_confidence / len(images) if images else 0.0
    else:
        # ダミー値
        combined_text = ""
        avg_confidence = 0.0

    # 3. Gemini API 実行判定 (信頼度が低い OR 強制モード)
    should_use_gemini = False
    if target_model:
        should_use_gemini = True
    elif avg_confidence < confidence_threshold:
        should_use_gemini = True
        
    if should_use_gemini and db_path:
        if not target_model:
            print(f"[INFO] Tesseract confidence ({avg_confidence:.2f}) < threshold. Trying Gemini API...")
            # デフォルトモデル (model_a = gemini-2.0-flash をデフォルトとする)
            target_model = config.get("ai_ocr", {}).get("model_a", "gemini-2.0-flash") if config else "gemini-2.0-flash"
            
        from .ai_ocr import get_gemini_api_key, ocr_pdf_with_gemini
        api_key = get_gemini_api_key(db_path)
        
        if api_key:
            try:
                ai_text, ai_conf = ocr_pdf_with_gemini(pdf_path, api_key, target_model)
                print(f"[INFO] Gemini OCR Result: confidence={ai_conf:.2f} model={target_model}")
                
                # 強制モードなら無条件採用、そうでなければ信頼度比較
                if force_model or ai_conf > avg_confidence:
                    return OCRResult(
                        text=ai_text,
                        confidence=ai_conf,
                        method=f"gemini ({target_model})",
                        page_count=len(images)
                    )
            except Exception as e:
                print(f"[ERROR] Gemini API failed: {e}")
        else:
            print("[WARN] Gemini API key not found in DB.")
    
    return OCRResult(
        text=combined_text,
        confidence=avg_confidence,
        method="pyocr",
        page_count=len(images)
    )


def ocr_image_file(image_path: Path, config: Optional[dict] = None, db_path: Optional[str] = None, force_model: Optional[str] = None) -> OCRResult:
    """
    画像ファイルをOCR
    force_model: 設定されている場合、強制的にモデル適用
    """
    from PIL import Image
    from .preprocess import preprocess_image
    
    lang = config.get("ocr", {}).get("tesseract_lang", "jpn+eng") if config else "jpn+eng"
    confidence_threshold = config.get("ocr", {}).get("confidence_threshold", 0.80) if config else 0.80
    
    # 強制モード判定
    target_model = None
    if force_model == "1":
        target_model = config.get("ai_ocr", {}).get("model_a", "gemini-2.0-flash") if config else "gemini-2.0-flash"
        print(f"[INFO] Force Gemini Model A (Image): {target_model}")
    elif force_model == "2":
        target_model = config.get("ai_ocr", {}).get("model_b", "gemini-2.0-flash") if config else "gemini-2.0-flash"
        print(f"[INFO] Force Gemini Model B (Image): {target_model}")
    
    try:
        img = Image.open(image_path)
        
        # OCR (Tesseract): 強制でない場合のみ実行
        if not target_model:
            processed = preprocess_image(img, do_rotate=True, do_deskew=True)
            text, conf = ocr_image(processed, lang=lang)
        else:
            text, conf = "", 0.0
        
        # 信頼度が低ければ Gemini API にフォールバック OR 強制モード
        should_use_gemini = False
        if target_model:
            should_use_gemini = True
        elif conf < confidence_threshold:
            should_use_gemini = True

        if should_use_gemini and db_path:
            if not target_model:
                print(f"[INFO] Tesseract confidence ({conf:.2f}) < threshold. Trying Gemini API for Image...")
                target_model = config.get("ai_ocr", {}).get("model_a", "gemini-2.0-flash") if config else "gemini-2.0-flash"

            from .ai_ocr import get_gemini_api_key, ocr_image_with_gemini
            api_key = get_gemini_api_key(db_path)
            if api_key:
                try:
                    ai_text, ai_conf = ocr_image_with_gemini(image_path, api_key, target_model)
                    print(f"[INFO] Gemini OCR Result (Image): confidence={ai_conf:.2f} model={target_model}")
                    if force_model or ai_conf > conf:
                         return OCRResult(
                            text=ai_text,
                            confidence=ai_conf,
                            method=f"gemini ({target_model})",
                            page_count=1
                        )
                except Exception as e:
                    print(f"[ERROR] Gemini API failed (Image): {e}")
            else:
                 print("[WARN] Gemini API key not found in DB.")
        
        return OCRResult(
            text=text,
            confidence=conf,
            method="pyocr",
            page_count=1
        )
    except Exception as e:
        print(f"[ERROR] 画像読み込みエラー: {image_path} - {e}")
        return OCRResult(text="", confidence=0.0, method="pyocr", page_count=0)


if __name__ == "__main__":
    # 依存関係チェック
    deps = check_dependencies()
    print("=== 依存関係チェック ===")
    for name, installed in deps.items():
        status = "✓" if installed else "✗"
        print(f"  {status} {name}")
    
    if not deps["pyocr"]:
        print("\n[INFO] pyocr をインストール: pip install pyocr")
    if not deps["tesseract"]:
        print("[INFO] Tesseract をインストールして PATH を通してください")
        print("       https://github.com/UB-Mannheim/tesseract/wiki")
    if deps["tesseract"] and not deps["tesseract_jpn"]:
        print("[INFO] Tesseract の日本語データをインストールしてください")
