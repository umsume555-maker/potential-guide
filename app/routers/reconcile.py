from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from typing import List
import shutil
from pathlib import Path
from datetime import datetime
import sqlite3

from features.vendor_invoice_reconcile.models import TemplateConfig, RunInfo
from features.vendor_invoice_reconcile.repositories.settings_repository import SettingsRepository
from infra.csv_loader import normalize_dept_code as _norm_dept_code
from features.vendor_invoice_reconcile.repositories.master_repository import MasterRepository
from features.vendor_invoice_reconcile.services.extractor import ExtractorFactory
from features.vendor_invoice_reconcile.services.matcher import DepartmentMatcher
from features.vendor_invoice_reconcile.services.reconciler import Reconciler
from features.vendor_invoice_reconcile.utils.excel_generator import ExcelGenerator
from infra.settings_repository import SettingsRepository as InfraSettingsRepo
from infra.database import get_db, DB_PATH, resolve_credentials_path

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])

settings_repo = SettingsRepository()
master_repo = MasterRepository()

@router.get("/vendors")
async def get_vendors():
    """テンプレート設定済みの取引先一覧を取得"""
    templates = settings_repo.load_all_templates()
    master_vendors = master_repo.get_vendor_master()
    
    result = []
    # テンプレートがある取引先
    for v_code, config in templates.items():
        result.append({
            "vendor_code": v_code,
            "vendor_name": config.vendor_name,
            "has_template": True,
            "file_type": config.file_type,
            "config": config.dict()
        })
    
    # テンプレートがない取引先も選択肢に出す（初期化用）
    for v_code, v_name in master_vendors.items():
        if v_code not in templates:
             result.append({
                "vendor_code": v_code,
                "vendor_name": v_name,
                "has_template": False,
                "file_type": None
            })
            
    # Sort by code
    return sorted(result, key=lambda x: x["vendor_code"])

