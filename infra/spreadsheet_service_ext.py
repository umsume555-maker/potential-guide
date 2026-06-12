import sqlite3
import gspread
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from infra.retry_utils import call_with_retry
from infra.spreadsheet_service import SpreadsheetService

class SpreadsheetServiceExt:
    """拡張スプレッドシートサービス（突合用）"""
    
    def __init__(self, credentials_path: str = None):
        if credentials_path:
            self.credentials_path = Path(credentials_path)
        else:
            # Default path
            self.credentials_path = Path(__file__).parent.parent / "data" / "credentials.json"
    def authenticate(self) -> gspread.Client:
        return SpreadsheetService(str(self.credentials_path)).authenticate()

    def sync_site_sheet(self, db_path: str, run_id: str, site_sheet_id: str, site_dept_codes: List[str], overrides: Dict[tuple, str] = None, site_rows: List[Dict] = None, merge_mode: bool = False) -> Dict[str, str]:
        """
        現場用スプレッドシートを更新する
        
        Args:
            overrides: (dept_code, vendor_code) -> "ズレ" などの強制ステータス辞書
            site_rows: DB検索の代わりに直接書き込むデータリスト (Sync from Reconcile PDF)
        """
        log = {"updated": False}
        if overrides is None:
            overrides = {}
        
        # site_rowsがある場合はdept_codesチェックを緩和（rowsに含まれているため）
        if not site_sheet_id:
            log["status"] = "skipped"
            log["reason"] = "Settings not configured"
            return log

        # URLからID抽出
        import re
        if "google.com" in site_sheet_id or "/" in site_sheet_id:
            match = re.search(r"/d/([a-zA-Z0-9-_]+)", site_sheet_id)
            if match:
                site_sheet_id = match.group(1)

        try:
            import time as _t
            _client = None
            for _attempt in range(3):
                try:
                    _client = self.authenticate()
                    sh = call_with_retry(_client.open_by_key, site_sheet_id, max_retries=3, delay=5.0)
                    sheet = sh.sheet1
                    break
                except (ConnectionError, ConnectionResetError, OSError) as _ce:
                    if _attempt < 2:
                        print(f"[WARN] Ext sheet 接続失敗 (attempt {_attempt+1}/3): {_ce} — 5秒後リトライ...")
                        _t.sleep(5)
                    else:
                        raise
            
            # --- 1. データ取得 & フィルタリング ---
            if site_rows is not None:
                # 直接渡されたデータを使用
                db_rows = site_rows
                log["source"] = "direct"
            else:
                # DBから取得
                if not site_dept_codes:
                     log["status"] = "skipped"
                     log["reason"] = "No dept codes specified"
                     return log
                db_rows = self._fetch_site_data(db_path, run_id, site_dept_codes)
                log["source"] = "db"
                
            # --- 実行時の除外フィルタリング (Python側で強制) ---
            try:
                with sqlite3.connect(db_path) as conn:
                    # 例外部門リスト取得
                    ex_cursor = conn.execute("SELECT dept_code FROM masters_exception_dept")
                    ex_depts = set()
                    for r in ex_cursor.fetchall():
                        code = str(r[0]).strip()
                        if code.isdigit():
                            ex_depts.add(f"{int(code):08d}")
                        else:
                            ex_depts.add(code)
                
                filtered_rows = []
                for row in db_rows:
                    try:
                        # rowは辞書型またはRow型を想定
                        d_code = row.get("dept_code") if isinstance(row, dict) else row["dept_code"]
                        dept_code_str = str(d_code).strip()
                        if dept_code_str.isdigit():
                            dept_code_str = f"{int(dept_code_str):08d}"
                            
                        if dept_code_str in ex_depts:
                            continue
                        filtered_rows.append(row)
                    except:
                        filtered_rows.append(row)
                
                db_rows = filtered_rows
                
            except Exception as e:
                print(f"[WARN] Failed to filter exception depts in Ext: {e}")

            log["rows_filtered"] = len(db_rows)
            
            if not db_rows and not overrides:
                log["status"] = "skipped"
                log["reason"] = "No matching data found"
                return log

            # --- 2. 既存データ取得 (Header + Body) ---
            # site_status, site_comment を引き継ぐため
            all_values = sheet.get_all_values()
            existing_header = all_values[0] if all_values else []
            existing_rows = all_values[1:] if len(all_values) > 1 else []
            
            # 必須カラム定義（順序固定・半角カナ統一）
            # チェック実行タブ(spreadsheet_service.py)と同じヘッダー名を使用
            CORE_HEADERS = [
                "ｽﾃｰﾀｽ", "ｺﾒﾝﾄ", "区分", 
                "部門ｺｰﾄﾞ", "部門名", "取引先ｺｰﾄﾞ", "取引先名",
                "取引日付", "支払金額"
            ]
            
            # ヘッダー同期
            col_map = {name: idx for idx, name in enumerate(existing_header)}
            
            # 既存データのマップ化（照合用）
            map_key_a = {}
            map_key_b = {}
            
            # 既存データのインデックス特定 (半角カナ優先、全角フォールバック)
            idx_status = col_map.get("ｽﾃｰﾀｽ", col_map.get("ステータス", -1))
            idx_comment = col_map.get("ｺﾒﾝﾄ", col_map.get("コメント", -1))
            idx_dept = col_map.get("部門ｺｰﾄﾞ", col_map.get("部門コード", -1))
            idx_vendor = col_map.get("取引先ｺｰﾄﾞ", col_map.get("取引先コード", -1))
            idx_vendor_name = col_map.get("取引先名", -1)
            idx_amount = col_map.get("支払金額", -1)
            
            for i, row in enumerate(existing_rows):
                if idx_dept >= 0 and idx_vendor >= 0 and len(row) > max(idx_dept, idx_vendor):
                    d_code = str(row[idx_dept]).strip()
                    v_code = str(row[idx_vendor]).strip()
                    key_a = (d_code, v_code)
                    if key_a not in map_key_a: map_key_a[key_a] = []
                    map_key_a[key_a].append(i)
                    
                    if idx_amount >= 0 and len(row) > idx_amount:
                        amt = str(row[idx_amount]).strip().replace(",", "")
                        try:
                            # 金額表記の揺れを吸収するため一度int化
                            amt_int = int(float(amt))
                        except:
                            amt_int = amt
                        key_b = (d_code, v_code, str(amt_int))
                        if key_b not in map_key_b: map_key_b[key_b] = []
                        map_key_b[key_b].append(i)

            # --- 3. 新しい出力データの作成 ---
            new_rows = []
            validations = [] # 各行のValidationルール
            
            preserved_count = 0
            cleared_count = 0
            
            for db_row in db_rows:
                # 照合ロジック
                d_code = str(db_row["dept_code"]).strip()
                v_code = str(db_row["vendor_code"]).strip()
                amt = db_row["payment_amount"]
                
                status_val = ""
                comment_val = ""
                
                match_idx = -1
                
                # 1) Key B 検索 (Dept, Vendor, Amount) - Strict Match
                # 金額も含めて一致する場合のみ、ステータスを引き継ぐ
                candidates_b = map_key_b.get((d_code, v_code, str(amt)), [])
                if len(candidates_b) >= 1:
                    match_idx = candidates_b[0]
                else:
                    match_idx = -1 # Amount mismatch or new item -> Reset status
                
                if match_idx >= 0:
                    # 引継ぎ
                    old_row = existing_rows[match_idx]
                    if idx_status >= 0 and len(old_row) > idx_status:
                        status_val = old_row[idx_status]
                    if idx_comment >= 0 and len(old_row) > idx_comment:
                        comment_val = old_row[idx_comment]
                    preserved_count += 1
                elif match_idx == -2:
                    cleared_count += 1
                
                # 種別によるValidationチェック
                kind = db_row["anomaly_type"]
                
                # Override Check
                if (d_code, v_code) in overrides:
                    override_kind = overrides[(d_code, v_code)]
                    # 優先順位: Override > 既存の判定
                    kind = override_kind
                
                # kindが空の場合は適当なデフォルトにするか、空のまま
                if not kind: kind = ""
                
                options = self._get_validation_options(kind)
                
                # 引継いだStatusが選択肢になければクリア
                if status_val and options and status_val not in options:
                    status_val = ""
                
                # Fix None vendor_name and recurring missing amount
                v_name = db_row["vendor_name"] or ""
                if str(v_name) == "None":
                    v_name = ""
                
                final_amt = amt
                # 文字化け対策も含めて部分一致で判定 + Status check
                status_check = db_row.get("status", "")
                if "毎月" in str(kind) or status_check == "RECURRING_MISSING":
                    final_amt = ""

                # 部門コード補正: 8桁ゼロ埋め & 文字列化
                if d_code and d_code.isdigit():
                    d_code = f"{int(d_code):08d}"
                d_code_str = f"'{d_code}" if d_code and d_code.isdigit() else d_code

                # 取引先コード文字列化
                v_code_str = f"'{v_code}" if v_code and v_code.isdigit() else v_code

                # 行データの構築 (CORE_HEADERS順)
                new_row = [
                    status_val,
                    comment_val,
                    kind,
                    d_code_str,
                    db_row["dept_name"],
                    v_code_str,
                    v_name,
                    # db_row.get("is_monthly", ""), # Removed
                    db_row["transaction_date"],
                    final_amt
                ]
                new_rows.append(new_row)
                validations.append({"kind": kind, "options": options})

            # --- 4. 書き込み ---
            final_header = CORE_HEADERS
            
            if merge_mode:
                # === マージモード: 既存データを維持し、新規行を末尾に追記 ===
                # 重複チェック: (dept_code, vendor_code, amount, vendor_name, transaction_date)
                existing_keys = set()
                idx_date = col_map.get("取引日付", -1)
                idx_kind = col_map.get("区分", col_map.get("種別", -1))
                
                for row in existing_rows:
                    if idx_dept >= 0 and idx_vendor >= 0 and idx_amount >= 0 and len(row) > max(idx_dept, idx_vendor, idx_amount):
                        d = str(row[idx_dept]).strip()
                        # Normalize d
                        d_norm = d.replace("'", "")
                        if d_norm.isdigit(): d_norm = f"{int(d_norm):08d}"
                        
                        v = str(row[idx_vendor]).strip()
                        # Normalize v
                        v_norm = v.replace("'", "")
                        if v_norm.isdigit(): v_norm = str(int(v_norm))
                        
                        a = str(row[idx_amount]).strip().replace(",", "")
                        try:
                            a = str(int(float(a)))
                        except:
                            pass
                        
                        # 取引先名も含める
                        n = ""
                        if idx_vendor_name >= 0 and len(row) > idx_vendor_name:
                             n = str(row[idx_vendor_name]).strip()
                             
                        # 取引日付も含める
                        dt = ""
                        if idx_date >= 0 and len(row) > idx_date:
                            dt = str(row[idx_date]).strip()
                            
                        # 種別/区分も含める (Kind)
                        k = ""
                        if idx_kind >= 0 and len(row) > idx_kind:
                            k = str(row[idx_kind]).strip()
                        
                        key = (d_norm, v_norm, a, n, dt, k)
                        existing_keys.add(key)
                
                append_rows = []
                skipped = 0
                for new_row in new_rows:
                    # new_row は CORE_HEADERS 順
                    # 0:Status, 1:Comment, 2:Kind, 3:DeptCode, 4:DeptName, 5:VendorCode, 6:VendorName, 7:Date, 8:Amount
                    d = str(new_row[3]).strip()
                    # Normalize d
                    d_norm = d.replace("'", "")
                    if d_norm.isdigit(): d_norm = f"{int(d_norm):08d}"

                    v = str(new_row[5]).strip()
                    # Normalize v
                    v_norm = v.replace("'", "")
                    if v_norm.isdigit(): v_norm = str(int(v_norm))

                    n = str(new_row[6]).strip()
                    dt = str(new_row[7]).strip()
                    k = str(new_row[2]).strip()
                    
                    # Old index 9 -> New index 8
                    a = str(new_row[8]).strip().replace(",", "")
                    try:
                        a = str(int(float(a)))
                    except:
                        pass
                    
                    key = (d_norm, v_norm, a, n, dt, k)
                    
                    if key in existing_keys:
                        skipped += 1
                        continue
                    append_rows.append(new_row)
                    existing_keys.add(key)
                
                if append_rows:
                    # ヘッダーがなければ先にヘッダーを書く
                    if not existing_header:
                        sheet.update([final_header] + append_rows)
                        merge_start_row_idx = 1  # 0-indexed (header=0, data starts at 1)
                    else:
                        # 既存データの末尾に追記
                        start_row = len(all_values) + 1
                        needed_rows = start_row + len(append_rows)
                        
                        try:
                            # 行数が足りない場合は拡張
                            if sheet.row_count < needed_rows:
                                print(f"[DEBUG] Resizing sheet from {sheet.row_count} to {needed_rows}")
                                sheet.resize(rows=needed_rows)
                        except Exception as e:
                            print(f"[WARN] Failed to resize sheet: {e}")

                        sheet.update(append_rows, f"A{start_row}")
                        merge_start_row_idx = len(all_values)  # 0-indexed
                    
                    # 追記行にもDataValidation(プルダウン)を適用
                    merge_validations = []
                    for row_data in append_rows:
                        kind = row_data[2]  # CORE_HEADERS[2] = 種別
                        options = self._get_validation_options(kind)
                        merge_validations.append({"kind": kind, "options": options})
                    
                    if merge_validations:
                        requests = []
                        for i, val in enumerate(merge_validations):
                            row_idx = merge_start_row_idx + i
                            options = val["options"]
                            if options:
                                condition = {
                                    "type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": opt} for opt in options]
                                }
                                rule_def = {
                                    "condition": condition,
                                    "showCustomUi": True,
                                    "strict": True
                                }
                                requests.append({"setDataValidation": {
                                    "range": {
                                        "sheetId": sheet.id,
                                        "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                                        "startColumnIndex": 0, "endColumnIndex": 1
                                    },
                                    "rule": rule_def
                                }})
                        if requests:
                            sh.batch_update({"requests": requests})
                
                log.update({
                    "updated": True,
                    "rows_written": len(append_rows),
                    "rows_skipped_dup": skipped,
                    "fields_preserved": preserved_count,
                    "fields_cleared": cleared_count
                })
            else:
                # === 通常モード: シート全体を上書き ===
                final_data = [final_header] + new_rows
                
                sheet.clear()
                sheet.update(final_data)
                
                # 書式設定 (Header color, etc)
                self._apply_header_format(sh, sheet.id, len(final_header))
                
                # --- 5. DataValidation適用 ---
                self._apply_mixed_validations(sh, sheet.id, validations)
                self._apply_conditional_formatting(sh, sheet.id, len(new_rows))
                
                log.update({
                    "updated": True,
                    "rows_written": len(new_rows),
                    "fields_preserved": preserved_count,
                    "fields_cleared": cleared_count
                })
            
        except Exception as e:
            log["status"] = "error"
            log["error"] = str(e)
            
        return log

            # --- 1.5. モレ検知 (現場用シート限定) [NEW] ---
            # 連携データ(details)を正とするため、バックエンドでのモレ検知は一時停止
            # ユーザー要望により「もれ反映前の状態」に戻す
            # if log["source"] == "db": ... 
            
            # (以下、モレ検知ロジックがあればコメントアウトするか、site_rowsがある場合はスキップする)
            # 今回は site_rows が渡されている(source=direct)ので、
            # _fetch_site_data を呼ばない限りここは通らないはずだが、
            # 万が一通った場合でもスキップするように確認。
            
            # ... (Original code didn't have _find_missing_vendors in _ext.py? Wait.)
            # I need to check if I added it or if it was in the base class.
            # I viewed `spreadsheet_service.py` earlier and it had it.
            # `spreadsheet_service_ext.py` inherits? No, it's a standalone class or copies?
            # Let's check if `_find_missing_vendors` is called in `sync_site_sheet` of `_ext.py`.
            # I previously viewed `_ext.py` and it DID NOT have `rows_missing_added` logic.
            # So I probably don't need to disable it if I didn't add it.
            # But I need to revert `_fetch_site_data` filter.

    def _fetch_site_data(self, db_path, run_id, dept_codes):
        """DBから現場用データを取得・フィルタリング"""
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # カンマ区切り等を考慮し、IN句を構築
            placeholders = ",".join(["?"] * len(dept_codes))
            sql = f"""
                SELECT 
                    dept_code, dept_name, vendor_code, vendor_name,
                    payment_amount, transaction_date, anomaly_type, is_monthly
                FROM output_summary
                WHERE run_id = ?
                  AND dept_code IN ({placeholders})
                ORDER BY dept_code, vendor_code
            """
            params = [run_id] + dept_codes
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def _get_validation_options(self, kind: str) -> List[str]:
        """種別ごとの選択肢定義"""
        if kind == "毎月あるのに今月ない" or kind == "毎月あるけど今月なし":
            return ["今月実績なし", "申請済み"]
        elif kind in ("取引日付ズレ？", "月ズレ？"):
            return ["月ズレではありません", "月ズレを修正しました"]
        elif kind == "もれ":
            return ["申請しました", "誤請求のため取引先に連絡しました"]
        elif kind == "二重入力？":
            return ["二重ではない", "削除しました"]
        return []

    def _apply_header_format(self, spreadsheet, sheet_id, col_count):
        """ヘッダー装飾"""
        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": col_count
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.8, "green": 0.8, "blue": 0.8}, # Gray
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        }]
        spreadsheet.batch_update({"requests": requests})

    def _apply_mixed_validations(self, spreadsheet, sheet_id, validations):
        """行ごとに異なるValidationを適用 (Batch)"""
        if not validations: return

        requests = []
        for i, val in enumerate(validations):
            row_idx = i + 1 # 0-indexed data row (header excludes) -> sheet row index 1
            options = val["options"]
            
            rule = None
            if options:
                # プルダウンあり
                condition = {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": opt} for opt in options]
                }
                rule_def = {
                    "condition": condition,
                    "showCustomUi": True,
                    "strict": True
                }
                rule = {"setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                        "startColumnIndex": 0, "endColumnIndex": 1
                    },
                    "rule": rule_def
                }}
            else:
                # プルダウンなし（自由入力） -> Validation解除
                rule = {"setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                        "startColumnIndex": 0, "endColumnIndex": 1
                    },
                    "rule": None # Clear
                }}
            requests.append(rule)
            
        if requests:
            spreadsheet.batch_update({"requests": requests})

    def _apply_conditional_formatting(self, spreadsheet, sheet_id, row_count):
        """条件付き書式を適用"""
        # ルール: 種別(A列)が「取引日付ズレ？」の場合、取引日付(F列)の文字色を赤にする
        # F列は index 5
        
        requests = [{
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1, "endRowIndex": row_count + 1,
                        "startColumnIndex": 8, "endColumnIndex": 9 # I列 (取引日付)
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": '=$C2="取引日付ズレ？"'}]
                        },
                        "format": {
                            "backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}
                        }
                    }
                },
                "index": 0
            }
        }]
        
        spreadsheet.batch_update({"requests": requests})
