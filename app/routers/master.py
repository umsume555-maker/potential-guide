"""
マスター管理API
"""
import tempfile
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.database import get_db, init_database
from infra.holiday_api import fetch_holidays_sync, save_holidays_to_db, check_holidays_coverage
from infra.csv_loader import load_vendor_master_csv, load_department_master_csv, load_account_rule_csv, load_vendor_rule_csv, load_account_master_csv, load_exception_dept_csv, normalize_dept_code
from infra.rule_repository import RuleRepository


router = APIRouter(prefix="/api/master", tags=["master"])


class VendorExclude(BaseModel):
    """除外取引先"""
    vendor_code: str
    reason: Optional[str] = None


@router.get("/vendor/check/{code}")
async def check_vendor_exists(code: str):
    """デバッグ用: 取引先がDBに存在するか確認"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT vendor_code, vendor_name FROM masters_vendor WHERE vendor_code = ?",
            (code,)
        )
        row = cursor.fetchone()
        if row:
            return {"exists": True, "vendor_code": row["vendor_code"], "vendor_name": row["vendor_name"]}
        
        # 部分一致で検索
        cursor = conn.execute(
            "SELECT vendor_code, vendor_name FROM masters_vendor WHERE vendor_code LIKE ? LIMIT 5",
            (f"%{code}%",)
        )
        rows = cursor.fetchall()
        return {"exists": False, "similar": [dict(r) for r in rows]}


@router.get("/vendor/list")
async def list_vendors(q: str = ""):
    """取引先一覧を直接取得（デバッグ/検証用）"""
    with get_db() as conn:
        if q:
            cursor = conn.execute(
                "SELECT vendor_code, vendor_name FROM masters_vendor WHERE vendor_code LIKE ? OR vendor_name LIKE ? ORDER BY vendor_code LIMIT 50",
                (f"%{q}%", f"%{q}%")
            )
        else:
            cursor = conn.execute("SELECT vendor_code, vendor_name FROM masters_vendor ORDER BY vendor_code DESC LIMIT 50")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


class AllowedPayee(BaseModel):
    """許容支払先"""
    vendor_code: str
    allowed_payee_code: str
    note: Optional[str] = None


class AssignDeptRule(BaseModel):
    """担当割当（部門範囲ルール）"""
    dept_code_start: str
    dept_code_end: str
    assignee: str
    priority: int = 0


@router.get("/exclude")
async def list_excluded_vendors():
    """除外取引先一覧を取得"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT vendor_code, reason, created_at FROM masters_exclude ORDER BY vendor_code"
        )
        return [dict(row) for row in cursor]


