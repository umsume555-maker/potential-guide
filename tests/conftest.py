"""
テスト共通フィクスチャ
"""
import sys
import sqlite3
import tempfile
from pathlib import Path
from datetime import date

import pytest

# プロジェクトルートを sys.path に追加（どこから pytest を実行しても動くように）
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def holidays_set() -> set:
    """テスト用祝日セット（2025年）"""
    return {
        "2025-01-01",  # 元日
        "2025-01-13",  # 成人の日
        "2025-02-11",  # 建国記念の日
        "2025-03-20",  # 春分の日
        "2025-04-29",  # 昭和の日
        "2025-05-03",  # 憲法記念日
        "2025-05-04",  # みどりの日
        "2025-05-05",  # こどもの日
        "2025-07-21",  # 海の日
        "2025-08-11",  # 山の日
        "2025-09-15",  # 敬老の日
        "2025-09-23",  # 秋分の日
        "2025-10-13",  # スポーツの日
        "2025-11-03",  # 文化の日
        "2025-11-23",  # 勤労感謝の日
        "2025-11-24",  # 振替休日
    }


@pytest.fixture
def in_memory_db():
    """テスト用インメモリ SQLite DB"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()
