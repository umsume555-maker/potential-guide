
"""
設定情報（アプリ設定）へのアクセスを提供するリポジトリ
"""
import sqlite3
from datetime import datetime
from typing import Optional

class SettingsRepository:
    def get_setting(self, conn: sqlite3.Connection, key: str) -> Optional[str]:
        """設定値を取得"""
        cursor = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_setting(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        """設定値を保存"""
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now)
        )
