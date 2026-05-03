# domain/services/invoice_match_service.py
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from invoice_ocr.folder_scanner import scan_folder, ApprovalFolder
from invoice_ocr.ocr_engine import ocr_pdf, ocr_image_file
from invoice_ocr.extractor import extract_all
from invoice_ocr.scoring import calculate_score
from invoice_ocr.ai_ocr import extract_billing_amount_with_gemini, get_gemini_api_key

class InvoiceMatchService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config()

    def _load_config(self):
        try:
            import yaml
            # domain/services/ -> root
            base_dir = Path(__file__).resolve().parent.parent.parent
            config_path = base_dir / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
        except Exception:
            pass
        return None

    async def process_and_match(self, run_id: str, zip_out_path: Path, fast: bool = False) -> dict:
        """
        ZIP展開後のフォルダをスキャンし、OCR実行・突合を行う

        Args:
            fast: Trueの場合、Geminiによる傾き補正をスキップして高速化
        """
        self.logger.info(f"Starting OCR matching for RunID: {run_id}")
        
        # 1. フォルダスキャン
        folders = scan_folder(zip_out_path)
        self.logger.info(f"Found {len(folders)} approval folders")
        
        # 既に処理済みのapproval_noを取得（再開機能用）
        processed_approval_nos = set()
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT DISTINCT approval_no FROM invoice_ocr_results WHERE run_id = ?", (run_id,))
                processed_approval_nos = {row[0] for row in cursor.fetchall()}
            if processed_approval_nos:
                self.logger.info(f"Found {len(processed_approval_nos)} already processed approvals, skipping them")
        except Exception as e:
            self.logger.warning(f"Failed to get processed list: {e}")
        
        processed_count = 0
        match_ok_count = 0
        
        # 2. DBから申請データを取得 (キー: (dept_code, vendor_code) -> List[summary_row])
        # ユーザー要件: 部門コード&取引先コードでぶつける。同条件2件以上は金額も加味。
        summary_map = self._get_summary_map(run_id)
        
        # 取引先ごとのGemini強制フラグを取得
        vendor_flags = self._get_vendor_flags()
        
        results_to_save = []
        
        # 3. 各フォルダ（OCR対象）ごとに処理
        for folder in folders:
            # フォルダ情報
            folder_approval_no = folder.approval_no
            
            # 既に処理済みならスキップ（再開機能）
            if folder_approval_no in processed_approval_nos:
                continue
            
            dept_code = folder.dept_code
            dept_name = folder.dept_name
            vendor_code = folder.vendor_code
            vendor_name = folder.vendor_name
            
            # Gemini強制フラグ確認
            force_model = vendor_flags.get(vendor_code)
            
            # ファイルを請求書と稟議書に分類
            invoice_files = []
            ringi_files = []

            for file_path in folder.files:
                if self._is_ringi_file(file_path):
                    ringi_files.append(file_path)
                else:
                    invoice_files.append(file_path)

            has_ringi = len(ringi_files) > 0

            # 請求書ファイルがない場合はスキップ
            if not invoice_files:
                self.logger.warning(f"No invoice files found in {folder_approval_no}")
                continue

            # OCR対象: 複数の請求書がある場合はファイルサイズが最大のものを使用
            if len(invoice_files) > 1:
                ocr_target = max(invoice_files, key=lambda f: f.stat().st_size)
                self.logger.info(f"Multiple invoices found for {folder_approval_no}, OCR-ing largest: {ocr_target.name}")
            else:
                ocr_target = invoice_files[0]

            # 請求書ファイルをOCR処理（金額検出用は最大ファイル）
            file_path = ocr_target
            ocr_result = self._perform_ocr(file_path, force_model=force_model)
            extracted = extract_all(ocr_result.text)

            # PDF正立化（ハイブリッド版）: Geminiで向き判定 → /Rotate を書き戻す
            # テキストPDFでもコンテンツが傾いて描画されている場合があるため全PDFを対象とする
            # fast=True の場合は回転補正自体をスキップ（高速化）
            if not fast and file_path.suffix.lower() == ".pdf":
                try:
                    from invoice_ocr.pdf_tools import normalize_pdf_rotation_via_gemini
                    api_key = get_gemini_api_key(self.db_path)
                    if api_key:
                        rot_model = (
                            self.config.get("ai_ocr", {}).get("model", "gemini-2.0-flash")
                            if self.config else "gemini-2.0-flash"
                        )
                        changed = normalize_pdf_rotation_via_gemini(file_path, api_key, rot_model)
                        if changed:
                            self.logger.info(f"PDF rotation normalized: {file_path.name} ({changed} pages)")
                except Exception as e:
                    self.logger.warning(f"PDF rotation normalize skipped: {file_path.name} - {e}")
            
            # --- AI Structural Extraction (Post-process override) ---
            # Gemini強制フラグがある場合、構造化データ抽出を試みる
            if force_model and file_path.suffix.lower() == ".pdf":
                 api_key = get_gemini_api_key(self.db_path)
                 if api_key:
                     try:
                         # モデル指定があれば使う（force_modelは "gemini-2.0-flash" などの文字列が入っているはず、あるいは "1"/"2" か？）
                         # _get_vendor_flagsの実装を見ると、masters_ai_setting.gemini_flag の値をそのまま返している。
                         # 値は "1" (Model A), "2" (Model B), またはモデル名そのものかもしれない。
                         # ocr_engine.py では "1" -> model_a, "2" -> model_b と変換している。
                         # ここでも同様の変換が必要だが、簡易的に config から取れるか？
                         # ocr_pdf 内で解決済みだが、ここでは新たに関数を呼ぶのでモデル名が必要。
                         
                         target_model = "gemini-2.0-flash" # Default
                         if force_model == "1":
                             target_model = self.config.get("ai_ocr", {}).get("model_a", "gemini-2.0-flash")
                         elif force_model == "2":
                             target_model = self.config.get("ai_ocr", {}).get("model_b", "gemini-2.0-flash")
                         elif force_model.startswith("gemini"):
                             target_model = force_model

                         ai_data, ai_conf = extract_billing_amount_with_gemini(file_path, api_key, model=target_model)
                         
                         if ai_data.get("amount") is not None:
                             self.logger.info(f"AI Extracted Amount: {ai_data['amount']} (Legacy: {extracted.amount})")
                             extracted.amount = int(ai_data["amount"])
                             ocr_result.method = f"gemini_structure ({target_model})"
                             
                             # Date override if available and looks valid
                             if ai_data.get("date"):
                                 extracted.date = ai_data["date"]
                                 
                     except Exception as e:
                         self.logger.error(f"AI Structural Extraction Failed: {e}")
            # -------------------------------------------------------
            
            # スコアリング
            score = calculate_score(
                extracted.amount,
                extracted.confidence,
                extracted.invoice_number,
                extracted.has_reduced_tax,
                ocr_result.confidence
            )
            
            detected_amount = extracted.amount
            
            # 全ファイル名を記録（請求書 + 稟議書、カンマ区切り）
            all_files = invoice_files + ringi_files
            file_names = ",".join(f.name for f in all_files)
            
            # --- 突合ロジック ---
            candidates = summary_map.get((dept_code, vendor_code), [])
            
            matched_summary = None
            match_status = "UNCHECKED"
            amount_diff = None
            target_decision_no = None
            
            if not candidates:
                # 候補なし (UNMATCHED)
                match_status = "UNMATCHED"
                self.logger.warning(f"No summary found for {dept_code}-{vendor_code}")
            else:
                # 候補がある場合
                if len(candidates) == 1:
                    # 1件ならそれを採用
                    matched_summary = candidates[0]
                else:
                    # 複数ある場合、金額で絞り込み
                    if detected_amount is not None:
                        # 1. 完全一致を探す
                        exact_matches = [c for c in candidates if c['amount'] == detected_amount]
                        if exact_matches:
                            matched_summary = exact_matches[0] # 複数あれば先頭
                        else:
                            # 2. なければ差分が最小のものを探す（NGとして表示するため）
                            matched_summary = min(candidates, key=lambda c: abs((c['amount'] or 0) - detected_amount))
                    else:
                        # 金額不明なら先頭を採用
                        matched_summary = candidates[0]
                
                # 判定
                target_decision_no = matched_summary['decision_no']
                actual_amount = matched_summary['amount']
                
                if detected_amount is not None and actual_amount is not None:
                    amount_diff = detected_amount - actual_amount
                    if amount_diff == 0:
                        match_status = "OK"
                        match_ok_count += 1
                    else:
                        match_status = "NG"
                elif detected_amount is None:
                    match_status = "WARNING" # OCR失敗
                else:
                    match_status = "NG" # 相手方金額不明など
            
            results_to_save.append({
                "run_id": run_id,
                "approval_no": folder_approval_no, # フォルダ名の承認番号
                "file_name": file_names,
                "dept_code": dept_code,
                "dept_name": dept_name,
                "vendor_code": vendor_code,
                "vendor_name": vendor_name,
                "target_decision_no": target_decision_no, # 紐付いた決裁番号
                "detected_amount": detected_amount,
                "detected_invoice_no": extracted.invoice_number,
                "detected_date": extracted.date,
                "has_reduced_tax": 1 if extracted.has_reduced_tax else 0,
                "has_ringi": 1 if has_ringi else 0,  # フォルダ内の稟議書有無
                "status": folder.status,
                "confidence": score.total_score,
                "ocr_method": ocr_result.method,
                "match_status": match_status,
                "amount_diff": amount_diff
            })
            
            processed_count += 1
            
            # --- 中間保存 (10件ごと) ---
            if len(results_to_save) >= 10:
                self._save_results(results_to_save)
                results_to_save = [] # クリア
                self.logger.info(f"Saved intermediate results: {processed_count} files processed")
        
        # 4. 残りを保存
        if results_to_save:
            self._save_results(results_to_save)
        
        return {
            "processed_files": processed_count,
            "match_ok": match_ok_count,
            "match_ng": processed_count - match_ok_count
        }

    def _get_summary_map(self, run_id: str) -> Dict[Tuple[str, str], List[dict]]:
        """出力サマリから (dept_code, vendor_code) -> List[レコード] のマップを作成"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT decision_no, dept_code, vendor_code, payment_amount
                FROM output_summary
                WHERE run_id = ?
            """, (run_id,))
            
            result = {}
            for row in cursor.fetchall():
                key = (row["dept_code"], row["vendor_code"])
                if key not in result:
                    result[key] = []
                
                result[key].append({
                    "decision_no": row["decision_no"],
                    "amount": row["payment_amount"]
                })
            return result

    def _get_vendor_flags(self) -> Dict[str, str]:
        """取引先ごとのGemini強制フラグを取得（AI設定マスタ）"""
        flags = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # masters_ai_settingから取得
                cursor = conn.execute("SELECT vendor_code, gemini_flag FROM masters_ai_setting WHERE gemini_flag IS NOT NULL AND gemini_flag != ''")
                for row in cursor.fetchall():
                    flags[row["vendor_code"]] = str(row["gemini_flag"])
        except Exception as e:
            # テーブル未作成時など
            print(f"[WARN] Failed to load ai settings: {e}")
        return flags

    def _is_ringi_file(self, file_path: Path) -> bool:
        """稟議書ファイルかどうかを判定"""
        filename_lower = file_path.name.lower()
        # 稟議書を示すキーワード
        ringi_keywords = ['ringi', 'ringisho', '稟議', 'りんぎ']
        return any(keyword in filename_lower for keyword in ringi_keywords)
    
    def _perform_ocr(self, file_path: Path, force_model: Optional[str] = None):
        """ファイルタイプに応じてOCR実行"""
        if file_path.suffix.lower() == ".pdf":
            return ocr_pdf(file_path, config=self.config, db_path=self.db_path, force_model=force_model)
        else:
            return ocr_image_file(file_path, config=self.config, db_path=self.db_path, force_model=force_model)

    def _save_results(self, results: List[dict]):
        """結果をDBに一括保存"""
        if not results:
            return
            
        with sqlite3.connect(self.db_path) as conn:
            # target_decision_no, dept_code, vendor_code, status, detected_date, has_ringi を追加
            conn.executemany("""
                INSERT OR REPLACE INTO invoice_ocr_results (
                    run_id, approval_no, file_name,
                    dept_code, vendor_code, target_decision_no,
                    detected_amount, detected_invoice_no, detected_date,
                    has_reduced_tax, has_ringi, status,
                    confidence, ocr_method,
                    match_status, amount_diff
                ) VALUES (
                    :run_id, :approval_no, :file_name,
                    :dept_code, :vendor_code, :target_decision_no,
                    :detected_amount, :detected_invoice_no, :detected_date,
                    :has_reduced_tax, :has_ringi, :status,
                    :confidence, :ocr_method,
                    :match_status, :amount_diff
                )
            """, results)
