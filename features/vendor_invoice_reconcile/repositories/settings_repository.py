import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from ..models import TemplateConfig

class SettingsRepository:
    """
    設定ファイル(JSON)の読み書きを行うリポジトリ
    """
    def __init__(self, settings_path: str = "config/invoice_reconcile_settings.json"):
        self.settings_path = Path(settings_path)
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        if not self.settings_path.parent.exists():
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.settings_path.exists():
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"templates": {}}, f, ensure_ascii=False, indent=2)

    def load_all_templates(self) -> Dict[str, TemplateConfig]:
        """全テンプレートを読み込む"""
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                templates = {}
                for vendor_code, t_data in data.get("templates", {}).items():
                    config = TemplateConfig(**t_data)
                    # 既存のシノニムキーも正規化（全角スペース置換など）
                    normalized_synonyms = {}
                    for raw_name, dept_codes in config.dept_synonyms.items():
                        norm_name = raw_name.replace('\u3000', ' ').strip()
                        norm_name = " ".join(norm_name.split())
                        normalized_synonyms[norm_name] = dept_codes
                    config.dept_synonyms = normalized_synonyms
                    templates[vendor_code] = config
                return templates
        except Exception as e:
            print(f"Error loading settings: {e}")
            return {}

    def save_template(self, config: TemplateConfig):
        """テンプレートを保存・更新する"""
        templates = self.load_all_templates()
        config.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        templates[config.vendor_code] = config
        
        data = {"templates": {k: v.dict() for k, v in templates.items()}}
        
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_template(self, vendor_code: str) -> Optional[TemplateConfig]:
        """特定取引先のテンプレートを取得"""
        templates = self.load_all_templates()
        return templates.get(vendor_code)
