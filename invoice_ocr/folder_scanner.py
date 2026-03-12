# folder_scanner.py
"""
ZIP展開後のフォルダ階層を解析し、
承認番号単位でファイルを収集するモジュール。

フォルダ階層:
ZIP_FILE_OUT/
 └─ （無視）
    └─ 部門コード_部門名
       └─ 取引先コード_取引先名
          └─ ステータス（決裁済/未決済/保留）
             └─ 承認番号（ZSN...）
                └─ 添付ファイル群
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import re
import yaml


@dataclass
class ApprovalFolder:
    """承認番号単位のフォルダ情報"""
    approval_no: str  # 承認番号 (ZSN...)
    dept_code: str  # 部門コード
    dept_name: str  # 部門名
    vendor_code: str  # 取引先コード
    vendor_name: str  # 取引先名
    status: str  # ステータス（決裁済/未決済/保留）
    folder_path: Path  # フォルダパス
    files: list[Path] = field(default_factory=list)  # 対象ファイル一覧
    
    def __repr__(self):
        return f"ApprovalFolder({self.approval_no}, {self.dept_code}, {self.vendor_code}, files={len(self.files)})"


def load_config(config_path: Optional[Path] = None) -> dict:
    """設定ファイルを読み込む"""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_target_file(file_path: Path, config: dict) -> bool:
    """対象ファイルかどうかを判定"""
    ext = file_path.suffix.lower().lstrip(".")
    include_exts = config.get("file_extensions", {}).get("include", [])
    exclude_exts = config.get("file_extensions", {}).get("exclude", [])
    
    if ext in exclude_exts:
        return False
    if ext in include_exts:
        return True
    return False


def parse_code_name(folder_name: str) -> tuple[str, str]:
    """
    フォルダ名から コード_名前 を分解
    例: "12345678_株式会社テスト" -> ("12345678", "株式会社テスト")
    """
    parts = folder_name.split("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return folder_name, ""


def scan_folder(
    root_path: Path,
    config: Optional[dict] = None
) -> list[ApprovalFolder]:
    """
    ZIP展開後のフォルダを走査し、承認番号単位でファイルを収集
    
    Args:
        root_path: ZIP_FILE_OUT のパス
        config: 設定辞書（Noneの場合はデフォルト読み込み）
    
    Returns:
        ApprovalFolder のリスト
    """
    if config is None:
        config = load_config()
    
    results = []
    
    # ルート直下または1階層下を探索
    # どちらのパターンもあり得るため、柔軟に対応
    
    potential_dept_folders = []
    
    # パターン1: ルート直下に部門フォルダがある場合
    # パターン2: ルート直下に1つフォルダがあり、その中に部門フォルダがある場合
    
    for item in root_path.iterdir():
        if not item.is_dir():
            continue
            
        # 名前チェック: 数字_名前 の形式か？
        code, name = parse_code_name(item.name)
        if code and name and code.isdigit():
            # これは部門フォルダとみなす
            potential_dept_folders.append(item)
        else:
            # 従来の「1階層下」パターンも探索
            for sub_item in item.iterdir():
                if sub_item.is_dir():
                    sub_code, sub_name = parse_code_name(sub_item.name)
                    if sub_code and sub_name and sub_code.isdigit():
                        potential_dept_folders.append(sub_item)

    for dept_folder in potential_dept_folders:
        dept_code, dept_name = parse_code_name(dept_folder.name)
        
                # 3階層目: 取引先コード_取引先名 (以降は同じ)
        for vendor_folder in dept_folder.iterdir():
                if not vendor_folder.is_dir():
                    continue
                
                vendor_code, vendor_name = parse_code_name(vendor_folder.name)
                
                # 階層構造に揺らぎがあるため（間に不明なフォルダが挟まるなど）、
                # Vendorフォルダ以下を再帰的に探索し、承認番号形式(ZSN...)のフォルダを探す
                
                # 見つかった承認フォルダを管理するセット（重複防止）
                processed_approvals = set()
                
                for path in vendor_folder.rglob("*"):
                    if not path.is_dir():
                        continue
                    
                    folder_name = path.name
                    # 承認番号フォルダの簡易判定 (ZSNで始まる)
                    # 必要であれば正規表現で厳密化: re.match(r"^ZSN\d+$", folder_name)
                    if folder_name.startswith("ZSN"):
                        approval_no = folder_name
                        if approval_no in processed_approvals:
                            continue
                        
                        processed_approvals.add(approval_no)
                        approval_folder = path
                        
                        # ステータスは親フォルダ名とする
                        # 例: .../承認済/ZSN... -> status="承認済"
                        # 例: ...//請済/ZSN... -> status="請済"
                        status = approval_folder.parent.name
                        
                        # ファイル収集
                        files = []
                        for file_path in approval_folder.iterdir():
                            if file_path.is_file() and is_target_file(file_path, config):
                                files.append(file_path)
                        
                        if files:
                            results.append(ApprovalFolder(
                                approval_no=approval_no,
                                dept_code=dept_code,
                                dept_name=dept_name,
                                vendor_code=vendor_code,
                                vendor_name=vendor_name,
                                status=status,
                                folder_path=approval_folder,
                                files=files
                            ))
    
    return results


def group_by_dept_vendor(folders: list[ApprovalFolder]) -> dict[tuple[str, str], list[ApprovalFolder]]:
    """
    部門コード・取引先コードでグループ化
    
    Returns:
        {(dept_code, vendor_code): [ApprovalFolder, ...]}
    """
    result = {}
    for folder in folders:
        key = (folder.dept_code, folder.vendor_code)
        if key not in result:
            result[key] = []
        result[key].append(folder)
    return result


if __name__ == "__main__":
    # テスト実行
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法: python folder_scanner.py <ZIP_FILE_OUT_PATH>")
        sys.exit(1)
    
    root = Path(sys.argv[1])
    if not root.exists():
        print(f"エラー: フォルダが見つかりません: {root}")
        sys.exit(1)
    
    folders = scan_folder(root)
    print(f"\n=== スキャン結果 ===")
    print(f"承認番号数: {len(folders)}")
    
    for f in folders[:10]:  # 最初の10件を表示
        print(f"  {f.approval_no}: {f.dept_code}_{f.vendor_code} ({len(f.files)} files)")
    
    if len(folders) > 10:
        print(f"  ... 他 {len(folders) - 10} 件")
