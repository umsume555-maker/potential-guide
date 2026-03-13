# 支払依頼チェックツール 移行ブループリント

> **目的**: Claude Code での再構築（Rebuild）に向けた、現行システムの完全な仕様引き継ぎ文書  
> **作成日**: 2026-03-12  
> **リポジトリ**: https://github.com/umsume555-maker/potential-guide

---

## 1. アプリの目的

経理部門が、E2（基幹システム）から出力された**支払依頼書CSV**を取り込み、以下の観点で**自動チェック**を行い、結果をExcelおよびGoogle Sheetsに出力するWebアプリケーション。

**チェック項目（5つの判定軸）:**

| # | 判定名 | 内容 |
|---|--------|------|
| 1 | 支払先相違 | 取引先コードと支払先コードが許容リストに含まれているか |
| 2 | 税区分 | 正マスター（ルール）と一致するか |
| 3 | 費用科目 | 正マスター（ルール）と一致するか（部門タイプ別対応） |
| 4 | 支払予定日 | 取引先の締日・支払条件から計算した期待日と一致するか |
| 5 | ズレ/モレ/二重 | 過去実績と比較して異常パターンがないか |

**付随機能:**
- **請求書OCR**: 請求書PDF/画像をGoogle Gemini APIで読み取り、金額突合
- **取引先別突合（Reconcile）**: 取引先の請求一覧（Excel/PDF）と支払データの突合
- **Google Sheets連携**: 経理用・事業所用の2種類のスプレッドシートに自動反映
- **マスター管理**: 取引先、部門、科目、祝日等の各種マスターをUI上で管理

---

## 2. 現在の起動フロー

### バッチファイル (`run_server.bat`)

```
ユーザーがrun_server.batをダブルクリック
  ↓
[1] py -m pip install fastapi uvicorn openpyxl python-multipart jinja2 gspread oauth2client --quiet
  ↓
[2] __pycache__ フォルダを全削除（キャッシュクリア）
  ↓
[3] 2秒後にブラウザで http://127.0.0.1:8000 を開く
  ↓
[4] uvicorn で app.main:app を起動（reload=False, ログはserver.logに出力）
```

### サーバー起動時の内部処理 (`app/main.py`)

```
FastAPIアプリ作成
  ↓
静的ファイルマウント（ui/static/）
Jinja2テンプレート設定（ui/templates/）
  ↓
ルーター登録（check, master, rule, assignment, exclude, sync, settings, ocr, reconcile）
  ↓
@app.on_event("startup") → init_database()
  → infra/schema.sql を実行してテーブル作成（IF NOT EXISTS）
  → SQLite WALモード設定
```

---

## 3. 技術スタック

### バックエンド

| ライブラリ | 用途 | 備考 |
|-----------|------|------|
| **FastAPI** | Webフレームワーク | ルーティング・API |
| **uvicorn** | ASGIサーバー | 本番もこれで起動 |
| **SQLite3** | データベース | `data/payment_check.db` |
| **openpyxl** | Excel読み書き | OUTPUT生成 |
| **python-multipart** | ファイルアップロード | FastAPIのForm/File依存 |
| **Jinja2** | HTMLテンプレート | UI描画 |
| **gspread** + **oauth2client** | Google Sheets API | スプレッドシート連携 |
| **python-dateutil** | 日付計算 | relativedelta使用 |
| **google-generativeai** | Gemini API | 請求書OCR |
| **PyMuPDF** (fitz) | PDF処理 | 請求書画像変換 |

### フロントエンド

| 技術 | 用途 |
|------|------|
| **バニラHTML/CSS/JS** | フレームワーク不使用 |
| **Jinja2テンプレート** | `ui/templates/index.html`（SPA的な単一ページ、タブ切替） |
| **Fetch API** | バックエンドとの通信 |

### データベース

- **SQLite3**（WALモード）
- DBファイル: `data/payment_check.db`
- スキーマ: `infra/schema.sql`（429行, 20+テーブル）

### Python バージョン
- Python 3.13（ユーザー環境）

---

## 4. ディレクトリ構成と主要ファイルの役割

