# ai_ocr.py
"""
AI OCR モジュール (Gemini API)
"""
import base64
from pathlib import Path
from typing import Optional
import sqlite3


def get_gemini_api_key(db_path: str) -> Optional[str]:
    """DBから保存されたGemini APIキーを取得"""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'gemini_api_key'"
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception:
        return None


def ocr_with_gemini(image_bytes: bytes, api_key: str, model: str = "gemini-2.0-flash") -> tuple[str, float]:
    """
    Gemini APIで画像をOCR
    
    Args:
        image_bytes: 画像のバイトデータ
        api_key: Gemini APIキー
        model: モデル名
    
    Returns:
        (抽出テキスト, 信頼度スコア)
    """
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ERROR] google-generativeai がインストールされていません")
        print("       pip install google-generativeai")
        return "", 0.0
    
    try:
        genai.configure(api_key=api_key)
        
        # Base64エンコード
        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
        
        # モデル設定
        model_instance = genai.GenerativeModel(model)
        
        # プロンプト
        prompt = """この画像は日本の請求書です。以下の情報を抽出してください：

**重要**: 画像内で蛍光ペンやマーカーでハイライトされている箇所がある場合、その部分の情報（特に金額）を**最優先**で採用してください。
ユーザーが手動で修正指示を出している可能性が高いです。

1. すべてのテキストを読み取って出力してください
2. 特に以下の情報に注目してください：
   - 請求金額（税込合計） ※ハイライトがあればそれを優先
   - インボイス番号（T + 13桁の数字）
   - 請求日/発行日
   - 会社名/取引先名

テキストをそのまま出力してください。"""

        # API呼び出し
        response = model_instance.generate_content([
            prompt,
            {"mime_type": "image/png", "data": image_data}
        ])
        
        text = response.text if response.text else ""
        
        # 信頼度は高めに設定（AIは精度が高い前提）
        confidence = 0.85 if text else 0.0
        
        return text, confidence
        
    except Exception as e:
        print(f"[ERROR] Gemini API エラー: {e}")
        return "", 0.0


def ocr_pdf_with_gemini(pdf_path: Path, api_key: str, model: str = "gemini-2.0-flash") -> tuple[str, float]:
    """
    PDFをGemini APIでOCR
    
    PDFを画像に変換してからOCR（全ページを1回のリクエストで処理）
    """
    from .pdf_tools import pdf_to_images
    from io import BytesIO
    import base64
    
    images = pdf_to_images(pdf_path)
    if not images:
        return "", 0.0
    
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ERROR] google-generativeai がインストールされていません")
        return "", 0.0
    
    try:
        genai.configure(api_key=api_key)
        
        # モデル設定
        model_instance = genai.GenerativeModel(model)
        
        # プロンプト
        prompt = """この画像は日本の請求書です（複数ページの場合があります）。以下の情報を抽出してください：

**重要**: 画像内で蛍光ペンやマーカーでハイライトされている箇所がある場合、その部分の情報（特に金額）を**最優先**で採用してください。
ユーザーが手動で修正指示を出している可能性が高いです。

1. すべてのテキストを読み取って出力してください
2. 特に以下の情報に注目してください：
   - 請求金額（税込合計） ※ハイライトがあればそれを優先
   - インボイス番号（T + 13桁の数字）
   - 請求日/発行日
   - 会社名/取引先名

テキストをそのまま出力してください。"""

        # 全ページの画像をBase64エンコード
        content_parts = [prompt]
        for img in images:
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
            content_parts.append({"mime_type": "image/png", "data": image_data})
        
        # API呼び出し（全ページを1回で送信）
        response = model_instance.generate_content(content_parts)
        
        text = response.text if response.text else ""
        
        # 信頼度は高めに設定（AIは精度が高い前提）
        confidence = 0.85 if text else 0.0
        
        return text, confidence
        
    except Exception as e:
        print(f"[ERROR] Gemini API エラー: {e}")
        return "", 0.0


def ocr_image_with_gemini(image_path: Path, api_key: str, model: str = "gemini-2.0-flash") -> tuple[str, float]:
    """
    画像ファイルをGemini APIでOCR
    """
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        return ocr_with_gemini(image_bytes, api_key, model)
    except Exception as e:
        return "", 0.0


def extract_billing_amount_with_gemini(pdf_path: Path, api_key: str, model: str = "gemini-2.0-flash") -> tuple[dict, float]:
    """
    請求書PDFから「当月請求額」を抽出する
    
    Returns:
        (result_dict, confidence)
        result_dict: {"amount": int, "date": str, "vendor_name": str}
    """
    from .pdf_tools import pdf_to_images
    from io import BytesIO
    import base64
    import json
    import re
    
    images = pdf_to_images(pdf_path)
    if not images:
        return {}, 0.0
    
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ERROR] google-generativeai がインストールされていません")
        return {}, 0.0
    
    try:
        genai.configure(api_key=api_key)
        model_instance = genai.GenerativeModel(model) # Use flash for speed if possible
        
        prompt = """
あなたは日本の経理担当者です。
与えられた請求書画像から、以下の情報を抽出し、JSON形式で返してください。

**最優先事項**:
「今回請求額」または「当月請求額」を正確に特定してください。
※「繰越金額」や「請求書合計（繰越含む）」と混同しないように注意してください。
※画像内で蛍光ペンやマーカーでハイライトされている金額がある場合、それを**最優先**で採用してください。

出力JSONフォーマット:
{
  "amount": <数値(int) - 今回請求額>,
  "date": "<文字列 - 請求日または発行日 (YYYY-MM-DD)>",
  "vendor_name": "<文字列 - 請求元会社名>"
}

注意:
- 金額はカンマなしの整数で出力してください。
- 該当する情報がない場合は null を入れてください。
- 余計なMarkdown記法（```json など）は含めず、純粋なJSON文字列のみを返してください。
"""

        content_parts = [prompt]
        for img in images:
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
            content_parts.append({"mime_type": "image/png", "data": image_data})
        
        response = model_instance.generate_content(content_parts)
        text = response.text if response.text else ""
        
        # Clean up JSON
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()
        
        try:
            data = json.loads(text)
            return data, 0.9
        except json.JSONDecodeError:
            print(f"[WARN] JSON Parse Failed: {text}")
            return {}, 0.0
            
    except Exception as e:
        print(f"[ERROR] Gemini Extraction Failed: {e}")
        return {}, 0.0
