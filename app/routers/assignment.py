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
from infra.csv_loader import normalize_dept_code

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
                code = normalize_dept_code(str(row["申請部門表示コード"]).strip())
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
        cursor.execute("SELECT dept_code, dept_name, assignee, COALESCE(assignee2, '') as assignee2 FROM masters_assign_dept_override ORDER BY dept_code")
        return [dict(row) for row in cursor.fetchall()]

@router.get("/vendor")
async def get_vendor_assignments():
    """取引先担当一覧"""
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT vendor_code, vendor_name, assignee, COALESCE(assignee2, '') as assignee2 FROM masters_assign_vendor ORDER BY vendor_code")
        return [dict(row) for row in cursor.fetchall()]

@router.post("/dept")
async def update_dept_assignment(data: AssigneeUpdate):
    """部門担当更新"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE masters_assign_dept_override SET assignee = ? WHERE dept_code = ?", (data.assignee, data.code))
        if cursor.rowcount == 0:
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

@router.post("/copy-to-assignee2")
async def copy_assignee_to_assignee2():
    """担当1の値を担当2に一括コピー（月初リセット用）"""
    with get_db() as conn:
        conn.execute("UPDATE masters_assign_dept_override SET assignee2 = assignee")
        conn.execute("UPDATE masters_assign_vendor SET assignee2 = assignee")
        conn.commit()
    return {"status": "ok", "message": "担当2に担当1をコピーしました"}


class PushAssignee2Request(BaseModel):
    spreadsheet_id: str


@router.post("/push-assignee2")
async def push_assignee2_to_sheet(data: PushAssignee2Request):
    """DBのassignee2をスプレッドシートの担当2列に反映する"""
    import sqlite3
    import re
    from infra.database import DB_PATH

    spreadsheet_id = data.spreadsheet_id
    # URL形式の場合はIDを抽出
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', spreadsheet_id)
    if match:
        spreadsheet_id = match.group(1)

    # DB から vendor/dept の assignee2 を取得
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        vendor_map = {
            r["vendor_code"]: r["assignee2"] or ""
            for r in conn.execute("SELECT vendor_code, COALESCE(assignee2,'') as assignee2 FROM masters_assign_vendor").fetchall()
        }
        dept_map = {
            r["dept_code"]: r["assignee2"] or ""
            for r in conn.execute("SELECT dept_code, COALESCE(assignee2,'') as assignee2 FROM masters_assign_dept_override").fetchall()
        }
        # 最新run_idの output_summary から (vendor_code, dept_code, base_invoice_no) を取得
        run_row = conn.execute("SELECT run_id FROM run_log ORDER BY started_at DESC LIMIT 1").fetchone()
        if not run_row:
            return {"status": "error", "message": "チェック実行データがありません"}
        run_id = run_row["run_id"]
        summary_rows = conn.execute(
            "SELECT base_invoice_no, dept_code, vendor_code FROM output_summary WHERE run_id = ?", (run_id,)
        ).fetchall()

    # (base_invoice_no, dept_code) → assignee2 のマップを作成
    # 取引先優先、なければ部門
    row_assignee2 = {}
    for r in summary_rows:
        inv = str(r["base_invoice_no"])
        dept = str(r["dept_code"])
        try:
            dept_key = f"{int(dept):08d}"
        except:
            dept_key = dept
        key = f"{inv}_{dept_key}"
        a2 = vendor_map.get(str(r["vendor_code"]), "") or dept_map.get(str(r["dept_code"]), "")
        row_assignee2[key] = a2

    # スプレッドシートを開いて担当2列を更新
    from infra.database import resolve_credentials_path
    from infra.spreadsheet_service import SpreadsheetService
    from infra.settings_repository import SettingsRepository
    import sqlite3 as _sqlite3
    with _sqlite3.connect(str(DB_PATH)) as _c:
        _c.row_factory = _sqlite3.Row
        try:
            stored = SettingsRepository().get_setting(_c, "google_credentials_path")
        except Exception:
            stored = None
    creds = resolve_credentials_path(stored)
    if not creds:
        return {"status": "error", "message": "認証ファイル(credentials.json)が見つかりません"}
    service = SpreadsheetService(credentials_path=str(creds))
    try:
        client = service.authenticate()
        sh = client.open_by_key(spreadsheet_id)
        sheet = sh.sheet1
        all_values = sheet.get_all_values()
    except Exception as e:
        return {"status": "error", "message": f"スプレッドシート接続エラー: {e}"}

    if not all_values:
        return {"status": "error", "message": "スプレッドシートにデータがありません"}

    header = all_values[0]

    # 必要な列インデックスを取得
    try:
        idx_invoice = header.index("伝票番号")
    except ValueError:
        return {"status": "error", "message": "「伝票番号」列が見つかりません"}

    idx_dept = -1
    for h in ["申請部門コード", "部門コード"]:
        if h in header:
            idx_dept = header.index(h)
            break
    if idx_dept == -1:
        return {"status": "error", "message": "「申請部門コード」列が見つかりません"}

    # 担当2列を探す（なければ担当列の隣に追加）
    if "担当2" in header:
        idx_assignee2 = header.index("担当2")
    else:
        return {"status": "error", "message": "「担当2」列がスプレッドシートに見つかりません。先にスプレッドシート更新を実行してください。"}

    # 担当2列の値を更新（データ行のみ）
    updates = []
    updated_count = 0
    for row_idx, row in enumerate(all_values[1:], start=2):  # 1-indexed, skip header
        if len(row) <= max(idx_invoice, idx_dept):
            continue
        inv = str(row[idx_invoice])
        dept = str(row[idx_dept])
        try:
            dept = f"{int(dept):08d}"
        except:
            pass
        key = f"{inv}_{dept}"
        if key in row_assignee2:
            col_letter = _col_to_letter(idx_assignee2 + 1)
            updates.append({
                "range": f"{col_letter}{row_idx}",
                "values": [[row_assignee2[key]]]
            })
            updated_count += 1

    if updates:
        try:
            sheet.batch_update(
                [{"range": u["range"], "values": u["values"]} for u in updates],
                value_input_option="USER_ENTERED"
            )
        except Exception as e:
            return {"status": "error", "message": f"書き込みエラー: {e}"}

    return {"status": "ok", "message": f"担当2を{updated_count}行反映しました"}


def _col_to_letter(col: int) -> str:
    """列番号（1始まり）をA1記法のアルファベットに変換"""
    result = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        result = chr(65 + remainder) + result
    return result
