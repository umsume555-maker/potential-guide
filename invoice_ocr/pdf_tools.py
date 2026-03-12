# pdf_tools.py
"""
PDF処理ユーティリティ
- テキスト層抽出（文字PDF対応）
- 画像変換（OCR用）
"""

from pathlib import Path
from typing import Optional
import io


def check_dependencies() -> dict[str, bool]:
    """
    依存関係の確認
    
    Returns:
        {"pdfplumber": True/False, "pdf2image": True/False, "poppler": True/False}
    """
    result = {
        "pdfplumber": False,
        "pdf2image": False,
        "poppler": False
    }
    
    # pdfplumber
    try:
        import pdfplumber
        result["pdfplumber"] = True
    except ImportError:
        pass
    
    # pdf2image
    try:
        import pdf2image
        result["pdf2image"] = True
        
        # Poppler確認
        try:
            from pdf2image.exceptions import PDFInfoNotInstalledError
            pdf2image.pdfinfo_from_path.__wrapped__(Path(__file__).parent / "__init__.py")
        except PDFInfoNotInstalledError:
            pass
        except Exception:
            # pdfinfo が動作可能
            result["poppler"] = True
    except ImportError:
        pass
    
    return result


def extract_text_from_pdf(pdf_path: Path) -> Optional[str]:
    """
    PDFからテキスト層を抽出
    
    Args:
        pdf_path: PDFファイルパス
    
    Returns:
        抽出されたテキスト（テキスト層がない場合はNone）
    """
    try:
        import pdfplumber
    except ImportError:
        print("[WARN] pdfplumber がインストールされていません: pip install pdfplumber")
        return None
    
    try:
        texts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
        
        if texts:
            return "\n".join(texts)
        return None
    except Exception as e:
        print(f"[ERROR] PDF読み込みエラー: {pdf_path} - {e}")
        return None


def pdf_to_images(pdf_path: Path, dpi: int = 200) -> list:
    """
    PDFを画像に変換
    
    Args:
        pdf_path: PDFファイルパス
        dpi: 解像度（デフォルト200）
    
    Returns:
        PIL.Image のリスト（失敗時は空リスト）
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        print("[WARN] pdf2image がインストールされていません: pip install pdf2image")
        print("       また、Poppler のインストールが必要です")
        return []
    
    try:
        images = convert_from_path(str(pdf_path), dpi=dpi)
        return images
    except Exception as e:
        print(f"[ERROR] PDF→画像変換エラー: {pdf_path} - {e}")
        return []


def is_text_pdf(pdf_path: Path, min_chars: int = 50) -> bool:
    """
    テキスト層を持つPDFかどうかを判定
    
    Args:
        pdf_path: PDFファイルパス
        min_chars: テキストPDFと判定する最小文字数
    
    Returns:
        True: テキストPDF, False: 画像PDF
    """
    text = extract_text_from_pdf(pdf_path)
    if text and len(text.strip()) >= min_chars:
        return True
    return False


if __name__ == "__main__":
    # 依存関係チェック
    deps = check_dependencies()
    print("=== 依存関係チェック ===")
    for name, installed in deps.items():
        status = "✓" if installed else "✗"
        print(f"  {status} {name}")
    
    if not deps["pdfplumber"]:
        print("\n[INFO] pdfplumber をインストール: pip install pdfplumber")
    if not deps["pdf2image"]:
        print("[INFO] pdf2image をインストール: pip install pdf2image")
    if deps["pdf2image"] and not deps["poppler"]:
        print("[INFO] Poppler をインストールしてPATHを通してください")
        print("       https://github.com/oschwartz10612/poppler-windows/releases")