@router.post("/exclude")
async def add_excluded_vendor(data: VendorExclude):
    """除外取引先を追加"""
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO masters_exclude (vendor_code, reason) VALUES (?, ?)",
                (data.vendor_code, data.reason)
            )
            return {"status": "ok", "message": f"除外取引先を追加しました: {data.vendor_code}"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/exclude/{vendor_code}")
async def remove_excluded_vendor(vendor_code: str):
    """除外取引先を削除"""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM masters_exclude WHERE vendor_code = ?",
            (vendor_code,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="取引先が見つかりません")
        return {"status": "ok", "message": f"除外取引先を削除しました: {vendor_code}"}


@router.get("/allowed-payee")
async def list_allowed_payees():
    """許容支払先一覧を取得"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT vendor_code, allowed_payee_code, note FROM masters_allowed_payee ORDER BY vendor_code"
        )
        return [dict(row) for row in cursor]


@router.post("/allowed-payee")
async def add_allowed_payee(data: AllowedPayee):
    """許容支払先を追加"""
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO masters_allowed_payee (vendor_code, allowed_payee_code, note) VALUES (?, ?, ?)",
                (data.vendor_code, data.allowed_payee_code, data.note)
            )
            return {"status": "ok", "message": f"許容支払先を追加しました"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))



class AccountMasterCreate(BaseModel):
    account_code: str
    account_name: str
    account_type: Optional[str] = None


@router.post("/account")
async def create_account(data: AccountMasterCreate):
    """勘定科目マスタを手動登録"""
    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO masters_account (account_code, account_name) 
                VALUES (?, ?)
                ON CONFLICT(account_code) DO UPDATE SET
                  account_name = excluded.account_name
                """,
                (data.account_code, data.account_name)
            )
            return {"status": "ok", "message": f"勘定科目を登録しました: {data.account_name} ({data.account_code})"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/holiday/update")
async def update_holidays():
    """祝日データを更新"""
    try:
        holidays = fetch_holidays_sync()
        with get_db() as conn:
            count = save_holidays_to_db(conn, holidays)
            return {
                "status": "ok",
                "message": f"祝日データを更新しました",
                "count": count
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"祝日データの取得に失敗しました: {str(e)}")


@router.get("/holiday/status")
async def get_holiday_status():
    """祝日データの状態を確認"""
    current_year = datetime.now().year
    required_years = [current_year, current_year + 1, current_year + 2]
    
    with get_db() as conn:
        is_ok, missing = check_holidays_coverage(conn, required_years)
        
        # 祝日データの件数
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM holidays")
        count = cursor.fetchone()["cnt"]
        
        # 年別の件数
        cursor = conn.execute("""
            SELECT substr(holiday_date, 1, 4) as year, COUNT(*) as cnt 
            FROM holidays GROUP BY year ORDER BY year
        """)
        by_year = {row["year"]: row["cnt"] for row in cursor}
        
        return {
            "status": "ok" if is_ok else "missing",
            "total_count": count,
            "by_year": by_year,
            "required_years": required_years,
            "missing_years": missing
        }


@router.get("/assign/dept-rule")
async def list_assign_dept_rules():
    """担当割当（部門範囲ルール）一覧"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, dept_code_start, dept_code_end, assignee, priority FROM masters_assign_dept_rule ORDER BY priority DESC"
        )
        return [dict(row) for row in cursor]


@router.post("/assign/dept-rule")
async def add_assign_dept_rule(data: AssignDeptRule):
    """担当割当（部門範囲ルール）を追加"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO masters_assign_dept_rule (dept_code_start, dept_code_end, assignee, priority) VALUES (?, ?, ?, ?)",
            (data.dept_code_start, data.dept_code_end, data.assignee, data.priority)
        )
        return {"status": "ok", "message": "担当割当ルールを追加しました"}


@router.post("/vendor/upload")
async def upload_vendor_master(
    file: UploadFile = File(...)
):
    """
    取引先マスターCSVをアップロードして更新
    - 既存データを全削除して入れ替え
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="CSVファイルを選択してください")
    
    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        # CSV読み込み
        vendors = list(load_vendor_master_csv(tmp_path))
        if not vendors:
            raise HTTPException(status_code=400, detail="有効な取引先データが見つかりませんでした")
        
        with get_db() as conn:
            # 既存データ削除
            conn.execute("DELETE FROM masters_vendor")
            
            # データ挿入
            sql = """
                INSERT INTO masters_vendor (
                    vendor_code, vendor_name, payment_condition_code, payment_condition_name,
                    holiday_handling, payment_cycle_type, payment_month_offset, payment_day,
                    closing_day, bank_code, bank_name, branch_code, branch_name,
                    account_type, account_number, account_holder, gemini_flag
                ) VALUES (
                    :vendor_code, :vendor_name, :payment_condition_code, :payment_condition_name,
                    :holiday_handling, :payment_cycle_type, :payment_month_offset, :payment_day,
                    :closing_day, :bank_code, :bank_name, :branch_code, :branch_name,
                    :account_type, :account_number, :account_holder, :gemini_flag
                )
            """
            conn.executemany(sql, vendors)
            
            # 件数取得
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM masters_vendor")
            count = cursor.fetchone()["cnt"]
            
            return {
                "status": "ok",
                "message": f"取引先マスターを更新しました（{count}件）",
                "count": count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class VendorCreate(BaseModel):
    vendor_code: str
    vendor_name: str


class PaymentConditionUpdate(BaseModel):
    closing_day: int           # 締日 (99=末日, 1-31)
    payment_month_offset: int  # 締日から何ヶ月後 (0=当月, 1=翌月, ...)
    payment_day: int           # 支払日 (99=末日, 1-31)
    holiday_handling: str      # "1"=前倒し, "2"=後倒し
    no_month_crossing: int     # 0 or 1


@router.get("/vendor/{vendor_code}/payment-condition")
async def get_payment_condition(vendor_code: str):
    """取引先の支払条件を取得"""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT vendor_code, vendor_name,
                   closing_day, payment_month_offset, payment_day,
                   holiday_handling, no_month_crossing,
                   payment_condition_code, payment_condition_name
            FROM masters_vendor
            WHERE vendor_code = ?
            """,
            (vendor_code,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"取引先が見つかりません: {vendor_code}")
        return dict(row)


