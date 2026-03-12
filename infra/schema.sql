-- 支払依頼書チェックシステム SQLiteスキーマ
-- WALモードで運用（高速・同時読取対応）

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- 累積テーブル（14ヶ月ローテーション）
-- ============================================================
CREATE TABLE IF NOT EXISTS cumulative (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    yyyymm TEXT NOT NULL,                -- 取引日付の年月 (YYYY-MM)
    base_invoice_no TEXT NOT NULL,       -- ベース伝票番号
    dept_code TEXT NOT NULL,             -- 申請部門表示コード
    dept_name TEXT,                      -- 申請部門名
    vendor_code TEXT NOT NULL,           -- 取引先コード
    vendor_name TEXT,                    -- 取引先名
    payee_code TEXT,                     -- 支払先コード
    payee_name TEXT,                     -- 支払先名
    payment_amount INTEGER NOT NULL,     -- 支払金額合計
    tax_category TEXT,                   -- 税区分（最小枝番）
    tax_category_name TEXT,              -- 税区分名
    account_code TEXT,                   -- 科目コード（最小枝番）
    account_name TEXT,                   -- 科目名
    payment_date TEXT,                   -- 支払予定日 (YYYY-MM-DD)
    transaction_date TEXT,               -- 取引日付 (YYYY-MM-DD)
    status TEXT,                         -- 状況区分
    template_use INTEGER DEFAULT 0,      -- テンプレ採用=1
    overall_result TEXT,                 -- 総合判定 (OK/NG/-)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cumulative_lookup 
    ON cumulative(vendor_code, dept_code, yyyymm);
CREATE INDEX IF NOT EXISTS idx_cumulative_template 
    ON cumulative(vendor_code, dept_code, template_use, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_cumulative_yyyymm
    ON cumulative(yyyymm);

-- ============================================================
-- WorkID管理
-- ============================================================
CREATE TABLE IF NOT EXISTS work_items (
    work_id TEXT PRIMARY KEY,
    base_invoice_no TEXT,
    dept_code TEXT NOT NULL,
    vendor_code TEXT NOT NULL,
    fingerprint_hash TEXT,
    assigned_confirmed TEXT,             -- 担当（確定）
    assigned_proposed TEXT,              -- 担当（初期提案）
    hold_match INTEGER DEFAULT 0,        -- 照合保留=1
    needs_review INTEGER DEFAULT 0,      -- 要確認フラグ
    review_reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_work_items_invoice
    ON work_items(base_invoice_no);
CREATE INDEX IF NOT EXISTS idx_work_items_vendor_dept
    ON work_items(vendor_code, dept_code);

-- ============================================================
-- 明細ハッシュ（WorkIDマッチング用）
-- ============================================================
CREATE TABLE IF NOT EXISTS fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    detail_json TEXT,
    FOREIGN KEY (work_id) REFERENCES work_items(work_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fingerprints_hash 
    ON fingerprints(hash);

-- ============================================================
-- 取引先マスタ
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_vendor (
    vendor_code TEXT PRIMARY KEY,
    vendor_name TEXT,
    vendor_name_kana TEXT,
    payment_condition_code TEXT,         -- 支払決済条件コード
    payment_condition_name TEXT,         -- 支払決済条件名
    holiday_handling TEXT,               -- 休日考慮区分 (1:休日前, 2:休日後)
    payment_cycle_type TEXT,             -- 期日サイクル区分
    payment_month_offset INTEGER,        -- 期日指定月数
    payment_day INTEGER,                 -- 期日指定日 (0=末日, 1-31)
    closing_day INTEGER,                 -- 支払締日
    bank_code TEXT,
    bank_name TEXT,
    branch_code TEXT,
    branch_name TEXT,
    account_type TEXT,                   -- 1:普通, 2:当座
    account_number TEXT,
    account_holder TEXT,
    account_holder_kana TEXT,
    date_tolerance INTEGER DEFAULT 0,    -- 取引日付許容月ずれ (0 or +1)
    no_month_crossing INTEGER DEFAULT 0, -- 月跨ぎ不可=1
    is_disabled INTEGER DEFAULT 0,       -- 使用不可フラグ
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 許容支払先マスタ
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_allowed_payee (
    vendor_code TEXT NOT NULL,
    allowed_payee_code TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (vendor_code, allowed_payee_code)
);

-- ============================================================
-- 除外取引先マスタ
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_exclude (
    vendor_code TEXT PRIMARY KEY,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 担当割当（部門範囲ルール）
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_assign_dept_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_code_start TEXT NOT NULL,
    dept_code_end TEXT NOT NULL,
    assignee TEXT NOT NULL,
    priority INTEGER DEFAULT 0           -- 優先度（大きいほど優先）
);

-- ============================================================
-- 担当割当（部門個別例外）
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_assign_dept_override (
    dept_code TEXT PRIMARY KEY,
    dept_name TEXT,
    assignee TEXT NOT NULL
);

-- ============================================================
-- 例外部門マスタ（出力対象外）
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_exception_dept (
    dept_code TEXT PRIMARY KEY,
    dept_name TEXT,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 担当割当（取引先別）
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_assign_vendor (
    vendor_code TEXT PRIMARY KEY,
    vendor_name TEXT,
    assignee TEXT NOT NULL
);

-- ============================================================
-- 祝日テーブル
-- ============================================================
CREATE TABLE IF NOT EXISTS holidays (
    holiday_date TEXT PRIMARY KEY,       -- YYYY-MM-DD
    holiday_name TEXT
);

-- ============================================================
-- 科目マスタ
-- ============================================================
CREATE TABLE IF NOT EXISTS masters_account (
    account_code TEXT PRIMARY KEY,       -- 科目コード
    account_name TEXT NOT NULL,          -- 科目名
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 実行ログ
-- ============================================================
CREATE TABLE IF NOT EXISTS run_log (
    run_id TEXT PRIMARY KEY,
    base_month TEXT,                     -- 基準月 (YYYY-MM)
    started_at TEXT,
    ended_at TEXT,
    status TEXT,                         -- running/completed/error
    input_rows INTEGER,
    output_rows INTEGER,
    ng_count INTEGER,
    hold_count INTEGER,
    dash_count INTEGER,
    error_message TEXT
);

-- ============================================================
-- 請求書OCR結果
-- ============================================================
CREATE TABLE IF NOT EXISTS invoice_ocr_results (
    run_id TEXT,
    approval_no TEXT,
    file_name TEXT,
    
    -- 部門・取引先情報
    dept_code TEXT,
    dept_name TEXT,
    vendor_code TEXT,
    vendor_name TEXT,
    
    -- OCR抽出結果
    detected_amount INTEGER,             -- 抽出された金額
    detected_invoice_no TEXT,            -- 抽出されたインボイス番号
    has_reduced_tax INTEGER DEFAULT 0,   -- 軽減税率有無 (0/1)
    has_ringi INTEGER DEFAULT 0,         -- 稟議書有無 (0/1)
    confidence REAL,                     -- 信頼度スコア (0.0-1.0)
    ocr_method TEXT,                     -- 使用手法 (text_layer/pyocr/ai_ocr)
    
    -- 突合結果
    match_status TEXT,                   -- OK/NG/WARNING/UNCHECKED
    amount_diff INTEGER,                 -- 金額差分 (detected - actual)
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (run_id, approval_no, file_name)
);

-- ============================================================
-- 出力サマリ（チェック結果）
-- ============================================================
CREATE TABLE IF NOT EXISTS output_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    work_id TEXT,
    base_invoice_no TEXT,
    decision_no TEXT,                    -- 決裁番号 (ZSN...) [NEW]
    dept_code TEXT NOT NULL,
    dept_name TEXT,
    vendor_code TEXT,
    vendor_name TEXT,
    payee_code TEXT,
    payee_name TEXT,
    payment_amount INTEGER,
    tax_category TEXT,
    tax_category_name TEXT,
    account_code TEXT,
    account_name TEXT,
    payment_date TEXT,
    transaction_date TEXT,
    status TEXT,
    bank_account_info TEXT,              -- 振込先口座情報
    -- 判定結果
    vendor_payee_result TEXT,            -- 支払先相違判定 (OK/NG)
    tax_result TEXT,                     -- 税区分判定 (OK/NG/-)
    tax_expected TEXT,                   -- 税区分（正）
    account_result TEXT,                 -- 科目判定 (OK/NG/-)
    account_expected TEXT,               -- 科目（正）
    account_expected_name TEXT,          -- 科目名（正）
    payment_date_result TEXT,            -- 支払予定日判定 (OK/NG)
    payment_date_expected TEXT,          -- 支払予定日（期待値）
    anomaly_result TEXT,                 -- ズレモレ判定 (OK/NG)
    anomaly_type TEXT,                   -- 種別 (モレ/ズレ/二重/空欄)
    is_monthly TEXT,                     -- 毎月判定 (毎月/空欄)
    overall_result TEXT,                 -- 総合判定 (OK/NG/-)
    -- 担当
    assigned_confirmed TEXT,
    assigned_proposed TEXT,
    -- 過去金額・個数
    amount_3m_ago INTEGER,
    count_3m_ago INTEGER,
    amount_2m_ago INTEGER,
    count_2m_ago INTEGER,
    amount_1m_ago INTEGER,
    count_1m_ago INTEGER,
    amount_current INTEGER,
    count_current INTEGER,
    amount_next INTEGER,
    count_next INTEGER,
    -- フラグ
    hold_match INTEGER DEFAULT 0,
    needs_review INTEGER DEFAULT 0,
    review_reason TEXT,
    is_synthetic INTEGER DEFAULT 0,      -- 合成行（モレ）=1
    FOREIGN KEY (run_id) REFERENCES run_log(run_id)
);

CREATE INDEX IF NOT EXISTS idx_output_summary_run
    ON output_summary(run_id);
CREATE INDEX IF NOT EXISTS idx_output_summary_vendor_dept
    ON output_summary(vendor_code, dept_code);

-- ============================================================
-- 出力明細（INPUTそのまま保持）
-- ============================================================
CREATE TABLE IF NOT EXISTS output_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    invoice_no TEXT NOT NULL,            -- 枝番付き伝票番号
    base_invoice_no TEXT NOT NULL,       -- ベース伝票番号
    branch_no TEXT,                      -- 枝番
    dept_code TEXT,
    dept_name TEXT,
    vendor_code TEXT,
    vendor_name TEXT,
    payee_code TEXT,
    payee_name TEXT,
    account_code TEXT,
    account_name TEXT,
    payment_amount INTEGER,
    tax_category TEXT,
    tax_category_name TEXT,
    payment_date TEXT,
    transaction_date TEXT,
    status TEXT,
    FOREIGN KEY (run_id) REFERENCES run_log(run_id)
);

CREATE INDEX IF NOT EXISTS idx_output_detail_run
    ON output_detail(run_id);
CREATE INDEX IF NOT EXISTS idx_output_detail_base_invoice
    ON output_detail(base_invoice_no);

-- ============================================================
-- 税区分・科目 正マスター（ルール） [NEW]
-- ============================================================
CREATE TABLE IF NOT EXISTS rule_tax_account_master (
    vendor_code TEXT PRIMARY KEY,
    expected_tax TEXT NOT NULL,
    expected_account TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    update_reason TEXT NOT NULL
);

-- ============================================================
-- 税区分・科目 正マスター変更履歴 [NEW]
-- ============================================================
CREATE TABLE IF NOT EXISTS rule_tax_account_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_code TEXT NOT NULL,
    old_expected_tax TEXT,
    old_expected_account TEXT,
    new_expected_tax TEXT,
    new_expected_account TEXT,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    update_reason TEXT NOT NULL
);
-- ============================================================
-- [NEW] 堅牢なマスタ管理 (Phase 2.5)
-- ============================================================

-- 部門マスタ（dept_type判定用）
CREATE TABLE IF NOT EXISTS masters_department (
    dept_code TEXT PRIMARY KEY,
    dept_name TEXT,
    dept_type TEXT,  -- 'COST'(原価) / 'SGA'(販管) など
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 税区分ルール (取引先単位)
CREATE TABLE IF NOT EXISTS rule_tax_master (
    vendor_code TEXT PRIMARY KEY,
    expected_tax TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT,
    reason TEXT
);

-- 税区分ルール例外 (部門別・タイプ別) [MISSING TABLE]
CREATE TABLE IF NOT EXISTS rule_tax_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_code TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_key TEXT,
    expected_tax TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule_tax_rules_lookup 
    ON rule_tax_rules(vendor_code, scope_type, scope_key);

-- 科目ルール (取引先 × 適用範囲)
-- scope_type: 'DEPT' (部門個別), 'DEPT_TYPE' (タイプ), 'ANY' (共通)
-- scope_key: 部門コード or 'SGA'/'COST' or ''
CREATE TABLE IF NOT EXISTS rule_account_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_code TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_key TEXT,
    expected_account TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule_account_lookup 
    ON rule_account_master(vendor_code, scope_type, scope_key);

-- 強制修正 (Override)
CREATE TABLE IF NOT EXISTS override_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_code TEXT NOT NULL,
    dept_code TEXT,              -- 特定部門のみの場合 (NULLなら全部門)
    dept_type TEXT,              -- 補助情報
    field_name TEXT NOT NULL,    -- 'expected_tax' / 'expected_account'
    new_value TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_override_lookup 
    ON override_rule(vendor_code, dept_code, field_name) WHERE is_active = 1;

-- ============================================================
-- アプリ設定保存用 (永続化)
-- ============================================================
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,        -- 設定キー (ex: google_credentials_path)
    value TEXT NOT NULL,         -- 設定値
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