@router.post("/init_template")
async def init_template(
    vendor_code: str = Form(...), 
    file_type: str = Form(...),
    dept_column: str = Form(None),
    amount_column: str = Form(None),
    header_row: int = Form(1)
):
    """テンプレート初期化"""
    vendor_master = master_repo.get_vendor_master()
    vendor_name = vendor_master.get(vendor_code, "Unknown Vendor")
    
    config = TemplateConfig(
        vendor_code=vendor_code,
        vendor_name=vendor_name,
        file_type=file_type,
        last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    # Set columns based on type
    if file_type == "excel":
        config.excel_dept_column = dept_column if dept_column else "事業所"
        config.excel_amount_column = amount_column if amount_column else "ご請求金額"
        config.excel_header_row = header_row
    elif file_type == "pdf":
        config.pdf_dept_column = dept_column
        config.pdf_amount_column = amount_column
    
    settings_repo.save_template(config)
    return {"status": "success", "message": f"Template initialized for {vendor_code}"}

@router.get("/departments")
async def get_departments():
    """部門マスタ一覧を取得"""
    depts = master_repo.get_department_master()
    # Sort by code
    return sorted([{"code": k, "name": v} for k, v in depts.items()], key=lambda x: x["code"])

@router.get("/synonyms/{vendor_code}")
async def get_synonyms(vendor_code: str):
    """取引先の全シノニム（紐付けルール）一覧を取得"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        return []
    result = []
    for raw_name, dept_codes in config.dept_synonyms.items():
        if isinstance(dept_codes, list):
            code1 = dept_codes[0] if len(dept_codes) > 0 else ""
            code2 = dept_codes[1] if len(dept_codes) > 1 else ""
        else:
            code1 = str(dept_codes)
            code2 = ""
        result.append({"raw_name": raw_name, "dept_code": code1, "dept_code_2": code2})
    return sorted(result, key=lambda x: x["raw_name"])

@router.delete("/synonyms/{vendor_code}")
async def delete_synonym(vendor_code: str, raw_name: str):
    """シノニム（紐付けルール）を削除"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        raise HTTPException(status_code=400, detail="Template not found")
    normalized = raw_name.replace('\u3000', ' ').strip()
    normalized = " ".join(normalized.split())
    if normalized in config.dept_synonyms:
        del config.dept_synonyms[normalized]
        settings_repo.save_template(config)
        return {"status": "success", "message": f"Deleted '{normalized}'"}
    raise HTTPException(status_code=404, detail="Synonym not found")

@router.post("/synonyms")
async def update_synonyms(
    vendor_code: str = Form(...),
    raw_name: str = Form(...),
    dept_code: str = Form(...),
    dept_code_2: str = Form(None)
):
    """シノニム（紐付けルール）を登録"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        raise HTTPException(status_code=400, detail="Template not found")
    
    # Normalize raw_name to match DepartmentMatcher logic
    # 全角スペースを半角にし、連続するスペースを1つにまとめる
    normalized_raw_name = raw_name.replace('\u3000', ' ').strip()
    normalized_raw_name = " ".join(normalized_raw_name.split())
    
    # Update synonyms
    if dept_code_2 and dept_code_2.strip():
        # Save as list if 2nd candidate exists
        config.dept_synonyms[normalized_raw_name] = [dept_code, dept_code_2]
        msg = f"Mapped '{normalized_raw_name}' to [{dept_code}, {dept_code_2}]"
    else:
        # Save as string (backward compatibility)
        config.dept_synonyms[normalized_raw_name] = dept_code
        msg = f"Mapped '{normalized_raw_name}' to {dept_code}"

    config.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    settings_repo.save_template(config)
    return {"status": "success", "message": msg}

@router.get("/excluded_depts/{vendor_code}")
async def get_excluded_depts(vendor_code: str):
    """取引先の除外部門一覧を取得"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        return []
    result = [
        {"dept_code": code, "reason": reason}
        for code, reason in config.excluded_dept_codes.items()
    ]
    return sorted(result, key=lambda x: x["dept_code"])


@router.post("/excluded_depts")
async def add_excluded_dept(
    vendor_code: str = Form(...),
    dept_code: str = Form(...),
    reason: str = Form("")
):
    """除外部門を追加"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        raise HTTPException(status_code=400, detail="Template not found")
    dept_code = dept_code.strip()
    if not dept_code:
        raise HTTPException(status_code=400, detail="部門コードが空です")
    config.excluded_dept_codes[dept_code] = reason.strip()
    config.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings_repo.save_template(config)
    return {"status": "success", "message": f"除外部門 {dept_code} を追加しました"}


@router.delete("/excluded_depts/{vendor_code}")
async def delete_excluded_dept(vendor_code: str, dept_code: str):
    """除外部門を削除"""
    config = settings_repo.get_template(vendor_code)
    if not config:
        raise HTTPException(status_code=400, detail="Template not found")
    dept_code = dept_code.strip()
    if dept_code in config.excluded_dept_codes:
        del config.excluded_dept_codes[dept_code]
        config.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        settings_repo.save_template(config)
        return {"status": "success", "message": f"除外部門 {dept_code} を削除しました"}
    raise HTTPException(status_code=404, detail="除外部門が見つかりません")


@router.post("/run")
def run_reconcile(
    base_month: str = Form(...),
    vendor_code: str = Form(...),
    files: List[UploadFile] = File(...)
):
    """突合実行"""
    import time
    import traceback
    start_time = time.time()
    
    def log_step(msg):
        elapsed = time.time() - start_time
        print(f"[RECONCILE DEBUG] {elapsed:.2f}s - {msg}")
    
    log_step("Start reconcile")
    
    try:
        # 1. Load Config
        config = settings_repo.get_template(vendor_code)
        if not config:
            raise HTTPException(status_code=400, detail="Template not found. Please initialize first.")
        log_step("Config loaded")

        # Validation: Check file extension
        for file in files:
            ext = Path(file.filename).suffix.lower()
            if config.file_type == "excel":
                if ext not in [".xlsx", ".xls", ".xlsm"]:
                    raise HTTPException(status_code=400, detail=f"ファイル形式エラー: 設定は 'Excel' ですが、誤った形式のファイル '{file.filename}' がアップロードされました。")
            elif config.file_type == "pdf":
                if ext != ".pdf":
                    raise HTTPException(status_code=400, detail=f"ファイル形式エラー: 設定は 'PDF' ですが、誤った形式のファイル '{file.filename}' がアップロードされました。")

        log_step("File validation passed")

        # 2. Save Uploaded Files Temporarily
        temp_dir = Path("tmp/reconcile_uploads")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        for file in files:
            file_path = temp_dir / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_files.append(str(file_path))
            log_step(f"Saved file: {file.filename}")

        # 3. Extract
        log_step("Starting extraction...")
        extractor = ExtractorFactory.get_extractor(config.file_type)
        all_records = []
        for file_path in saved_files:
            log_step(f"Extracting: {file_path}")
            records = extractor.extract(file_path, config)
            log_step(f"Extracted {len(records)} records from {file_path}")
            all_records.extend(records)
            
        if not all_records:
            raise HTTPException(status_code=400, detail="No records extracted from files.")

        # 4. Match
        log_step("Starting matching...")
        matcher = DepartmentMatcher(master_repo)
        matched_records = []
        unmapped_items = set()
        
        for rec in all_records:
            matched = matcher.match(rec, config)
            matched_records.append(matched)
            if not matched.mapped_dept_code:
                unmapped_items.add(matched.raw_dept_name)


        log_step(f"Matching complete: {len(matched_records)} records, {len(unmapped_items)} unmapped")

        # 5. Reconcile
        log_step("Starting reconciliation...")
        reconciler = Reconciler(master_repo)
        results = reconciler.reconcile(base_month, vendor_code, config.vendor_name, matched_records)
        log_step(f"Reconciliation complete: {len(results)} results")

        # 5b. 除外部門フィルタリング
        if config.excluded_dept_codes:
            before_count = len(results)
            results = [r for r in results if r.dept_code not in config.excluded_dept_codes]
            log_step(f"Excluded dept filter: {before_count} -> {len(results)} results")
        
        # 6. Generate Excel
        log_step("Generating Excel...")
        
        # Determine Run ID
        import uuid
        run_id = str(uuid.uuid4())[:8].upper()
        
        # Save to DB (run_log & output_summary) for Sync Sheet
        log_step(f"Saving to DB (RunID={run_id})...")
        with get_db() as conn:
            # run_log
            ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO run_log (run_id, base_month, started_at, ended_at, status, input_rows, output_rows, ng_count, hold_count, dash_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, base_month, datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"), ended_at, "completed", 
                  len(all_records), len(results), sum(1 for r in results if r.status != "OK"), 0, 0))
            
            # output_summary
            # Map ReconcileResult to Schema
            for res in results:
                # Map Status to Anomaly Type
                anomaly_type = ""
                if res.status == "MISSING": anomaly_type = "もれ"
                elif res.status == "DOUBLE_INPUT": anomaly_type = "二重入力？"
                elif res.status == "DATE_DIFF": anomaly_type = "取引日付ズレ？"
                elif res.status == "RECURRING_MISSING": anomaly_type = "毎月あるけど今月なし"
                elif res.status == "EXCESS": anomaly_type = "" # Hidden (OK)
                elif res.status == "DIFF": anomaly_type = "取引日付ズレ？"
                elif res.status == "UNMAPPED": anomaly_type = "マスタ未登録"
                elif res.status == "DATE_GAP": anomaly_type = "月ズレ？"
                
                # Base Invoice No (From Details or E2?)
                base_inv = ""
                if res.details:
                    base_inv = res.details[0].base_invoice_no
                
                # Insert
                conn.execute("""
                    INSERT INTO output_summary (
                        run_id, dept_code, dept_name, vendor_code, vendor_name,
                        payment_amount, ocr_amount, transaction_date, 
                        status, anomaly_type, base_invoice_no, is_monthly
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, _norm_dept_code(res.dept_code), res.dept_name, res.vendor_code, res.vendor_name,
                    res.payment_amount, res.invoice_amount, res.transaction_date,
                    res.status, anomaly_type, base_inv, res.is_monthly
                ))
            conn.commit()
            
        run_info = RunInfo(
            run_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            base_month=base_month,
            target_vendors=[vendor_code],
            input_files=[f.filename for f in files]
        )
        
        generator = ExcelGenerator()
        output_path = generator.generate(results, run_info)
        log_step(f"Excel generated: {output_path}")

        # Collect Mapped Items (Synonyms)
        mapped_items_map = {}
        for rec in matched_records:
            if rec.raw_dept_name in config.dept_synonyms:
                if rec.raw_dept_name not in mapped_items_map:
                    mapped_items_map[rec.raw_dept_name] = {
                        "raw_name": rec.raw_dept_name,
                        "candidate_codes": rec.candidate_dept_codes,
                        "mapped_code": rec.mapped_dept_code
                    }
        mapped_items_list = sorted(list(mapped_items_map.values()), key=lambda x: x["raw_name"])
        
        # 第2候補の部門名解決用マスタ
        _dept_master = master_repo.get_department_master()

        # Details for Sync
        details_list = []
        for r in results:
            if r.dept_code:
                # raw_dept_name: 請求書から抽出された元の事業所名表記
                raw_name = ""
                dept_code_2 = ""
                dept_name_2 = ""
                if r.details:
                    raw_name = r.details[0].raw_dept_name or ""
                    codes = r.details[0].candidate_dept_codes or []
                    if len(codes) >= 2:
                        dept_code_2 = codes[1]
                        dept_name_2 = _dept_master.get(dept_code_2, "")
                details_list.append({
                    "dept_code": r.dept_code,
                    "dept_name": r.dept_name,
                    "dept_code_2": dept_code_2,
                    "dept_name_2": dept_name_2,
                    "raw_dept_name": raw_name,
                    "vendor_code": r.vendor_code or vendor_code,
                    "vendor_name": r.vendor_name,
                    "invoice_amount": r.invoice_amount,
                    "e2_amount": r.payment_amount,
                    "transaction_date": getattr(r, "transaction_date", ""),
                    "status": r.status,
                    "diff_amount": "" if r.status == "RECURRING_MISSING" else r.diff_amount,
                    "anomaly_type": "二重入力？" if r.status == "DOUBLE_INPUT" else ("毎月あるけど今月なし" if r.status == "RECURRING_MISSING" else "")
                })
        
        # DEBUG: Check for Double Input in response
        di_count = sum(1 for d in details_list if d["status"] == "DOUBLE_INPUT")
        print(f"[DEBUG_RUN] details_list has {len(details_list)} items. DoubleInput count: {di_count}")
        if di_count > 0:
            for d in details_list:
                if d["status"] == "DOUBLE_INPUT":
                    print(f"[DEBUG_RUN]   -> DI Item: {d['dept_code']} {d['vendor_name']} {d['e2_amount']}")

        return {
            "status": "success", 
            "output_path": output_path,
            "filename": Path(output_path).name,
            "summary": {
                "extracted": len(all_records),
                "matched": sum(1 for r in matched_records if r.mapped_dept_code),
                "unmapped": len(unmapped_items),
                "reconciled_rows": len(results),
                "mapped_synonyms": len(mapped_items_list)
            },
            "unmapped_items": sorted(list(unmapped_items)),
            "mapped_items": mapped_items_list,
            "details": details_list
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        pass


@router.post("/sync_sheet")
async def sync_sheet(
    vendor_code: str = Form(...),
    base_month: str = Form(...),
    details: str = Form(...) # JSON string of list
):
    """
    スプレッドシート連携 (現場案内用)
    """
    from infra.spreadsheet_service_ext import SpreadsheetServiceExt
    import json
    import sqlite3
    
    # Load settings
    infra_repo = InfraSettingsRepo()
    with get_db() as conn:
        site_sheet_id = infra_repo.get_setting(conn, "site_sheet_id")
        site_dept_codes_str = infra_repo.get_setting(conn, "site_dept_codes")
        # 認証情報パスも取得（SpreadsheetServiceExtに渡すため）
        _stored_creds = infra_repo.get_setting(conn, "google_credentials_path")
    creds_path = str(resolve_credentials_path(_stored_creds)) if resolve_credentials_path(_stored_creds) else None
        
    if not site_sheet_id:
        raise HTTPException(status_code=400, detail="現場案内用スプレッドシートIDが設定されていません")
        
    if site_dept_codes_str:
        site_dept_codes = set(site_dept_codes_str.split(","))
    else:
        site_dept_codes = set()
    
    try:
        detail_list = json.loads(details)

        # 現在の取引先の除外部門リストを読み込み
        _vendor_config = settings_repo.get_template(vendor_code)
        _excluded_in_sync = set(_vendor_config.excluded_dept_codes.keys()) if _vendor_config and _vendor_config.excluded_dept_codes else set()
        if _excluded_in_sync:
            before_len = len(detail_list)
            detail_list = [item for item in detail_list if str(item.get("dept_code", "")).strip() not in _excluded_in_sync]
            print(f"[SYNC_DEBUG] Excluded dept filter: {before_len} -> {len(detail_list)} items")

        # ファイルベースのデバッグログ
        import pathlib
        debug_log = pathlib.Path("sync_debug.log")
        with open(debug_log, "w", encoding="utf-8") as f:
            f.write(f"sync_sheet received {len(detail_list)} items\n")
            for i, item in enumerate(detail_list):
                f.write(f"  item[{i}]: status={item.get('status','')}, anomaly_type={item.get('anomaly_type','')}, dept_code={item.get('dept_code','')}, tx_date={item.get('transaction_date', 'MISSING')}\n")
        
        print(f"[DEBUG] sync_sheet received {len(detail_list)} items from frontend")
        
        # === 「もれ」のみを抽出（現場シートに追記するため） ===
        more_rows = []
        
        for item in detail_list:
            d_code = str(item.get("dept_code", "")).strip()
            v_code = str(item.get("vendor_code", "")).strip()
            if not d_code: continue
            
            # ステータス判定
            anomaly_type = item.get("anomaly_type", "")
            status = item.get("status", "")
            
            print(f"[SYNC_DEBUG] item: dept={d_code}, status={status}, anomaly_type_in={anomaly_type}")
            
            if not anomaly_type:
                if status == "MISSING": 
                    anomaly_type = "もれ"
                elif status == "RECURRING_MISSING":
                    anomaly_type = "毎月あるけど今月なし"
                elif status == "DATE_GAP":
                    anomaly_type = "月ズレ？"
                elif status == "DOUBLE_INPUT":
                    anomaly_type = "二重入力？"
            
            print(f"[SYNC_DEBUG]   -> anomaly_type_out={anomaly_type}")
            
            # 「もれ」または「毎月あるけど今月なし」または「月ズレ？」以外はスキップ
            # 文字化け対策: statusコードでも判定する
            allowed_statuses = ["MISSING", "RECURRING_MISSING", "DATE_GAP", "DOUBLE_INPUT"]
            allowed_types = ["もれ", "毎月あるけど今月なし", "月ズレ？", "取引日付ズレ？", "二重入力？"]
            
            is_target = False
            if status in allowed_statuses:
                is_target = True
            elif anomaly_type in allowed_types:
                is_target = True
                
            if not is_target:
                print(f"[SYNC_DEBUG]   -> SKIPPED (not in allowed list)")
                continue

            # 「もれ」かつ金額0円はスキップ
            if status == "MISSING" or anomaly_type == "もれ":
                inv_amt_check = item.get("invoice_amount", 0)
                try:
                    inv_amt_check = int(float(inv_amt_check))
                except:
                    inv_amt_check = 0
                if inv_amt_check == 0:
                    print(f"[SYNC_DEBUG]   -> SKIPPED (もれ 0円)")
                    continue

            print(f"[SYNC_DEBUG]   -> ACCEPTED")
            
            # 金額判定: ステータスに応じて参照する金額を変える
            # MISSING -> Invoice Amount (OCR)
            # DOUBLE_INPUT, DATE_GAP -> E2 Amount (DB Payment Amount)
            # RECURRING_MISSING -> 0
            
            amt = 0
            if status == "MISSING":
                inv_amt = item.get("invoice_amount", 0)
                try: amt = int(float(inv_amt))
                except: amt = 0
            elif status in ["DOUBLE_INPUT", "DATE_GAP", "DATE_DIFF", "月ズレ？", "二重入力？"]:
                # DB側の金額を採用
                e2_amt = item.get("e2_amount", 0)
                try: amt = int(float(e2_amt))
                except: amt = 0
                
                # もしe2_amountが0で、invoice_amountがある場合（稀なケース）はfallback
                if amt == 0:
                    inv_amt = item.get("invoice_amount", 0)
                    try: amt = int(float(inv_amt))
                    except: pass
            
            
            # Transaction Date: Use provided date for DATE_GAP/DOUBLE_INPUT as evidence
            tx_date = ""
            if status in ["DATE_GAP", "DOUBLE_INPUT"]:
                 tx_date = item.get("transaction_date", "")
            
            row = {
                "dept_code": d_code,
                "dept_name": item.get("dept_name", ""),
                "vendor_code": v_code,
                "vendor_name": item.get("vendor_name", ""),
                "payment_amount": amt, 
                "transaction_date": tx_date,
                "anomaly_type": anomaly_type,
                "status": status
            }
            more_rows.append(row)
        
        # 2. Add Recurring Missing for ALL Target Vendors
        # User requested to include all "Recurring Missing" items even if not in current view
        try:
            with get_db() as conn:
                targets = conn.execute("SELECT vendor_code, vendor_name FROM vendor_reconciliation_target").fetchall()
                target_vendors = {r["vendor_code"]: r["vendor_name"] for r in targets}

            for t_vcode, t_vname in target_vendors.items():
                monthly_items = _calculate_monthly_status(t_vcode, base_month)
                # 除外部門を除く
                t_config = settings_repo.get_template(t_vcode)
                t_excluded = set(t_config.excluded_dept_codes.keys()) if t_config and t_config.excluded_dept_codes else set()
                for m_item in monthly_items:
                    if m_item["dept_code"] in t_excluded:
                        continue
                    # Only RECURRING_MISSING
                    # Or if (is_monthly="毎月") and (status is empty/missing) -> Implicitly RECURRING_MISSING
                    is_missing = False
                    if m_item["status"] == "RECURRING_MISSING":
                        is_missing = True
                    elif m_item["is_monthly"] == "毎月" and not m_item["status"]:
                        # No record found for this monthly dept -> Missing
                        is_missing = True
                    
                    if is_missing:
                         row = {
                            "dept_code": m_item["dept_code"],
                            "dept_name": m_item["dept_name"],
                            "vendor_code": m_item["vendor_code"],
                            "vendor_name": t_vname, 
                            "payment_amount": m_item["payment_amount"], 
                            "transaction_date": "",
                            "anomaly_type": "毎月あるけど今月なし",
                            "status": "RECURRING_MISSING"
                        }
                         more_rows.append(row)
        except Exception as e:
            print(f"[WARN] Failed to add all target vendors monthly status: {e}")
            import traceback
            traceback.print_exc()

        print(f"[SYNC_DEBUG] Total rows to merge: {len(more_rows)}")
        
        if not more_rows:
            return {
                "status": "success",
                "message": "「もれ」データがないため、シート更新はスキップしました。",
                "details": {"rows_written": 0}
            }
        
        # ソート: 部門コード > 取引先コード
        more_rows.sort(key=lambda x: (x["dept_code"], x["vendor_code"]))
        
        # マージモードでシート更新（既存データを維持し、「もれ」行を追記）
        if not creds_path:
            raise HTTPException(status_code=400, detail="認証ファイル(credentials.json)が見つかりません。data/credentials.json に配置するか、設定タブからアップロードしてください。")
        
        service = SpreadsheetServiceExt(credentials_path=creds_path)
        
        print(f"[SYNC_DEBUG] credentials_path={creds_path}")
        print(f"[SYNC_DEBUG] site_sheet_id={site_sheet_id}")
        print(f"[SYNC_DEBUG] more_rows count={len(more_rows)}")
        for i, row in enumerate(more_rows[:5]):
            print(f"[SYNC_DEBUG]   row[{i}]: dept={row['dept_code']}, vendor={row['vendor_code']}, amt={row['payment_amount']}, anomaly={row['anomaly_type']}, status={row['status']}")
        
        result = service.sync_site_sheet(
            db_path=str(DB_PATH),
            run_id="RECONCILE_MERGE", 
            site_sheet_id=site_sheet_id,
            site_dept_codes=[],
            site_rows=more_rows,
            merge_mode=True
        )
        
        print(f"[DEBUG] sync_site_sheet result: {result}")
        
        # エラーチェック: sync_site_sheetが失敗した場合はユーザーに通知
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"シート更新エラー: {result.get('error', '不明なエラー')}")
        
        if result.get("status") == "skipped":
            return {
                "status": "success",
                "message": f"シート更新スキップ: {result.get('reason', '')}",
                "details": result
            }
        
        return {
            "status": "success",
            "message": f"「もれ」{result.get('rows_written', 0)}件を現場シートに追記しました",
            "details": result
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
async def download_result(filename: str):
    """結果Excelのダウンロード"""
    file_path = Path("output/reconcile") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path, 
        filename=filename, 
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

def _calculate_monthly_status(vendor_code: str, base_month: str):
    from features.vendor_invoice_reconcile.repositories.master_repository import MasterRepository
    from infra.database import get_db
    
    try:
        repo = MasterRepository()
        
        # 1. 過去実績のある全事業所を取得
        depts = repo.get_vendor_departments(vendor_code)
        if not depts:
            return []
            
        # 2. 毎月判定 (過去4ヶ月)
        y, m = map(int, base_month.split("-"))
        past_months = []
        for i in range(1, 5):
            pm = m - i
            py = y
            while pm <= 0:
                pm += 12
                py -= 1
            past_months.append(f"{py:04d}-{pm:02d}")
            
        from infra.csv_loader import normalize_dept_code as _norm_dc

        # 部門コードを8桁正規化して累積/output_summary間の桁数差異を吸収
        dept_codes = [_norm_dc(d["dept_code"]) for d in depts]
        dc_orig_map = {_norm_dc(d["dept_code"]): d for d in depts}

        monthly_flags = {dc: False for dc in dept_codes}
        history_counts = {dc: 0 for dc in dept_codes}

        for pm in past_months:
            rows = repo.get_cumulative_data(pm, [vendor_code])
            seen_depts = set(_norm_dc(r["dept_code"]) for r in rows)
            for dc in seen_depts:
                if dc in history_counts:
                    history_counts[dc] += 1
                    
        for dc, count in history_counts.items():
            if count >= 3:
                monthly_flags[dc] = True
                
        # 3. 当月実績 (Current Amount)
        current_amounts = {}
        current_statuses = {}
        
        with get_db() as conn:
            # 各(vendor, dept_code)について最新runの値のみ使用する
            # 古いrunの結果が残り続けるのを防ぐため、vendor_codeごとの最新run_idを特定する
            latest_run = conn.execute("""
                SELECT run_id FROM run_log
                WHERE base_month = ? AND input_rows < 150
                  AND run_id IN (
                      SELECT DISTINCT run_id FROM output_summary WHERE vendor_code = ?
                  )
                ORDER BY started_at DESC LIMIT 1
            """, (base_month, vendor_code)).fetchone()

            if latest_run:
                latest_run_id = latest_run[0]
                rows = conn.execute("""
                    SELECT dept_code, payment_amount, status
                    FROM output_summary
                    WHERE vendor_code = ? AND run_id = ?
                """, (vendor_code, latest_run_id)).fetchall()
                for r in rows:
                    dc_norm = _norm_dc(r["dept_code"])
                    current_amounts[dc_norm] = r["payment_amount"]
                    current_statuses[dc_norm] = r["status"]

        # 3b. 除外部門フィルタリング
        excluded_dept_set = set()
        try:
            _cfg = settings_repo.get_template(vendor_code)
            if _cfg and _cfg.excluded_dept_codes:
                excluded_dept_set = set(_cfg.excluded_dept_codes.keys())
        except Exception:
            pass

        # 4. Build Result
        result = []
        for dc in dept_codes:
            if dc in excluded_dept_set:
                continue
            d = dc_orig_map.get(dc, {})
            dn = d.get("dept_name", "")
            is_monthly = "毎月" if monthly_flags.get(dc) else ""
            amt = current_amounts.get(dc, 0)

            status = current_statuses.get(dc, "")
            
            # Skip if 0 amount AND no significant status
            try:
                val = float(str(amt).replace(',', ''))
                if val == 0:
                    # Allow if status indicates an anomaly (Missing, Gap, etc.)
                    if status not in ["RECURRING_MISSING", "MISSING", "DATE_GAP", "DATE_DIFF", "UNMAPPED"]:
                        continue
            except (ValueError, TypeError):
                if status not in ["RECURRING_MISSING", "MISSING", "DATE_GAP", "DATE_DIFF", "UNMAPPED"]:
                     continue
            
            result.append({
                "dept_code": dc,  # 正規化済み8桁コード
                "dept_name": dn,
                "is_monthly": is_monthly,
                "payment_amount": amt,
                "status": status,
                "vendor_code": vendor_code,
            })
            
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return []

@router.get("/monthly_status")
def get_monthly_status(vendor_code: str, base_month: str):
    """
    指定取引先の事業所別請求状況を取得（画面表示用）
    """
    return _calculate_monthly_status(vendor_code, base_month)


@router.get("/target_vendors")
def get_target_vendors():
    with get_db() as conn:
        try:
            return [dict(row) for row in conn.execute("SELECT * FROM vendor_reconciliation_target ORDER BY vendor_code").fetchall()]
        except sqlite3.OperationalError:
            # Lazy migration: Create table if not exists
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                        vendor_code TEXT PRIMARY KEY,
                        vendor_name TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                return []
            except Exception:
                return []

@router.post("/target_vendors")
def add_target_vendor(vendor_code: str = Form(...), vendor_name: str = Form(...)):
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO vendor_reconciliation_target (vendor_code, vendor_name) VALUES (?, ?)", 
                         (vendor_code, vendor_name))
            conn.commit()
            return {"status": "success"}
        except sqlite3.OperationalError:
            # Lazy migration
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                    vendor_code TEXT PRIMARY KEY,
                    vendor_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            # Retry insert
            try:
                conn.execute("INSERT INTO vendor_reconciliation_target (vendor_code, vendor_name) VALUES (?, ?)", 
                             (vendor_code, vendor_name))
                conn.commit()
                return {"status": "success"}
            except sqlite3.IntegrityError as e:
                return {"status": "error", "detail": str(e)}
        except sqlite3.IntegrityError as e:
             return {"status": "error", "detail": str(e)}

