
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
