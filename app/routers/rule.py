"""
正マスター（税区分・科目ルール・強制修正）管理API
"""
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from infra.database import get_db
from infra.rule_repository import RuleRepository

router = APIRouter(prefix="/api/rules", tags=["rules"])
repo = RuleRepository()

# --- リクエストモデル ---

class TaxRuleUpsert(BaseModel):
    vendor_code: str
    expected_tax: str
    update_reason: str
    updated_by: Optional[str] = "user"

class AccountRuleUpsert(BaseModel):
    vendor_code: str
    scope_type: str  # DEPT / DEPT_TYPE / ANY
    scope_key: Optional[str] = ""
    expected_account: str
    update_reason: str
    updated_by: Optional[str] = "user"

class OverrideUpsert(BaseModel):
    vendor_code: str
    dept_code: Optional[str] = ""
    field_name: str
    new_value: str
    reason: str
    updated_by: Optional[str] = "user"

# --- レスポンスモデル ---

# 検索結果用（簡略化）
class TaxRuleResponse(BaseModel):
    vendor_code: str
    vendor_name: Optional[str] = None
    expected_tax: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None
    cost_account: Optional[str] = None
    cost_account_name: Optional[str] = None
    sga_account: Optional[str] = None
    sga_account_name: Optional[str] = None
    expected_account: Optional[str] = None
    expected_account_name: Optional[str] = None

class AccountRuleResponse(BaseModel):
    vendor_code: str
    vendor_name: Optional[str] = None
    scope_type: str
    scope_key: Optional[str] = None
    expected_account: str
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None

# --- エンドポイント ---

# 1. 税区分ルール

@router.get("/tax", response_model=List[TaxRuleResponse])
async def search_tax_rules(q: str = ""):
    """税区分ルールを検索"""
    with get_db() as conn:
        results = repo.search_tax_rules(conn, q)
        return results

@router.post("/tax")
async def upsert_tax_rule(data: TaxRuleUpsert):
    """税区分ルールを登録・更新"""
    try:
        with get_db() as conn:
            repo.upsert_tax_rule(
                conn,
                vendor_code=data.vendor_code,
                expected_tax=data.expected_tax,
                updated_by=data.updated_by,
                reason=data.update_reason
            )
        return {"status": "ok", "message": "税区分ルールを保存しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/tax/{vendor_code}")
async def delete_tax_rule(vendor_code: str):
    """税区分ルールを削除"""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM rule_tax_master WHERE vendor_code = ?", (vendor_code,))
        return {"status": "ok", "message": "税区分ルールを削除しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. 科目ルール

@router.get("/account", response_model=List[AccountRuleResponse])
async def search_account_rules(q: str = ""):
    """科目ルールを検索"""
    with get_db() as conn:
        results = repo.search_account_rules(conn, q)
        return results

@router.post("/account")
async def upsert_account_rule(data: AccountRuleUpsert):
    """科目ルールを登録・更新"""
    try:
        with get_db() as conn:
            repo.upsert_account_rule(
                conn,
                vendor_code=data.vendor_code,
                scope_type=data.scope_type,
                scope_key=data.scope_key,
                expected_account=data.expected_account,
                updated_by=data.updated_by,
                reason=data.update_reason
            )
        return {"status": "ok", "message": "科目ルールを保存しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/account")
async def delete_account_rule(vendor_code: str, scope_type: str, scope_key: str = ""):
    """科目ルールを削除"""
    try:
        with get_db() as conn:
            repo.delete_account_rule(conn, vendor_code, scope_type, scope_key)
        return {"status": "ok", "message": "科目ルールを削除しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. 強制修正 (Override)

@router.post("/override")
async def upsert_override(data: OverrideUpsert):
    """強制修正を登録"""
    try:
        with get_db() as conn:
            repo.upsert_override(
                conn,
                vendor_code=data.vendor_code,
                dept_code=data.dept_code or "",
                field_name=data.field_name,
                new_value=data.new_value,
                reason=data.reason,
                updated_by=data.updated_by
            )
        return {"status": "ok", "message": "強制修正を保存しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 5. Tax Rule Exceptions (New)

class TaxRuleExceptionRequest(BaseModel):
    vendor_code: str
    scope_type: str
    scope_key: Optional[str] = None
    expected_tax: str
    reason: Optional[str] = None
    updated_by: str = "user"

@router.get("/tax_rules/{vendor_code}")
async def get_tax_rule_exceptions(vendor_code: str):
    """税区分例外ルール取得"""
    with get_db() as conn:
        return repo.get_tax_rule_exceptions(conn, vendor_code)

@router.post("/tax_rules")
async def save_tax_rule_exception(data: TaxRuleExceptionRequest):
    """税区分例外ルール保存"""
    try:
        with get_db() as conn:
            repo.upsert_tax_rule_exception(
                conn, 
                data.vendor_code, 
                data.scope_type, 
                data.scope_key, 
                data.expected_tax, 
                data.updated_by, 
                data.reason
            )
        return {"status": "ok", "message": "税区分例外ルールを保存しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/tax_rules/{rule_id}")
async def delete_tax_rule_exception(rule_id: int):
    """税区分例外ルール削除"""
    try:
        with get_db() as conn:
            repo.delete_tax_rule_exception(conn, rule_id)
        return {"status": "ok", "message": "削除しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 6. 統計

@router.get("/stats")
async def get_stats():
    """統計情報を取得"""
    with get_db() as conn:
        # 簡易的にTaxルールの統計を返す（本来は全統計）
        return repo.get_stats(conn)