```
支払依頼チェックツール/
├── run_server.bat              # 起動バッチ（ダブルクリックでサーバー起動）
├── system_specification.md     # 既存仕様書（異常検知・ステータス判定・出力仕様）
│
├── app/                        # FastAPIアプリケーション層
│   ├── main.py                 # エントリーポイント（FastAPI初期化・ルーター登録）
│   └── routers/
│       ├── check.py            # チェック実行API（CSV取込→判定→Excel出力→シート更新）
│       ├── master.py           # マスター管理API（取引先・部門・科目・祝日等のCRUD）
│       ├── rule.py             # 正マスター（税区分・科目ルール）管理API
│       ├── assignment.py       # 担当割当管理API（部門別・取引先別）
│       ├── exclude.py          # 除外取引先管理API
│       ├── sync.py             # Google Sheets同期API（経理用・事業所用）
│       ├── settings.py         # アプリ設定API（GoogleCredentials等）
│       ├── ocr.py              # 請求書OCR API（ファイルアップロード→AI読取→突合）
│       └── reconcile.py        # 取引先別突合API（Excel/PDF突合、シノニム管理）
│
├── domain/                     # ドメインロジック層
│   ├── validators/             # 判定モジュール（純粋関数）
│   │   ├── vendor_check.py     # 支払先相違チェック
│   │   ├── tax_category_check.py # 税区分チェック
│   │   ├── account_check.py    # 費用科目チェック
│   │   ├── payment_date_check.py # 支払予定日チェック（期待日計算含む）
│   │   ├── anomaly_check.py    # ズレ/モレ/二重チェック（毎月判定含む）
│   │   └── overall_check.py    # 総合判定（全判定結果から OK/NG/- を決定）
│   └── services/
│       ├── check_service.py    # メインチェック処理（CSV→判定→DB保存→Excel出力）★最大のファイル
│       ├── cumulative_service.py # 累積データ管理（14ヶ月ローテーション）
│       ├── excel_exporter.py   # Excel出力ヘルパー
│       └── invoice_match_service.py # WorkID照合サービス
│
├── infra/                      # インフラストラクチャ層
│   ├── database.py             # DB接続管理（get_db, init_database）
│   ├── schema.sql              # 全テーブル定義（20+テーブル）
│   ├── csv_loader.py           # CSV取込（E2出力CSV, マスターCSV各種）★大きいファイル
│   ├── excel_writer.py         # Excel出力（OUTPUTシート・DETAILシート・INFO）
│   ├── spreadsheet_service.py  # 経理用Google Sheets連携（★最大60KB）
│   ├── spreadsheet_service_ext.py # 事業所用Google Sheets連携
│   ├── drive_service.py        # Google Drive連携
│   ├── holiday_api.py          # 祝日API（内閣府CSVから自動取得）
│   ├── rule_repository.py      # 税区分・科目ルールのDB操作
│   └── settings_repository.py  # アプリ設定のDB操作
│
├── features/                   # 独立機能モジュール
│   └── vendor_invoice_reconcile/  # 取引先別突合機能
│       ├── models.py           # データモデル（TemplateConfig, InvoiceRecord等）
│       ├── repositories/
│       │   ├── settings_repository.py  # JSON設定ファイル管理
│       │   └── master_repository.py    # マスター参照
│       ├── services/
│       │   ├── extractor.py    # Excel/PDFからデータ抽出
│       │   ├── matcher.py      # 事業所名→部門コードのマッチング
│       │   └── reconciler.py   # 突合実行エンジン
│       └── utils/
│           └── excel_generator.py # 突合結果Excel出力
│
├── invoice_ocr/                # 請求書OCR機能
│   ├── ocr_engine.py           # OCRエンジン（テキスト抽出→AI解析の統合）
│   ├── ai_ocr.py               # Google Gemini API呼び出し
│   ├── extractor.py            # 金額・インボイス番号抽出
│   ├── pdf_tools.py            # PDF→画像変換
│   ├── folder_scanner.py       # ZIPフォルダ走査
│   ├── scoring.py              # 信頼度スコア計算
│   ├── preprocess.py           # 画像前処理
│   └── config.yaml             # OCR設定
│
├── ui/                         # フロントエンド
│   ├── templates/
│   │   └── index.html          # メインHTML（SPA、タブ切替で全機能を1画面に集約）
│   └── static/
│       ├── style.css           # スタイルシート
│       ├── app.js              # メインJS（チェック実行・マスター管理等）
│       └── reconcile.js        # 突合機能用JS
│
├── scripts/                    # マイグレーション・ユーティリティスクリプト
│   ├── migrate_*.py            # 各種DBマイグレーションスクリプト
│   ├── seed_*.py               # マスターデータ投入スクリプト
│   └── auto_register_depts.py  # 部門自動登録
│
├── config/                     # 設定ファイル
│   └── invoice_reconcile_settings.json  # 突合テンプレート設定（取引先別）
│
└── data/                       # データディレクトリ（.gitignore対象）
    ├── payment_check.db        # メインDB
    ├── credentials.json        # Google API認証情報
    └── OUTPUT_*.xlsx           # チェック結果Excel
```

