"""
担当割当管理API
"""
import sqlite3
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException, Form 
from pydantic import BaseModel
from typing import List, Optional

from infra.database import get_db

router = APIRouter(prefix="/api/assignment", tags=["assignment"])

# --- Models ---
class AssigneeUpdate(BaseModel):
    code: str
    assignee: str
    updated_by: str = "user"

class SyncRequest(BaseModel):
    pass 

# --- API Endpoints ---

@router.post("/sync")
async def sync_from_input_data(csv_file: UploadFile = File(...)):
    """
    入力CSVから部門・取引先を抽出し、担当割当マスタを更新する
    - 新規コード: 追加 (担当者空)
    - 既存コード: 名称更新 (担当者維持)
    """
    try:
        # CSV読み込み
        df = pd.read_csv(csv_file.file, encoding="cp932", dtype=str)
        # ヘッダーの空白除去
        df.columns = [c.strip() for c in df.columns]
        
        print(f"DEBUG_SYNC: Columns found: {df.columns.tolist()}")
        
        # 必須カラム: 申請部門表示コード, 申請部門名, 取引先コード
        required_cols = ["申請部門表示コード", "申請部門名", "取引先コード"]
        missing = [c for c in required_cols if c not in df.columns]
        
        if missing:
            # 試しにBOM付きかも考慮して、先頭カラムのBOM除去を試みる（Pandasは自動処理するはずだが念のため）
            # もしくは "Input Data" フォーマットの違い
            print(f"DEBUG_SYNC: Missing columns: {missing}")
            raise HTTPException(status_code=400, detail=f"必須カラムが不足しています: {missing} (検出: {list(df.columns)})")

        # 取引先名カラムの推定（バリエーション対応）
        vendor_name_col = "取引先名"
        for col in ["取引先名（略）", "取引先名(略)", "取引先名"]:
            if col in df.columns:
                vendor_name_col = col
                break
        
        print(f"DEBUG_SYNC: Vendor Name Column determined as: {vendor_name_col}")

        # デバッグ: 抽出前の状態
        print(f"DEBUG_SYNC: Total Rows Read: {len(df)}")
        
        try:
            # Drop duplicates and NA
            dept_source = df[["申請部門表示コード", "申請部門名"]]
            dept_data = dept_source.drop_duplicates().dropna(subset=["申請部門表示コード"])
            
            vendor_source = df[["取引先コード", vendor_name_col]]
            vendor_data = vendor_source.drop_duplicates().dropna(subset=["取引先コード"])
            
        except KeyError as e:
             raise HTTPException(status_code=400, detail=f"列指定エラー: {str(e)}")
        
        print(f"DEBUG_SYNC: Extract Rows: Dept={len(dept_data)} (from {len(dept_source)}), Vendor={len(vendor_data)}")
        
        dept_new = 0
        dept_updated = 0
        vendor_new = 0
        vendor_updated = 0
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # --- 部門同期 ---
            for _, row in dept_data.iterrows():
                code = str(row["申請部門表示コード"]).strip()
                name = str(row["申請部門名"]).strip()
                
                # 'nan' 文字列対策
                if not code or code.lower() == 'nan': continue
                
                # 存在確認
                cursor.execute("SELECT assignee FROM masters_assign_dept_override WHERE dept_code = ?", (code,))
                row_db = cursor.fetchone()
                
                if row_db:
                    cursor.execute("UPDATE masters_assign_dept_override SET dept_name = ? WHERE dept_code = ?", (name, code))
                    dept_updated += 1
                else:
                    cursor.execute("INSERT INTO masters_assign_dept_override (dept_code, dept_name, assignee) VALUES (?, ?, '')", (code, name))
                    dept_new += 1
            
            # --- 取引先同期 ---
            for _, row in vendor_data.iterrows():
                code = str(row["取引先コード"]).strip()
                name = str(row[vendor_name_col]).strip()
                
                # 'nan' 文字列対策
                if not code or code.lower() == 'nan': continue
                
                cursor.execute("SELECT assignee FROM masters_assign_vendor WHERE vendor_code = ?", (code,))
                row_db = cursor.fetchone()
                
                if row_db:
                    cursor.execute("UPDATE masters_assign_vendor SET vendor_name = ? WHERE vendor_code = ?", (name, code))
                    vendor_updated += 1
                else:
                    cursor.execute("INSERT INTO masters_assign_vendor (vendor_code, vendor_name, assignee) VALUES (?, ?, '')", (code, name))
                    vendor_new += 1
            
            conn.commit()
            
        return {
            "status": "ok", 
            "message": (
                f"同期完了\n"
                f"CSV読込行数: {len(df)}行\n"
                f"部門: 新規{dept_new} / 更新{dept_updated} (抽出対象{len(dept_data)})\n"
                f"取引先: 新規{vendor_new} / 更新{vendor_updated} (抽出対象{len(vendor_data)})"
            ),
            "debug_info": {
                "total_rows": len(df),
                "dept_valid": len(dept_data),
                "vendor_valid": len(vendor_data),
                "columns": df.columns.tolist()
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dept")
async def get_dept_assignments():
    """部門担当一覧"""
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT dept_code, dept_name, assignee FROM masters_assign_dept_override ORDER BY dept_code")
        return [dict(row) for row in cursor.fetchall()]

@router.get("/vendor")
async def get_vendor_assignments():
    """取引先担当一覧"""
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT vendor_code, vendor_name, assignee FROM masters_assign_vendor ORDER BY vendor_code")
        return [dict(row) for row in cursor.fetchall()]

@router.post("/dept")
async def update_dept_assignment(data: AssigneeUpdate):
    """部門担当更新"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE masters_assign_dept_override SET assignee = ? WHERE dept_code = ?", (data.assignee, data.code))
        if cursor.rowcount == 0:
            # マスタにない場合はエラー（同期してから編集すべき）
           raise HTTPException(status_code=404, detail="指定された部門コードが見つかりません。先に同期を行ってください。")
        conn.commit()
    return {"status": "ok"}

@router.post("/vendor")
async def update_vendor_assignment(data: AssigneeUpdate):
    """取引先担当更新"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE masters_assign_vendor SET assignee = ? WHERE vendor_code = ?", (data.assignee, data.code))
        if cursor.rowcount == 0:
           raise HTTPException(status_code=404, detail="指定された取引先コードが見つかりません。先に同期を行ってください。")
        conn.commit()
    return {"status": "ok"}
