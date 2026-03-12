"""
データベース接続管理
WALモードでSQLite接続を管理
"""
import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

# データディレクトリ
# プロジェクト直下の data/payment_check.db を使用
APP_NAME = "PayCheckTool"
# infra/database.py から見て親の親がプロジェクトルート
base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = base_dir / "data"
DB_PATH = DATA_DIR / "payment_check.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def ensure_data_dir() -> None:
    """データディレクトリを作成"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


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
                print("Migration: Added gemini_flag column to vendors")

            # Phase 9: AI設定テーブル作成（取引先マスタとは独立して管理）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS masters_ai_setting (
                    vendor_code TEXT PRIMARY KEY,
                    gemini_flag TEXT,
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            print("Migration: Guaranteed masters_ai_setting table")

            # Phase 10: Recurring Missing Refinements
            # 1. Vendor Reconciliation Target Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                    vendor_code TEXT PRIMARY KEY,
                    vendor_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("Migration: Guaranteed vendor_reconciliation_target table")

            # 2. Output Summary is_monthly column
            cursor = conn.execute("PRAGMA table_info(output_summary)")
            columns = [info["name"] for info in cursor.fetchall()]
            if "is_monthly" not in columns:
                conn.execute("ALTER TABLE output_summary ADD COLUMN is_monthly TEXT")
                print("Migration: Added is_monthly column to output_summary")

            conn.commit()
        except Exception as e:
            print(f"Migration Warning: {e}")
        # -----------------

        print(f"データベースを初期化しました: {DB_PATH}")


def reset_database() -> None:
    """データベースをリセット（削除して再作成）"""
    ensure_data_dir()
    
    if DB_PATH.exists():
        # WALファイルも削除
        for suffix in ["", "-wal", "-shm"]:
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        print(f"データベースを削除しました: {DB_PATH}")
    
    init_database()


if __name__ == "__main__":
    # 直接実行時はDB初期化
    init_database()