---

## 5. データベーススキーマ（主要テーブル）

### 業務データ

| テーブル名 | 役割 |
|-----------|------|
| `cumulative` | 累積データ（14ヶ月ローテーション）。毎月判定・過去比較の基盤 |
| `output_summary` | チェック結果サマリ（ベース伝票単位、全判定結果含む） |
| `output_detail` | チェック結果明細（INPUT CSVの各行をそのまま保持） |
| `run_log` | 実行ログ（run_id, 基準月, 開始/終了時刻, 件数等） |
| `work_items` | WorkID管理（伝票と担当の紐付け） |
| `fingerprints` | 明細ハッシュ（WorkIDマッチング用） |
| `invoice_ocr_results` | OCR読取結果（金額・信頼度・突合ステータス） |

### マスターデータ

| テーブル名 | 役割 |
|-----------|------|
| `masters_vendor` | 取引先マスタ（支払条件・締日・口座情報等） |
| `masters_department` | 部門マスタ（部門タイプ: COST/SGA） |
| `masters_account` | 科目マスタ |
| `masters_allowed_payee` | 許容支払先（取引先×支払先の組み合わせ） |
| `masters_exclude` | 除外取引先（チェック対象外） |
| `masters_exception_dept` | 例外部門（出力対象外） |
| `masters_assign_dept_override` | 担当割当（部門個別例外） |
| `masters_assign_dept_rule` | 担当割当（部門範囲ルール） |
| `masters_assign_vendor` | 担当割当（取引先別） |
| `holidays` | 祝日マスタ |

### ルール（正マスター）

| テーブル名 | 役割 |
|-----------|------|
| `rule_tax_master` | 税区分ルール（取引先単位） |
| `rule_tax_rules` | 税区分ルール例外（部門別・タイプ別） |
| `rule_account_master` | 科目ルール（取引先×適用範囲: ANY/DEPT/DEPT_TYPE） |
| `rule_tax_account_master` | 旧: 税区分＋科目統合ルール |
| `rule_tax_account_audit` | ルール変更履歴 |
| `override_rule` | 強制修正ルール |
| `app_settings` | アプリ設定（KVS形式） |

---

## 6. 判定ロジック詳細

### 6.1 支払先相違 (`vendor_check.py`)
- 取引先コード ≠ 支払先コード の場合、`masters_allowed_payee` に登録があれば OK
- 登録がなければ NG

### 6.2 税区分 (`tax_category_check.py`)
- `rule_tax_rules` → `rule_tax_master` の優先順で正解値を取得
- 適用範囲: DEPT（部門個別） > DEPT_TYPE（原価/販管） > ANY（共通）
- 正解値と申請値が一致すれば OK

### 6.3 費用科目 (`account_check.py`)
- `rule_account_master` から適用範囲を考慮して正解値を取得
- 優先順: DEPT > DEPT_TYPE > ANY
- 正解値と申請値が一致すれば OK

### 6.4 支払予定日 (`payment_date_check.py`)

**⚠️ 既知のバグ: `closing_day`（締日）が計算に使用されていない**