@router.patch("/vendor/{vendor_code}/payment-condition")
async def update_payment_condition(vendor_code: str, data: PaymentConditionUpdate):
    """取引先の支払条件を更新"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM masters_vendor WHERE vendor_code = ?", (vendor_code,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"取引先が見つかりません: {vendor_code}")

        conn.execute(
            """
            UPDATE masters_vendor
            SET closing_day          = ?,
                payment_month_offset = ?,
                payment_day          = ?,
                holiday_handling     = ?,
                no_month_crossing    = ?,
                updated_at           = datetime('now', 'localtime')
            WHERE vendor_code = ?
            """,
            (
                data.closing_day,
                data.payment_month_offset,
                data.payment_day,
                data.holiday_handling,
                data.no_month_crossing,
                vendor_code,
            )
        )
        conn.commit()
        return {"status": "ok", "message": "支払条件を更新しました"}


@router.post("/vendor")
async def create_vendor(data: VendorCreate):
    """
    取引先マスター手動登録
    - 必須: コード、名称
    - その他: デフォルト値
    """
    # Duplicate check first (outside main transaction)
    with get_db() as conn:
        cursor = conn.execute("SELECT 1 FROM masters_vendor WHERE vendor_code = ?", (data.vendor_code,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"取引先コード {data.vendor_code} は既に登録されています")
    
    # Insert in separate transaction
    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO masters_vendor (
                    vendor_code, vendor_name, 
                    payment_condition_code, payment_condition_name,
                    holiday_handling, payment_cycle_type, payment_month_offset, payment_day,
                    closing_day, bank_code, bank_name, branch_code, branch_name,
                    account_type, account_number, account_holder
                ) VALUES (
                    ?, ?, 
                    '', '', 
                    '1', '', '1', '0', 
                    '0', '', '', '', '', 
                    '', '', ''
                )
                """,
                (data.vendor_code, data.vendor_name)
            )
            # Explicit commit
            conn.commit()
            
            # Verify insertion
            cursor = conn.execute("SELECT vendor_code, vendor_name FROM masters_vendor WHERE vendor_code = ?", (data.vendor_code,))
            row = cursor.fetchone()
            if row:
                return {"status": "ok", "message": f"取引先を登録しました: {row['vendor_name']}", "vendor_code": row["vendor_code"]}
            else:
                raise HTTPException(status_code=500, detail="登録処理は完了しましたが、確認に失敗しました")
                
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=f"登録エラー: {str(e)}")


