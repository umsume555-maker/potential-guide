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


def normalize_pdf_rotation(pdf_path: Path, dpi: int = 100) -> Optional[int]:
    """PDFの各ページ向きを検出し、/Rotate メタデータを書き戻して正立化する。

    元ファイルを上書き更新する（再描画はせず /Rotate を更新するだけなので軽量・無劣化）。
    既に正立しているページは変更しない。失敗時は None を返し元ファイルは保持。

    Returns:
        書き換えたページ数。pypdf 等が無い、または処理失敗時は None。
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("[WARN] pypdf がインストールされていません: pip install pypdf")
        return None

    images = pdf_to_images(pdf_path, dpi=dpi)
    if not images:
        return None

    from .preprocess import detect_rotation

    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        if page_count == 0:
            return 0

        # 検出ページ数 == PDFページ数 でないと対応が崩れる
        if len(images) != page_count:
            print(f"[WARN] PDF page count mismatch: pdf={page_count}, images={len(images)} ({pdf_path.name})")
            return None

        writer = PdfWriter(clone_from=reader)
        changed = 0
        for i, page in enumerate(writer.pages):
            try:
                angle = detect_rotation(images[i])
            except Exception:
                angle = 0
            if not angle:
                continue
            # 既存の /Rotate に合算（90単位に正規化）
            current = int(page.get("/Rotate", 0)) % 360
            new_rot = (current + int(angle)) % 360
            if new_rot != current:
                page.rotate(int(angle))
                changed += 1

        if changed == 0:
            return 0

        tmp_path = pdf_path.with_suffix(pdf_path.suffix + ".tmp")
        with open(tmp_path, "wb") as f:
            writer.write(f)
        # 原子的に置き換え
        import os
        os.replace(str(tmp_path), str(pdf_path))
        return changed
    except Exception as e:
        print(f"[ERROR] PDF rotation normalize failed: {pdf_path} - {e}")
        return None


def normalize_pdf_rotation_via_gemini(pdf_path: Path, api_key: str, model: str = "gemini-2.0-flash") -> Optional[int]:
    """Geminiにページ向きを判定させ、PDFの /Rotate メタデータを書き戻す。

    pdf2image / Poppler / Tesseract に非依存。再描画はせず /Rotate を更新するだけなので
    軽量・無劣化で、画像化のコストもかからない。

    Returns:
        書き換えたページ数。pypdf 不在 or 取得失敗 or 不一致時は None。
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return None

    from .ai_ocr import detect_pdf_rotation_with_gemini

    angles = detect_pdf_rotation_with_gemini(pdf_path, api_key, model)
    if not angles:
        return None

    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        if page_count == 0:
            return 0

        if len(angles) != page_count:
            print(f"[WARN] Gemini rotation page count mismatch: pdf={page_count}, gemini={len(angles)} ({pdf_path.name})")
            return None

        writer = PdfWriter(clone_from=reader)
        changed = 0
        for i, page in enumerate(writer.pages):
            angle = angles[i]
            if not angle:
                continue
            current = int(page.get("/Rotate", 0)) % 360
            new_rot = (current + angle) % 360
            if new_rot != current:
                page.rotate(angle)
                changed += 1

        if changed == 0:
            return 0

        tmp_path = pdf_path.with_suffix(pdf_path.suffix + ".tmp")
        with open(tmp_path, "wb") as f:
            writer.write(f)
        import os
        os.replace(str(tmp_path), str(pdf_path))
        return changed
    except Exception as e:
        print(f"[ERROR] PDF rotation write failed: {pdf_path} - {e}")
        return None


def get_pdf_page_count(pdf_path: Path) -> int:
    """
    PDFのページ数を取得（画像化せず、軽量にメタデータのみ読む）

    Returns:
        ページ数。読み取り失敗時は 1（安全側に倒し、スキップ判定で誤って
        除外しないようにする）
    """
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception as e:
        print(f"[WARN] PDFページ数取得失敗: {pdf_path.name} - {e}")
        return 1


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
