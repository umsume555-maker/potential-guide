from typing import Dict, List, Optional
from ..models import InvoiceRecord, TemplateConfig
from ..repositories.master_repository import MasterRepository

class DepartmentMatcher:
    def __init__(self, master_repo: MasterRepository):
        self.master_repo = master_repo
        # Cache for exact name matching
        self.dept_name_to_code: Dict[str, str] = {}
        self._load_master_cache()

    def _load_master_cache(self):
        """
        マスタから (正規化された名前 -> コード) のマップを作成
        """
        depts = self.master_repo.get_department_master()
        for code, name in depts.items():
            if name:
                # Normalize: trim whitespace
                self.dept_name_to_code[name.strip()] = code
    
    def match(self, record: InvoiceRecord, config: TemplateConfig) -> InvoiceRecord:
        """
        1行データの事業所名をマスタおよび設定(Synonyms)と照合してコードを埋める
        """
        # Normalize full-width spaces to half-width and collapse multiple spaces
        raw_name = record.raw_dept_name.replace('\u3000', ' ').strip()
        raw_name = " ".join(raw_name.split())
        record.candidate_dept_codes = []
        
        # 1. Configured Synonyms (High priority)
        if raw_name in config.dept_synonyms:
            val = config.dept_synonyms[raw_name]
            if isinstance(val, list):
                record.candidate_dept_codes = [str(x).strip() for x in val]
            elif isinstance(val, str):
                if "," in val:
                    record.candidate_dept_codes = [x.strip() for x in val.split(",")]
                else:
                    record.candidate_dept_codes = [val.strip()]
            
            if record.candidate_dept_codes:
                # 暫定的に先頭をセット（Reconcilerで確定させる）
                record.mapped_dept_code = record.candidate_dept_codes[0]
                record.mapped_dept_name = self._get_name_by_code(record.mapped_dept_code)
                return record

        # 2. Exact Match with Master Name
        if raw_name in self.dept_name_to_code:
            code = self.dept_name_to_code[raw_name]
            record.candidate_dept_codes = [code]
            record.mapped_dept_code = code
            record.mapped_dept_name = raw_name
            return record

        # 3. Fuzzy logic / Heuristics (Optional for Phase 2)
        # e.g., removal of "店" suffix, etc.
        # For PoC, simple heuristics might help reduce manual mapping.
        
        # Try stripping "店" or "店舗"
        for suffix in ["店", "店舗", "事業所", "支店"]:
            if raw_name.endswith(suffix):
                stem = raw_name[:-len(suffix)]
                if stem in self.dept_name_to_code:
                    record.mapped_dept_code = self.dept_name_to_code[stem]
                    record.mapped_dept_name = stem # or full official name
                    return record

        # 4. Unmapped
        record.mapped_dept_code = None
        record.mapped_dept_name = None
        return record

    def _get_name_by_code(self, code: str) -> Optional[str]:
        # Reverse lookup (inefficient but safe for PoC)
        # Better: keep code_to_name map in memory too
        depts = self.master_repo.get_department_master()
        return depts.get(code)
