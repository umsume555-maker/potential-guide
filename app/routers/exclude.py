"""
除外取引先管理API
"""
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from infra.database import get_db

router = APIRouter(prefix="/api/exclude", tags=["exclude"])

class ExcludeRule(BaseModel):
    vendor_code: str
    reason: str

@router.get("", response_model=List[ExcludeRule])
async def get_excluded_vendors():
    """除外取引先一覧"""
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT vendor_code, reason FROM masters_exclude ORDER BY vendor_code")
        return [dict(row) for row in cursor.fetchall()]

@router.post("")
async def add_excluded_vendor(rule: ExcludeRule):
    """除外取引先追加"""
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO masters_exclude (vendor_code, reason) VALUES (?, ?)",
                (rule.vendor_code, rule.reason)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            cursor.execute(
                "UPDATE masters_exclude SET reason = ? WHERE vendor_code = ?",
                (rule.reason, rule.vendor_code)
            )
            conn.commit()
    return {"status": "ok", "message": "登録しました"}

@router.delete("/{code}")
async def delete_excluded_vendor(code: str):
    """除外取引先削除"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM masters_exclude WHERE vendor_code = ?", (code,))
        conn.commit()
    return {"status": "ok", "message": "削除しました"}
