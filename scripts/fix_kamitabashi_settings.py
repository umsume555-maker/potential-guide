import sys
import os
sys.path.append(os.getcwd())

from features.vendor_invoice_reconcile.repositories.settings_repository import SettingsRepository
from features.vendor_invoice_reconcile.models import TemplateConfig

def fix_settings():
    repo = SettingsRepository()
    vendor_code = "1000890" # Credence
    
    config = repo.get_template(vendor_code)
    if not config:
        print(f"Template for {vendor_code} not found.")
        return

    # Update Synonym for Kamitabashi
    # Invoice Dept Name: 上板橋住宅役務部門 (Code: 20305540)
    # E2 Dept Code: 20305530 (上板橋訪問介護部門)
    # We want Invoice (40) to match E2 (30).
    
    target_key = "上板橋住宅役務部門"
    new_value = ["20305540", "20305530"]
    
    print(f"Updating synonym for '{target_key}'...")
    print(f"Old value: {config.dept_synonyms.get(target_key)}")
    
    config.dept_synonyms[target_key] = new_value
    
    repo.save_template(config)
    print(f"New value: {config.dept_synonyms.get(target_key)}")
    print("Settings updated successfully.")

if __name__ == "__main__":
    try:
        fix_settings()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
