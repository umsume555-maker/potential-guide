import pandas as pd
import pdfplumber
import re
from pathlib import Path
from typing import List, Optional, Union
from ..models import InvoiceRecord, TemplateConfig

class BaseExtractor:
    def extract(self, file_path: str, config: TemplateConfig) -> List[InvoiceRecord]:
        raise NotImplementedError

class ExcelExtractor(BaseExtractor):
    def extract(self, file_path: str, config: TemplateConfig) -> List[InvoiceRecord]:
        records = []
        try:
            # Load Excel, defaulting to first sheet if not specified
            sheet_name = config.excel_sheet_name if config.excel_sheet_name else 0
            header_row = config.excel_header_row - 1 # 0-based index for pandas
            
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
            
            # Column mapping
            dept_col = config.excel_dept_column
            amount_col = config.excel_amount_column
            
            if not dept_col or not amount_col:
                raise ValueError("Excel department or amount column not configured")

            # Check if columns exist
            if dept_col not in df.columns or amount_col not in df.columns:
                # Todo: Add fuzzy matching or user prompt logic here in future
                raise ValueError(f"Columns not found: {dept_col}, {amount_col}. Available: {list(df.columns)}")

            for index, row in df.iterrows():
                raw_dept = row[dept_col]
                raw_amount = row[amount_col]
                
                # Basic validation: Skip empty rows
                if pd.isna(raw_dept) or pd.isna(raw_amount):
                    continue
                    
                # Clean amount
                try:
                    amount_val = float(str(raw_amount).replace(",", "").replace("¥", "").strip())
                    # Convert to int if it's a whole number
                    if amount_val.is_integer():
                        amount_val = int(amount_val)
                except ValueError:
                    continue # Skip non-numeric amounts (e.g. headers/footers mixed in)

                record = InvoiceRecord(
                    row_index=index + config.excel_header_row + 1, # 1-based row index (approx)
                    source_file=Path(file_path).name,
                    raw_dept_name=str(raw_dept).strip(),
                    raw_amount=amount_val
                )
                records.append(record)
                
        except Exception as e:
            print(f"Error extracting Excel {file_path}: {e}")
            raise e
            
        return records

class PDFExtractor(BaseExtractor):
    def extract(self, file_path: str, config: TemplateConfig) -> List[InvoiceRecord]:
        records = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Strategy 1: Table Extraction
                    tables = page.extract_tables()
                    for table in tables:
                        records.extend(self._process_table(table, config, file_path, page_num))
                    
                    # Strategy 2: Text/Line analysis (if tables fail - simplified for PoC)
                    # For now, rely on tables as they are most common in invoice lists.
                    
        except Exception as e:
            print(f"Error extracting PDF {file_path}: {e}")
            raise e
            
        return records

    def _process_table(self, table: List[List[Optional[str]]], config: TemplateConfig, file_path: str, page_num: int) -> List[InvoiceRecord]:
        records = []
        
        # Simple heuristic: Look for header row containing keywords
        header_idx = -1
        dept_idx = -1
        amount_idx = -1
        
        keywords = config.pdf_header_keywords
        # Default keywords if not configured
        if not keywords:
            keywords = ["事業所", "部門", "店舗", "金額", "請求額", "合計"]
            
        def normalize_text(s: str) -> str:
            """改行・タブ・連続スペースを単一スペースに正規化"""
            import re
            return re.sub(r'[\s\n\t]+', ' ', str(s)).strip()

        # Find header row
        for i, row in enumerate(table):
            row_text = [normalize_text(cell) if cell else "" for cell in row]

            # Check if this row looks like a header
            d_idx = -1
            a_idx = -1

            for col_i, text in enumerate(row_text):
                # Dept detection
                if config.pdf_dept_column:
                    if normalize_text(config.pdf_dept_column) in text:
                        d_idx = col_i
                else:
                    if any(k in text for k in ["事業所", "部門", "店舗", "店名"]):
                        d_idx = col_i

                # Amount detection
                if config.pdf_amount_column:
                    if normalize_text(config.pdf_amount_column) in text:
                        a_idx = col_i
                else:
                    if any(k in text for k in ["金額", "請求", "合計", "小計"]):
                        a_idx = col_i
            
            if d_idx != -1 and a_idx != -1:
                header_idx = i
                dept_idx = d_idx
                amount_idx = a_idx
                break
        
        if header_idx != -1:
            # Process rows after header
            for i in range(header_idx + 1, len(table)):
                row = table[i]
                if len(row) <= max(dept_idx, amount_idx):
                    continue
                
                raw_dept = row[dept_idx]
                raw_amount = row[amount_idx]

                if not raw_dept or not raw_amount:
                    continue

                # 改行を含む場合（例: "注文No.\n事業所名"）→ 最後の行を事業所名として使用
                raw_dept_str = str(raw_dept).strip()
                if "\n" in raw_dept_str:
                    raw_dept_str = raw_dept_str.split("\n")[-1].strip()
                else:
                    raw_dept_str = raw_dept_str
                
                # Clean amount
                try:
                    clean_amt_str = str(raw_amount).replace(",", "").replace("¥", "").strip()
                    # PDF extraction might leave spaces
                    clean_amt_str = "".join(clean_amt_str.split())
                    if not clean_amt_str: continue

                    amount_val = float(clean_amt_str)
                    if amount_val.is_integer():
                        amount_val = int(amount_val)
                except ValueError:
                    continue

                # 0円・合計行はスキップ
                if amount_val == 0:
                    continue
                skip_keywords = ["合計", "小計", "総計", "total", "subtotal"]
                if any(k in raw_dept_str for k in skip_keywords):
                    continue

                record = InvoiceRecord(
                    row_index=i + 1, # Relative to table
                    source_file=f"{Path(file_path).name} (Page {page_num+1})",
                    raw_dept_name=raw_dept_str,
                    raw_amount=amount_val
                )
                records.append(record)
                
        return records

class ExtractorFactory:
    @staticmethod
    def get_extractor(file_type: str) -> BaseExtractor:
        if file_type == "excel":
            return ExcelExtractor()
        elif file_type == "pdf":
            return PDFExtractor()
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
