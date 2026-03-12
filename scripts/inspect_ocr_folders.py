
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

BASE_DIR = Path(r"c:\Users\012835-uno\Desktop\unzip_and_cleanup\支払依頼チェックツール\invoice_ocr\ZIP_FILE_OUT")

def inspect_structure():
    print(f"Inspecting: {BASE_DIR}")
    if not BASE_DIR.exists():
        print("Directory not found!")
        return

    total_files = 0
    pdf_files = 0
    depth_counts = {}

    for root, dirs, files in os.walk(str(BASE_DIR)): # os.walk needs str for safety on some envs
        root_path = Path(root)
        try:
            rel_path = root_path.relative_to(BASE_DIR)
            depth = len(rel_path.parts)
        except ValueError:
            depth = 0
        
        depth_counts[depth] = depth_counts.get(depth, 0) + len(files)
        
        for f in files:
            total_files += 1
            if f.lower().endswith(".pdf"):
                pdf_files += 1
            
        if len(files) > 0:
            if total_files < 20 or total_files % 100 == 0:
                try:
                    print(f"Files found in: {rel_path} (Depth: {depth}, Count: {len(files)})")
                except:
                    print(f"Files found in: {repr(str(rel_path))} (Depth: {depth}, Count: {len(files)})")

    print("\n--- Summary ---")
    print(f"Total Files: {total_files}")
    print(f"PDF Files: {pdf_files}")
    print(f"Files by Depth (relative to ZIP_FILE_OUT): {depth_counts}")
    
    # Check folder scanner logic
    print("\n--- Checking for invalid Department folders ---")
    try:
        for item in BASE_DIR.iterdir():
            if item.is_dir():
                try:
                    print(f"Level 1: {item.name}")
                    if "_" in item.name and item.name.split("_", 1)[0].isdigit():
                        pass 
                    else:
                         print(f"  -> checking detail for non-dept looking folder: {item.name}")
                         for sub in item.iterdir():
                             if sub.is_dir():
                                 print(f"    Level 2: {sub.name}")
                except:
                    print(f"Level 1: {repr(item.name)}")
    except Exception as e:
        print(f"Error iterating dirs: {e}")

if __name__ == "__main__":
    inspect_structure()