@router.post("/department/upload")
async def upload_department_master(
    file: UploadFile = File(...)
):
    """
    部門マスターCSVをアップロードして更新
    - 既存データを全削除して入れ替え
    - 計上区分が「直接部門」ならCOST、それ以外はSGA
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="CSVファイルを選択してください")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        # CSV読み込み
        depts = list(load_department_master_csv(tmp_path))
        if not depts:
            raise HTTPException(status_code=400, detail="有効な部門データが見つかりませんでした（8桁コード必須）")
        
        with get_db() as conn:
            # 既存データ削除
            conn.execute("DELETE FROM masters_department")
            
            # データ挿入
            sql = """
                INSERT INTO masters_department (
                    dept_code, dept_name, dept_type
                ) VALUES (
                    :dept_code, :dept_name, :dept_type
                )
            """
            conn.executemany(sql, depts)
            
            # 件数取得
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM masters_department")
            count = cursor.fetchone()["cnt"]
            
            return {
                "status": "ok",
                "message": f"部門マスターを更新しました（{count}件）",
                "count": count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/department-master")
async def list_department_master(q: str = ""):
    """部門マスタ一覧取得（部門コード・部門名で検索）"""
    sql = "SELECT dept_code, dept_name FROM masters_department"
    params = []
    if q:
        sql += " WHERE dept_code LIKE ? OR dept_name LIKE ?"
        params = [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY dept_code"

    with get_db() as conn:
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


@router.post("/account/upload")
async def upload_account_rule(
    file: UploadFile = File(...)
):
    """
    科目ルールCSVをアップロードして更新
    - 3段階優先（Dept/Type/Any）対応
    - 既存ルールは維持し、CSVの内容でUpsert（上書き登録）する
    - ※全入れ替えではなく追加更新とする
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="CSVファイルを選択してください")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        # CSV読み込み
        rules = list(load_account_rule_csv(tmp_path))
        if not rules:
            raise HTTPException(status_code=400, detail="有効な科目ルールデータが見つかりませんでした")
        
        repo = RuleRepository()
        
        with get_db() as conn:
            count = 0
            for r in rules:
                repo.upsert_account_rule(
                    conn,
                    vendor_code=r["vendor_code"],
                    scope_type=r["scope_type"],
                    scope_key=r["scope_key"],
                    expected_account=r["expected_account"],
                    updated_by="csv_import",
                    reason=r["reason"]
                )
                count += 1
            
            return {
                "status": "ok",
                "message": f"科目ルールを更新しました（{count}件）",
                "count": count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/vendor-rule/upload")
async def upload_vendor_rule(
    file: UploadFile = File(...)
):
    """
    取引先ルールCSV（科目+税区分）をアップロードして一括登録
    
    想定フォーマット:
    取引先ｺｰﾄﾞ,cost科目ｺｰﾄﾞ,sga科目ｺｰﾄﾞ,税区分ｺｰﾄﾞ
    
    - 1行から科目2件（COST用/SGA用）+税区分1件を登録
    - 既存ルールはUpsert（上書き）
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="CSVファイルを選択してください")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        rules = list(load_vendor_rule_csv(tmp_path))
        if not rules:
            raise HTTPException(status_code=400, detail="有効なルールデータが見つかりませんでした")
        
        repo = RuleRepository()
        
        account_count = 0
        tax_count = 0
        ai_count = 0
        
        with get_db() as conn:
            for r in rules:
                if r["type"] == "account":
                    repo.upsert_account_rule(
                        conn,
                        vendor_code=r["vendor_code"],
                        scope_type=r["scope_type"],
                        scope_key=r["scope_key"],
                        expected_account=r["expected_account"],
                        updated_by="csv_import",
                        reason=r["reason"]
                    )
                    account_count += 1
                elif r["type"] == "tax":
                    repo.upsert_tax_rule(
                        conn,
                        vendor_code=r["vendor_code"],
                        expected_tax=r["expected_tax"],
                        updated_by="csv_import",
                        reason=r["reason"]
                    )
                    tax_count += 1
                elif r["type"] == "ai_setting":
                    conn.execute("""
                        INSERT INTO masters_ai_setting (vendor_code, gemini_flag)
                        VALUES (?, ?)
                        ON CONFLICT(vendor_code) DO UPDATE SET
                           gemini_flag = excluded.gemini_flag,
                           updated_at = datetime('now', 'localtime')
                    """, (r["vendor_code"], r["gemini_flag"]))
                    ai_count += 1
            
            return {
                "status": "ok",
                "message": f"ルールを更新しました（科目: {account_count}件, 税区分: {tax_count}件, AI設定: {ai_count}件）",
                "account_count": account_count,
                "tax_count": tax_count,
                "ai_count": ai_count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/account-master/upload")
async def upload_account_master(
    file: UploadFile = File(...)
):
    """
    科目マスタCSVをアップロードして登録
    - 既存データはUpsert（上書き）
    """
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="CSVファイルを選択してください")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        accounts = list(load_account_master_csv(tmp_path))
        if not accounts:
            raise HTTPException(status_code=400, detail="有効な科目データが見つかりませんでした")
        
        with get_db() as conn:
            for acc in accounts:
                conn.execute(
                    """
                    INSERT INTO masters_account (account_code, account_name)
                    VALUES (?, ?)
                    ON CONFLICT(account_code) DO UPDATE SET
                        account_name = excluded.account_name
                    """,
                    (acc["account_code"], acc["account_name"])
                )
            
            cursor = conn.execute("SELECT COUNT(*) FROM masters_account")
            count = cursor.fetchone()[0]
            
            return {
                "status": "ok",
                "message": f"科目マスタを更新しました（{count}件）",
                "count": count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# --- 科目マスタ CRUD ---

class AccountMaster(BaseModel):
    account_code: str
    account_name: str

@router.get("/account-master")
async def list_account_master(q: str = ""):
    """科目マスタ一覧取得"""
    sql = "SELECT account_code, account_name FROM masters_account"
    params = []
    if q:
        sql += " WHERE account_code LIKE ? OR account_name LIKE ?"
        params = [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY account_code"
    
    with get_db() as conn:
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

@router.post("/account-master")
async def upsert_account_master(data: AccountMaster):
    """科目マスタ登録/更新"""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO masters_account (account_code, account_name)
            VALUES (?, ?)
            ON CONFLICT(account_code) DO UPDATE SET
                account_name = excluded.account_name
            """,
            (data.account_code, data.account_name)
        )
        return {"status": "ok", "message": "保存しました"}

