from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union, Literal
from datetime import date
print("[DEBUG] Loading features.vendor_invoice_reconcile.models (Updated 2026-05-14 excluded_dept_codes)")

class InvoiceRecord(BaseModel):
    """
    請求一覧ファイルから抽出した1行データ（正規化前含む）
    """
    row_index: int = Field(..., description="元ファイルの行番号")
    source_file: str = Field(..., description="元ファイル名")
    
    # 抽出された生の文字列
    raw_dept_name: str = Field(..., description="抽出された事業所名（表記揺れあり）")
    raw_amount: Union[int, float] = Field(..., description="抽出された金額")
    invoice_no: Optional[str] = Field(None, description="請求書番号")
    base_invoice_no: Optional[str] = Field(None, description="ベース伝票番号(システム用)")
    
    # 紐付け後のコード（未紐付けの場合はNone）
    candidate_dept_codes: List[str] = Field(default_factory=list, description="紐付け候補のE2事業所コードリスト")
    mapped_dept_code: Optional[str] = Field(None, description="紐付けられたE2事業所コード")
    mapped_dept_name: Optional[str] = Field(None, description="紐付けられたE2事業所名")

class ReconcileResult(BaseModel):
    """
    突合結果（1行単位）
    """
    base_month: str = Field(..., description="基準月(YYYY-MM)")
    vendor_code: str = Field(..., description="取引先コード")
    vendor_name: str = Field(..., description="取引先名")
    
    dept_code: str = Field(..., description="事業所コード")
    dept_name: str = Field(..., description="事業所名")
    
    invoice_amount: int = Field(0, description="請求一覧の金額合計")
    payment_amount: int = Field(0, description="E2支払実績の金額合計")
    
    diff_amount: int = Field(0, description="差額 (invoice - payment)")
    status: Literal["OK", "MISSING", "EXCESS", "DIFF", "UNMAPPED", "DOUBLE_INPUT", "DATE_DIFF", "DATE_GAP", "RECURRING_MISSING"] = Field(..., description="判定結果")
    is_monthly: Optional[str] = None  # 毎月判定 (毎月/空欄)
    
    details: List[InvoiceRecord] = Field(default_factory=list, description="構成する請求明細")
    note: str = Field("", description="備考")
    transaction_date: Optional[str] = Field(None, description="取引日付(YYYY-MM-DD)")

class RunInfo(BaseModel):
    """
    実行情報
    """
    run_date: str
    base_month: str
    target_vendors: List[str]
    input_files: List[str]

class TemplateConfig(BaseModel):
    """
    取引先ごとの抽出設定
    """
    vendor_code: str
    vendor_name: str
    file_type: Literal["excel", "pdf"]
    
    # Excel用設定
    excel_sheet_name: Optional[str] = None # Noneなら先頭シート
    excel_dept_column: Optional[str] = None # 列名ヘッダー
    excel_amount_column: Optional[str] = None
    excel_header_row: int = 1 # ヘッダー行番号(1-based)
    
    # PDF用設定（簡易版）
    pdf_header_keywords: List[str] = Field(default_factory=list) # "事業所", "金額" などのキーワード
    pdf_dept_column: Optional[str] = None
    pdf_amount_column: Optional[str] = None
    
    # マッピング辞書 (Raw Dept Name -> Dept Code or List of Dept Codes)
    dept_synonyms: Dict[str, Union[str, List[str]]] = Field(default_factory=dict)

    # 除外部門 (Dept Code -> 理由)
    # 請求一覧突合・現場シートの「もれ」から除外する部門コードと理由
    excluded_dept_codes: Dict[str, str] = Field(default_factory=dict, description="除外部門 {dept_code: reason}")

    last_updated: str = Field(..., description="最終更新日時")
