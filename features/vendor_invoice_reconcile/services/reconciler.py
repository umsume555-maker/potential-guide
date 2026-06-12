from typing import List, Dict, Tuple
from collections import defaultdict
from ..models import InvoiceRecord, ReconcileResult
from ..repositories.master_repository import MasterRepository

class Reconciler:
    def __init__(self, master_repo: MasterRepository):
        self.master_repo = master_repo
        self.dept_master = self.master_repo.get_department_master() # Cache for display

    def _normalize_code(self, code) -> str:
        """
        Normalize department code to string (remove .0, whitespace, zero-pad to 8 digits)
        """
        if code is None:
            return ""
        s = str(code).strip()
        try:
            # Handle 20966520.0 / 3101010.0 case
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except:
            pass
        # 8桁以下の数字コードは先頭ゼロでパディング（例: 3101010 → 03101010）
        if s.isdigit() and len(s) < 8:
            s = s.zfill(8)
        return s

    def reconcile(self, 
                  base_month: str, 
                  vendor_code: str, 
                  vendor_name: str,
                  invoice_records: List[InvoiceRecord]) -> List[ReconcileResult]:
        """
        請求一覧(invoice_records) と E2実績(DB) を突合する
        ユーザー要望(2025-02): 
        - Double Input: Base count(Dept+Amt)>=2 AND Prev count(Dept)<=1. Apply to ALL.
        - Date Diff: Base count(Dept)==0 AND Next count(Dept)>=1.
        - Recurring Missing: Base count(Dept)==0 AND Monthly Check(Past 4m)>=3 AND Not Date Diff.
        - Missing > Recurring Missing checks.
        """
        results = []
        
        # 1. Date Calculation
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        
        try:
            dt = datetime.strptime(base_month + "-01", "%Y-%m-%d")
            next_month = (dt + relativedelta(months=1)).strftime("%Y-%m")
            prev_month_1 = (dt - relativedelta(months=1)).strftime("%Y-%m")
            prev_month_2 = (dt - relativedelta(months=2)).strftime("%Y-%m")
            prev_month_3 = (dt - relativedelta(months=3)).strftime("%Y-%m")
            prev_month_4 = (dt - relativedelta(months=4)).strftime("%Y-%m")
        except:
            next_month = base_month 
            prev_month_1 = base_month
            prev_month_2 = base_month
            prev_month_3 = base_month
            prev_month_4 = base_month
            
        # 2. Fetch E2 Data (Base + Next + Prev 4 months)
        e2_rows_base = self.master_repo.get_cumulative_data(base_month, [vendor_code])
        e2_rows_next = self.master_repo.get_cumulative_data(next_month, [vendor_code])
        e2_rows_p1 = self.master_repo.get_cumulative_data(prev_month_1, [vendor_code])
        e2_rows_p2 = self.master_repo.get_cumulative_data(prev_month_2, [vendor_code])
        e2_rows_p3 = self.master_repo.get_cumulative_data(prev_month_3, [vendor_code])
        e2_rows_p4 = self.master_repo.get_cumulative_data(prev_month_4, [vendor_code])
        
        # Helper: Count rows per Dept
        def count_per_dept(rows, ignore_zero=False):
            c = defaultdict(int)
            for r in rows:
                d = self._normalize_code(r["dept_code"])
                if d: 
                    if ignore_zero:
                        try:
                            # Keep robust: handle None, handle commas, handle yen sign
                            raw_val = str(r["payment_amount"] or 0).replace(",", "").replace("¥", "")
                            amt = float(raw_val)
                            if amt == 0:
                                continue
                        except:
                            continue
                    c[d] += 1
            return c

        count_base_dept = count_per_dept(e2_rows_base, ignore_zero=False)
        count_next_dept = count_per_dept(e2_rows_next, ignore_zero=False)
        count_p1_dept = count_per_dept(e2_rows_p1, ignore_zero=True)
        count_p2_dept = count_per_dept(e2_rows_p2, ignore_zero=True)
        count_p3_dept = count_per_dept(e2_rows_p3, ignore_zero=True)
        count_p4_dept = count_per_dept(e2_rows_p4, ignore_zero=True)

        # Helper: Count per (Dept, Amount) for Double Input
        count_base_dept_amt = defaultdict(int)
        for r in e2_rows_base:
            d = self._normalize_code(r["dept_code"])
            try: amt = int(float(r["payment_amount"] or 0))
            except: amt = 0
            if d: 
                count_base_dept_amt[(d, amt)] += 1
                if d == "20301530":
                     print(f"[RECONCILE_DEBUG] Counting Base: Dept={d}, Amt={amt}, NewCount={count_base_dept_amt[(d, amt)]}")

        # 3. Build Match Pool (Base Only? Or Base+Next?)
        # Current logic matches Base+Next.
        
        e2_pool = defaultdict(list)
        e2_rows_match_candidates = e2_rows_base + e2_rows_next
        for row in e2_rows_match_candidates:
            d_code = self._normalize_code(row["dept_code"])
            if not d_code: continue
            try: amt = int(float(row["payment_amount"] or 0))
            except: amt = 0
            e2_pool[(d_code, amt)].append(row)

        # 4. Process Invoices
        unmapped_records = []
        mapped_invoices = []
        
        for rec in invoice_records:
            if rec.candidate_dept_codes:
                best_code = self._normalize_code(rec.candidate_dept_codes[0])
                try: rec_amount = int(float(rec.raw_amount or 0))
                except: rec_amount = 0
                
                # Try strict match
                for code in rec.candidate_dept_codes:
                    code_str = self._normalize_code(code)
                    if (code_str, rec_amount) in e2_pool and e2_pool[(code_str, rec_amount)]:
                        best_code = code_str
                        break
                rec.mapped_dept_code = best_code
            
            if rec.mapped_dept_code:
                mapped_invoices.append(rec)
            else:
                unmapped_records.append(rec)
                
        # 5. Matching Logic & Result Generation
        processed_depts = set() # Track depts that have results (OK, MISSING, etc.)
        
        # Aggregate multiple invoice rows for the same mapped_dept_code
        aggregated_invoices = {}
        for rec in mapped_invoices:
            d_code = self._normalize_code(rec.mapped_dept_code)
            if d_code not in aggregated_invoices:
                aggregated_invoices[d_code] = {
                    "raw_amount": 0,
                    "records": [],
                    "mapped_dept_name": rec.mapped_dept_name
                }
            try:
                amt = int(float(rec.raw_amount or 0))
            except:
                amt = 0
            aggregated_invoices[d_code]["raw_amount"] += amt
            aggregated_invoices[d_code]["records"].append(rec)

        for d_code, agg_data in aggregated_invoices.items():
            processed_depts.add(d_code) # Mark as processed
            # 同じ請求書レコードの全候補部門コードも処理済みにする
            # → DATE_DIFF で第1候補に紐づいた場合、第2候補が RECURRING_MISSING にならないよう防止
            for _rec in agg_data["records"]:
                for _cand in (_rec.candidate_dept_codes or []):
                    processed_depts.add(self._normalize_code(_cand))
            
            amt = agg_data["raw_amount"]
            
            match_row = None
            if (d_code, amt) in e2_pool and e2_pool[(d_code, amt)]:
                match_row = e2_pool[(d_code, amt)].pop(0)
            
            status = "MISSING"
            tx_date = ""
            dept_name = ""
            
            if match_row:
                status = "OK"
                dept_name = match_row["dept_name"]
                tx_date = match_row["transaction_date"]
                
                # Check Date Diff (Matched Next Month?)
                is_next = match_row in e2_rows_next
                if is_next:
                    status = "DATE_DIFF" # Transaction Date Diff (Paid Next Month)
            
            if not dept_name and d_code in self.dept_master:
                dept_name = self.dept_master[d_code]
            if not dept_name:
                dept_name = agg_data["mapped_dept_name"]

            # Double Input Check (Apply to Matched too)
            if status in ["OK", "DATE_DIFF"]:
                 c_base = count_base_dept_amt.get((d_code, amt), 0)
                 c_prev = count_p1_dept.get(d_code, 0)
                 if c_base >= 2 and c_prev <= 1:
                     status = "DOUBLE_INPUT"

            res = ReconcileResult(
                base_month=base_month,
                vendor_code=vendor_code,
                vendor_name=vendor_name,
                dept_code=d_code,
                dept_name=str(dept_name),
                invoice_amount=amt,
                payment_amount=amt,
                diff_amount=0,
                status=status,
                details=agg_data["records"],
                transaction_date=tx_date
            )
            results.append(res)
            
        # 6. Excess E2 Items (Base Month Only) -> Double Input or Excess(Hidden)
        # Note: e2_pool contains leftovers.
        for (d_code, amt), rows in e2_pool.items():
            # Filter 0 yen items from Excess check
            if amt == 0:
                continue

            for row in rows:
                if row in e2_rows_base:
                    processed_depts.add(d_code) # Mark as processed
                else:
                    continue # Skip Next Month leftovers (Date Diff handled by scan later? No, Unmatched Next items are ignored)

                dept_name = row["dept_name"]
                if not dept_name and d_code in self.dept_master:
                     dept_name = self.dept_master[d_code]
                
                # Double Input Check
                c_base = count_base_dept_amt.get((d_code, amt), 0)
                # P1 count excludes 0, which is correct for meaningful comparison
                c_prev = count_p1_dept.get(d_code, 0)
                
                if c_base >= 2 and c_prev <= 1:
                    status = "DOUBLE_INPUT"
                else:
                    status = "EXCESS" # Hidden

                res = ReconcileResult(
                    base_month=base_month,
                    vendor_code=vendor_code,
                    vendor_name=vendor_name,
                    dept_code=d_code,
                    dept_name=dept_name,
                    invoice_amount=0,
                    payment_amount=amt,
                    diff_amount=-amt,
                    status=status,
                    details=[],
                    transaction_date=row["transaction_date"]
                )
                results.append(res)

        # 7. Scan for Date Diff (Unmatched Base=0, Next>=1)
        # Identify Depts with Base=0 but Next>=1
        # This covers "No Invoice" scenarios too.
        # But wait, we processed Invoices. If Invoice matched Next, we handled it.
        # If Invoice Missing (Base data missing), we marked MISSING.
        # Does User want "Missing Invoice" to become "Date Diff" if Next exists?
        # User: "Transaction Date Diff is Base=0, Next>=1".
        # If Invoice Missing (Base=0 in E2), and Next>=1.
        # Then it fits definition.
        # But we already output MISSING result?
        # If we have MISSING result (Invoice exist), it means we failed to match E2.
        # If we failed to match E2, calculate status.
        # Wait, if Invoice matches Next E2, we set DATE_DIFF.
        # If Invoice matches nothing, we set MISSING.
        
        # What about "No Invoice, No Base E2, But Next E2"?
        # This is "Pure Date Diff" (unclaimed in base, appears in next).
        # Should we report it?
        # User said "Base=0, Next>=1" is Date Diff.
        # I will report these as "Date Diff" results (Unmatched E2 in Next).
        # We need to find depts with Base=0, Next>=1.
        
        # Simpler: Iterate e2_pool leftovers again for Next Month items that imply Date Diff
        for (d_code, amt), rows in e2_pool.items():
            for row in rows:
                if row in e2_rows_next:
                    # Unmatched Next Month item.
                    # Check Base Count for this Dept.
                    if count_base_dept[d_code] == 0:
                        processed_depts.add(d_code) # Mark as processed
                        # Base=0, Next>=1 (since this row exists).
                        # Status = DATE_GAP (Month Shift).
                        res = ReconcileResult(
                            base_month=base_month,
                            vendor_code=vendor_code,
                            vendor_name=vendor_name,
                            dept_code=d_code,
                            dept_name=row["dept_name"] or self.dept_master.get(d_code, ""),
                            invoice_amount=0,
                            payment_amount=amt,
                            diff_amount=-amt,
                            status="DATE_GAP",
                            details=[],
                            transaction_date=row["transaction_date"],
                            note="月ズレ？"
                        )
                        results.append(res)
            
        # 8. Recurring Missing — 全取引先を対象にチェック
        # 突合実行中の取引先（vendor_code）とTarget Vendors、および除外取引先（Excluded Vendors）は除外
        target_vendors = self.master_repo.get_target_vendors()
        excluded_vendors_master = self.master_repo.get_excluded_vendors()
        
        exclude_vendors = list(set([vendor_code] + target_vendors + excluded_vendors_master))
        
        # 全取引先の月別データを取得（除外リスト以外）
        all_rows_base = self.master_repo.get_cumulative_data_all(base_month, exclude_vendors)
        all_rows_next = self.master_repo.get_cumulative_data_all(next_month, exclude_vendors)
        all_rows_p1 = self.master_repo.get_cumulative_data_all(prev_month_1, exclude_vendors)
        all_rows_p2 = self.master_repo.get_cumulative_data_all(prev_month_2, exclude_vendors)
        all_rows_p3 = self.master_repo.get_cumulative_data_all(prev_month_3, exclude_vendors)
        all_rows_p4 = self.master_repo.get_cumulative_data_all(prev_month_4, exclude_vendors)
        
        # (dept_code, vendor_code) の組み合わせ別にカウント
        def count_per_dv(rows):
            """部門+取引先の組み合わせ別にカウント"""
            c = defaultdict(int)
            for r in rows:
                d = self._normalize_code(r["dept_code"])
                v = str(r.get("vendor_code", "")).strip()
                if d and v:
                    c[(d, v)] += 1
            return c
        
        cnt_base = count_per_dv(all_rows_base)
        cnt_next = count_per_dv(all_rows_next)
        cnt_p1 = count_per_dv(all_rows_p1)
        cnt_p2 = count_per_dv(all_rows_p2)
        cnt_p3 = count_per_dv(all_rows_p3)
        cnt_p4 = count_per_dv(all_rows_p4)
        
        # 過去4ヶ月に存在する全ての (dept, vendor) ペアを収集
        all_dv_pairs = set()
        for r in all_rows_p1 + all_rows_p2 + all_rows_p3 + all_rows_p4:
            d = self._normalize_code(r["dept_code"])
            v = str(r.get("vendor_code", "")).strip()
            if d and v:
                all_dv_pairs.add((d, v))
        
        # 取引先名マスタ（全取引先マスタから取得）
        vendor_names = self.master_repo.get_all_vendor_names()
        
        for (d_code, v_code) in all_dv_pairs:
            # If already processed (e.g. MISSING or OK), skip Recurring Missing
            if v_code == vendor_code and d_code in processed_depts:
                # Only check processed_depts for the CURRENT analyzing vendor
                # Because processed_depts only tracks the current vendor's departments
                continue

            # 今月に取引があるならスキップ
            if cnt_base[(d_code, v_code)] > 0:
                continue
            
            # 過去4ヶ月で3回以上か (合計回数)
            monthly = cnt_p1[(d_code, v_code)] + cnt_p2[(d_code, v_code)] + cnt_p3[(d_code, v_code)] + cnt_p4[(d_code, v_code)]
            if monthly < 3:
                continue
            
            # 翌月に取引があるならスキップ（月ズレの可能性）
            # -> 「月ズレ？」として追加する (User Requirement)
            # 翌月に取引があるならスキップ（月ズレの可能性）
            # -> 「月ズレ？」として追加する (User Requirement)
            if cnt_next[(d_code, v_code)] > 0:
                d_name = self.dept_master.get(d_code, "")
                v_name = vendor_names.get(v_code, "")
                
                # Fetch date from next month data
                next_date = ""
                for r in all_rows_next:
                    if self._normalize_code(r["dept_code"]) == d_code and str(r.get("vendor_code", "")).strip() == v_code:
                        next_date = r["transaction_date"]
                        break

                res = ReconcileResult(
                    base_month=base_month,
                    vendor_code=v_code,
                    vendor_name=str(v_name),
                    dept_code=d_code,
                    dept_name=str(d_name),
                    invoice_amount=0,
                    payment_amount=0,
                    diff_amount=0,
                    status="DATE_GAP", # Internal status for Date Gap
                    details=[],
                    transaction_date=next_date,
                    note="月ズレ？"
                )
                results.append(res)
                continue
            
            # RECURRING_MISSING を生成
            d_name = self.dept_master.get(d_code, "")
            v_name = vendor_names.get(v_code, "")
            
            res = ReconcileResult(
                base_month=base_month,
                vendor_code=v_code,
                vendor_name=str(v_name),
                dept_code=d_code,
                dept_name=str(d_name),
                invoice_amount=0,
                payment_amount=0,
                diff_amount=0,
                status="RECURRING_MISSING",
                details=[],
                transaction_date=""
            )
            results.append(res)
        
        # 9. Unmapped (Keep existing)
        unmapped_grouped: Dict[str, List[InvoiceRecord]] = defaultdict(list)
        for rec in unmapped_records:
            unmapped_grouped[rec.raw_dept_name].append(rec)
            
        for raw_name, recs in unmapped_grouped.items():
            total_amt = sum(int(r.raw_amount or 0) for r in recs)
            res = ReconcileResult(
                base_month=base_month,
                vendor_code=vendor_code,
                vendor_name=vendor_name,
                dept_code="UNMAPPED",
                dept_name=raw_name, 
                invoice_amount=total_amt,
                payment_amount=0, 
                diff_amount=total_amt,
                status="UNMAPPED",
                details=recs,
                note="マスタ未登録"
            )
            results.append(res)
            
        # 10. Set is_monthly flag for all results [NEW]
        for res in results:
            d = self._normalize_code(res.dept_code)
            if not d or d == "UNMAPPED":
                res.is_monthly = ""
                continue
                
            c1 = count_p1_dept[d]
            c2 = count_p2_dept[d]
            c3 = count_p3_dept[d]
            c4 = count_p4_dept[d]
            if (c1 + c2 + c3 + c4) >= 3:
                res.is_monthly = "毎月"
            else:
                res.is_monthly = ""

        results.sort(key=lambda x: x.dept_code or "")
        return results
