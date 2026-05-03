"""
正マスター（税・科目ルール・強制修正）へのアクセスを提供するリポジトリ
"""
from typing import Optional, List, Dict
from datetime import datetime
import sqlite3

class RuleRepository:
    """税区分・科目ルールおよび強制修正の操作を行う"""

    @staticmethod
    def normalize_code(code: Optional[str]) -> str:
        if code is None:
            return ""
        s = str(code).strip()
        if s.endswith(".0"):
            return s[:-2]
        return s

    # --- 共通ヘルパー ---

    @staticmethod
    def normalize_dept_code(code: Optional[str]) -> str:
        """部門コードを正規化（8桁ゼロパディング）"""
        if code is None:
            return ""
        s = str(code).strip()
        if s.endswith(".0"):
            s = s[:-2]
        # masters_departmentは8桁ゼロパディング形式
        if s.isdigit() and len(s) < 8:
            s = s.zfill(8)
        return s

    def get_dept_type(self, conn: sqlite3.Connection, dept_code: str) -> Optional[str]:
        """部門コードから部門タイプを取得"""
        norm = self.normalize_dept_code(dept_code)
        cursor = conn.execute(
            "SELECT dept_type FROM masters_department WHERE dept_code = ?",
            (norm,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        # フォールバック: そのままのコードで再検索（8桁超など）
        raw = self.normalize_code(dept_code)
        if raw != norm:
            cursor = conn.execute(
                "SELECT dept_type FROM masters_department WHERE dept_code = ?",
                (raw,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        return None

    def get_override(self, conn: sqlite3.Connection, vendor_code: str, dept_code: str, field_name: str) -> Optional[str]:
        """強制修正値を取得 (有効なもののみ)"""
        # 特定部門へのOverride
        cursor = conn.execute(
            """
            SELECT new_value FROM override_rule 
            WHERE vendor_code = ? AND dept_code = ? AND field_name = ? AND is_active = 1
            ORDER BY id DESC LIMIT 1
            """,
            (self.normalize_code(vendor_code), self.normalize_code(dept_code), field_name)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
            
        # 全部門対象のOverride (dept_code IS NULL) ?
        # 今回の要件では「dept_code TEXT」だが、NULLで全対象とするか？
        # 一般にOverrideは個別対応なので、まずは「部門指定」のみを優先実装
        # 必要ならここで fetch logic を追加
        return None

    # --- 解決ロジック (Resolve) ---

    def resolve_tax(self, conn: sqlite3.Connection, vendor_code: str, dept_code: str) -> Optional[str]:
        """
        税区分の正解を解決
        Priority:
        1. Override (Vendor + Dept) - 既存互換（未使用？）
        2. Rule (Vendor + Scope:DEPT + Key:DeptCode)
        3. Rule (Vendor + Scope:DEPT_TYPE + Key:DeptType)
        4. Rule (Vendor) - rule_tax_master
        """
        v_code = self.normalize_code(vendor_code)
        d_code = self.normalize_code(dept_code)

        # 1. Override (Existing)
        override = self.get_override(conn, v_code, d_code, 'expected_tax')
        if override:
            return override

        # 2. Rule: DEPT Specific (例外)
        cursor = conn.execute(
            """
            SELECT expected_tax FROM rule_tax_rules 
            WHERE vendor_code = ? AND scope_type = 'DEPT' AND scope_key = ?
            """,
            (v_code, d_code)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # 3. Rule: DEPT_TYPE (COST/SGA) (例外)
        dept_type = self.get_dept_type(conn, d_code)
        if dept_type:
            cursor = conn.execute(
                """
                SELECT expected_tax FROM rule_tax_rules 
                WHERE vendor_code = ? AND scope_type = 'DEPT_TYPE' AND scope_key = ?
                """,
                (v_code, dept_type)
            )
            row = cursor.fetchone()
            if row:
                return row[0]

        # 4. Rule Tax Master (Default)
        cursor = conn.execute(
            "SELECT expected_tax FROM rule_tax_master WHERE vendor_code = ?",
            (v_code,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
            
        return None

    # --- Tax Rule Exceptions CRUD ---

    def get_tax_rule_exceptions(self, conn: sqlite3.Connection, vendor_code: str) -> List[Dict]:
        """税区分例外ルール一覧取得"""
        v_code = self.normalize_code(vendor_code)
        cursor = conn.execute(
            """
            SELECT id, vendor_code, scope_type, scope_key, expected_tax, reason, updated_at
            FROM rule_tax_rules
            WHERE vendor_code = ?
            ORDER BY scope_type DESC, scope_key ASC
            """,
            (v_code,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def upsert_tax_rule_exception(self, conn: sqlite3.Connection, vendor_code: str, scope_type: str, scope_key: str, expected_tax: str, updated_by: str, reason: str):
        """税区分例外ルールの登録/更新"""
        now = datetime.now().isoformat()
        v_code = self.normalize_code(vendor_code)
        s_key = self.normalize_code(scope_key) if scope_key else ""
        
        # Check existence
        cursor = conn.execute(
            """
            SELECT id FROM rule_tax_rules 
            WHERE vendor_code = ? AND scope_type = ? AND scope_key = ?
            """,
            (v_code, scope_type, s_key)
        )
        row = cursor.fetchone()

        if row:
            # UPDATE
            conn.execute(
                """
                UPDATE rule_tax_rules 
                SET expected_tax = ?, updated_by = ?, updated_at = ?, reason = ?
                WHERE id = ?
                """,
                (expected_tax, updated_by, now, reason, row[0])
            )
        else:
            # INSERT
            conn.execute(
                """
                INSERT INTO rule_tax_rules (vendor_code, scope_type, scope_key, expected_tax, updated_by, updated_at, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (v_code, scope_type, s_key, expected_tax, updated_by, now, reason)
            )

    def delete_tax_rule_exception(self, conn: sqlite3.Connection, rule_id: int):
        """税区分例外ルールの削除"""
        conn.execute("DELETE FROM rule_tax_rules WHERE id = ?", (rule_id,))


    def resolve_account(self, conn: sqlite3.Connection, vendor_code: str, dept_code: str) -> Optional[str]:
        """
        科目の正解を解決 (3段階優先順位)
        Priority:
        1. Override (Vendor + Dept)
        2. Rule (Vendor + Scope:DEPT + Key:DeptCode)
        3. Rule (Vendor + Scope:DEPT_TYPE + Key:DeptType)
        4. Rule (Vendor + Scope:ANY)
        """
        v_code = self.normalize_code(vendor_code)
        d_code = self.normalize_code(dept_code)

        # 1. Override
        override = self.get_override(conn, v_code, d_code, 'expected_account')
        if override:
            return override

        # 2. Rule: DEPT Specific
        cursor = conn.execute(
            """
            SELECT expected_account FROM rule_account_master 
            WHERE vendor_code = ? AND scope_type = 'DEPT' AND scope_key = ?
            """,
            (v_code, d_code)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # 3. Rule: DEPT_TYPE (exact match)
        dept_type = self.get_dept_type(conn, d_code)
        if dept_type:
            cursor = conn.execute(
                """
                SELECT expected_account FROM rule_account_master
                WHERE vendor_code = ? AND scope_type = 'DEPT_TYPE' AND scope_key = ?
                """,
                (v_code, dept_type)
            )
            row = cursor.fetchone()
            if row:
                return row[0]

        # 3b. Rule: DEPT_TYPE fallback (他の DEPT_TYPE ルールを代用)
        #   COST/SGA どちらか一方しか登録がない場合、もう一方の部門からの請求にも適用する
        cursor = conn.execute(
            """
            SELECT expected_account FROM rule_account_master
            WHERE vendor_code = ? AND scope_type = 'DEPT_TYPE'
            ORDER BY scope_key
            LIMIT 1
            """,
            (v_code,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        # 4. Rule: ANY
        cursor = conn.execute(
            """
            SELECT expected_account FROM rule_account_master
            WHERE vendor_code = ? AND scope_type = 'ANY'
            """,
            (v_code,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        return None

    # --- 登録・更新 (Upsert) ---

    def upsert_tax_rule(self, conn: sqlite3.Connection, vendor_code: str, expected_tax: str, updated_by: str, reason: str):
        """税区分ルールの登録"""
        now = datetime.now().isoformat()
        v_code = self.normalize_code(vendor_code)
        
        conn.execute(
            """
            INSERT INTO rule_tax_master (vendor_code, expected_tax, updated_by, updated_at, reason)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(vendor_code) DO UPDATE SET
                expected_tax = excluded.expected_tax,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at,
                reason = excluded.reason
            """,
            (v_code, expected_tax, updated_by, now, reason)
        )

    def upsert_account_rule(self, conn: sqlite3.Connection, vendor_code: str, scope_type: str, scope_key: str, expected_account: str, updated_by: str, reason: str):
        """科目ルールの登録 (3段階優先構造)"""
        now = datetime.now().isoformat()
        v_code = self.normalize_code(vendor_code)
        s_key = self.normalize_code(scope_key) if scope_key else ""
        
        # Check existence first because ON CONFLICT requires a UNIQUE index which might be missing in older schemas
        cursor = conn.execute(
            """
            SELECT id FROM rule_account_master 
            WHERE vendor_code = ? AND scope_type = ? AND scope_key = ?
            """,
            (v_code, scope_type, s_key)
        )
        row = cursor.fetchone()

        if row:
            # UPDATE
            conn.execute(
                """
                UPDATE rule_account_master 
                SET expected_account = ?, updated_by = ?, updated_at = ?, reason = ?
                WHERE id = ?
                """,
                (expected_account, updated_by, now, reason, row[0])
            )
        else:
            # INSERT
            conn.execute(
                """
                INSERT INTO rule_account_master (vendor_code, scope_type, scope_key, expected_account, updated_by, updated_at, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (v_code, scope_type, s_key, expected_account, updated_by, now, reason)
            )

    def delete_account_rule(self, conn: sqlite3.Connection, vendor_code: str, scope_type: str, scope_key: str):
        """科目ルールの削除"""
        v_code = self.normalize_code(vendor_code)
        s_key = self.normalize_code(scope_key) if scope_key else ""
        
        conn.execute(
            """
            DELETE FROM rule_account_master 
            WHERE vendor_code = ? AND scope_type = ? AND scope_key = ?
            """,
            (v_code, scope_type, s_key)
        )

    def upsert_override(self, conn: sqlite3.Connection, vendor_code: str, dept_code: str, field_name: str, new_value: str, reason: str, updated_by: str):
        """強制修正の登録 (常にINSERT)"""
        now = datetime.now().isoformat()
        
        norm_vendor = self.normalize_code(vendor_code)
        norm_dept = self.normalize_code(dept_code)

        conn.execute(
            """
            UPDATE override_rule SET is_active = 0 
            WHERE vendor_code = ? AND dept_code = ? AND field_name = ? AND is_active = 1
            """,
            (norm_vendor, norm_dept, field_name)
        )
        
        conn.execute(
            """
            INSERT INTO override_rule (
                vendor_code, dept_code, field_name, new_value, reason, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (norm_vendor, norm_dept, field_name, new_value, reason, updated_by, now)
        )

    # --- 検索・一覧 ---

    def search_tax_rules(self, conn: sqlite3.Connection, query: str = "") -> List[Dict]:
        """税区分・代表科目ルール検索 (マスタ全検索+ルール結合)"""
        # COST/SGA/ANYの科目を個別に表示
        sql = """
            SELECT m.vendor_code, m.vendor_name,
                   r.expected_tax, r.updated_by, r.updated_at, r.reason,
                   ra_cost.expected_account as cost_account,
                   mac.account_name as cost_account_name,
                   ra_sga.expected_account as sga_account,
                   mas.account_name as sga_account_name,
                   COALESCE(ra_cost.expected_account, ra_sga.expected_account, ra_any.expected_account) as expected_account,
                   ma.account_name as expected_account_name
            FROM masters_vendor m
            LEFT JOIN rule_tax_master r ON m.vendor_code = r.vendor_code
            -- 1. COST
            LEFT JOIN rule_account_master ra_cost 
              ON m.vendor_code = ra_cost.vendor_code AND ra_cost.scope_type = 'DEPT_TYPE' AND ra_cost.scope_key = 'COST'
            LEFT JOIN masters_account mac ON ra_cost.expected_account = mac.account_code
            -- 2. SGA
            LEFT JOIN rule_account_master ra_sga 
              ON m.vendor_code = ra_sga.vendor_code AND ra_sga.scope_type = 'DEPT_TYPE' AND ra_sga.scope_key = 'SGA'
            LEFT JOIN masters_account mas ON ra_sga.expected_account = mas.account_code
            -- 3. ANY
            LEFT JOIN rule_account_master ra_any 
              ON m.vendor_code = ra_any.vendor_code AND ra_any.scope_type = 'ANY'
            
            -- Resolve Name (代表科目)
            LEFT JOIN masters_account ma 
              ON COALESCE(ra_cost.expected_account, ra_sga.expected_account, ra_any.expected_account) = ma.account_code
            
            WHERE 1=1
        """
        params = []
        
        # 検索クエリがある場合: ルール有無に関わらず検索ヒットするものを表示
        if query:
            sql += " AND (m.vendor_code LIKE ? OR m.vendor_name LIKE ?)"
            params = [f"%{query}%", f"%{query}%"]
        else:
            # 検索クエリがない場合: ルールが設定されているもののみ表示（全件表示回避）
            sql += """
                AND (r.expected_tax IS NOT NULL 
                   OR ra_cost.expected_account IS NOT NULL 
                   OR ra_sga.expected_account IS NOT NULL 
                   OR ra_any.expected_account IS NOT NULL)
            """
        
        # シンプルなソート: コード順
        sql += """
            ORDER BY m.vendor_code 
            LIMIT 100
        """
        
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def search_account_rules(self, conn: sqlite3.Connection, query: str = "") -> List[Dict]:
        """科目ルール検索 (3段階構造)"""
        sql = """
            SELECT r.*, m.vendor_name 
            FROM rule_account_master r
            LEFT JOIN masters_vendor m ON r.vendor_code = m.vendor_code
        """
        params = []
        if query:
            sql += " WHERE r.vendor_code LIKE ? OR m.vendor_name LIKE ?"
            params = [f"%{query}%", f"%{query}%"]
        
        # ソート: Vendor -> ScopeType (DEPT < DEPT_TYPE < ANY 順にしたいが便宜上辞書順) -> Key
        sql += " ORDER BY r.vendor_code, r.scope_type, r.scope_key LIMIT 100"
        
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """統計情報を取得"""
        # Tax Rule Count
        cursor = conn.execute("SELECT COUNT(*) FROM rule_tax_master")
        tax_total = cursor.fetchone()[0]
        
        # Account Rule Count
        cursor = conn.execute("SELECT COUNT(*) FROM rule_account_master")
        acc_total = cursor.fetchone()[0]

        # Override Count (active)
        cursor = conn.execute("SELECT COUNT(*) FROM override_rule WHERE is_active=1")
        ov_total = cursor.fetchone()[0]
        
        # Last Updated (from any, simplified to tax for now)
        cursor = conn.execute("SELECT MAX(updated_at) FROM rule_tax_master")
        last_updated = cursor.fetchone()[0]
        
        return {
            "total_rules": tax_total + acc_total,
            "total_tax": tax_total,
            "total_account": acc_total,
            "total_override": ov_total,
            "last_updated": last_updated
        }