現状のロジック:
```
期待日 = 取引日付 + payment_month_offset ヶ月後の payment_day 日 → 休日調整
```

本来あるべきロジック:
```
1. 取引日付が、どの締め期間に属するかを判定（closing_dayを使用）
2. その締め期間の翌月（payment_month_offset）の payment_day 日
3. 休日調整（休日前 or 休日後、月跨ぎ不可対応）
```

休日調整ロジック自体は正しく実装済み:
- 土日 + 祝日（DBテーブル） + 年末年始（12/31～1/3）
- holiday_handling: "1"=前倒し, "2"=後ろ倒し
- no_month_crossing: 後ろ倒しで翌月になる場合は前倒しに切替

### 6.5 ズレ/モレ/二重 (`anomaly_check.py`)

**毎月取引判定**: 直近4ヶ月で3回以上の取引実績

| 種別 | 条件 |
|------|------|
| 月ズレ？ | 取引日付が翌月 + 当月データ0件 |
| 毎月あるのに今月ない | 毎月判定=True + 当月データ0件（事業所シートのみ出力） |
| 二重入力？ | 毎月判定=True + 前月≤1件 + 当月≥2件 + **全額同一** |

### 6.6 総合判定 (`overall_check.py`)
- 全判定が OK → OK
- 1つでも NG → NG
- NGなし + 1つ以上「-」 → -

---

## 7. Google Sheets 連携仕様

### 7.1 経理用チェックシート (`spreadsheet_service.py`)
- 全OUTPUTデータを反映（モレ除く）
- 条件付き書式: ステータス「承認済」→行全体グレーアウト
- ゼロ埋め防止: コード値の先頭にシングルクォート付与

### 7.2 事業所用チェックシート (`spreadsheet_service.py` の `sync_site_sheet`)
- 異常検知データ（二重・月ズレ・モレ）のみ抽出
- 条件付き書式:
  - 二重入力？ → 取引先名セル: 薄い赤
  - 月ズレ？ → 取引日付セル: 薄い黄
  - 毎月あるのに今月ない → 取引先名セル: 薄い青
  - もれ（突合MISSING） → 取引先名セル: 薄い赤

### 7.3 突合結果シート (`spreadsheet_service_ext.py`)
- 取引先別突合結果を専用シートに反映

### ステータス更新ルール
| CSV入力値 | シート更新値 |
|-----------|------------|
| 支払確定 / 全額決裁 / 全額決済 / 締未済 | 承認済（強制上書き） |
| 未承認 | 手動変更値を維持、なければ「未承認」 |
| その他 | 未承認 |

---

## 8. CSV入力仕様

### 8.1 支払依頼書CSV（E2出力）
- エンコーディング: CP932（自動判別あり）
- 必須列: 伝票番号, 申請部門表示コード, 取引先コード, 支払先コード, 取引日付, 支払予定日付, 支払金額, 消費税区分, 費用科目コード
- 伝票番号フォーマット: `PI2511000007-0001`（ベース伝票番号-枝番）
- 集約: ベース伝票番号単位で合計、税区分・科目は最小枝番を採用

### 8.2 取引先マスターCSV
- 列位置をヘッダー名から自動推定
- 支払条件（closing_day, payment_month_offset, payment_day, holiday_handling）を抽出

### 8.3 部門マスターCSV
- 11列目: 部門コード（8桁のみ）、14列目: 部門名、20列目: 計上区分
- 「直接部門」→ COST、その他 → SGA

---

## 9. 請求書OCR仕様 (`invoice_ocr/`)

- **入力**: ZIPファイル → フォルダ走査 → PDF/画像を検出
- **処理**: PDF→画像変換 → Google Gemini API で金額・インボイス番号抽出
- **突合**: 部門コード×取引先コードで支払データと結合
- **出力**: OCR結果をDBに保存、チェック結果Excelに列追加

---

## 10. 取引先別突合仕様 (`features/vendor_invoice_reconcile/`)

