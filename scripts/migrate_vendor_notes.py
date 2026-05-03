"""
取引先注意事項テーブルの追加マイグレーション

テーブル:
  masters_note_labels   - 注意事項ラベルマスタ (例: 要確認, 保留, 月次 etc.)
  masters_vendor_notes  - 取引先ごとのラベル紐付け
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.database import get_db

def migrate():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS masters_note_labels (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                label     TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS masters_vendor_notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_code TEXT NOT NULL,
                label_id    INTEGER NOT NULL REFERENCES masters_note_labels(id),
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(vendor_code, label_id)
            )
        """)
        # デフォルトラベルを追加（未登録の場合のみ）
        defaults = ["要確認", "保留", "月次", "都度", "未払"]
        for lbl in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO masters_note_labels (label) VALUES (?)",
                (lbl,)
            )
        conn.commit()
        print("Migration complete: masters_note_labels, masters_vendor_notes created.")

        cursor = conn.execute("SELECT id, label FROM masters_note_labels ORDER BY id")
        for row in cursor.fetchall():
            print(f"  Label {row[0]}: {row[1]}")

if __name__ == "__main__":
    migrate()
