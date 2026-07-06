
import json
import logging
import gspread
from pathlib import Path
from typing import List, Dict, Optional
import sqlite3
from datetime import datetime
from infra.drive_service import DriveService
from infra.csv_loader import normalize_dept_code
from infra.retry_utils import call_with_retry
import os

logger = logging.getLogger(__name__)


def _load_excluded_dept_map() -> Dict[str, set]:
    """
    invoice_reconcile_settings.json から取引先別除外部門コードを読み込む
    Returns: {vendor_code: set(dept_code, ...)}
    """
    settings_path = Path("config/invoice_reconcile_settings.json")
    result: Dict[str, set] = {}
    try:
        if not settings_path.exists():
            return result
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for vendor_code, tmpl in data.get("templates", {}).items():
            excluded = tmpl.get("excluded_dept_codes", {})
            if excluded:
                result[vendor_code] = set(excluded.keys())
    except Exception as e:
        logger.warning(f"_load_excluded_dept_map エラー: {e}")
    return result


class SpreadsheetService:
    def __init__(self, credentials_path: str):
        self.credentials_path = Path(credentials_path)
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

    # gspread API 呼び出しのタイムアウト秒数
    _SHEETS_TIMEOUT = 120  # 秒

    def authenticate(self) -> gspread.Client:
        if not self.credentials_path.exists():
            raise FileNotFoundError(f"Credential file not found: {self.credentials_path}")

        # gspread 6.x の正式API (google-auth ベース) — ConnectionError 時リトライ
        client = call_with_retry(
            gspread.service_account,
            filename=str(self.credentials_path),
            scopes=self.scope,
            max_retries=3, delay=5.0
        )

        # セッションにタイムアウトを設定（ReadTimeout 防止）
        try:
            session = client.http_client.session  # gspread 6.x
            session.timeout = self._SHEETS_TIMEOUT
        except AttributeError:
            try:
                client.session.timeout = self._SHEETS_TIMEOUT  # 旧バージョン互換
            except Exception:
                pass

        return client

    def fetch_data_from_db(self, db_path: str, run_id: str) -> List[Dict]:
        """指定されたRUN_IDの出力データを取得（例外部門を除外）"""
        # サーバーベースURLを取得（課員PCからもリンクが開けるよう localhost を使わない）
        from domain.services.check_service import _get_server_base_url
        _base_url = _get_server_base_url()

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"""
                SELECT
                    o.base_invoice_no, o.dept_code, o.dept_name, o.vendor_code, o.vendor_name,
                    o.ocr_amount,
                    -- OCRリンク: output_summaryが空の場合、最新のinvoice_ocr_resultsから補完
                    -- 優先順位: 1) output_summary既存値, 2) 承認番号一致, 3) (部門+取引先)一致
                    COALESCE(
                        NULLIF(o.ocr_file_link, ''),
                        (SELECT '=HYPERLINK("{_base_url}/api/ocr/files/' || r.file_name || '", "リンク")'
                         FROM invoice_ocr_results r
                         WHERE r.run_id = (
                             SELECT i2.run_id FROM invoice_ocr_results i2
                             JOIN run_log rl ON rl.run_id = i2.run_id
                             ORDER BY rl.started_at DESC LIMIT 1
                         )
                         AND r.target_decision_no = o.base_invoice_no
                         AND r.file_name IS NOT NULL AND r.file_name != ''
                         LIMIT 1),
                        (SELECT '=HYPERLINK("{_base_url}/api/ocr/files/' || r.file_name || '", "リンク")'
                         FROM invoice_ocr_results r
                         WHERE r.run_id = (
                             SELECT i2.run_id FROM invoice_ocr_results i2
                             JOIN run_log rl ON rl.run_id = i2.run_id
                             ORDER BY rl.started_at DESC LIMIT 1
                         )
                         AND r.dept_code = o.dept_code
                         AND r.vendor_code = o.vendor_code
                         AND r.file_name IS NOT NULL AND r.file_name != ''
                         LIMIT 1)
                    ) as ocr_file_link,
                    o.ocr_drive_link, o.ocr_match_status,
                    COALESCE(
                        NULLIF(av.assignee2, ''),
                        NULLIF(av.assignee, ''),
                        NULLIF(ad.assignee2, ''),
                        NULLIF(ad.assignee, ''),
                        o.assigned_proposed,
                        ''
                    ) as assignee, o.payment_amount,
                    o.transaction_date, o.payment_date,
                    o.payee_code, o.vendor_payee_result,
                    o.payment_date_result, o.payment_date_expected,
                    o.tax_category, o.tax_category_name, o.tax_result, o.tax_expected,
                    o.account_code, o.account_name, o.account_result, o.account_expected, o.account_expected_name,
                    o.anomaly_result, o.anomaly_type, o.is_monthly,
                    o.status, o.bank_account_info,
                    o.overall_result, o.review_reason,
                    o.amount_3m_ago, o.count_3m_ago,
                    o.amount_2m_ago, o.count_2m_ago,
                    o.amount_1m_ago, o.count_1m_ago,
                    o.amount_current, o.count_current,
                    o.amount_next, o.count_next,
                    (SELECT GROUP_CONCAT(nl.label, ' ')
                     FROM masters_vendor_notes vn
                     JOIN masters_note_labels nl ON nl.id = vn.label_id
                     WHERE vn.vendor_code = o.vendor_code) as vendor_notes
                ,COALESCE(NULLIF(av.assignee2,''), NULLIF(ad.assignee2,''), '') as assignee2
                FROM output_summary o
                LEFT JOIN masters_assign_vendor av ON av.vendor_code = o.vendor_code
                LEFT JOIN masters_assign_dept_override ad ON ad.dept_code = o.dept_code
                LEFT JOIN masters_exception_dept ex ON
                    (o.dept_code = ex.dept_code OR
                     CAST(o.dept_code AS INTEGER) = CAST(ex.dept_code AS INTEGER))
                WHERE o.run_id = ?
                  AND ex.dept_code IS NULL  -- 例外部門を除外
                  AND (o.anomaly_type IS NULL OR o.anomaly_type != '毎月あるのに今月ない') -- モレは経理シートに出さない
                ORDER BY o.base_invoice_no
                """,
                (run_id,)
            )
            rows = [dict(row) for row in cursor.fetchall()]
            
            # Python側でのダメ押しフィルタリング
            # (SQLのJOINが何らかの理由で効かないケースへの対策)
            try:
                ex_cursor = conn.execute("SELECT dept_code FROM masters_exception_dept")
                ex_depts = set()
                for r in ex_cursor.fetchall():
                    code = str(r[0]).strip()
                    if code.isdigit():
                        ex_depts.add(f"{int(code):08d}")
                    else:
                        ex_depts.add(code)
                
                filtered_rows = []
                for row in rows:
                    try:
                        dept_code = str(row["dept_code"]).strip()
                        if dept_code.isdigit():
                            dept_code = f"{int(dept_code):08d}"
                            
                        # 除外リストに含まれていればスキップ
                        if dept_code in ex_depts:
                            continue
                            
                        filtered_rows.append(row)
                    except:
                        filtered_rows.append(row)
                        
                return filtered_rows
            except Exception as e:
                logger.warning(f"Failed to filter exception depts in Python: {e}")
                return rows

    def _setup_status_master(self, spreadsheet):
        """ステータスマスタシートの作成・更新"""
        MASTER_SHEET_NAME = "_STATUS_MASTER"
        OPTIONS = ["未承認", "承認済", "差戻", "削除", "問合せ中"]
        
        try:
            ws = spreadsheet.worksheet(MASTER_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=MASTER_SHEET_NAME, rows=10, cols=1)
            
        # 選択肢書き込み
        cell_list = []
        for i, opt in enumerate(OPTIONS):
            cell_list.append(gspread.Cell(i + 1, 1, opt))
        ws.update_cells(cell_list)
        
        return f"{MASTER_SHEET_NAME}!$A$1:$A${len(OPTIONS)}"




    # メソッド追加場所: クラスの末尾あるいは適切な場所。
    # sync_to_sheetメソッド内の変更。
    
    def _extract_filename(self, hyperlink_formula):
        """HYPERLINK数式からファイル名を抽出"""
        if not hyperlink_formula: return None
        try:
            # http://.../files/filename.pdf
            token = "/files/"
            idx = hyperlink_formula.find(token)
            if idx == -1: return None
            start = idx + len(token)
            end = hyperlink_formula.find('"', start)
            if end == -1: return None
            return hyperlink_formula[start:end]
        except:
            return None

    def _extract_filename_from_url(self, url: str):
        """プレーンURL（HYPERLINK数式なし）からファイル名を抽出。__MULTI__形式の各URL用。"""
        if not url: return None
        try:
            token = "/files/"
            idx = url.find(token)
            if idx == -1: return None
            fname = url[idx + len(token):]
            # クエリ文字列・フラグメントを除去
            fname = fname.split("?")[0].split("#")[0].strip()
            return fname if fname else None
        except:
            return None

    def _load_drive_cache(self, db_path: str) -> dict:
        """drive_file_cache テーブルから {file_name: drive_link} を返す"""
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT file_name, drive_link, drive_file_id FROM drive_file_cache"
                ).fetchall()
            return {r[0]: {"link": r[1], "file_id": r[2]} for r in rows}
        except Exception as e:
            logger.warning(f"Failed to load drive_file_cache: {e}")
            return {}

    def _save_drive_cache(self, db_path: str, entries: list):
        """(file_name, drive_link, drive_file_id) のリストをキャッシュに保存"""
        if not entries:
            return
        try:
            with sqlite3.connect(db_path) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO drive_file_cache (file_name, drive_link, drive_file_id)
                    VALUES (?, ?, ?)
                """, entries)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to save drive_file_cache: {e}")

    def _ensure_drive_upload(self, db_rows, db_path, run_id):
        """未アップロードのファイルをDriveに上げ、リンクを更新する（キャッシュ + 逐次アップロード）"""
        try:
            # --- キャッシュ読み込み（テーブルがなければ自動作成）---
            try:
                with sqlite3.connect(db_path) as _c:
                    _c.execute("""
                        CREATE TABLE IF NOT EXISTS drive_file_cache (
                            file_name TEXT PRIMARY KEY,
                            drive_link TEXT NOT NULL,
                            drive_file_id TEXT,
                            uploaded_at TEXT DEFAULT (datetime('now', 'localtime'))
                        )
                    """)
                    _c.commit()
            except Exception as _e:
                logger.warning(f"drive_file_cache table ensure failed: {_e}")

            cache = self._load_drive_cache(db_path)
            logger.info(f"Drive cache: {len(cache)} files cached.")

            base_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            zip_out_dir = base_dir / "invoice_ocr" / "ZIP_FILE_OUT"

            # ZIP_FILE_OUT 配下の全ファイルを1回だけ走査してマップ化
            file_map = {}
            for p in zip_out_dir.rglob("*"):
                if p.is_file() and p.name not in file_map:
                    file_map[p.name] = p

            # --- 各行の処理: ocr_drive_link → キャッシュ → アップロード待ち ---
            to_upload = []      # (row, fname, local_path)  単一リンク用
            multi_pending = []  # (row, resolved_urls, [(idx, fname, local_path)])  __MULTI__用
            cache_hits = 0

            for row in db_rows:
                # 1. すでにDB上にDriveリンクがある
                drive_link = row.get("ocr_drive_link")
                if drive_link:
                    row["ocr_file_link"] = f'=HYPERLINK("{drive_link}", "リンク")'
                    continue

                ocr_link = row.get("ocr_file_link")
                if not ocr_link:
                    continue

                # 2. __MULTI__ 形式（複数ファイル）
                if ocr_link.startswith("__MULTI__"):
                    urls = [u for u in ocr_link[len("__MULTI__"):].split("|") if u]
                    resolved = list(urls)
                    items_to_upload = []

                    for i, url in enumerate(urls):
                        if "/api/ocr/files/" not in url:
                            continue
                        fname = self._extract_filename_from_url(url)
                        if not fname:
                            continue
                        if fname in cache:
                            resolved[i] = cache[fname]["link"]
                            cache_hits += 1
                        else:
                            local_path = file_map.get(fname)
                            if local_path:
                                items_to_upload.append((i, fname, local_path))
                            else:
                                logger.warning(f"File not found for __MULTI__ upload: {fname}")

                    if not items_to_upload:
                        # 全てキャッシュ解決済み → 即座に更新
                        row["ocr_file_link"] = "__MULTI__" + "|".join(resolved)
                    else:
                        multi_pending.append((row, resolved, items_to_upload))
                    continue

                # 3. 単一リンク
                if "/api/ocr/files/" not in ocr_link:
                    continue

                fname = self._extract_filename(ocr_link)
                if not fname:
                    continue

                # キャッシュにあれば Drive API 不要
                if fname in cache:
                    cached_link = cache[fname]["link"]
                    row["ocr_drive_link"] = cached_link
                    row["ocr_file_link"] = f'=HYPERLINK("{cached_link}", "リンク")'
                    cache_hits += 1
                    continue

                # キャッシュになければアップロード対象
                local_path = file_map.get(fname)
                if not local_path:
                    logger.warning(f"File not found for upload: {fname}")
                    continue

                to_upload.append((row, fname, local_path))

            logger.info(f"Drive upload: cache_hits={cache_hits}, to_upload={len(to_upload)}, multi_pending={len(multi_pending)}")

            if not to_upload and not multi_pending:
                return

            # --- Drive サービス初期化（アップロードが必要な場合のみ）---
            drive_service = DriveService(self.credentials_path)
            # DBに保存された共有ドライブフォルダIDを使用（未設定時はフォルダ名で検索・作成）
            try:
                with sqlite3.connect(db_path) as _dc:
                    _row = _dc.execute("SELECT value FROM app_settings WHERE key='drive_folder_id'").fetchone()
                    folder_id = _row[0] if _row and _row[0] else None
            except Exception:
                folder_id = None
            if not folder_id:
                folder_id = drive_service.ensure_folder("支払依頼チェックツール_証憑")
            logger.info(f"Drive upload target folder_id: {folder_id}")

            # --- 逐次アップロード（Python 3.14 スレッド安定性のため）---
            new_cache_entries = []
            output_summary_updates = []

            for i, (row, fname, local_path) in enumerate(to_upload):
                try:
                    logger.info(f"Uploading ({i+1}/{len(to_upload)}): {fname}")
                    uploaded = drive_service.upload_file(str(local_path), folder_id)
                    web_link = uploaded.get('webViewLink')
                    file_id = uploaded.get('id')
                    if web_link:
                        row["ocr_drive_link"] = web_link
                        row["ocr_file_link"] = f'=HYPERLINK("{web_link}", "リンク")'
                        new_cache_entries.append((fname, web_link, file_id))
                        output_summary_updates.append((web_link, file_id, run_id, fname))
                        # 10件ごとにキャッシュを中間保存（クラッシュ対策）
                        if len(new_cache_entries) % 10 == 0:
                            self._save_drive_cache(db_path, new_cache_entries[-10:])
                except Exception as e:
                    logger.warning(f"Upload failed for {fname}: {e}")

            # --- __MULTI__ アップロード ---
            for row, resolved, items in multi_pending:
                for idx, fname, local_path in items:
                    # 単一リンク処理で同名ファイルが既にアップロード済みなら流用
                    already = next((e for e in new_cache_entries if e[0] == fname), None)
                    if already:
                        resolved[idx] = already[1]
                        continue
                    try:
                        logger.info(f"Uploading (multi): {fname}")
                        uploaded = drive_service.upload_file(str(local_path), folder_id)
                        web_link = uploaded.get('webViewLink')
                        file_id = uploaded.get('id')
                        if web_link:
                            resolved[idx] = web_link
                            new_cache_entries.append((fname, web_link, file_id))
                    except Exception as e:
                        logger.warning(f"Upload failed for {fname}: {e}")
                row["ocr_file_link"] = "__MULTI__" + "|".join(resolved)

            logger.info(f"Drive upload complete: {len(new_cache_entries)} new files uploaded.")

            # --- キャッシュ保存 ---
            self._save_drive_cache(db_path, new_cache_entries)

            # --- output_summary の ocr_drive_link を更新 ---
            if output_summary_updates:
                with sqlite3.connect(db_path) as conn:
                    for link, fid, rid, fname in output_summary_updates:
                        conn.execute("""
                            UPDATE output_summary
                            SET ocr_drive_link = ?, ocr_drive_file_id = ?
                            WHERE run_id = ? AND ocr_file_link LIKE ?
                        """, (link, fid, rid, f"%{fname}%"))
                    conn.commit()

        except Exception as e:
            logger.error(f"Drive Upload Fatal Error: {e}")
            import traceback
            traceback.print_exc()

    def sync_to_sheet(self, db_path: str, run_id: str, spreadsheet_id: str, upload_drive: bool = False):
        """DBデータをスプレッドシートに同期（マージ）"""
        # リトライ付きで認証 & シート接続
        import time as _time
        for _attempt in range(3):
            try:
                client = self.authenticate()
                sh = client.open_by_key(spreadsheet_id)
                sheet = sh.sheet1
                break
            except Exception as _e:
                if _attempt < 2:
                    logger.warning(f"Sheets 接続失敗 (attempt {_attempt+1}/3): {_e} - 5秒後リトライ...")
                    _time.sleep(5)
                else:
                    raise

        # マスタシート準備 & 入力規則範囲取得
        range_str = self._setup_status_master(sh)

        # 1. 現状のデータを全取得（リトライあり）
        # get_all_recordsはヘッダー重複でエラーになるため、get_all_valuesを使用して手動パースする
        for _attempt in range(3):
            try:
                all_values = sheet.get_all_values()
                break
            except Exception as _e:
                if _attempt < 2:
                    logger.warning(f"get_all_values 失敗 (attempt {_attempt+1}/3): {_e} - 5秒後リトライ...")
                    _time.sleep(5)
                    client = self.authenticate()
                    sh = client.open_by_key(spreadsheet_id)
                    sheet = sh.sheet1
                else:
                    raise
        existing_header = all_values[0] if all_values else []
        existing_rows = all_values[1:] if len(all_values) > 1 else []
        
        # 必要な列のインデックスを探す
        idx_invoice = -1
        idx_dept = -1
        idx_status = -1
        idx_remark = -1
        idx_assignee2 = -1

        for i, h in enumerate(existing_header):
            if h == "伝票番号": idx_invoice = i
            elif h in ["部門コード", "申請部門コード"]: idx_dept = i
            elif h == "ステータス": idx_status = i
            elif h in ["備考", "コメント"]: idx_remark = i
            elif h == "担当2": idx_assignee2 = i

        # KEY: base_invoice_no + dept_code (ユニークキーと仮定)
        existing_map = {}
        if idx_invoice != -1 and idx_dept != -1:
            for row in existing_rows:
                # 行の長さチェック
                if len(row) <= max(idx_invoice, idx_dept):
                    continue

                inv = str(row[idx_invoice])
                dept = str(row[idx_dept])
                # 既存データの部門コードも正規化してキーを作成
                try:
                    dept = f"{int(dept):08d}"
                except:
                    pass
                key = f"{inv}_{dept}"

                status_val = ""
                if idx_status != -1 and len(row) > idx_status:
                    status_val = row[idx_status]

                remark_val = ""
                if idx_remark != -1 and len(row) > idx_remark:
                    remark_val = row[idx_remark]

                assignee2_val = ""
                if idx_assignee2 != -1 and len(row) > idx_assignee2:
                    assignee2_val = row[idx_assignee2]

                existing_map[key] = {
                    "ステータス": status_val,
                    "備考": remark_val,
                    "担当2": assignee2_val,
                }

        # 2. DBから最新データを取得
        db_rows = self.fetch_data_from_db(db_path, run_id)
        logger.debug(f"sync_to_sheet: run_id={run_id}, upload_drive={upload_drive}, rows={len(db_rows)}")
        
        if not db_rows:
            logger.warning(f"sync_to_sheet: No data found for run_id={run_id}")
            return 0
            
        # --- Drive Upload Start ---
        if upload_drive:
            self._ensure_drive_upload(db_rows, db_path, run_id)
        # --- Drive Upload End ---
        
        # 3. マージデータの作成
        # 3. マージデータの作成
        # ヘッダー定義 (Excel Output Order + Manual Columns)
        # Excel WriterのSUMMARY_COLUMNSに準拠
        
        # マニュアル列(左)
        manual_left = ["ステータス"]
        
        # DB列 (Excel Writer定義順)
        db_columns = [
            ("総合", "overall_result"),
            ("OCR判定", "ocr_match_status"),
            ("リンク", "ocr_file_link"),
            ("当月請求書", "ocr_amount"),
            ("支払金額", "payment_amount"),
            ("担当", "assignee"),
            ("担当2", "assignee2"),
            ("取引日付", "transaction_date"),
            ("注意事項", "vendor_notes"),
            ("取引先コード", "vendor_code"),
            ("取引先名", "vendor_name"),
            ("申請部門コード", "dept_code"),
            ("申請部門名", "dept_name"),
            ("予定日判定", "payment_date_result"),
            ("支払予定日", "payment_date"),
            ("予定日（正）", "payment_date_expected"),
            ("税区分判定", "tax_result"),
            ("税区分", "tax_category"),
            ("税区分（正）", "tax_expected"),
            ("科目判定", "account_result"),
            ("科目", "account_code"),
            ("科目名", "account_name"),
            ("科目（正）", "account_expected"),
            ("科目名（正）", "account_expected_name"),
            ("ズレモレ判定", "anomaly_result"),
            ("種別", "anomaly_type"),
            ("金額(3M前)", "amount_3m_ago"),
            ("個数(3M前)", "count_3m_ago"),
            ("金額(2M前)", "amount_2m_ago"),
            ("個数(2M前)", "count_2m_ago"),
            ("金額(1M前)", "amount_1m_ago"),
            ("個数(1M前)", "count_1m_ago"),
            ("金額(当月)", "amount_current"),
            ("個数(当月)", "count_current"),
            ("金額(翌月)", "amount_next"),
            ("個数(翌月)", "count_next"),
            ("支払先相違", "vendor_payee_result"),
            ("支払先コード", "payee_code"),
            ("伝票番号", "base_invoice_no"),
            ("状況区分", "status"),
            ("口座番号", "bank_account_info")
        ]
        
        # マニュアル列(右)
        manual_right = ["備考"]
        
        headers = manual_left + [col[0] for col in db_columns] + manual_right
        
        new_records = []
        
        for row in db_rows:
            d_code_key = str(row['dept_code'])
            try:
                d_code_key = f"{int(d_code_key):08d}"
            except:
                pass
            key = f"{row['base_invoice_no']}_{d_code_key}"
            
            # DBデータ構築
            row_data = {
                "ステータス": "", 
                "備考": ""
            }
            
            # DB値のマッピング
            # Note: SQL select mapping needs to be correct.
            # Some fields in db_columns key might correlate to row dict keys differently if aliased?
            # row is dict from sqlite row.
            
            for header, key_name in db_columns:
                # 特殊なマッピングが必要な場合 (例: tax_category code vs name)
                # output_summary table has 'tax_category' (code) and 'tax_category_name'.
                # excel_writer uses 'tax_category' -> code.
                val = row[key_name]
                
                # None対応
                if val is None:
                    val = ""
                
                # 数字のみの文字列コードは先頭に ' をつけて強制的に文字列にする
                # これによりスプレッドシート側で数値として解釈されず、前ゼロが保持される
                # 対象カラム名は db_columns の定義に基づく
                if header in ["部門コード", "申請部門コード", "取引先コード", "支払先コード", "科目"]:
                     if val:
                         # 部門コード補正: 8桁ゼロ埋め
                         if header in ["部門コード", "申請部門コード"]:
                             try:
                                 val = f"{int(str(val)):08d}"
                             except:
                                 pass
                                 
                         # 数字のみの文字列はシングルクォート付与で型固定
                         if str(val).isdigit():
                             val = f"'{val}"
                         
                row_data[header] = val

            # 特例処理: Vendor Name 'None' fix & Recurring Missing amount clear
            vendor_val = str(row_data.get("取引先名", "")).strip()
            if vendor_val == "None":
                logger.debug(f"Found None vendor name at {key}. Replacing with ''.")
                row_data["取引先名"] = ""

            status_check = row.get("status", "")
            if row.get("anomaly_type") == "毎月あるけど今月なし" or status_check == "RECURRING_MISSING":
                logger.debug(f"Found RECURRING_MISSING at {key}. Clearing amount.")
                row_data["支払金額"] = ""

            # デフォルトステータス計算 (ユーザー要件: 2026/01/29)
            db_status = row["status"]
            new_status = ""
            
            # 定義
            # 1. 「支払確定」「全額決裁」 -> 承認済 (強制上書き)
            # 2. 「未承認」の場合
            #    - 既存値が「未承認」以外なら維持
            #    - それ以外は「未承認」
            # 3. その他 -> 未承認
            
            if db_status in ["支払確定", "全額決裁", "全額決済", "締未済"]:
                new_status = "承認済"
            else:
                # 既存値の確認
                current_status = ""
                if key in existing_map:
                    current_status = str(existing_map[key].get("ステータス", "")).strip()
                
                if db_status == "未承認":
                    if current_status and current_status != "未承認":
                        new_status = current_status # 維持
                    else:
                        new_status = "未承認"
                else:
                    # その他の区分 -> 未承認
                    # (既存値維持の指示はないため、このケースでは強制的に未承認になるが、
                    #  2.のロジックからすると「未承認以外は維持」とも読める。
                    #  しかし3.で「それ以外は未承認」とあるため、未承認とする)
                    new_status = "未承認"
            
            # 備考の維持 (これは常に維持)
            row_data["ステータス"] = new_status
            # 担当2はスプシ更新時に一切触れない（既存値を常に維持）
            # 書き込みは「担当2をスプシに反映」ボタンからのみ行う
            if key in existing_map:
                row_data["担当2"] = str(existing_map[key].get("担当2", "")).strip()
            else:
                row_data["担当2"] = ""  # 新規行は空欄
            # マニュアル列の維持
            for m_col in manual_right:
                val = ""
                if key in existing_map:
                    val = str(existing_map[key].get(m_col, "")).strip()
                    # 備考の後方互換(コメント)
                    if m_col == "備考" and not val:
                        val = str(existing_map[key].get("コメント", "")).strip()
                row_data[m_col] = val
            
            # 配列化 (headers順)
            new_records.append(row_data)

        # 4. 書き込みデータの整形 (リストのリスト)
        # __MULTI__形式の複数リンクはリッチテキストで後処理するため、
        # ここではプレーンテキスト "リンク1 リンク2 ..." に置換して位置を記録する
        link_col_idx = headers.index("リンク") if "リンク" in headers else -1
        multi_link_cells = []  # (row_idx_0based, [url1, url2, ...])

        output_data = [headers]
        for rec_idx, r in enumerate(new_records):
            row_vals = [r[col] for col in headers]
            if link_col_idx >= 0:
                cell_val = row_vals[link_col_idx]
                if isinstance(cell_val, str) and cell_val.startswith("__MULTI__"):
                    urls = cell_val[len("__MULTI__"):].split("|")
                    urls = [u for u in urls if u]
                    # プレーンテキストに変換
                    plain = " ".join(f"リンク{i+1}" for i in range(len(urls)))
                    row_vals[link_col_idx] = plain
                    # スプレッドシート上の行インデックス (ヘッダー行=0, データ1行目=1)
                    multi_link_cells.append((rec_idx + 1, urls))
            output_data.append(row_vals)

        # 5. 書き込みと整形 (安全更新)
        # sheet.clear() は書式設定（プルダウン等）も消すため使用しない。
        # 必要な範囲だけ値を更新し、余分な行は値をクリアする。

        # 全データを書き込む
        # 数式を有効にするため USER_ENTERED を指定

        # 行数が足りない場合は拡張
        needed_rows = len(output_data) + 10 # 余裕を持たせる
        try:
            if sheet.row_count < needed_rows:
                logger.debug(f"Resizing sheet from {sheet.row_count} to {needed_rows}")
                sheet.resize(rows=needed_rows)
        except Exception as e:
            logger.warning(f"Failed to resize sheet: {e}")

        call_with_retry(
            sheet.update,
            output_data, "A1",
            value_input_option='USER_ENTERED',
            max_retries=3, delay=10.0
        )

        # 複数リンクセルにリッチテキスト（textFormatRuns）を適用
        if multi_link_cells and link_col_idx >= 0:
            try:
                LINK_COLOR = {"red": 0.06, "green": 0.43, "blue": 0.87}
                rich_requests = []
                for row_0, urls in multi_link_cells:
                    labels = [f"リンク{i+1}" for i in range(len(urls))]
                    # "リンク1 リンク2 ..." の文字列を構築し各セグメントのオフセットを計算
                    text_runs = []
                    pos = 0
                    for i, (label, url) in enumerate(zip(labels, urls)):
                        text_runs.append({
                            "startIndex": pos,
                            "format": {
                                "link": {"uri": url},
                                "foregroundColor": LINK_COLOR,
                                "underline": True
                            }
                        })
                        pos += len(label)
                        if i < len(urls) - 1:
                            # スペース部分はリンクなし
                            text_runs.append({
                                "startIndex": pos,
                                "format": {"link": None, "foregroundColor": {"red": 0, "green": 0, "blue": 0}, "underline": False}
                            })
                            pos += 1  # スペース1文字

                    full_text = " ".join(labels)
                    rich_requests.append({
                        "updateCells": {
                            "rows": [{
                                "values": [{
                                    "userEnteredValue": {"stringValue": full_text},
                                    "textFormatRuns": text_runs
                                }]
                            }],
                            "range": {
                                "sheetId": sheet.id,
                                "startRowIndex": row_0,
                                "endRowIndex": row_0 + 1,
                                "startColumnIndex": link_col_idx,
                                "endColumnIndex": link_col_idx + 1
                            },
                            "fields": "userEnteredValue,textFormatRuns"
                        }
                    })
                if rich_requests:
                    call_with_retry(
                        sheet.spreadsheet.batch_update,
                        {"requests": rich_requests},
                        max_retries=3, delay=10.0
                    )
                    logger.info(f"Rich text applied to {len(rich_requests)} multi-link cells.")
            except Exception as e:
                logger.warning(f"Failed to apply rich text links: {e}")

        # 行数が減った場合、残骸を消す（行自体は残す）
        # prev: len(existing_records) + 1
        current_row_count = len(existing_rows) + 1 
        new_row_count = len(new_records) + 1
        
        if current_row_count > new_row_count:
            # 消すべき範囲: (new_row_count + 1)行目 ～ current_row_count行目
            # 列名計算 (A, B, ... Z, AA, AB...)
            def col_letter(n):
                """1-indexed列番号をアルファベットに変換 (1=A, 27=AA)"""
                result = ""
                while n > 0:
                    n -= 1
                    result = chr(65 + (n % 26)) + result
                    n //= 26
                return result
            
            last_col = col_letter(len(headers))
            clear_range = f"A{new_row_count + 1}:{last_col}{current_row_count}"
            sheet.batch_clear([clear_range])

        # 入力規則設定 (A列: 2行目以降)
        
        last_row = new_row_count
        if last_row > 1:
            try:
                sheet_id = sheet.id
                
                # 1. 既存の保護と条件付き書式をクリーンアップするためのID取得
                # (API call to get metadata)
                meta = sheet.spreadsheet.fetch_sheet_metadata()
                # meta is dict of sheet info. We need to find *this* sheet's info.
                current_sheet_meta = None
                for s in meta['sheets']:
                    if s['properties']['sheetId'] == sheet_id:
                        current_sheet_meta = s
                        break
                
                requests = []

                if current_sheet_meta is None:
                    current_sheet_meta = {}

                # 削除リクエスト（保護）
                if 'protectedRanges' in current_sheet_meta:
                    for pr in current_sheet_meta['protectedRanges']:
                        requests.append({
                            "deleteProtectedRange": {
                                "protectedRangeId": pr['protectedRangeId']
                            }
                        })

                # 削除リクエスト（条件付き書式）
                if 'conditionalFormats' in current_sheet_meta:
                    # 数が多いと面倒だが、後ろから消す
                    count = len(current_sheet_meta['conditionalFormats'])
                    for i in range(count - 1, -1, -1):
                        requests.append({
                            "deleteConditionalFormatRule": {
                                "index": i,
                                "sheetId": sheet_id
                            }
                        })

                # 2. スタイル定義 (RGB)
                # Google Sheets API uses 0-1 float (e.g. 255 -> 1.0)
                def rgb(r, g, b):
                    return {"red": r/255, "green": g/255, "blue": b/255}

                COLOR_HEADER = rgb(31, 78, 121)   # 1F4E79
                COLOR_OK = rgb(198, 239, 206)     # C6EFCE
                COLOR_NG = rgb(255, 199, 206)     # FFC7CE
                COLOR_DASH = rgb(255, 235, 156)   # FFEB9C
                COLOR_GRAY = rgb(217, 217, 217)   # D9D9D9 (承認済用)
                COLOR_WHITE = rgb(255, 255, 255)
                
                # 3. ヘッダー装飾 (Row 1)
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": COLOR_HEADER,
                                "textFormat": {
                                    "foregroundColor": COLOR_WHITE,
                                    "bold": True
                                },
                                "horizontalAlignment": "CENTER"
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                    }
                })

                # 4. 条件付き書式 (OK, NG, -)
                # 全範囲 (A2:LastCol/LastRow)
                grid_range = {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": last_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(headers)
                }
                
                # Helper for conditional format rule
                def make_cond_rule(condition_value, bg_color):
                    return {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [grid_range],
                                "booleanRule": {
                                    "condition": {
                                        "type": "TEXT_EQ",
                                        "values": [{"userEnteredValue": condition_value}]
                                    },
                                    "format": {
                                        "backgroundColor": bg_color
                                    }
                                }
                            },
                            "index": 0
                        }
                    }

                requests.append(make_cond_rule("OK", COLOR_OK))
                requests.append(make_cond_rule("NG", COLOR_NG))
                requests.append(make_cond_rule("-", COLOR_DASH))

                # 承認済 -> 行全体グレー (CUSTOM_FORMULA)
                # 承認済 -> 行全体グレー (CUSTOM_FORMULA)
                requests.append({
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [grid_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{"userEnteredValue": '=$A2="承認済"'}]
                                },
                                "format": {
                                    "backgroundColor": COLOR_GRAY
                                }
                            }
                        },
                        "index": 0 # 最優先
                    }
                })

                # 削除 -> 赤
                COLOR_RED = rgb(255, 100, 100)
                requests.append({
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [grid_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{"userEnteredValue": '=$A2="削除"'}]
                                },
                                "format": {
                                    "backgroundColor": COLOR_RED
                                }
                            }
                        },
                        "index": 0
                    }
                })

                # 差戻 -> オレンジ
                COLOR_ORANGE = rgb(255, 165, 0)
                requests.append({
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [grid_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{"userEnteredValue": '=$A2="差戻"'}]
                                },
                                "format": {
                                    "backgroundColor": COLOR_ORANGE
                                }
                            }
                        },
                        "index": 0
                    }
                })

                # 問合せ中 -> ピンク
                COLOR_PINK = rgb(255, 192, 203)
                requests.append({
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [grid_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{"userEnteredValue": '=$A2="問合せ中"'}]
                                },
                                "format": {
                                    "backgroundColor": COLOR_PINK
                                }
                            }
                        },
                        "index": 0
                    }
                })

                # 5. シート保護 (StatusとRemarks以外)
                # ユーザー要望により保護解除 (2025/01/27)
                # if len(headers) > 2:
                #     requests.append({
                #         "addProtectedRange": {
                #             "protectedRange": {
                #                 "range": {
                #                     "sheetId": sheet_id,
                #                     "startRowIndex": 0, 
                #                     "startColumnIndex": 1,
                #                     "endColumnIndex": len(headers) - 1
                #                 },
                #                 "description": "System Protected (Auto-generated)",
                #                 "warningOnly": True,
                #             }
                #         }
                #     })

                # 6. プルダウン (A列) - Previous Step Logic Re-integrated
                # Use raw API as before
                # ... (Integrate validation request into this batch if possible, or append)
                range_str = self._setup_status_master(client.open_by_key(spreadsheet_id))
                safe_range_str = f"'{range_str.split('!')[0]}'!{range_str.split('!')[1]}"
                formula = f"={safe_range_str}"
                
                requests.append({
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": last_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": 1
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_RANGE",
                                "values": [{"userEnteredValue": formula}]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                })

                # Execute Batch
                call_with_retry(
                    sheet.spreadsheet.batch_update,
                    {"requests": requests},
                    max_retries=3, delay=10.0
                )
                
            except Exception as e:
                logger.warning(f"Format/Protect Error: {e}")
                pass

        return len(new_records)

    def sync_site_sheet(self, db_path: str, run_id: str, site_sheet_id: str) -> Dict[str, str]:
        """
        現場用スプレッドシートを更新する
        
        Args:
            db_path: DBパス
            run_id: 実行ID
            site_sheet_id: 現場用スプレッドシートID
            
        Returns:
            実行結果ログ（辞書形式）
        """
        log = {"updated": False}
        
        if not site_sheet_id:
            log["status"] = "skipped"
            log["reason"] = "Site sheet ID not configured"
            return log

        # URLからID抽出の試行
        import re
        if "google.com" in site_sheet_id or "/" in site_sheet_id:
            match = re.search(r"/d/([a-zA-Z0-9-_]+)", site_sheet_id)
            if match:
                site_sheet_id = match.group(1)

        try:
            import time as _time
            for _attempt in range(3):
                try:
                    client = self.authenticate()
                    sh = call_with_retry(client.open_by_key, site_sheet_id, max_retries=3, delay=5.0)
                    sheet = sh.sheet1
                    break
                except (ConnectionError, ConnectionResetError, OSError) as _e:
                    if _attempt < 2:
                        logger.warning(f"Site sheet 接続失敗 (attempt {_attempt+1}/3): {_e} - 5秒後リトライ...")
                        _time.sleep(5)
                    else:
                        raise
                except Exception as _e:
                    if _attempt < 2:
                        logger.warning(f"Site sheet 接続失敗 (attempt {_attempt+1}/3): {_e} - 5秒後リトライ...")
                        _time.sleep(5)
                    else:
                        raise

            # --- 1. DBデータ取得 & フィルタリング ---
            # 種別(anomaly_type)があるものだけ抽出
            db_rows = self._fetch_site_data(db_path, run_id)
            log["rows_filtered"] = len(db_rows)
            
            # Note: ここでdb_rowsが空でもreturnせず、後続のモレ検知やシートクリア処理へ進む
            # if not db_rows: ... (Removed to allow clearing sheet)

            # --- 1.5. モレ検知 (現場用シート限定) [NEW] ---
            # 2026/01/29: ユーザー要望により現場用シートのみモレを追加
            try:
                with sqlite3.connect(db_path) as conn:
                    row_bm = conn.execute("SELECT base_month FROM run_log WHERE run_id = ?", (run_id,)).fetchone()
                    if row_bm:
                        base_month = row_bm[0]
                        # Output summary全量からペア取得
                        cursor = conn.execute("SELECT DISTINCT vendor_code, dept_code FROM output_summary WHERE run_id = ?", (run_id,)).fetchall()
                        current_pairs = {(r[0], normalize_dept_code(r[1])) for r in cursor}
                        
                        from domain.validators.anomaly_check import find_missing_vendors
                        missing_rows = find_missing_vendors(conn, base_month, current_pairs)

                        # 取引先別除外部門マップを読み込む
                        _excluded_dept_map = _load_excluded_dept_map()

                        # 重複排除用セット (normalize(dept_code), vendor_code)
                        # 正規化して照合することで先頭ゼロの違いによる重複を防ぐ
                        existing_keys = set()
                        for row in db_rows:
                            _dk = normalize_dept_code(str(row["dept_code"]).strip())
                            _vk = str(row["vendor_code"]).strip()
                            existing_keys.add((_dk, _vk))
                        # 「月ズレ？」が既にある (dept, vendor) を記録 → 後で「もれ」を除外するため
                        gap_keys = set()
                        for row in db_rows:
                            if str(row.get("anomaly_type", "")).strip() in ("月ズレ？", "取引日付ズレ？"):
                                gap_keys.add((normalize_dept_code(str(row["dept_code"]).strip()), str(row["vendor_code"]).strip()))

                        if missing_rows:
                            count_added = 0
                            for m_row in missing_rows:
                                _v = str(m_row["vendor_code"]).strip()
                                _d = normalize_dept_code(str(m_row["dept_code"]).strip())
                                key = (_d, _v)
                                if key in existing_keys:
                                    continue
                                # 「月ズレ？」が既にある場合は「もれ」を追加しない
                                if key in gap_keys:
                                    logger.info(f"モレ除外（月ズレ優先）: vendor={_v}, dept={_d}")
                                    continue
                                # 除外部門チェック
                                if str(m_row["dept_code"]).strip() in _excluded_dept_map.get(_v, set()) or _d in _excluded_dept_map.get(_v, set()):
                                    logger.info(f"モレ除外（除外部門設定）: vendor={_v}, dept={_d}")
                                    continue

                                existing_keys.add(key)
                                combined_row = {
                                    "dept_code": m_row["dept_code"],
                                    "dept_name": m_row["dept_name"],
                                    "vendor_code": m_row["vendor_code"],
                                    "vendor_name": m_row["vendor_name"],
                                    "payment_amount": m_row["payment_amount"],
                                    "transaction_date": m_row["transaction_date"],
                                    "anomaly_type": m_row["anomaly_type"]
                                }
                                db_rows.append(combined_row)
                                count_added += 1
                            log["rows_missing_added"] = count_added
                        
                        # --- 1.6. 突合結果の「もれ」データ取得 [NEW] ---
                        # 同じ基準月の突合実行結果(output_summary)から「もれ」を取得
                        # 取引先ごとに最新 run のみ参照（古い run の「もれ」が混入しないよう）
                        try:
                            conn.row_factory = None
                            reconcile_more = conn.execute("""
                                SELECT o.dept_code, o.dept_name, o.vendor_code, o.vendor_name,
                                       o.payment_amount, o.transaction_date, o.anomaly_type
                                FROM output_summary o
                                JOIN run_log rl ON o.run_id = rl.run_id
                                LEFT JOIN masters_exception_dept ex_d ON o.dept_code = ex_d.dept_code
                                LEFT JOIN masters_exclude ex_v ON o.vendor_code = ex_v.vendor_code
                                WHERE rl.base_month = ?
                                  AND o.anomaly_type = 'もれ'
                                  AND COALESCE(o.payment_amount, 0) > 0
                                  AND ex_d.dept_code IS NULL
                                  AND ex_v.vendor_code IS NULL
                                  -- 最新runで実取引として解消済みでない(dept, vendor)のみ表示
                                  AND NOT EXISTS (
                                      SELECT 1
                                      FROM output_summary os_new
                                      JOIN run_log rl_new ON os_new.run_id = rl_new.run_id
                                      WHERE rl_new.base_month = ?
                                        AND os_new.vendor_code = o.vendor_code
                                        AND os_new.dept_code = o.dept_code
                                        AND (os_new.anomaly_type IS NULL OR os_new.anomaly_type != 'もれ')
                                        AND rl_new.run_id = (
                                            SELECT run_id FROM run_log
                                            WHERE base_month = ?
                                            ORDER BY started_at DESC LIMIT 1
                                        )
                                  )
                                  -- (dept, vendor)ごとに最新の「もれ」1件のみ取得（重複防止）
                                  AND o.run_id = (
                                      SELECT rl2.run_id
                                      FROM run_log rl2
                                      JOIN output_summary os2 ON rl2.run_id = os2.run_id
                                      WHERE rl2.base_month = ?
                                        AND os2.vendor_code = o.vendor_code
                                        AND os2.dept_code = o.dept_code
                                        AND os2.anomaly_type = 'もれ'
                                      ORDER BY rl2.started_at DESC
                                      LIMIT 1
                                  )
                                ORDER BY o.dept_code
                            """, (base_month, base_month, base_month, base_month)).fetchall()
                            
                            logger.info(f"突合「もれ」候補: {len(reconcile_more)}件 (base_month={base_month})")
                            
                            reconcile_count = 0
                            for r_row in reconcile_more:
                                # SELECT o.dept_code(0), o.dept_name(1), o.vendor_code(2), o.vendor_name(3),
                                #        o.payment_amount(4), o.transaction_date(5), o.anomaly_type(6)
                                _rd = normalize_dept_code(str(r_row[0]).strip())
                                _rv = str(r_row[2]).strip()
                                key = (_rd, _rv)
                                if key in existing_keys:
                                    logger.info(f"  スキップ(重複): dept={_rd}, vendor={_rv}")
                                    continue
                                # 「月ズレ？」が既にある場合は「もれ」を追加しない
                                if key in gap_keys:
                                    logger.info(f"  スキップ(月ズレ優先): dept={_rd}, vendor={_rv}")
                                    continue
                                # 除外部門チェック
                                if str(r_row[0]).strip() in _excluded_dept_map.get(_rv, set()) or _rd in _excluded_dept_map.get(_rv, set()):
                                    logger.info(f"  スキップ(除外部門): dept={r_row[0]}, vendor={r_row[2]}")
                                    continue
                                existing_keys.add(key)
                                db_rows.append({
                                    "dept_code": r_row[0],
                                    "dept_name": r_row[1],
                                    "vendor_code": r_row[2],
                                    "vendor_name": r_row[3],
                                    "payment_amount": r_row[4],
                                    "transaction_date": r_row[5],
                                    "anomaly_type": r_row[6]
                                })
                                reconcile_count += 1
                                logger.info(f"  追加: dept={r_row[0]}, vendor={r_row[2]}, amt={r_row[4]}")
                            if reconcile_count > 0:
                                logger.info(f"突合「もれ」データ追加: {reconcile_count}件")
                            log["rows_reconcile_more_added"] = reconcile_count
                        except Exception as e2:
                            import traceback as tb2
                            logger.error(f"突合もれデータ取得エラー: {e2}")
                            tb2.print_exc()
            except Exception as e:
                import traceback
                traceback.print_exc()
                log["missing_check_error"] = str(e)
            
            # --- 1.7. 月ズレ優先フィルタ ---
            # 同じ取引先・同じ金額で「月ズレ？」が存在する場合、「もれ」を抑制する
            # (部門コードが違っても同一取引とみなす)
            try:
                gap_vendor_amounts = set()
                # db_rows 内の月ズレ？
                for row in db_rows:
                    _at = str(row.get("anomaly_type", "")).strip()
                    if _at in ("月ズレ？", "取引日付ズレ？"):
                        try:
                            _amt = int(float(str(row.get("payment_amount", 0) or 0)))
                        except Exception:
                            _amt = 0
                        if _amt > 0:
                            gap_vendor_amounts.add((str(row.get("vendor_code", "")).strip(), _amt))
                # output_summary の DATE_DIFF / DATE_GAP も追加（reconcile 結果）
                try:
                    with sqlite3.connect(db_path) as _conn2:
                        _conn2.row_factory = sqlite3.Row
                        _gap_rows = _conn2.execute("""
                            SELECT o.vendor_code, o.payment_amount
                            FROM output_summary o
                            JOIN run_log rl ON o.run_id = rl.run_id
                            WHERE rl.base_month = ?
                              AND o.status IN ('DATE_DIFF', 'DATE_GAP')
                              AND COALESCE(o.payment_amount, 0) > 0
                        """, (base_month,)).fetchall()
                        for _gr in _gap_rows:
                            try:
                                _amt2 = int(float(str(_gr["payment_amount"] or 0)))
                            except Exception:
                                _amt2 = 0
                            if _amt2 > 0:
                                gap_vendor_amounts.add((str(_gr["vendor_code"]).strip(), _amt2))
                except Exception:
                    pass

                if gap_vendor_amounts:
                    before_len = len(db_rows)
                    filtered_rows = []
                    for row in db_rows:
                        _at = str(row.get("anomaly_type", "")).strip()
                        if _at in ("もれ", "毎月あるのに今月ない", "毎月あるけど今月なし"):
                            try:
                                _amt = int(float(str(row.get("payment_amount", 0) or 0)))
                            except Exception:
                                _amt = 0
                            _vk = str(row.get("vendor_code", "")).strip()
                            if (_vk, _amt) in gap_vendor_amounts:
                                logger.info(f"もれ抑制（月ズレ優先）: vendor={_vk}, dept={row.get('dept_code','')}, amt={_amt}")
                                continue
                        filtered_rows.append(row)
                    db_rows = filtered_rows
                    if len(db_rows) < before_len:
                        logger.info(f"月ズレ優先フィルタ: {before_len} → {len(db_rows)} 件")
            except Exception as _ef:
                logger.warning(f"月ズレ優先フィルタエラー: {_ef}")

            # データが0件でもシートをクリアするために続行する
            if not db_rows:
                log["status"] = "cleared"
                log["reason"] = "No data found (Sheet cleared)"

            # --- 2. 既存データ取得 (Header + Body) リトライあり ---
            # site_status, site_comment を引き継ぐため
            for _attempt in range(3):
                try:
                    all_values = sheet.get_all_values()
                    break
                except Exception as _e:
                    if _attempt < 2:
                        logger.warning(f"site get_all_values 失敗 (attempt {_attempt+1}/3): {_e} - 5秒後リトライ...")
                        _time.sleep(5)
                        client = self.authenticate()
                        sh = client.open_by_key(site_sheet_id)
                        sheet = sh.sheet1
                    else:
                        raise
            existing_header = all_values[0] if all_values else []
            existing_rows = all_values[1:] if len(all_values) > 1 else []
            
            # 必須カラム定義（順序固定）
            CORE_HEADERS = [
                "ｽﾃｰﾀｽ", "ｺﾒﾝﾄ", "区分", 
                "部門ｺｰﾄﾞ", "部門名", "取引先ｺｰﾄﾞ", "取引先名", 
                "取引日付", "支払金額"
            ]
            
            # 既存列の位置を探す
            col_map = {name: idx for idx, name in enumerate(existing_header)}
            
            # 既存データのマップ化（照合用）
            map_key_a = {}
            map_key_b = {}
            
            # 新旧カラム名の両方に対応 (Old: site_status -> New: ｽﾃｰﾀｽ)
            idx_status = col_map.get("site_status", col_map.get("ｽﾃｰﾀｽ", -1))
            idx_comment = col_map.get("site_comment", col_map.get("ｺﾒﾝﾄ", -1))
            idx_dept = col_map.get("dept_code", col_map.get("部門ｺｰﾄﾞ", -1))
            idx_vendor = col_map.get("vendor_code", col_map.get("取引先ｺｰﾄﾞ", -1))
            idx_amount = col_map.get("pay_amount", col_map.get("支払金額", -1))
            
            for i, row in enumerate(existing_rows):
                if idx_dept >= 0 and idx_vendor >= 0 and len(row) > idx_vendor:
                    d_code = str(row[idx_dept]).strip()
                    # 既存データの部門コードも正規化
                    # 既存データの部門コードも正規化
                    try:
                        d_code = f"{int(d_code):08d}"
                        # 照合用にもシングルクォートで正規化（出力側もつけるため）
                        d_code = f"'{d_code}"
                    except:
                        pass
                    
                    v_code = str(row[idx_vendor]).strip()
                    key_a = (d_code, v_code)
                    if key_a not in map_key_a: map_key_a[key_a] = []
                    map_key_a[key_a].append(i)
                    
                    if idx_amount >= 0 and len(row) > idx_amount:
                        amt = str(row[idx_amount]).strip().replace(",", "")
                        try:
                            amt_int = int(float(amt))
                        except:
                            amt_int = amt
                        key_b = (d_code, v_code, str(amt_int))
                        if key_b not in map_key_b: map_key_b[key_b] = []
                        map_key_b[key_b].append(i)

            # --- 3. 新しい出力データの作成 ---
            new_rows = []
            validations = []
            
            preserved_count = 0
            cleared_count = 0
            
            for db_row in db_rows:
                d_code = str(db_row["dept_code"]).strip()
                # 出力データの部門コード正規化: 8桁ゼロ埋め
                if d_code:
                    try:
                        d_code = f"{int(d_code):08d}"
                    except:
                        pass
                
                # 数字のみの場合はシングルクォート付与（ゼロ落ち防止）
                if d_code and str(d_code).isdigit():
                    d_code = f"'{d_code}"
                
                v_code = str(db_row["vendor_code"]).strip()
                amt = db_row["payment_amount"]
                
                status_val = ""
                comment_val = ""
                match_idx = -1
                
                # 1) Key A 検索
                candidates_a = map_key_a.get((d_code, v_code), [])
                if len(candidates_a) == 1:
                    match_idx = candidates_a[0]
                elif len(candidates_a) > 1:
                    # 2) Key B 検索
                    candidates_b = map_key_b.get((d_code, v_code, str(amt)), [])
                    if len(candidates_b) == 1:
                        match_idx = candidates_b[0]
                    else:
                        match_idx = -2
                
                if match_idx >= 0:
                    old_row = existing_rows[match_idx]
                    if idx_status >= 0 and len(old_row) > idx_status:
                        status_val = old_row[idx_status]
                    if idx_comment >= 0 and len(old_row) > idx_comment:
                        comment_val = old_row[idx_comment]
                    preserved_count += 1
                elif match_idx == -2:
                    cleared_count += 1
                
                kind = db_row["anomaly_type"]
                if not kind: kind = ""
                
                options = self._get_validation_options(kind)
                
                if status_val and options and status_val not in options:
                    status_val = ""
                
                new_row = [
                    status_val,
                    comment_val,
                    kind,
                    d_code,
                    db_row["dept_name"],
                    v_code,
                    db_row["vendor_name"],
                    db_row["transaction_date"],
                    amt
                ]
                new_rows.append(new_row)
                validations.append({"kind": kind, "options": options})

            # 4. 書き込み ---
            final_header = CORE_HEADERS
            final_data = [final_header] + new_rows
            
            sheet.clear()
            # 数式を有効にするため USER_ENTERED を指定 (現場用は不要なため削除)
            sheet.update(final_data, "A1", value_input_option='USER_ENTERED')
            
            sheet_id = sheet.id
            self._apply_header_format(sh, sheet_id, len(final_header))
            self._apply_mixed_validations(sh, sheet_id, validations)
            
            # 条件付き書式 (2026/02/04 追加)
            # C列(Index 2): 区分
            # G列(Index 6): 取引先名
            # H列(Index 7): 取引日付
            
            # 色定義
            COLOR_DUP = {"red": 1.0, "green": 0.8, "blue": 0.8}     # 薄い赤 (二重)
            COLOR_GAP = {"red": 1.0, "green": 1.0, "blue": 0.8}     # 薄い黄 (ズレ)
            COLOR_MISS = {"red": 0.8, "green": 0.9, "blue": 1.0}    # 薄い青 (モレ)

            requests = []
            
            # 既存の条件付き書式を削除・競合回避のため古いAPI呼び出しロジックは使わず
            # ここで全削除リクエストを入れるのはリスクがあるが、ツール制御なので入れる
            try:
                sheet_meta = client.open_by_key(site_sheet_id).fetch_sheet_metadata()
                curr_sheet = next((s for s in sheet_meta['sheets'] if s['properties']['sheetId'] == sheet_id), None)
                if curr_sheet and 'conditionalFormats' in curr_sheet:
                    for i in range(len(curr_sheet['conditionalFormats']) - 1, -1, -1):
                        requests.append({
                            "deleteConditionalFormatRule": {
                                "sheetId": sheet_id,
                                "index": i
                            }
                        })
            except:
                pass

            # 1. 二重 -> 取引先名(G列)
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1, "endRowIndex": len(final_data),
                            "startColumnIndex": 6, "endColumnIndex": 7
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": '=$C2="二重入力？"'}]
                            },
                            "format": {
                                "backgroundColor": COLOR_DUP
                            }
                        }
                    },
                    "index": 0
                }
            })
            
            # 2. ズレ -> 取引日付(H列)
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1, "endRowIndex": len(final_data),
                            "startColumnIndex": 7, "endColumnIndex": 8
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": '=$C2="月ズレ？"'}]
                            },
                            "format": {
                                "backgroundColor": COLOR_GAP
                            }
                        }
                    },
                    "index": 1
                }
            })
            
            # 3. モレ -> 取引先名(G列)
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1, "endRowIndex": len(final_data),
                            "startColumnIndex": 6, "endColumnIndex": 7
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": '=$C2="毎月あるのに今月ない"'}]
                            },
                            "format": {
                                "backgroundColor": COLOR_MISS
                            }
                        }
                    },
                    "index": 2
                }
            })
            
            # 4. 突合もれ -> 取引先名(G列) 薄い赤
            COLOR_RECONCILE_MISS = {"red": 1.0, "green": 0.85, "blue": 0.85}
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1, "endRowIndex": len(final_data),
                            "startColumnIndex": 6, "endColumnIndex": 7
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [{"userEnteredValue": '=$C2="もれ"'}]
                            },
                            "format": {
                                "backgroundColor": COLOR_RECONCILE_MISS
                            }
                        }
                    },
                    "index": 3
                }
            })
            
            if requests:
                sh.batch_update({"requests": requests})
            
            log.update({
                "updated": True,
                "rows_written": len(new_rows),
                "fields_preserved": preserved_count,
                "fields_cleared": cleared_count,
                "status": "success"
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            log["status"] = "error"
            log["error"] = str(e)
            
        return log

    def _fetch_site_data(self, db_path, run_id):
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # 部門指定なし、anomaly_typeがあるもののみ
            # 例外部門(masters_exception_dept) と 除外取引先(masters_exclude) を除外
            sql = f"""
                SELECT 
                    o.dept_code, o.dept_name, o.vendor_code, o.vendor_name,
                    o.payment_amount, o.transaction_date, o.anomaly_type
                FROM output_summary o
                LEFT JOIN masters_exception_dept ex_d ON o.dept_code = ex_d.dept_code
                LEFT JOIN masters_exclude ex_v ON o.vendor_code = ex_v.vendor_code
                WHERE o.run_id = ?
                  AND o.anomaly_type IS NOT NULL
                  AND o.anomaly_type != ''
                  AND NOT (o.anomaly_type = 'もれ' AND COALESCE(o.payment_amount, 0) = 0)
                  AND ex_d.dept_code IS NULL
                  AND ex_v.vendor_code IS NULL
                ORDER BY o.dept_code, o.vendor_code
            """
            cursor = conn.execute(sql, (run_id,))
            return [dict(row) for row in cursor.fetchall()]

    def _get_validation_options(self, kind: str) -> List[str]:
        if kind == "毎月あるのに今月ない":
            return ["今月実績なし", "申請済み"]
        elif kind == "月ズレ？":
            return ["ズレてません", "修正しました"]
        elif kind == "もれ":
            return ["申請しました", "コメントに理由記載"]
        elif kind == "二重入力？":
            return ["二重ではない", "削除しました"]
        return []

    def _apply_header_format(self, sh, sheet_id, col_count):
        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": col_count
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        }]
        sh.batch_update({"requests": requests})

    def _apply_mixed_validations(self, sh, sheet_id, validations):
        if not validations: return

        requests = []
        for i, val in enumerate(validations):
            row_idx = i + 1 
            options = val["options"]
            
            if options:
                condition = {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": opt} for opt in options]
                }
                rule = {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                            "startColumnIndex": 0, "endColumnIndex": 1
                        },
                        "rule": {
                            "condition": condition,
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                }
            else:
                rule = {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                            "startColumnIndex": 0, "endColumnIndex": 1
                        },
                        "rule": None
                    }
                }
            requests.append(rule)
            
        if requests:
            sh.batch_update({"requests": requests})

