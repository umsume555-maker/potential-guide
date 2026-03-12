# 請求書OCRモジュール

支払依頼書に添付された請求書（PDF/画像）を解析し、金額やインボイス番号を抽出するモジュールです。

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install pdfplumber pdf2image pyocr Pillow opencv-python PyYAML python-dotenv
```

### 2. 外部ツールのインストール

#### Tesseract OCR（必須）
- ダウンロード: https://github.com/UB-Mannheim/tesseract/wiki
- インストール時に **日本語言語パック** を選択
- PATHを通す（または環境変数 `TESSDATA_PREFIX` を設定）

確認コマンド:
```bash
tesseract --version
tesseract --list-langs  # jpn が含まれていること
```

#### Poppler（PDF→画像変換用、必須）
- ダウンロード: https://github.com/oschwartz10612/poppler-windows/releases
- 展開して `bin` フォルダをPATHに追加

確認コマンド:
```bash
pdfinfo --version
```

#### 7-Zip（ZIP展開用）
- ダウンロード: https://www.7-zip.org/
- `invoice_ocr/7z/` に `7z.exe` と `7z.dll` を配置
- または PATH に追加

### 3. 環境変数の設定（AI OCR使用時）

`.env.sample` を `.env` にコピーして編集:
```bash
cp .env.sample .env
```

## 使い方

### ZIP展開

```bash
# ZIP_FILE_IN にZIPファイルを配置
# バッチ実行
unzip_invoices.bat
# ZIP_FILE_OUT に展開される
```

### フォルダスキャン（デバッグ用）

```bash
python -m invoice_ocr.folder_scanner <ZIP_FILE_OUT_PATH>
```

### 依存関係チェック

```bash
python -m invoice_ocr.pdf_tools
python -m invoice_ocr.preprocess
python -m invoice_ocr.ocr_engine
```

## フォルダ階層

```
ZIP_FILE_OUT/
 └─ （無視）
    └─ 部門コード_部門名
       └─ 取引先コード_取引先名
          └─ ステータス（決裁済/未決済/保留）
             └─ 承認番号（ZSN...）
                └─ 添付ファイル群（PDF/画像）
```

## 設定ファイル

`config.yaml` で以下を設定可能:
- OCR閾値
- スコアリング重み
- 対象/除外ファイル拡張子
- 金額抽出の除外/優先ラベル
- 稟議書キーワード

## トラブルシューティング

### 「Tesseract が見つかりません」
- Tesseractをインストールしてください
- PATHに追加するか、環境変数 `TESSDATA_PREFIX` を設定

### 「Poppler が見つかりません」
- Popplerをダウンロードして展開
- `bin` フォルダをPATHに追加

### 「日本語が読めない」
- Tesseractの日本語言語パックが必要
- `tesseract --list-langs` で `jpn` があるか確認

### 「7-Zip が見つかりません」
- `invoice_ocr/7z/` に `7z.exe` と `7z.dll` を配置
- または 7-Zip をインストールしてPATHに追加

## 注意事項

- APIキーは `.env` に保存し、ログやExcelに出力しないでください
- OCR結果は100%正確ではありません。重要な判断には目視確認を併用してください