@router.get("/fix_db")
def fix_db_schema():
    """
    DBスキーマの修正を強制実行（デバッグ用）
    """
    from infra.database import get_db
    import sqlite3
    
    log = []
    try:
        with get_db() as conn:
            # 1. vendor_reconciliation_target
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                        vendor_code TEXT PRIMARY KEY,
                        vendor_name TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                log.append("Created table: vendor_reconciliation_target")
            except Exception as e:
                log.append(f"Error creating table: {e}")

            # 2. is_monthly column
            try:
                cursor = conn.execute("PRAGMA table_info(output_summary)")
                columns = [row[1] for row in cursor.fetchall()]
                if "is_monthly" not in columns:
                    conn.execute("ALTER TABLE output_summary ADD COLUMN is_monthly TEXT")
                    log.append("Added column: is_monthly")
                else:
                    log.append("Column is_monthly already exists")
            except Exception as e:
                log.append(f"Error adding column: {e}")
                
            conn.commit()
            return {"status": "success", "log": log}
    except Exception as e:
        return {"status": "error", "message": str(e), "log": log}
@router.delete("/target_vendors/{vendor_code}")
def delete_target_vendor(vendor_code: str):
    with get_db() as conn:
        try:
            conn.execute("DELETE FROM vendor_reconciliation_target WHERE vendor_code = ?", (vendor_code,))
            conn.commit()
            return {"status": "success"}
        except sqlite3.OperationalError:
            # Lazy migration (create table if missing, though delete will result in 0 rows anyway)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
                    vendor_code TEXT PRIMARY KEY,
                    vendor_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            return {"status": "success"}

