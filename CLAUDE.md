# 支払依頼チェックツール2 — 引き継ぎメモ (CLAUDE.md)

このファイルは、Claude Codeが新しいセッションを開始する際に自動的に読み込む前提で作成しています。
過去のデスクトップアプリ再インストールにより会話履歴自体は失われましたが、このメモにより次回以降の修正依頼をスムーズに開始できるようにしています。

## プロジェクト概要

**場所:** `D:\支払依頼チェックツール2`
**目的:** 社内の支払依頼書チェック業務を自動化するツール。FastAPI + SQLite + Python。

### 技術スタック
- FastAPI (Python) / SQLite / uvicorn
- Google Sheets API (gspread) / Google Drive API
- Gemini API（OCR・請求書解析）
- UI: HTML + vanilla JS (`ui/templates/index.html`, `ui/static/app.js`)

### 起動方法
- `run_server.bat` → サーバーPC（ユーザーのPC）で起動、他の課員はブラウザでLAN経由アクセス
- ポート: 8000
- 起動時に `config/server_base_url.txt` に現在のIPを書き込む
- 起動時に `invoice_ocr/PDF_ARCHIVE/` 内のZIPを自動展開

### 主要ファイル
- `app/main.py` — FastAPIアプリ本体・startup処理
- `app/routers/` — APIエンドポイント群（check, ocr, assignment, sync など）
- `infra/spreadsheet_service.py` — Google Sheetsへの書き込み
- `infra/database.py` — DB接続・マイグレーション
- `infra/schema.sql` — DBスキーマ
- `domain/services/check_service.py` — チェックロジック
- `invoice_ocr/` — OCR関連モジュール
- `data/payment_check.db` — SQLiteデータベース

### 重要なフォルダ
- `invoice_ocr/ZIP_FILE_IN/` — ZIPアップロード先（解析後削除）
- `invoice_ocr/ZIP_FILE_OUT/` — ZIP展開先（再解析時に削除される）
- `invoice_ocr/PDF_ARCHIVE/` — 永続アーカイブ（削除されない）
- `config/server_base_url.txt` — 現在のサーバーIP記録
- `data/credentials.json` — Google認証ファイル

### 詳しい仕様書
- `system_specification.md` — 異常検知ロジック（月ズレ・二重入力・毎月あるのに今月ないetc）、ステータス自動承認ロジック、出力仕様の詳細
- `migration_blueprint.md` — 移行・改修計画の詳細

## 直近の実装状況（2026-07-03時点の記録）

- 「担当2をスプシに反映」ボタン: 正常動作確認済み
- 未解決事項なし（この時点では）
- バグ修正・コード最適化を実施し、GitHub mainブランチにプッシュ済み（コミット a97371e）
  - `infra/csv_loader.py` の重複フィールド定義・空スタブ削除
  - `check_service.py` のDB_PATH参照を正式import化
  - デバッグ用コード（print文・デバッグエンドポイント）の整理
  - `reconciler.py` の重複関数を `infra.csv_loader` に委譲

※ この記録以降に行われた作業がある場合は、最新の `git log` やコードの状態を優先してください。

## ユーザーについて（作業スタイル）

- 経理財務部門の管理者。支払依頼チェックツールの開発・運用担当。
- 実装前に要件を相談・確認してから進めることを好む。「まだ実装しないで」と言われたら相談フェーズと実装フェーズを分けること。
- 過剰なUI変更や不要な実装は指摘される → シンプルな解決策を優先する。
- 動作確認はユーザー自身がブラウザで行う。
- 提案時はシンプルな実装を優先し、内容を確認してもらってから実装に進む。

## 次回セッションでのおすすめの進め方

1. まず `git log` や `git status` で最新のコード状態を確認する。
2. 修正・追加の依頼内容をヒアリングし、実装前に方針を確認する（いきなり実装しない）。
3. 実装は必要最小限にとどめ、シンプルな解決策を優先する。
