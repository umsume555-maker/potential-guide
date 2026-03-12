
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
import os

class DriveService:
    def __init__(self, credentials_path):
        self.scopes = ['https://www.googleapis.com/auth/drive']
        self.credentials = Credentials.from_service_account_file(
            credentials_path, scopes=self.scopes)
        self.service = build('drive', 'v3', credentials=self.credentials)

    def find_folder(self, folder_name, parent_id=None):
        """フォルダを検索してIDを返す（共有ドライブ対応）"""
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
            
        # supportsAllDrives=True, includeItemsFromAllDrives=True が必要
        results = self.service.files().list(
            q=query, 
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        
        files = results.get('files', [])
        if files:
            return files[0]['id']
        return None

    def create_folder(self, folder_name, parent_id=None):
        """フォルダを作成してIDを返す"""
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
            
        file = self.service.files().create(
            body=file_metadata, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return file.get('id')

    def ensure_folder(self, folder_name, parent_id=None):
        """フォルダがあればIDを返し、なければ作成する"""
        folder_id = self.find_folder(folder_name, parent_id)
        if folder_id:
            # Debug log
            try:
                folder = self.service.files().get(
                    fileId=folder_id, 
                    fields="id, name, driveId",
                    supportsAllDrives=True
                ).execute()
                drive_id = folder.get('driveId')
                print(f"[INFO] Using folder: {folder.get('name')} (ID: {folder_id}, DriveID: {drive_id})")
                if not drive_id:
                    print(f"[WARN] This folder is in My Drive, NOT in a Shared Drive. Upload will fail for Service Accounts.")
            except Exception as e:
                print(f"[WARN] Failed to check folder info: {e}")
            return folder_id
            
        # 作成時は共有ドライブのルート直下に作られるとは限らない（parent_idがない場合）
        # ユーザーにフォルダを作ってもらう前提なら create_folder は呼ばれないはず
        try:
            return self.create_folder(folder_name, parent_id)
        except Exception:
            return None # 作成権限がない場合など

    def find_file(self, file_name, parent_id):
        """指定フォルダ内のファイルを検索"""
        query = f"name = '{file_name}' and '{parent_id}' in parents and trashed = false"
        results = self.service.files().list(
            q=query, 
            fields="files(id, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]
        return None

    def upload_file(self, file_path, folder_id):
        """ファイルをアップロードする"""
        file_name = os.path.basename(file_path)
        
        # 既に存在するかチェック
        existing = self.find_file(file_name, folder_id)
        if existing:
            return existing

        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, resumable=True)
        
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink',
            supportsAllDrives=True
        ).execute()
        
        # 共有ドライブ内のファイルはデフォルトでメンバーに共有されるので、
        # 明示的な権限付与はエラーになる場合がある（権限不足など）。
        # try-catchで囲むか、共有ドライブならスキップする必要があるが、
        # additional permission として anyone reader を付与するのは有効。
        try:
            self.service.permissions().create(
                fileId=file.get('id'),
                body={'type': 'anyone', 'role': 'reader'},
                fields='id',
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            # 共有ドライブの設定によっては外部共有が禁止されている場合がある
            print(f"Warning: Failed to set public permission: {e}")
        
        return file