@router.delete("/account-master/{code}")
async def delete_account_master(code: str):
    """科目マスタ削除"""
    with get_db() as conn:
        conn.execute("DELETE FROM masters_account WHERE account_code = ?", (code,))
        return {"status": "ok", "message": "削除しました"}


# ============================================================
# 例外部門マスタ（出力対象外）
# ============================================================

@router.get("/exception-dept")
async def list_exception_depts():
    """例外部門一覧を取得"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT dept_code, dept_name, reason FROM masters_exception_dept ORDER BY dept_code"
        )
        rows = cursor.fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/exception-dept/upload")
async def upload_exception_dept(
    file: UploadFile = File(...)
):
    """
    例外部門CSVをアップロード
    CSVフォーマット: 部門コード,部門名,除外理由
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        records = list(load_exception_dept_csv(tmp_path))
        
        if not records:
            return {"status": "error", "message": "データが見つかりませんでした"}
        
        with get_db() as conn:
            # 既存データを削除（全件洗い替え）
            conn.execute("DELETE FROM masters_exception_dept")
            
            count = 0
            for row in records:
                conn.execute(
                    """
                    INSERT INTO masters_exception_dept (dept_code, dept_name, reason)
                    VALUES (?, ?, ?)
                    """,
                    (normalize_dept_code(row["dept_code"]), row["dept_name"], row["reason"])
                )
                count += 1
            
            return {
                "status": "ok",
                "message": f"例外部門を登録しました（{count}件）",
                "count": count
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取込エラー: {str(e)}")
    
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class ExceptionDeptInput(BaseModel):
    """例外部門入力"""
    dept_code: str
    dept_name: str = ""
    reason: str = ""


@router.post("/exception-dept")
async def add_exception_dept(data: ExceptionDeptInput):
    """例外部門を追加"""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO masters_exception_dept (dept_code, dept_name, reason)
            VALUES (?, ?, ?)
            ON CONFLICT(dept_code) DO UPDATE SET
                dept_name = excluded.dept_name,
                reason = excluded.reason
            """,
            (normalize_dept_code(data.dept_code), data.dept_name, data.reason)
        )
        return {"status": "ok", "message": "登録しました"}


@router.delete("/exception-dept/{code}")
async def delete_exception_dept(code: str):
    """例外部門を削除"""
    with get_db() as conn:
        conn.execute("DELETE FROM masters_exception_dept WHERE dept_code = ?", (code,))
        return {"status": "ok", "message": "削除しました"}


# ============================================================
# AIモデル設定（手動管理）
# ============================================================

class AiSetting(BaseModel):
    vendor_code: str
    gemini_flag: str  # "1", "2", or ""

@router.get("/ai-setting")
async def list_ai_settings():
    """AIモデル設定一覧を取得"""
    with get_db() as conn:
        cursor = conn.execute("SELECT vendor_code, gemini_flag, updated_at FROM masters_ai_setting ORDER BY vendor_code")
        return [dict(r) for r in cursor.fetchall()]

@router.post("/ai-setting")
async def update_ai_setting(data: AiSetting):
    """AIモデル設定を更新（登録/削除）"""
    with get_db() as conn:
        if not data.gemini_flag:
            # フラグが空なら削除
            conn.execute("DELETE FROM masters_ai_setting WHERE vendor_code = ?", (data.vendor_code,))
            msg = "設定を解除しました"
        else:
            # Upsert
            conn.execute("""
                INSERT INTO masters_ai_setting (vendor_code, gemini_flag)
                VALUES (?, ?)
                ON CONFLICT(vendor_code) DO UPDATE SET
                   gemini_flag = excluded.gemini_flag,
                   updated_at = datetime('now', 'localtime')
            """, (data.vendor_code, data.gemini_flag))
            msg = "設定を保存しました"
            
        return {"status": "ok", "message": msg}


# ============================================================
# 取引先注意事項（ラベル管理 + 取引先紐付け）
# ============================================================

class NoteLabelCreate(BaseModel):
    label: str  # 5文字程度

class VendorNoteCreate(BaseModel):
    vendor_code: str
    label_id: int


@router.get("/note-labels")
async def list_note_labels():
    """注意事項ラベル一覧を取得"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, label FROM masters_note_labels ORDER BY id"
        )
        return [dict(r) for r in cursor.fetchall()]


