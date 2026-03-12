# preprocess.py
"""
OCR前処理モジュール
- 回転補正（0/90/180/270度）
- 傾き補正（deskew）
- 画像強調

生成AIは使用せず、OpenCV等の画像処理のみ使用
"""

from pathlib import Path
from typing import Optional, Tuple
import io


def check_dependencies() -> dict[str, bool]:
    """依存関係の確認"""
    result = {
        "opencv": False,
        "numpy": False,
        "pillow": False
    }
    
    try:
        import cv2
        result["opencv"] = True
    except ImportError:
        pass
    
    try:
        import numpy
        result["numpy"] = True
    except ImportError:
        pass
    
    try:
        from PIL import Image
        result["pillow"] = True
    except ImportError:
        pass
    
    return result


def pil_to_cv2(pil_image):
    """PIL Image を OpenCV形式に変換"""
    import numpy as np
    import cv2
    
    # RGB -> BGR 変換
    if pil_image.mode == "RGB":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    elif pil_image.mode == "RGBA":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGBA2BGRA)
    elif pil_image.mode == "L":
        return np.array(pil_image)
    else:
        # その他の形式はRGBに変換
        return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv2_image):
    """OpenCV形式を PIL Image に変換"""
    import cv2
    from PIL import Image
    
    if len(cv2_image.shape) == 2:
        # グレースケール
        return Image.fromarray(cv2_image)
    elif cv2_image.shape[2] == 3:
        # BGR -> RGB
        return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))
    else:
        # BGRA -> RGBA
        return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGRA2RGBA))


def detect_rotation(image) -> int:
    """
    画像の回転角度を検出（0, 90, 180, 270のいずれか）
    
    Tesseract OSD または ヒューリスティックを使用
    
    Returns:
        検出された回転角度（度）
    """
    try:
        import pyocr
        import pyocr.builders
        from PIL import Image
        
        tools = pyocr.get_available_tools()
        if tools:
            tool = tools[0]
            # OSD (Orientation and Script Detection) 使用
            try:
                # tesseract --psm 0 で向き検出
                osd = tool.detect_orientation(image, lang="osd")
                return osd.get("angle", 0)
            except Exception:
                pass
    except ImportError:
        pass
    
    # フォールバック: 0度とする
    return 0


def rotate_image(image, angle: int):
    """
    画像を回転
    
    Args:
        image: PIL Image
        angle: 回転角度（0, 90, 180, 270）
    
    Returns:
        回転後の PIL Image
    """
    from PIL import Image
    
    if angle == 0:
        return image
    elif angle == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    elif angle == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    elif angle == 270:
        return image.transpose(Image.Transpose.ROTATE_90)
    else:
        # 任意角度
        return image.rotate(-angle, expand=True, fillcolor=(255, 255, 255))


def deskew(image) -> Tuple:
    """
    傾き補正（deskew）
    
    Args:
        image: PIL Image
    
    Returns:
        (補正後の PIL Image, 傾き角度)
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[WARN] OpenCV/NumPy がインストールされていません")
        return image, 0.0
    
    # PIL -> OpenCV
    cv_image = pil_to_cv2(image)
    
    # グレースケール変換
    if len(cv_image.shape) == 3:
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv_image
    
    # 二値化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # 傾き角度を検出
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 100:
        return image, 0.0
    
    angle = cv2.minAreaRect(coords)[-1]
    
    # 角度の正規化
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    
    # 微小な傾きのみ補正（大きな回転は rotate_image で対応）
    if abs(angle) < 0.5 or abs(angle) > 10:
        return image, 0.0
    
    # 回転補正
    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        cv_image, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    
    # OpenCV -> PIL
    return cv2_to_pil(rotated), angle


def enhance_image(image):
    """
    OCR用の画像強調
    - コントラスト調整
    - ノイズ除去
    
    Args:
        image: PIL Image
    
    Returns:
        強調後の PIL Image
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return image
    
    cv_image = pil_to_cv2(image)
    
    # グレースケール変換
    if len(cv_image.shape) == 3:
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv_image
    
    # ノイズ除去
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    
    # コントラスト調整 (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    return cv2_to_pil(enhanced)


def preprocess_image(image, do_rotate: bool = True, do_deskew: bool = True, do_enhance: bool = False):
    """
    画像の前処理パイプライン
    
    Args:
        image: PIL Image
        do_rotate: 回転補正を行うか
        do_deskew: 傾き補正を行うか
        do_enhance: 画像強調を行うか
    
    Returns:
        前処理後の PIL Image
    """
    result = image
    
    # 回転補正
    if do_rotate:
        angle = detect_rotation(result)
        if angle != 0:
            result = rotate_image(result, angle)
            print(f"[INFO] 回転補正: {angle}度")
    
    # 傾き補正
    if do_deskew:
        result, skew_angle = deskew(result)
        if skew_angle != 0:
            print(f"[INFO] 傾き補正: {skew_angle:.2f}度")
    
    # 画像強調（オプション）
    if do_enhance:
        result = enhance_image(result)
    
    return result


if __name__ == "__main__":
    # 依存関係チェック
    deps = check_dependencies()
    print("=== 依存関係チェック ===")
    for name, installed in deps.items():
        status = "✓" if installed else "✗"
        print(f"  {status} {name}")
    
    if not deps["opencv"]:
        print("\n[INFO] OpenCV をインストール: pip install opencv-python")
    if not deps["numpy"]:
        print("[INFO] NumPy をインストール: pip install numpy")
    if not deps["pillow"]:
        print("[INFO] Pillow をインストール: pip install Pillow")
