"""
データベース接続管理
WALモードでSQLite接続を管理
"""
import sqlite3
import os
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# データディレクトリ
# プロジェクト直下の data/payment_check.db を使用
APP_NAME = "PayCheckTool"
# infra/database.py から見て親の親がプロジェクトルート
base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = base_dir / "data"
DB_PATH = DATA_DIR / "payment_check.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


CREDENTIALS_PATH = DATA_DIR / "credentials.json"


def ensure_data_dir() -> None:
    """データディレクトリを作成"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def resolve_credentials_path(stored_value: str = None) -> Path:
    """
    認証ファイルのパスを解決する（ポータブル対応）。

    優先順位:
      1. data/credentials.json が存在すればそれを使用（正規の置き場所）
      2. stored_value が絶対パスで存在すればそれを使用（後方互換）
      3. どちらも存在しなければ None を返す
    """
    if CREDENTIALS_PATH.exists():
        return CREDENTIALS_PATH
    if stored_value:
        p = Path(stored_value)
        if not p.is_absolute():
            p = base_dir / p
        if p.exists():
            return p
    return None


def get_connection() -> sqlite3.Connection:
    """SQLite接続を取得（WALモード）"""
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """データベース接続のコンテキストマネージャ"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    """データベースを初期化（スキーマ適用）"""
    ensure_data_dir()
    
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"スキーマファイルが見つかりません: {SCHEMA_PATH}")
    
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    
    with get_db() as conn:
        conn.executescript(schema_sql)
        
        # --- Migration ---
        try:
            # 取引先マスタに gemini_flag カラムを追加
            cursor = conn.execute("PRAGMA table_info(vendors)")
            columns = [info["name"] for info in cursor.fetchall()]
            if "gemini_flag" not in columns:
                conn.execute("ALTER TABLE vendors ADD COLUMN gemini_flag TEXT")
                logger.info("Migration: Added gemini_flag column to vendors")

            # Phase 9: AI設定テーブル作成（取引先マスタとは独立して管理）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS masters_ai_setting (
                    vendor_code TEXT PRIMARY KEY,
                    gemini_flag TEXT,
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            logger.debug("Migration: Guaranteed masters_ai_setting table")

            # Phase 10: Recurring Missing Refinements
            # 1. Vendor Reconciliation Target Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                    vendor_code TEXT PRIMARY KEY,
                    vendor_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.debug("Migration: Guaranteed vendor_reconciliation_target table")

            # 2. Output Summary is_monthly column
            cursor = conn.execute("PRAGMA table_info(output_summary)")
            columns = [info["name"] for info in cursor.fetchall()]
            if "is_monthly" not in columns:
                conn.execute("ALTER TABLE output_summary ADD COLUMN is_monthly TEXT")
                logger.info("Migration: Added is_monthly column to output_summary")

            # Drive ファイルキャッシュテーブル（ファイル名ベースの重複アップロード防止）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drive_file_cache (
                    file_name   TEXT PRIMARY KEY,
                    drive_link  TEXT NOT NULL,
                    drive_file_id TEXT,
                    uploaded_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            logger.debug("Migration: Guaranteed drive_file_cache table")

            # OCR ZIP処理履歴（差分解析用）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ocr_zip_log (
                    zip_filename TEXT PRIMARY KEY,
                    zip_size     INTEGER NOT NULL,
                    processed_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            logger.debug("Migration: Guaranteed ocr_zip_log table")

            # 担当2カラム追加（部門・取引先担当テーブル）
            for table, pk in [("masters_assign_dept_override", "dept_code"),
                               ("masters_assign_vendor", "vendor_code")]:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                cols = [r["name"] for r in cursor.fetchall()]
                if "assignee2" not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN assignee2 TEXT DEFAULT ''")
                    logger.info(f"Migration: Added assignee2 column to {table}")

            conn.commit()
        except Exception as e:
            logger.warning("Migration Warning: %s", e)
        # -----------------

        logger.info("データベースを初期化しました: %s", DB_PATH)


def reset_database() -> None:
    """データベースをリセット（削除して再作成）"""
    ensure_data_dir()
    
    if DB_PATH.exists():
        # WALファイルも削除
        for suffix in ["", "-wal", "-shm"]:
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        logger.info("データベースを削除しました: %s", DB_PATH)
    
    init_database()


if __name__ == "__main__":
    # 直接実行時はDB初期化
    init_database()