@router.post("/note-labels")
async def create_note_label(data: NoteLabelCreate):
    """注意事項ラベルを新規追加"""
    label = data.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="ラベル名を入力してください")
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO masters_note_labels (label) VALUES (?)",
                (label,)
            )
            return {"status": "ok", "id": cursor.lastrowid, "label": label}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"既に同じラベルが存在します: {label}")


@router.delete("/note-labels/{label_id}")
async def delete_note_label(label_id: int):
    """注意事項ラベルを削除（紐付きも削除）"""
    with get_db() as conn:
        conn.execute("DELETE FROM masters_vendor_notes WHERE label_id = ?", (label_id,))
        conn.execute("DELETE FROM masters_note_labels WHERE id = ?", (label_id,))
        return {"status": "ok", "message": "削除しました"}


@router.get("/vendor-notes/{vendor_code}")
async def get_vendor_notes(vendor_code: str):
    """取引先に設定された注意事項を取得"""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT vn.id, vn.label_id, nl.label
            FROM masters_vendor_notes vn
            JOIN masters_note_labels nl ON nl.id = vn.label_id
            WHERE vn.vendor_code = ?
            ORDER BY vn.id
        """, (vendor_code,))
        return [dict(r) for r in cursor.fetchall()]


@router.post("/vendor-notes")
async def add_vendor_note(data: VendorNoteCreate):
    """取引先に注意事項ラベルを紐付け"""
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO masters_vendor_notes (vendor_code, label_id) VALUES (?, ?)",
                (data.vendor_code, data.label_id)
            )
            # ラベル名も返す
            row = conn.execute(
                "SELECT id, label FROM masters_note_labels WHERE id = ?", (data.label_id,)
            ).fetchone()
            return {
                "status": "ok",
                "id": cursor.lastrowid,
                "label_id": data.label_id,
                "label": row["label"] if row else ""
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail="既にこのラベルは設定済みです")


@router.delete("/vendor-notes/{note_id}")
async def delete_vendor_note(note_id: int):
    """取引先の注意事項紐付けを削除"""
    with get_db() as conn:
        conn.execute("DELETE FROM masters_vendor_notes WHERE id = ?", (note_id,))
        return {"status": "ok", "message": "削除しました"}