- **入力**: 取引先の請求一覧ファイル（Excel or PDF）
- **テンプレート設定**: 取引先ごとに列位置・ヘッダー行を設定（JSON保存）
- **事業所名マッチング**: 請求書上の事業所名 → 部門コード（シノニム辞書 + マスター照合 + ファジーマッチ）
- **突合結果**: OK（金額一致）, NG（金額不一致）, MISSING（請求書にあるが支払データにない）
- **出力**: Excel + Google Sheets + DB保存

---

## 11. 未解決の課題・改善したい点

### 🔴 重大なバグ

1. **支払予定日の締日未使用**: `closing_day` が `calculate_expected_payment_date()` に渡されているが、内部で使われていない。月末締め以外の取引先で誤った期待日が計算される。

2. **突合「もれ」のDB取得エラー**: `spreadsheet_service.py` の `sync_site_sheet` 内で、突合結果から「もれ」データを取得する際に `conn.row_factory` の不整合でタプルアクセスエラーが発生していた（修正済みだが要確認）。

### 🟡 設計上の課題

3. **spreadsheet_service.py の巨大化**: 60KB超、1200行以上。経理用シート・事業所用シート・条件付き書式・ステータス更新が全て1ファイルに集約されている。

4. **check_service.py の巨大化**: 44KB超。CSV取込→判定→DB保存→Excel出力の全処理が1メソッド (`run_check`) に集中している。

5. **csv_loader.py の複数責務**: 支払依頼書CSV、取引先マスターCSV、部門マスターCSV、例外部門CSV、科目ルールCSV、取引先ルールCSVの6種類のローダーが1ファイルに同居。

6. **設定リポジトリの二重定義**: `infra/settings_repository.py`（DB設定）と `features/.../settings_repository.py`（JSON設定）が別ファイル。

7. **フロントエンドの保守性**: バニラJS + Jinja2テンプレートで全機能を1つのHTMLに集約しており、UIの拡張が困難。

8. **テストの欠如**: ユニットテスト・統合テストが一切存在しない。

9. **エラーハンドリングの不統一**: 一部で例外を握り潰し（silent catch）、ログのみに出力しているため、問題の特定が困難。

10. **デバッグスクリプトの散在**: ルート直下に `debug_*.py` が複数あり、本番コードとの境界が不明確。

### 🟢 改善要望

11. **環境変数管理**: 現在はDBの `app_settings` テーブルに保存。`.env` ファイルでの管理に統一したい。

12. **依存管理**: `requirements.txt` が存在しない。`run_server.bat` 内で `pip install` している。

13. **ログ管理**: `print()` が散在。Python標準の `logging` モジュールに統一したい。

14. **型ヒント**: 一部の関数で型ヒントが欠如。

---

## 12. 維持すべき重要な仕様

再構築時に**絶対に変えてはいけない**ポイント:

1. **バッチファイル起動**: ダブルクリック1回でサーバー起動→ブラウザ自動オープン
2. **CSV入力フォーマット**: E2出力のCSV形式（CP932, カラム名）への互換性
3. **SQLiteの使用**: サーバーレス（インストール不要）で動作すること
4. **Google Sheets連携**: gspread + oauth2clientでの認証フロー
5. **Excel出力フォーマット**: 既存のOUTPUTファイル形式（カラム構成・コード列の文字列化）
6. **ゼロ埋め防止**: 部門コード・取引先コード等の先頭ゼロが消えない処理
7. **ステータス手動変更の保護**: スプレッドシート上で手動編集した値が次回更新で上書きされないこと
8. **累積14ヶ月ローテーション**: 過去データの保持期間

---

## 13. 再構築時の推奨アプローチ

1. **関心の分離**: check_service.py と spreadsheet_service.py を機能別に分割
2. **テスト導入**: pytest で各バリデータの単体テストを最優先で作成
3. **requirements.txt 作成**: 依存ライブラリのバージョン固定
4. **logging 統一**: print() をすべて logging に置換
5. **型ヒント強化**: mypy での静的型チェック対応
6. **フロントエンド分離**: 必要であればReact/Vue等のSPAフレームワーク導入を検討
7. **設定管理統一**: `.env` + `pydantic-settings` での環境変数管理
