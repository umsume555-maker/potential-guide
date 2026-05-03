"""
ネットワークエラー対応リトライユーティリティ
ConnectionError / ConnectionResetError / ReadTimeout 等の一時的なエラーを自動リトライ
"""
import time
import logging

logger = logging.getLogger(__name__)

# リトライ対象の標準例外
_RETRYABLE_BASE = (
    ConnectionError,
    ConnectionResetError,
    TimeoutError,
    OSError,
)

def _is_retryable(exc: Exception) -> bool:
    """例外がリトライ対象かどうかを判定（requests.exceptions も含む）"""
    if isinstance(exc, _RETRYABLE_BASE):
        return True
    # requests.exceptions.Timeout / ReadTimeout / ConnectionError は
    # IOError(=OSError) 継承だが念のため名前でも判定
    cls_name = type(exc).__name__
    module = getattr(type(exc), '__module__', '')
    if 'requests' in module and cls_name in ('ReadTimeout', 'ConnectTimeout', 'Timeout',
                                              'ConnectionError', 'ChunkedEncodingError',
                                              'RetryError'):
        return True
    # gspread / google-auth 由来のタイムアウト
    if 'ReadTimeout' in cls_name or 'Timeout' in cls_name:
        return True
    return False


def call_with_retry(fn, *args, max_retries: int = 3, delay: float = 5.0, **kwargs):
    """
    fn(*args, **kwargs) を最大 max_retries 回リトライして実行する。
    一時的なネットワークエラー・タイムアウト発生時は delay 秒待機してリトライ。
    最終リトライでも失敗した場合は例外をそのまま raise する。
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if _is_retryable(e):
                last_exc = e
                if attempt < max_retries:
                    logger.warning(
                        "[RETRY %d/%d] ネットワークエラー: %s — %.0f秒後にリトライします",
                        attempt, max_retries, e, delay
                    )
                    time.sleep(delay)
                else:
                    logger.error("[RETRY] %d回リトライしましたが失敗しました: %s", max_retries, e)
            else:
                raise  # 対象外の例外はすぐ raise
    raise last_exc
