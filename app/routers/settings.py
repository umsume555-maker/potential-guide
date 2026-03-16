
from pathlib import Path
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
import yaml
import re

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.database import get_db, DATA_DIR, DB_PATH
from infra.settings_repository import SettingsRepository

router = APIRouter(prefix="/api/settings", tags=["settings"])
repo = SettingsRepository()
CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"

class SettingUpdate(BaseModel):
    key: str
    value: str

class AIModelSettings(BaseModel):
    model_a: str
    model_b: str

@router.get("/ai-models")
async def get_ai_models():
    """現在のAIモデル設定を取得"""
    settings = {"model_a": "", "model_b": ""}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "ai_ocr" in data:
                    settings["model_a"] = data["ai_ocr"].get("model_a", "")
                    settings["model_b"] = data["ai_ocr"].get("model_b", "")
        except Exception as e:
            print(f"Config Load Error: {e}")
    return settings

@router.post("/ai-models")
async def update_ai_models(settings: AIModelSettings):
    """AIモデル設定を更新（config.yamlの書き換え）"""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.yaml not found")
    
    try:
        # 行単位で読み込んで正規表現置換（コメント維持のため）
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        new_lines = []
        for line in lines:
            # model_a: "..."
            if re.match(r'^\s*model_a:', line):
                # インデント保持
                prefix = line.split("model_a:")[0]
                # コメント保持
                comment = ""
                if "#" in line:
                    comment = " #" + line.split("#", 1)[1].strip()
                new_lines.append(f'{prefix}model_a: "{settings.model_a}"{comment}\n')
            
            # model_b: "..."
            elif re.match(r'^\s*model_b:', line):
                prefix = line.split("model_b:")[0]
                comment = ""
                if "#" in line:
                    comment = " #" + line.split("#", 1)[1].strip()
                new_lines.append(f'{prefix}model_b: "{settings.model_b}"{comment}\n')
                
            else:
                new_lines.append(line)
        
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        return {"status": "ok", "message": "保存しました。反映にはアプリの再起動が必要です。"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失敗: {e}")

@router.get("/")
async def get_settings():
    """全設定を取得"""
    with get_db() as conn:
        # DBパスも返す
        settings = {
            "db_path": str(DB_PATH)
        }
        
        # 保存されている設定を取得（キー指定で拡張可能だが、一旦主要なものを取得）
        creds_path = repo.get_setting(conn, "google_credentials_path")
        if creds_path:
            settings["google_credentials_path"] = creds_path
            
        sheet_id = repo.get_setting(conn, "google_sheet_id")
        if sheet_id:
            settings["google_sheet_id"] = sheet_id
            
        site_sheet_id = repo.get_setting(conn, "site_sheet_id")
        if site_sheet_id:
            settings["site_sheet_id"] = site_sheet_id
            
        site_dept_codes = repo.get_setting(conn, "site_dept_codes")
        if site_dept_codes:
            settings["site_dept_codes"] = site_dept_codes
        
        # Gemini APIキー（マスク表示用: 先頭5文字 + ***）
        gemini_key = repo.get_setting(conn, "gemini_api_key")
        if gemini_key:
            settings["gemini_api_key_masked"] = gemini_key[:5] + "***" if len(gemini_key) > 5 else "***"
            settings["gemini_api_key_set"] = True
        else:
            settings["gemini_api_key_set"] = False
            
        return settings

@router.post("/credentials")
async def upload_credentials(file: UploadFile = File(...)):
    """Google認証ファイルをアップロード"""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="JSONファイルを選択してください")
    
    # 保存先: DATA_DIR/credentials.json（固定）
    save_path = DATA_DIR / "credentials.json"

    try:
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # DBには相対パスで保存（ポータブル対応）
        with get_db() as conn:
            repo.set_setting(conn, "google_credentials_path", "data/credentials.json")

        return {"status": "ok", "message": "認証ファイルを保存しました", "path": str(save_path)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存エラー: {str(e)}")

@router.post("/value")
async def update_setting_value(data: SettingUpdate):
    """汎用設定更新"""
    with get_db() as conn:
        repo.set_setting(conn, data.key, data.value)
        return {"status": "ok", "message": f"設定 {data.key} を更新しました"}
