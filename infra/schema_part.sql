
-- ============================================================
-- 請求一覧対象取引先（毎月請求があるはずの取引先）
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_reconciliation_target (
    vendor_code TEXT PRIMARY KEY,
    vendor_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
