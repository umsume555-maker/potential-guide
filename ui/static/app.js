/**
 * 支払依頼書チェックツール - フロントエンドJS
 */
document.addEventListener('DOMContentLoaded', () => {

    // Helper
    const escapeHtml = (str) => {
        if (!str) return '';
        return str.replace(/[&<>"']/g, function (m) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            }[m];
        });
    };

    // DOM要素
    const checkForm = document.getElementById('checkForm');
    const btnCheck = document.getElementById('btnCheck');
    const btnSpreadsheet = document.getElementById('btnSpreadsheet');
    const btnMonthly = document.getElementById('btnMonthly');
    const btnHoliday = document.getElementById('btnHoliday');
    const btnUnlock = document.getElementById('btnUnlock');

    // マスタ更新ボタン
    const btnVendorUpdate = document.getElementById('btnVendorUpdate');
    const vendorFile = document.getElementById('vendorFile');
    const btnDeptUpdate = document.getElementById('btnDeptUpdate');
    const deptFile = document.getElementById('deptFile');
    const btnVendorRuleUpdate = document.getElementById('btnVendorRuleUpdate');
    const vendorRuleFile = document.getElementById('vendorRuleFile');
    const btnAccountMasterUpdate = document.getElementById('btnAccountMasterUpdate');
    const accountMasterFile = document.getElementById('accountMasterFile');

    // Status Elements
    const runStatus = document.getElementById('runStatus');
    const overallBadge = document.getElementById('overallBadge');
    const inputRows = document.getElementById('inputRows');
    const outputRows = document.getElementById('outputRows');
    const ngCount = document.getElementById('ngCount');
    const holdCount = document.getElementById('holdCount');
    const dashCount = document.getElementById('dashCount');
    const holidayStatus = document.getElementById('holidayStatus');
    const excelFilename = document.getElementById('excelFilename');
    const downloadLink = document.getElementById('downloadLink');
    const resultMessage = document.getElementById('resultMessage');
    const errorMessage = document.getElementById('errorMessage');
    const toast = document.getElementById('toast');

    // 正マスター管理 DOM (Tax)
    const ruleSearch = document.getElementById('ruleSearch');
    const btnRuleSearch = document.getElementById('btnRuleSearch');
    const ruleListBody = document.getElementById('ruleListBody');
    const ruleCount = document.getElementById('ruleCount');

    // 正マスター管理 DOM (Tax Edit)
    const detailVendorCode = document.getElementById('detailVendorCode');
    const detailVendorName = document.getElementById('detailVendorName');
    const taxRuleForm = document.getElementById('taxRuleForm');
    const editTax = document.getElementById('editTax');
    const editTaxReason = document.getElementById('editTaxReason');
    const taxUpdatedAt = document.getElementById('taxUpdatedAt');
    const btnSaveTax = document.getElementById('btnSaveTax');

    // 正マスター管理 DOM (Account Edit)
    const accountRuleListBody = document.getElementById('accountRuleListBody');
    const newAccountDeptType = document.getElementById('newAccountDeptType');
    const newAccountCode = document.getElementById('newAccountCode');
    const newAccountReason = document.getElementById('newAccountReason');
    const btnAddAccountRule = document.getElementById('btnAddAccountRule');
    const btnAccountRuleUpload = document.getElementById('btnAccountRuleUpload');
    const accountRuleFile = document.getElementById('accountRuleFile');

    // Override DOM
    const overrideForm = document.getElementById('overrideForm');
    const ovVendorCode = document.getElementById('ovVendorCode');
    const ovDeptCode = document.getElementById('ovDeptCode');
    const ovField = document.getElementById('ovField');
    const ovValue = document.getElementById('ovValue');
    const ovReason = document.getElementById('ovReason');
    const btnSaveOverride = document.getElementById('btnSaveOverride');

    let currentRunId = null; // 実行ID保持用


    // --- メイン処理開始 ---

    // 現在の日付をデフォルト値に設定
    // 現在の日付をデフォルト値に設定（前回の保存値があればそれを使用）
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const defaultMonth = `${year}-${month}`;

    const baseMonthParams = document.getElementById('baseMonth');
    if (baseMonthParams) {
        // localStorageから前回値を復元
        const savedMonth = localStorage.getItem('lastBaseMonth');
        if (savedMonth) {
            baseMonthParams.value = savedMonth;
        } else {
            baseMonthParams.value = defaultMonth;
        }

        // 変更時に保存
        baseMonthParams.addEventListener('change', (e) => {
            localStorage.setItem('lastBaseMonth', e.target.value);
        });
    }

    // 祝日ステータスとルール検索を初期実行
    checkHolidayStatus();
    searchTaxRules();
    loadServerSettings(); // サーバー設定読み込み

    // サーバー設定を読み込んでフォームに反映
    async function loadServerSettings() {
        try {
            const res = await fetch('/api/settings/');
            if (!res.ok) throw new Error('設定の読み込みに失敗しました');
            const data = await res.json();

            // Google Sheets ID (Run Tab)
            const spreadsheetIdInput = document.getElementById('spreadsheetId');
            if (spreadsheetIdInput && data.google_sheet_id) {
                spreadsheetIdInput.value = data.google_sheet_id;
                // localStorageも更新しておく
                localStorage.setItem('lastSpreadsheetId', data.google_sheet_id);
            }

            // Google Sheets ID (Settings Tab)
            const settingSheetIdInput = document.getElementById('settingSheetId');
            if (settingSheetIdInput && data.google_sheet_id) {
                settingSheetIdInput.value = data.google_sheet_id;
            }

            // Site Sheet ID (Settings Tab)
            const settingSiteSheetIdInput = document.getElementById('settingSiteSheetId');
            if (settingSiteSheetIdInput && data.site_sheet_id) {
                settingSiteSheetIdInput.value = data.site_sheet_id;
            }

            // DB Path
            const settingDbPath = document.getElementById('settingDbPath');
            if (settingDbPath && data.db_path) {
                settingDbPath.value = data.db_path;
            }

            // Creds Path
            const settingCredsPath = document.getElementById('settingCredsPath');
            if (settingCredsPath && data.google_credentials_path) {
                settingCredsPath.value = data.google_credentials_path;
            }

            // Gemini API Key (Masked)
            const settingGeminiApiKey = document.getElementById('settingGeminiApiKey');
            const geminiStatus = document.getElementById('geminiApiStatus');
            if (settingGeminiApiKey && data.gemini_api_key_set) {
                settingGeminiApiKey.value = data.gemini_api_key_masked || '********';
                if (geminiStatus) geminiStatus.textContent = '✅ 設定済み';
            }

        } catch (e) {
            console.error("Failed to load settings:", e);
        }
    }


    // --- Helper Functions ---

    // トースト表示
    function showToast(message, duration = 3000) {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), duration);
    }

    // エラー表示
    function showError(message) {
        if (!errorMessage) return;
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        if (resultMessage) resultMessage.style.display = 'none';
    }
    window.showError = showError;  // グローバルに公開

    // 成功表示
    function showSuccess(message) {
        if (!resultMessage) return;
        resultMessage.textContent = message;
        resultMessage.classList.add('success');
        resultMessage.style.display = 'block';
        if (errorMessage) errorMessage.style.display = 'none';
    }
    window.showSuccess = showSuccess;  // グローバルに公開

    // ステータス更新
    function updateStatus(data) {
        if (inputRows) inputRows.textContent = data.input_rows?.toLocaleString() ?? '-';
        if (outputRows) outputRows.textContent = data.output_rows?.toLocaleString() ?? '-';
        if (ngCount) ngCount.textContent = data.ng_count?.toLocaleString() ?? '-';
        if (holdCount) holdCount.textContent = data.hold_count?.toLocaleString() ?? '-';
        if (dashCount) dashCount.textContent = data.dash_count?.toLocaleString() ?? '-';

        // NG件数に応じてスタイル変更
        if (data.ng_count > 0) {
            if (ngCount) ngCount.className = 'badge ng';
            if (overallBadge) {
                overallBadge.textContent = 'NG';
                overallBadge.className = 'badge ng';
            }
        } else if (data.dash_count > 0) {
            if (overallBadge) {
                overallBadge.textContent = '-';
                overallBadge.className = 'badge dash';
            }
        } else if (data.output_rows > 0) {
            if (overallBadge) {
                overallBadge.textContent = 'OK';
                overallBadge.className = 'badge ok';
            }
        }
    }


    // --- Event Listeners ---

    // チェック実行
    if (checkForm) {
        checkForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData(checkForm);

            // ボタン無効化
            btnCheck.disabled = true;
            btnCheck.innerHTML = '<span class="loading"></span> 実行中...';
            runStatus.textContent = '実行中';
            runStatus.className = 'badge dash';

            try {
                const response = await fetch('/api/check/run', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || 'チェック処理に失敗しました');
                }

                if (data.status === 'error') {
                    // エラーの場合でも、診断用Excelがあればダウンロード可能にする
                    if (data.excel_filename) {
                        excelFilename.textContent = data.excel_filename;
                        downloadLink.href = `/api/check/download/${data.excel_filename}`;
                        // 拡張子補完してdownload属性に設定
                        const fName = data.excel_filename.toLowerCase().endsWith('.xlsx') ? data.excel_filename : data.excel_filename + '.xlsx';
                        downloadLink.setAttribute('download', fName);
                        downloadLink.style.display = 'inline-flex';

                        showError(`エラーが発生しましたが、診断用ファイルをダウンロードできます: ${data.error_message || '詳細不明'}`);
                        runStatus.textContent = 'エラー(診断可)';
                        runStatus.className = 'badge ng';
                    } else {
                        throw new Error(data.error_message || '不明なエラーが発生しました');
                    }
                } else {
                    // 成功（completed / warning など）
                    runStatus.textContent = '完了';
                    runStatus.className = 'badge ok';

                    // 成功時のみ実行IDを保存（月次更新用）
                    currentRunId = data.run_id;

                    updateStatus(data);

                    // ダウンロードリンク
                    if (data.excel_filename) {
                        excelFilename.textContent = data.excel_filename;
                        downloadLink.href = `/api/check/download/${data.excel_filename}`;
                        // 拡張子補完してdownload属性に設定
                        const fName = data.excel_filename.toLowerCase().endsWith('.xlsx') ? data.excel_filename : data.excel_filename + '.xlsx';
                        downloadLink.setAttribute('download', fName);
                        downloadLink.style.display = 'inline-flex';

                        // スプシ更新・月次更新ボタンを有効化（成功時のみ）
                        if (btnSyncSheet) btnSyncSheet.disabled = false;
                        if (btnSyncSheetDrive) btnSyncSheetDrive.disabled = false;
                        if (btnMonthly) btnMonthly.disabled = false;
                    }

                    showSuccess(`チェック完了: ${data.output_rows}件処理、NG ${data.ng_count}件`);
                    showToast('チェック完了！結果を確認してください');
                }

            } catch (error) {
                runStatus.textContent = 'エラー';
                runStatus.className = 'badge ng';
                showError(`エラー: ${error.message}`);
                showToast('エラーが発生しました');
            } finally {
                btnCheck.disabled = false;
                btnCheck.innerHTML = '▶ チェック実行';
            }
        });
    }

    // 取引先マスタ更新
    if (btnVendorUpdate) {
        btnVendorUpdate.addEventListener('click', () => {
            if (confirm('取引先マスタを更新しますか？\n現在登録されている取引先データは全て削除され、新しくCSVから取り込みます。')) {
                vendorFile.click();
            }
        });

        vendorFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;
            handleFileUpload('/api/master/vendor/upload', e.target.files[0], btnVendorUpdate, '取引先マスタ');
        });
    }

    // 部門マスタ更新
    if (btnDeptUpdate) {
        btnDeptUpdate.addEventListener('click', () => {
            if (confirm('部門マスタを更新しますか？\n現在登録されている部門データは全て削除され、新しくCSVから取り込みます。\n※8桁の部門コードのみが対象です。')) {
                deptFile.click();
            }
        });

        deptFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;
            handleFileUpload('/api/master/department/upload', e.target.files[0], btnDeptUpdate, '部門マスタ', (data) => {
                return `完了: ${data.count}件の部門を取り込みました\n(販管/原価の自動判定も完了しました)`;
            });
        });
    }

    // 取引先ルール（科目+税区分）一括更新
    if (btnVendorRuleUpdate) {
        btnVendorRuleUpdate.addEventListener('click', () => {
            if (confirm('取引先ルール（科目+税区分）を一括登録しますか？\nCSVフォーマット: 取引先ｺｰﾄﾞ,cost科目ｺｰﾄﾞ,sga科目ｺｰﾄﾞ,税区分ｺｰﾄﾞ')) {
                vendorRuleFile.click();
            }
        });

        vendorRuleFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;
            handleFileUpload('/api/master/vendor-rule/upload', e.target.files[0], btnVendorRuleUpdate, '取引先ルール', (data) => {
                return `完了: 科目${data.account_count}件, 税区分${data.tax_count}件を登録しました`;
            });
        });
    }

    // 科目マスタ更新
    if (btnAccountMasterUpdate) {
        btnAccountMasterUpdate.addEventListener('click', () => {
            if (confirm('科目マスタを更新しますか？\nCSVフォーマット: 科目コード,科目名')) {
                accountMasterFile.click();
            }
        });

        accountMasterFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;
            handleFileUpload('/api/master/account-master/upload', e.target.files[0], btnAccountMasterUpdate, '科目マスタ', (data) => {
                return `完了: ${data.count}件の科目マスタを登録しました`;
            });
        });
    }

    // 例外部門管理ダイアログ
    const btnExceptionDeptManage = document.getElementById('btnExceptionDeptManage');
    const exceptionDeptDialog = document.getElementById('exceptionDeptDialog');
    const exceptionDeptList = document.getElementById('exceptionDeptList');
    const btnAddExceptionDept = document.getElementById('btnAddExceptionDept');
    const btnCloseExceptionDeptDialog = document.getElementById('btnCloseExceptionDeptDialog');
    const newExceptionDeptCode = document.getElementById('newExceptionDeptCode');
    const newExceptionDeptName = document.getElementById('newExceptionDeptName');

    // 例外部門一覧を読み込み
    async function loadExceptionDepts() {
        if (!exceptionDeptList) return;
        exceptionDeptList.innerHTML = '<em style="color:#888;">読込中...</em>';
        try {
            const res = await fetch('/api/master/exception-dept');
            const data = await res.json();
            if (data.items && data.items.length > 0) {
                exceptionDeptList.innerHTML = data.items.map(item => `
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.05);">
                        <div>
                            <strong>${escapeHtml(item.dept_code)}</strong>
                            ${item.dept_name ? `<span style="color:#999;margin-left:8px;">${escapeHtml(item.dept_name)}</span>` : ''}
                        </div>
                        <button type="button" class="danger" style="padding:4px 8px;font-size:11px;" onclick="deleteExceptionDept('${item.dept_code}')">削除</button>
                    </div>
                `).join('');
            } else {
                exceptionDeptList.innerHTML = '<em style="color:#888;">登録されている例外部門はありません</em>';
            }
        } catch (e) {
            exceptionDeptList.innerHTML = '<em style="color:red;">読込エラー: ' + e.message + '</em>';
        }
    }

    // ダイアログを開く
    if (btnExceptionDeptManage) {
        btnExceptionDeptManage.addEventListener('click', () => {
            if (exceptionDeptDialog) {
                exceptionDeptDialog.style.display = 'flex';
                loadExceptionDepts();
            }
        });
    }

    // ダイアログを閉じる
    if (btnCloseExceptionDeptDialog) {
        btnCloseExceptionDeptDialog.addEventListener('click', () => {
            if (exceptionDeptDialog) exceptionDeptDialog.style.display = 'none';
        });
    }

    // 例外部門を追加
    if (btnAddExceptionDept) {
        btnAddExceptionDept.addEventListener('click', async () => {
            const code = newExceptionDeptCode ? newExceptionDeptCode.value.trim() : '';
            const name = newExceptionDeptName ? newExceptionDeptName.value.trim() : '';
            if (!code) {
                showToast('部門コードを入力してください');
                return;
            }
            try {
                const res = await fetch('/api/master/exception-dept', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ dept_code: code, dept_name: name, reason: '' })
                });
                if (!res.ok) throw new Error('登録失敗');
                showToast('例外部門を追加しました');
                if (newExceptionDeptCode) newExceptionDeptCode.value = '';
                if (newExceptionDeptName) newExceptionDeptName.value = '';
                loadExceptionDepts();
            } catch (e) {
                showToast('エラー: ' + e.message);
            }
        });
    }

    // 例外部門を削除（グローバル関数）
    window.deleteExceptionDept = async (code) => {
        if (!confirm(`部門 ${code} を例外から削除しますか？`)) return;
        try {
            const res = await fetch(`/api/master/exception-dept/${encodeURIComponent(code)}`, { method: 'DELETE' });
            if (!res.ok) throw new Error('削除失敗');
            showToast('例外部門を削除しました');
            loadExceptionDepts();
        } catch (e) {
            showToast('エラー: ' + e.message);
        }
    };

    // 祝日更新
    if (btnHoliday) {
        btnHoliday.addEventListener('click', async () => {
            if (!confirm('祝日データを更新しますか？')) return;

            btnHoliday.disabled = true;
            btnHoliday.innerHTML = '<span class="loading"></span> 更新中...';

            try {
                const response = await fetch('/api/master/holiday/update', { method: 'POST' });
                const data = await response.json();

                if (!response.ok) throw new Error(data.detail || '更新失敗');

                showToast(`祝日データを更新しました: ${data.count}件`);
                checkHolidayStatus();

            } catch (error) {
                showToast(`エラー: ${error.message}`);
            } finally {
                btnHoliday.disabled = false;
                btnHoliday.innerHTML = '☀ 祝日更新';
            }
        });
    }

    // 汎用ファイルアップロードハンドラ
    async function handleFileUpload(url, file, btn, name, successMsgCallback) {
        const formData = new FormData();
        formData.append('file', file);

        btn.disabled = true;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="loading"></span> 取込中...';

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (!response.ok) throw new Error(data.detail || `${name}取込に失敗しました`);

            const msg = successMsgCallback ? successMsgCallback(data) : `完了: ${data.count}件の${name}を登録しました`;
            showToast(msg);
            showSuccess(`${name}更新完了`);

        } catch (error) {
            showError(`${name}更新エラー: ${error.message}`);
            showToast('更新失敗');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
            // リセットしたいがinput要素がスコープ外の場合はquerySelector等で再取得するか、呼び出し元でやるか
            // 今回は簡易的に、各input要素のvalueリセットはここでやらない（changeイベント発火のためにはリセット推奨だが）
            // DOM要素をcaptureしているので、各イベントリスナー内で個別にリセットするほうが安全だが、
            // ここでは変数アクセスできないため、input.value = '' は呼び出し元ですべきだった。
            // しかし既存コードの構造上、ここでリセットしたい。
            // 仕方ないので、イベントリスナー側でリセット処理を書くべきだが、今回はユーザーが再選択すればchange発火するので許容
            // またはdocument.getElementByIdで再取得してリセット
        }
    }


    // 祝日ステータス確認
    async function checkHolidayStatus() {
        if (!holidayStatus) return;
        try {
            const response = await fetch('/api/master/holiday/status');
            const data = await response.json();

            if (data.status === 'ok') {
                holidayStatus.textContent = `OK (${data.total_count}件)`;
                holidayStatus.className = 'badge ok';
            } else {
                holidayStatus.textContent = `要更新 (${data.missing_years.join(', ')})`;
                holidayStatus.className = 'badge dash';
            }
        } catch (error) {
            holidayStatus.textContent = '確認失敗';
            holidayStatus.className = 'badge ng';
        }
    }

    // ロック解除
    if (btnUnlock) {
        btnUnlock.addEventListener('click', async () => {
            if (!confirm('ロックを強制解除しますか？\n他のユーザーが使用中の場合、データが破損する可能性があります。')) {
                return;
            }
            showToast('ロック解除機能は未実装です');
        });
    }

    // スプシ更新
    // Google Sheets Sync
    const spreadsheetId = document.getElementById('spreadsheetId');
    const btnSyncSheet = document.getElementById('btnSyncSheet');
    const btnSyncSheetDrive = document.getElementById('btnSyncSheetDrive');
    const syncStatus = document.getElementById('syncStatus');

    // Persistence for Spreadsheet ID (Main)
    if (spreadsheetId) {
        const savedId = localStorage.getItem('lastSpreadsheetId');
        if (savedId) spreadsheetId.value = savedId;

        spreadsheetId.addEventListener('change', () => {
            localStorage.setItem('lastSpreadsheetId', spreadsheetId.value.trim());
        });
    }

    // 共通Sync関数（常にDriveアップロードあり）
    async function runSheetSync() {
        // ID抽出 (URLが貼られた場合も対応)
        const rawId = spreadsheetId.value.trim();
        // URL形式 (/d/xxxxxxxx/...) からIDを抽出
        const match = rawId.match(/\/d\/([a-zA-Z0-9-_]+)/);
        const sheetId = match ? match[1] : rawId;

        if (!sheetId) {
            showError("スプレッドシートIDを入力してください");
            return;
        }
        if (!currentRunId) {
            showError("チェック結果がありません");
            return;
        }

        const msg = 'スプレッドシートを更新しますか？\n（プルダウンや手入力ステータスは維持されます）\n\n証憑ファイルをGoogle Driveへアップロードします。\n初回は数分かかる場合があります。';
        if (!confirm(msg)) return;

        // ボタン制御
        if (btnSyncSheet) btnSyncSheet.disabled = true;
        if (btnSyncSheetDrive) btnSyncSheetDrive.disabled = true;

        if (syncStatus) syncStatus.textContent = '⏳ 同期中 (証憑アップロードあり)...';

        try {
            const res = await fetch('/api/sync/google-sheet', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    run_id: currentRunId,
                    spreadsheet_id: sheetId,
                    upload_drive: true
                })
            });
            const data = await res.json();

            if (!res.ok) throw new Error(data.detail || "同期に失敗しました");

            showSuccess(data.message);
            if (syncStatus) syncStatus.textContent = '✅ ' + data.message;
            showToast('シート更新完了');

        } catch (e) {
            showError(e.message);
            if (syncStatus) syncStatus.textContent = '❌ エラー: ' + e.message;
        } finally {
            if (btnSyncSheet) btnSyncSheet.disabled = false;
            if (btnSyncSheetDrive) btnSyncSheetDrive.disabled = false;
        }
    }

    if (btnSyncSheet) {
        btnSyncSheet.addEventListener('click', () => runSheetSync());
    }
    if (btnSyncSheetDrive) {
        btnSyncSheetDrive.addEventListener('click', () => runSheetSync());
    }

    // 月次更新
    if (btnMonthly) {
        btnMonthly.addEventListener('click', async () => {
            if (!confirm('月次更新を実行しますか？\n今回のチェック結果（OK分）を累積データに反映し、次回チェックの「正」として使用します。\nまた、14ヶ月より古いデータは削除されます。')) {
                return;
            }

            if (!currentRunId) {
                showError('チェックが実行されていません。先にチェックを実行してください。');
                return;
            }

            btnMonthly.disabled = true;
            btnMonthly.innerHTML = '<span class="loading"></span> 更新中...';

            try {
                const response = await fetch('/api/check/monthly-update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        run_id: currentRunId,
                        base_month: document.getElementById('baseMonth').value
                    })
                });

                const data = await response.json();

                if (!response.ok) throw new Error(data.detail || '月次更新に失敗しました');

                showSuccess(`月次更新完了: 正解データとして${data.count}件登録しました`);
                showToast('月次更新が完了しました');

            } catch (error) {
                showError(`更新エラー: ${error.message}`);
                showToast('月次更新に失敗しました');
            } finally {
                btnMonthly.disabled = false;
                btnMonthly.innerHTML = '↻ 月次更新';
            }
        });
    }

    // --- タブ切り替え ---
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const targetId = `tab-${btn.dataset.target}`;
            const target = document.getElementById(targetId);
            if (target) target.classList.add('active');
        });
    });

    // --- 正マスター管理 Logic ---

    // Tax Rule Search
    if (btnRuleSearch) {
        btnRuleSearch.addEventListener("click", () => searchTaxRules(ruleSearch.value));
    }
    if (ruleSearch) {
        ruleSearch.addEventListener("keypress", (e) => {
            if (e.key === "Enter") searchTaxRules(ruleSearch.value);
        });
    }

    async function searchTaxRules(query = "") {
        if (!ruleListBody) return;
        try {
            const res = await fetch(`/api/rules/tax?q=${encodeURIComponent(query)}`);
            if (!res.ok) throw new Error("検索に失敗しました");
            const rules = await res.json();

            renderTaxRuleList(rules);
            if (ruleCount) ruleCount.textContent = `${rules.length}件`;

        } catch (e) {
            showToast(`検索エラー: ${e.message}`);
        }
    }

    function renderTaxRuleList(rules) {
        ruleListBody.innerHTML = "";
        if (rules.length === 0) {
            ruleListBody.innerHTML = `<tr><td colspan="6" style="text-align:center">該当なし</td></tr>`;
            return;
        }

        rules.forEach(r => {
            const tr = document.createElement("tr");
            const tax = r.expected_tax || '<span class="dash">-</span>';
            // COST科目とSGA科目を個別表示（コード + 名前）
            const costAcc = r.cost_account
                ? `${r.cost_account}<br><small style="color:#aaa;">${escapeHtml(r.cost_account_name || '')}</small>`
                : '<span class="dash">-</span>';
            const sgaAcc = r.sga_account
                ? `${r.sga_account}<br><small style="color:#aaa;">${escapeHtml(r.sga_account_name || '')}</small>`
                : '<span class="dash">-</span>';

            tr.innerHTML = `
                <td>${r.vendor_code}</td>
                <td style="max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(r.vendor_name || '')}">${escapeHtml(r.vendor_name || '-')}</td>
                <td style="font-size:12px;">${costAcc}</td>
                <td style="font-size:12px;">${sgaAcc}</td>
                <td>${tax}</td>
                <td style="text-align:center;"><button type="button" class="danger delete-tax-btn" style="padding:2px 6px;font-size:11px;" data-code="${r.vendor_code}" data-name="${escapeHtml(r.vendor_name || '')}">削除</button></td>
            `;
            tr.style.cursor = "pointer";

            // データ属性で科目情報も保持
            tr.dataset.costAccount = r.cost_account || '';
            tr.dataset.sgaAccount = r.sga_account || '';

            // 削除ボタンのイベントリスナー
            const deleteBtn = tr.querySelector('.delete-tax-btn');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const code = deleteBtn.dataset.code;
                    const name = deleteBtn.dataset.name;
                    if (!confirm(`${name} (${code}) の税区分ルールを削除しますか？`)) return;
                    try {
                        const res = await fetch(`/api/rules/tax/${encodeURIComponent(code)}`, { method: 'DELETE' });
                        if (!res.ok) throw new Error('削除失敗');
                        showToast('税区分ルールを削除しました');
                        // 一覧を再読み込み
                        const searchInput = document.getElementById('ruleSearch');
                        const query = searchInput ? searchInput.value : "";
                        searchTaxRules(query);
                    } catch (err) {
                        showToast('エラー: ' + err.message);
                    }
                });
            }

            tr.addEventListener("click", (e) => {
                // 削除ボタンクリック時は詳細表示しない
                if (e.target.tagName === 'BUTTON') return;
                selectVendor(r);
            });
            ruleListBody.appendChild(tr);
        });
    }

    // 税区分ルール削除（グローバル関数）
    window.deleteTaxRule = async (vendorCode, vendorName) => {
        if (!confirm(`${vendorName} (${vendorCode}) の税区分ルールを削除しますか？`)) return;
        try {
            const res = await fetch(`/api/rules/tax/${encodeURIComponent(vendorCode)}`, { method: 'DELETE' });
            if (!res.ok) throw new Error('削除失敗');
            showToast('税区分ルールを削除しました');
            // 一覧を再読み込み
            const searchInput = document.getElementById('ruleSearch');
            const query = searchInput ? searchInput.value : "";
            searchTaxRules(query);
        } catch (e) {
            showToast('エラー: ' + e.message);
        }
    };

    function selectVendor(rule) {
        console.log("Selected rule:", rule);
        try {
            // ハイライト
            if (ruleListBody) {
                ruleListBody.querySelectorAll('tr').forEach(row => row.style.background = '');
                // event.targetはここにはない
            }

            if (!detailVendorCode || !detailVendorName) {
                console.error("Detail elements not found");
                return;
            }

            detailVendorCode.textContent = rule.vendor_code;
            detailVendorName.textContent = rule.vendor_name || '-';

            if (editTax) editTax.value = rule.expected_tax || "";
            if (editTaxReason) editTaxReason.value = "";
            if (taxUpdatedAt) taxUpdatedAt.textContent = rule.updated_at ? new Date(rule.updated_at).toLocaleString() : "-";

            // COST/SGA科目を設定
            const editCostAccount = document.getElementById('editCostAccount');
            const editSgaAccount = document.getElementById('editSgaAccount');
            if (editCostAccount) {
                editCostAccount.value = rule.cost_account || "";
                if (editCostAccount._resolveOnSet) editCostAccount._resolveOnSet(rule.cost_account || "");
            }
            if (editSgaAccount) {
                editSgaAccount.value = rule.sga_account || "";
                if (editSgaAccount._resolveOnSet) editSgaAccount._resolveOnSet(rule.sga_account || "");
            }

            loadAccountRules(rule.vendor_code);

            // 注意事項を読み込む
            if (window.loadVendorNotes) window.loadVendorNotes(rule.vendor_code);
        } catch (e) {
            console.error("selectVendor error:", e);
            showError("選択処理でエラーが発生しました: " + e.message);
        }
    }

    // Save Tax
    if (taxRuleForm) {
        taxRuleForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const vCode = detailVendorCode ? detailVendorCode.textContent.trim() : "-";
            if (vCode === "-" || !vCode) {
                showError("取引先が選択されていません（リストからクリックしてください）");
                return;
            }

            const data = {
                vendor_code: vCode,
                expected_tax: editTax.value,
                update_reason: editTaxReason.value,
                updated_by: "user"
            };

            btnSaveTax.disabled = true;
            try {
                const res = await fetch("/api/rules/tax", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                showSuccess("税区分ルールを保存しました");
                searchTaxRules(ruleSearch.value);
            } catch (err) {
                showError(err.message);
            } finally {
                btnSaveTax.disabled = false;
            }
        });
    }

    // ---- 科目検索ドロップダウン共通ロジック ----
    function setupAccountSearch(inputId, btnId, dropdownId, nameDisplayId) {
        const input    = document.getElementById(inputId);
        const btn      = document.getElementById(btnId);
        const dropdown = document.getElementById(dropdownId);
        const nameDisp = document.getElementById(nameDisplayId);
        if (!input || !dropdown) return;

        let currentItems = [];
        let highlightIdx = -1;

        // 科目名をコードから取得して表示
        async function resolveAccountName(code) {
            if (!nameDisp || !code) { if (nameDisp) nameDisp.textContent = ''; return; }
            try {
                const r = await fetch(`/api/master/account-master?q=${encodeURIComponent(code)}`);
                const list = await r.json();
                const exact = list.find(a => a.account_code === code);
                nameDisp.textContent = exact ? exact.account_name : '';
            } catch { nameDisp.textContent = ''; }
        }

        // ドロップダウン表示
        async function showDropdown(q) {
            if (!q) { dropdown.style.display = 'none'; return; }
            try {
                const r = await fetch(`/api/master/account-master?q=${encodeURIComponent(q)}`);
                const list = await r.json();
                currentItems = list;
                highlightIdx = -1;
                if (list.length === 0) {
                    dropdown.innerHTML = `<div class="account-dropdown-empty">「${escapeHtml(q)}」に一致する科目なし</div>`;
                } else {
                    dropdown.innerHTML = list.map((a, i) => `
                        <div class="account-dropdown-item" data-idx="${i}">
                            <span class="ac-code">${escapeHtml(a.account_code)}</span>
                            <span class="ac-name">${escapeHtml(a.account_name)}</span>
                        </div>`).join('');
                    // クリックで選択
                    dropdown.querySelectorAll('.account-dropdown-item').forEach(el => {
                        el.addEventListener('mousedown', (e) => {
                            e.preventDefault();
                            const idx = parseInt(el.dataset.idx);
                            selectItem(currentItems[idx]);
                        });
                    });
                }
                dropdown.style.display = 'block';
            } catch(e) { dropdown.style.display = 'none'; }
        }

        function selectItem(item) {
            input.value = item.account_code;
            if (nameDisp) nameDisp.textContent = item.account_name;
            dropdown.style.display = 'none';
        }

        // 入力時リアルタイム検索（デバウンス150ms）
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => showDropdown(input.value.trim()), 150);
        });

        // 🔍ボタン押下
        if (btn) {
            btn.addEventListener('click', () => {
                const q = input.value.trim() || '';
                showDropdown(q || ' ');  // 空なら全件
                input.focus();
            });
        }

        // キーボード操作
        input.addEventListener('keydown', (e) => {
            if (dropdown.style.display === 'none') return;
            const items = dropdown.querySelectorAll('.account-dropdown-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                highlightIdx = Math.min(highlightIdx + 1, items.length - 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                highlightIdx = Math.max(highlightIdx - 1, 0);
            } else if (e.key === 'Enter' && highlightIdx >= 0) {
                e.preventDefault();
                selectItem(currentItems[highlightIdx]);
                return;
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
                return;
            }
            items.forEach((el, i) => el.classList.toggle('active', i === highlightIdx));
            if (highlightIdx >= 0) items[highlightIdx].scrollIntoView({ block: 'nearest' });
        });

        // フォーカスアウトで閉じる
        input.addEventListener('blur', () => {
            setTimeout(() => { dropdown.style.display = 'none'; }, 200);
            resolveAccountName(input.value.trim());
        });

        // 外部からコードをセットされたとき名前を解決
        const origDescriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
        input._resolveOnSet = resolveAccountName;
    }

    // COST科目・SGA科目に検索機能を設定
    setupAccountSearch('editCostAccount', 'btnSearchCostAccount', 'costAccountDropdown', 'costAccountName');
    setupAccountSearch('editSgaAccount',  'btnSearchSgaAccount',  'sgaAccountDropdown',  'sgaAccountName');

    // Save COST/SGA Accounts
    const btnSaveAccounts = document.getElementById('btnSaveAccounts');
    if (btnSaveAccounts) {
        btnSaveAccounts.addEventListener('click', async () => {
            const vCode = detailVendorCode ? detailVendorCode.textContent.trim() : "-";
            if (vCode === "-" || !vCode) {
                showError("取引先が選択されていません");
                return;
            }

            const editCostAccount = document.getElementById('editCostAccount');
            const editSgaAccount = document.getElementById('editSgaAccount');
            const costVal = editCostAccount ? editCostAccount.value.trim() : "";
            const sgaVal = editSgaAccount ? editSgaAccount.value.trim() : "";

            btnSaveAccounts.disabled = true;
            try {
                // COSTを保存
                if (costVal) {
                    const r1 = await fetch("/api/rules/account", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            vendor_code: vCode,
                            scope_type: "DEPT_TYPE",
                            scope_key: "COST",
                            expected_account: costVal,
                            update_reason: "COST科目設定",
                            updated_by: "user"
                        })
                    });
                    if (!r1.ok) { const e = await r1.json().catch(() => ({})); throw new Error("COST保存失敗: " + (e.detail || r1.status)); }
                }
                // SGAを保存
                if (sgaVal) {
                    const r2 = await fetch("/api/rules/account", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            vendor_code: vCode,
                            scope_type: "DEPT_TYPE",
                            scope_key: "SGA",
                            expected_account: sgaVal,
                            update_reason: "SGA科目設定",
                            updated_by: "user"
                        })
                    });
                    if (!r2.ok) { const e = await r2.json().catch(() => ({})); throw new Error("SGA保存失敗: " + (e.detail || r2.status)); }
                }

                showSuccess(`[${vCode}] 科目ルールを保存しました`);
                // 一覧を更新
                const searchInput = document.getElementById('ruleSearch');
                const query = searchInput ? searchInput.value : "";
                searchTaxRules(query);
                loadAccountRules(vCode);
            } catch (err) {
                showError("保存エラー: " + err.message);
            } finally {
                btnSaveAccounts.disabled = false;
            }
        });
    }

    // Add Master Account (Manual - Quick)
    const btnQuickAddAccount = document.getElementById('btnQuickAddAccount');
    if (btnQuickAddAccount) {
        btnQuickAddAccount.addEventListener('click', async () => {
            const codeInput = document.getElementById('quickAccountCode');
            const nameInput = document.getElementById('quickAccountName');
            const code = codeInput ? codeInput.value.trim() : "";
            const name = nameInput ? nameInput.value.trim() : "";

            if (!code || !name) {
                showError("科目コードと科目名を入力してください");
                return;
            }

            // 簡易バリデーション (数字のみ等)
            if (!/^\d+$/.test(code)) {
                if (!confirm("科目コードに数字以外が含まれていますが、登録しますか？")) return;
            }

            btnQuickAddAccount.disabled = true;
            try {
                const res = await fetch("/api/master/account", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        account_code: code,
                        account_name: name
                    })
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                const data = await res.json();
                showSuccess(data.message);

                // clear inputs
                codeInput.value = "";
                nameInput.value = "";

            } catch (err) {
                showError("登録エラー: " + err.message);
            } finally {
                btnQuickAddAccount.disabled = false;
            }
        });
    }

    // New Vendor Manual Registration
    const btnNewVendor = document.getElementById('btnNewVendor');
    const newVendorArea = document.getElementById('newVendorArea');
    const btnSaveNewVendor = document.getElementById('btnSaveNewVendor');
    const newVendorCode = document.getElementById('newVendorCode');
    const newVendorName = document.getElementById('newVendorName');

    if (btnNewVendor && newVendorArea) {
        btnNewVendor.addEventListener('click', () => {
            newVendorArea.style.display = 'block';
            newVendorCode.focus();
        });
    }

    if (btnSaveNewVendor) {
        btnSaveNewVendor.addEventListener('click', async () => {
            console.log("btnSaveNewVendor clicked!");
            const vCode = newVendorCode.value.trim();
            const vName = newVendorName.value.trim();
            if (!vCode || !vName) {
                showError("コードと名称は必須です");
                return;
            }

            btnSaveNewVendor.disabled = true;
            try {
                const res = await fetch("/api/master/vendor", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ vendor_code: vCode, vendor_name: vName })
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                showSuccess("取引先を登録しました");
                showToast("取引先を登録しました！");
                newVendorCode.value = "";
                newVendorName.value = "";
                newVendorArea.style.display = 'none';

                // Refresh list with new vendor
                if (ruleSearch) ruleSearch.value = vCode;
                searchTaxRules(vCode);

            } catch (e) {
                showError(e.message);
            } finally {
                btnSaveNewVendor.disabled = false;
            }
        });
    }

    // Account Rules
    async function loadAccountRules(vendorCode) {
        if (!accountRuleListBody) return;
        accountRuleListBody.innerHTML = '<tr><td colspan="4">読込中...</td></tr>';
        try {
            const res = await fetch(`/api/rules/account?q=${encodeURIComponent(vendorCode)}`);
            if (!res.ok) throw new Error("科目ルール取得失敗");
            const rules = await res.json();
            const filtered = rules.filter(r => r.vendor_code === vendorCode);
            renderAccountRuleList(filtered);
        } catch (e) {
            accountRuleListBody.innerHTML = `<tr><td colspan="4" style="color:var(--ng)">エラー: ${e.message}</td></tr>`;
        }
    }

    function renderAccountRuleList(rules) {
        accountRuleListBody.innerHTML = "";
        if (rules.length === 0) {
            accountRuleListBody.innerHTML = `<tr><td colspan="4" style="text-align:center">登録なし</td></tr>`;
            return;
        }

        const scopeOrder = { 'DEPT': 1, 'DEPT_TYPE': 2, 'ANY': 3 };
        rules.sort((a, b) => {
            if (scopeOrder[a.scope_type] !== scopeOrder[b.scope_type]) {
                return (scopeOrder[a.scope_type] || 9) - (scopeOrder[b.scope_type] || 9);
            }
            return (a.scope_key || '').localeCompare(b.scope_key || '');
        });

        rules.forEach(r => {
            let scopeDisplay = '';
            if (r.scope_type === 'DEPT') {
                scopeDisplay = `<span class="badge" style="background:#444; color:#fff;">部門</span> ${r.scope_key}`;
            } else if (r.scope_type === 'DEPT_TYPE') {
                scopeDisplay = `<span class="badge" style="background:#007bff; color:#fff;">タイプ</span> ${r.scope_key}`;
            } else if (r.scope_type === 'ANY') {
                scopeDisplay = `<span class="badge" style="background:#28a745; color:#fff;">共通(Any)</span>`;
            }

            const tr = document.createElement("tr");
            tr.innerHTML = `
            <td>${scopeDisplay}</td>
            <td>${r.expected_account}</td>
            <td style="font-size:0.8em; color:var(--muted);">${r.updated_at ? new Date(r.updated_at).toLocaleDateString() : ''}</td>
            <td>
            <td>
                <button type="button" class="secondary sm" style="padding:2px 5px;" onclick="copyToAccountInput('${r.scope_type}', '${r.scope_key || ''}', '${r.expected_account}')">編集</button>
                <button type="button" class="danger sm" style="padding:2px 5px; margin-left:5px;" onclick="deleteAccountRule('${r.vendor_code}', '${r.scope_type}', '${r.scope_key || ''}')">削除</button>
            </td>
        `;
            accountRuleListBody.appendChild(tr);
        });
    }

    // Delete Account Rule
    window.deleteAccountRule = async (vCode, sType, sKey) => {
        if (!confirm(`この科目ルールを削除しますか？\n範囲: ${sType} ${sKey || ''}`)) return;
        try {
            const params = new URLSearchParams({
                vendor_code: vCode,
                scope_type: sType,
                scope_key: sKey
            });
            const res = await fetch(`/api/rules/account?${params.toString()}`, { method: 'DELETE' });
            if (!res.ok) throw new Error((await res.json()).detail || "削除失敗");

            showSuccess("削除しました");
            loadAccountRules(vCode);
        } catch (e) {
            showError(e.message);
        }
    };

    // Account Rule Save
    if (btnAddAccountRule) {
        btnAddAccountRule.addEventListener("click", async () => {
            const vCode = detailVendorCode.textContent;
            if (vCode === "-" || !vCode) {
                showError("取引先が選択されていません");
                return;
            }
            // ... validation ...
            const sType = document.getElementById('newAccountScopeType').value;
            const sKey = document.getElementById('newAccountScopeKey').value.trim();
            const acode = newAccountCode.value.trim();
            const reason = newAccountReason.value.trim();

            if (!sType || !acode || !reason) {
                showError("適用範囲、科目CD、理由は必須です");
                return;
            }
            if (sType !== 'ANY' && !sKey) {
                showError("部門コードまたはタイプを指定してください");
                return;
            }

            const data = {
                vendor_code: vCode,
                scope_type: sType,
                scope_key: sKey,
                expected_account: acode,
                update_reason: reason,
                updated_by: "user"
            };

            btnAddAccountRule.disabled = true;
            try {
                const res = await fetch("/api/rules/account", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                showSuccess("科目ルールを保存しました");
                newAccountCode.value = "";
                newAccountReason.value = "";
                loadAccountRules(vCode);
            } catch (err) {
                showError(err.message);
            } finally {
                btnAddAccountRule.disabled = false;
            }
        });
    }

    // 科目ルール一括アップロード
    if (btnAccountRuleUpload) {
        btnAccountRuleUpload.addEventListener('click', () => {
            if (confirm('科目ルールを一括更新（追加・上書き）しますか？\n既存のルールは維持され、CSVにある取引先・条件のルールのみ更新されます。')) {
                accountRuleFile.click();
            }
        });
        accountRuleFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;
            handleFileUpload('/api/master/account/upload', e.target.files[0], btnAccountRuleUpload, '科目ルール', (data) => {
                const vCode = document.getElementById('detailVendorCode').textContent;
                if (vCode && vCode !== '-') {
                    loadAccountRules(vCode);
                }
                return `完了: ${data.count}件の科目ルールを更新しました`;
            });
        });
    }



    // --- Assignment Tab Handling ---
    const tabAssignment = document.getElementById('tab-assignment');
    const searchAssignDept = document.getElementById('searchAssignDept');
    const searchAssignVendor = document.getElementById('searchAssignVendor');
    const btnSyncAssignment = document.getElementById('btnSyncAssignment');
    const syncAssignmentFile = document.getElementById('syncAssignmentFile');
    const assignDeptBody = document.getElementById('assignDeptBody');
    const assignVendorBody = document.getElementById('assignVendorBody');

    // タブ切り替え時にデータロード
    document.querySelectorAll('.tab-btn[data-target="assignment"]').forEach(btn => {
        btn.addEventListener('click', () => {
            loadAssignmentDept();
            loadAssignmentVendor();
        });
    });

    // 部門担当ロード
    async function loadAssignmentDept() {
        if (!assignDeptBody) return;
        assignDeptBody.innerHTML = '<tr><td colspan="3" class="loading">Loading...</td></tr>';
        try {
            const res = await fetch('/api/assignment/dept');
            if (!res.ok) throw new Error("Failed to load");
            const list = await res.json();
            window._deptList = list; // Cache for search

            // 検索フィルターが入力済みの場合はフィルター後のリストで描画（フィルター保持）
            const currentQ = searchAssignDept ? searchAssignDept.value.trim().toLowerCase() : '';
            if (currentQ) {
                const filtered = list.filter(item =>
                    (item.dept_code && item.dept_code.toLowerCase().includes(currentQ)) ||
                    (item.dept_name && item.dept_name.toLowerCase().includes(currentQ)) ||
                    (item.assignee && item.assignee.toLowerCase().includes(currentQ))
                );
                renderAssignmentDept(filtered);
            } else {
                renderAssignmentDept(list);
            }
        } catch (e) {
            assignDeptBody.innerHTML = `<tr><td colspan="3" class="error">${e.message}</td></tr>`;
        }
    }

    function renderAssignmentDept(list) {
        if (list.length === 0) {
            assignDeptBody.innerHTML = '<tr><td colspan="3" class="muted">データがありません</td></tr>';
            return;
        }
        assignDeptBody.innerHTML = list.map(item => `
            <tr>
                <td>${escapeHtml(item.dept_code)}</td>
                <td>${escapeHtml(item.dept_name || '')}</td>
                <td class="editable" onclick="editAssignee('dept', '${item.dept_code}', '${escapeHtml(item.assignee || '')}')">
                    ${item.assignee ? escapeHtml(item.assignee) : '<span class="muted">(未設定)</span>'}
                </td>
            </tr>
        `).join('');
    }

    // 取引先担当ロード
    async function loadAssignmentVendor() {
        if (!assignVendorBody) return;
        assignVendorBody.innerHTML = '<tr><td colspan="3" class="loading">Loading...</td></tr>';
        try {
            const res = await fetch('/api/assignment/vendor');
            if (!res.ok) throw new Error("Failed to load");
            const list = await res.json();
            window._vendorList = list;

            // 検索フィルターが入力済みの場合はフィルター後のリストで描画（フィルター保持）
            const currentQ = searchAssignVendor ? searchAssignVendor.value.trim().toLowerCase() : '';
            if (currentQ) {
                const filtered = list.filter(item =>
                    (item.vendor_code && item.vendor_code.toLowerCase().includes(currentQ)) ||
                    (item.vendor_name && item.vendor_name.toLowerCase().includes(currentQ)) ||
                    (item.assignee && item.assignee.toLowerCase().includes(currentQ))
                );
                renderAssignmentVendor(filtered);
            } else {
                renderAssignmentVendor(list);
            }
        } catch (e) {
            assignVendorBody.innerHTML = `<tr><td colspan="3" class="error">${e.message}</td></tr>`;
        }
    }

    function renderAssignmentVendor(list) {
        if (list.length === 0) {
            assignVendorBody.innerHTML = '<tr><td colspan="3" class="muted">データがありません</td></tr>';
            return;
        }
        assignVendorBody.innerHTML = list.map(item => `
            <tr>
                <td>${escapeHtml(item.vendor_code)}</td>
                <td>${escapeHtml(item.vendor_name || '')}</td>
                <td class="editable" onclick="editAssignee('vendor', '${item.vendor_code}', '${escapeHtml(item.assignee || '')}')">
                    ${item.assignee ? escapeHtml(item.assignee) : '<span class="muted">(未設定)</span>'}
                </td>
            </tr>
        `).join('');
    }

    // 検索フィルタ
    if (searchAssignDept) {
        searchAssignDept.addEventListener('input', (e) => {
            const q = e.target.value.toLowerCase();
            const filtered = (window._deptList || []).filter(item =>
                (item.dept_code && item.dept_code.toLowerCase().includes(q)) ||
                (item.dept_name && item.dept_name.toLowerCase().includes(q)) ||
                (item.assignee && item.assignee.toLowerCase().includes(q))
            );
            renderAssignmentDept(filtered);
        });
    }
    if (searchAssignVendor) {
        searchAssignVendor.addEventListener('input', (e) => {
            const q = e.target.value.toLowerCase();
            const filtered = (window._vendorList || []).filter(item =>
                (item.vendor_code && item.vendor_code.toLowerCase().includes(q)) ||
                (item.vendor_name && item.vendor_name.toLowerCase().includes(q)) ||
                (item.assignee && item.assignee.toLowerCase().includes(q))
            );
            renderAssignmentVendor(filtered);
        });
    }

    // Inputデータ同期 (Sync)
    if (btnSyncAssignment) {
        btnSyncAssignment.addEventListener('click', () => {
            if (confirm('入力データCSVから部門・取引先リストを更新しますか？\n（担当者名は維持されます）')) {
                syncAssignmentFile.click();
            }
        });
        syncAssignmentFile.addEventListener('change', async (e) => {
            if (!e.target.files.length) return;

            const file = e.target.files[0];
            const formData = new FormData();
            formData.append("csv_file", file);

            btnSyncAssignment.disabled = true;
            btnSyncAssignment.innerHTML = '<span class="loading"></span> 更新中...';

            try {
                const res = await fetch('/api/assignment/sync', {
                    method: 'POST',
                    body: formData
                });

                // レスポンスがJSONでない場合（500エラーのHTMLなど）を考慮
                let data;
                const contentType = res.headers.get("content-type");
                if (contentType && contentType.includes("application/json")) {
                    data = await res.json();
                } else {
                    throw new Error(await res.text() || "サーバーエラーが発生しました");
                }

                if (!res.ok) {
                    // エラーオブジェクトから詳細を取り出す
                    throw new Error(data.detail || data.message || JSON.stringify(data));
                }

                showSuccess(typeof data.message === 'string' ? data.message : JSON.stringify(data));
                loadAssignmentDept();
                loadAssignmentVendor();
            } catch (err) {
                console.error(err);
                showError(`リスト更新エラー: ${err.message}`);
            } finally {
                btnSyncAssignment.disabled = false;
                btnSyncAssignment.textContent = '📥 入力データからリスト更新';
                syncAssignmentFile.value = '';
            }
        });
    }

    // --- 除外取引先管理 (モーダル版) ---
    const excludeVendorDialog       = document.getElementById('excludeVendorDialog');
    const btnExcludeVendorManage    = document.getElementById('btnExcludeVendorManage');
    const btnCloseExcludeVendorDialog = document.getElementById('btnCloseExcludeVendorDialog');
    const newExcludeCode            = document.getElementById('newExcludeCode');
    const newExcludeReason          = document.getElementById('newExcludeReason');
    const btnAddExclude             = document.getElementById('btnAddExclude');
    const excludeVendorList         = document.getElementById('excludeVendorList');

    // ダイアログを開く
    if (btnExcludeVendorManage) {
        btnExcludeVendorManage.addEventListener('click', () => {
            if (excludeVendorDialog) {
                excludeVendorDialog.style.display = 'block';
                loadExcludedVendors();
            }
        });
    }

    // ダイアログを閉じる
    if (btnCloseExcludeVendorDialog) {
        btnCloseExcludeVendorDialog.addEventListener('click', () => {
            if (excludeVendorDialog) excludeVendorDialog.style.display = 'none';
        });
    }

    // タブ切り替え時（担当割当）はロードのみ（表示はモーダル経由に変更）
    document.querySelectorAll('.tab-btn[data-target="assignment"]').forEach(btn => {
        btn.addEventListener('click', () => {
            loadAssignmentDept();
            loadAssignmentVendor();
        });
    });

    async function loadExcludedVendors() {
        if (!excludeVendorList) return;
        excludeVendorList.innerHTML = '<em style="color:#888;">読込中...</em>';
        try {
            const res = await fetch('/api/exclude');
            if (!res.ok) throw new Error("Load Failed");
            const list = await res.json();
            renderExcludedVendors(list);
        } catch (e) {
            excludeVendorList.innerHTML = `<div style="color:red;">${e.message}</div>`;
        }
    }

    function renderExcludedVendors(list) {
        if (list.length === 0) {
            excludeVendorList.innerHTML = '<div style="color:var(--muted);padding:8px;">登録なし</div>';
            return;
        }
        excludeVendorList.innerHTML = `
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
              <thead>
                <tr style="color:var(--muted);">
                  <th style="padding:4px 8px;text-align:left;width:30%">取引先コード</th>
                  <th style="padding:4px 8px;text-align:left;">理由</th>
                  <th style="padding:4px 8px;width:50px;"></th>
                </tr>
              </thead>
              <tbody>
                ${list.map(item => `
                  <tr style="border-top:1px solid rgba(255,255,255,0.07);">
                    <td style="padding:5px 8px;">${escapeHtml(item.vendor_code)}</td>
                    <td style="padding:5px 8px;">${escapeHtml(item.reason || '')}</td>
                    <td style="padding:5px 8px;">
                      <button class="danger xs" onclick="deleteExclude('${item.vendor_code}')">削除</button>
                    </td>
                  </tr>`).join('')}
              </tbody>
            </table>`;
    }

    if (btnAddExclude) {
        btnAddExclude.addEventListener('click', async () => {
            const code = newExcludeCode.value.trim();
            const reason = newExcludeReason.value.trim();
            if (!code) { showError("取引先コードを入力してください"); return; }

            btnAddExclude.disabled = true;
            try {
                const res = await fetch('/api/exclude', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vendor_code: code, reason: reason })
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                showSuccess("除外リストに追加しました");
                newExcludeCode.value = '';
                newExcludeReason.value = '';
                loadExcludedVendors();
            } catch (e) {
                showError(e.message);
            } finally {
                btnAddExclude.disabled = false;
            }
        });
    }

    // グローバル削除関数
    window.deleteExclude = async (code) => {
        if (!confirm(`取引先コード ${code} を除外リストから削除しますか？`)) return;
        try {
            const res = await fetch(`/api/exclude/${code}`, { method: 'DELETE' });
            if (!res.ok) throw new Error("Delete Failed");
            showSuccess("削除しました");
            loadExcludedVendors();
        } catch (e) {
            showError(e.message);
        }
    };

    // --- Account Master Handling (New) ---
    const newMasterAccountCode = document.getElementById('newMasterAccountCode');
    const newMasterAccountName = document.getElementById('newMasterAccountName');
    const btnAddMasterAccount = document.getElementById('btnAddMasterAccount');
    const searchMasterAccount = document.getElementById('searchMasterAccount');
    const masterAccountListBody = document.getElementById('masterAccountListBody');

    // Load on tab click (Master)
    document.querySelectorAll('.tab-btn[data-target="master"]').forEach(btn => {
        btn.addEventListener('click', () => {
            // Existing loads
            if (window.loadAccountRules) window.loadAccountRules(""); // clear or reload
            // New load
            loadMasterAccounts();
        });
    });

    // Search Event
    if (searchMasterAccount) {
        let debounceTimer;
        searchMasterAccount.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => loadMasterAccounts(searchMasterAccount.value), 300);
        });
    }

    async function loadMasterAccounts(query = "") {
        if (!masterAccountListBody) return;
        masterAccountListBody.innerHTML = '<tr><td colspan="3" class="loading">Loading...</td></tr>';

        try {
            const res = await fetch(`/api/master/account-master?q=${encodeURIComponent(query)}`);
            if (!res.ok) throw new Error("Load Failed");
            const list = await res.json();
            renderMasterAccounts(list);
        } catch (e) {
            masterAccountListBody.innerHTML = `<tr><td colspan="3" class="error">${e.message}</td></tr>`;
        }
    }

    function renderMasterAccounts(list) {
        if (list.length === 0) {
            masterAccountListBody.innerHTML = '<tr><td colspan="3" class="muted">登録なし</td></tr>';
            return;
        }
        masterAccountListBody.innerHTML = list.map(item => `
            <tr>
                <td>${escapeHtml(item.account_code)}</td>
                <td>${escapeHtml(item.account_name)}</td>
                <td>
                    <button class="secondary xs" onclick="editMasterAccount('${item.account_code}', '${escapeHtml(item.account_name)}')">編集</button>
                    <button class="danger xs" onclick="deleteMasterAccount('${item.account_code}')">削除</button>
                </td>
            </tr>
        `).join('');
    }

    if (btnAddMasterAccount) {
        btnAddMasterAccount.addEventListener('click', async () => {
            const code = newMasterAccountCode.value.trim();
            const name = newMasterAccountName.value.trim();
            if (!code || !name) {
                showError("コードと名称を入力してください");
                return;
            }
            try {
                const res = await fetch('/api/master/account-master', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_code: code, account_name: name })
                });
                if (!res.ok) throw new Error("登録失敗");

                showSuccess("科目マスタを保存しました");
                newMasterAccountCode.value = '';
                newMasterAccountName.value = '';
                loadMasterAccounts(searchMasterAccount ? searchMasterAccount.value : "");
            } catch (e) {
                showError(e.message);
            }
        });
    }

    window.editMasterAccount = (code, name) => {
        newMasterAccountCode.value = code;
        newMasterAccountName.value = name;
        newMasterAccountCode.focus();
    };

    window.deleteMasterAccount = async (code) => {
        if (!confirm(`科目コード ${code} を削除しますか？`)) return;
        try {
            const res = await fetch(`/api/master/account-master/${code}`, { method: 'DELETE' });
            if (!res.ok) throw new Error("Delete Failed");
            showSuccess("削除しました");
            loadMasterAccounts(searchMasterAccount ? searchMasterAccount.value : "");
        } catch (e) {
            showError(e.message);
        }
    };

    // 担当者編集 (Global function for inline onclick)
    window.editAssignee = async (type, code, current) => {
        const newVal = prompt("担当者を入力してください:", current);
        if (newVal === null) return; // Cancel

        try {
            const res = await fetch(`/api/assignment/${type}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code, assignee: newVal })
            });
            if (!res.ok) throw new Error((await res.json()).detail);

            // Reload
            if (type === 'dept') loadAssignmentDept();
            else loadAssignmentVendor();

            showSuccess("担当者を更新しました");
        } catch (e) {
            showError(e.message);
        }
    };


    // Override Save
    if (overrideForm) {
        overrideForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const data = {
                vendor_code: ovVendorCode.value,
                dept_code: ovDeptCode.value,
                field_name: ovField.value,
                new_value: ovValue.value,
                reason: ovReason.value,
                updated_by: "user"
            };

            btnSaveOverride.disabled = true;
            try {
                const res = await fetch("/api/rules/override", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(data)
                });
                if (!res.ok) throw new Error((await res.json()).detail);

                showSuccess("強制修正ルールを登録しました");
                ovReason.value = "";
            } catch (err) {
                showError(err.message);
            } finally {
                btnSaveOverride.disabled = false;
            }
        });
    }

    // --- Settings Tab Handling ---
    const settingDbPath = document.getElementById('settingDbPath');
    const settingCredsPath = document.getElementById('settingCredsPath');
    const settingCredsFile = document.getElementById('settingCredsFile');
    const btnUploadCreds = document.getElementById('btnUploadCreds');

    // Google Sheets Settings
    const settingSheetId = document.getElementById('settingSheetId');
    const btnSaveSheetId = document.getElementById('btnSaveSheetId');
    const settingSiteSheetId = document.getElementById('settingSiteSheetId');
    const btnSaveSiteSettings = document.getElementById('btnSaveSiteSettings');

    document.querySelectorAll('.tab-btn[data-target="settings"]').forEach(btn => {
        btn.addEventListener('click', loadSettings);
    });

    async function loadSettings() {
        try {
            const res = await fetch('/api/settings/');
            if (!res.ok) throw new Error("設定の読み込みに失敗しました");
            const data = await res.json();

            if (settingDbPath) settingDbPath.value = data.db_path || "";
            if (settingCredsPath) settingCredsPath.value = data.google_credentials_path || "未設定";

            if (settingSheetId) settingSheetId.value = data.google_sheet_id || "";
            if (settingSiteSheetId) settingSiteSheetId.value = data.site_sheet_id || "";

            // Gemini API設定表示
            const geminiStatus = document.getElementById('geminiApiStatus');
            if (geminiStatus) {
                if (data.gemini_api_key_set) {
                    geminiStatus.innerHTML = '✓ APIキー設定済み (' + (data.gemini_api_key_masked || '***') + ')';
                    geminiStatus.style.color = 'var(--success)';
                } else {
                    geminiStatus.textContent = '✗ APIキー未設定';
                    geminiStatus.style.color = 'var(--danger)';
                }
            }
        } catch (e) {
            showError(e.message);
        }
    }

    // Helper to save settings
    async function saveSettingInternal(key, val) {
        const res = await fetch('/api/settings/value', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: key, value: val })
        });
        if (!res.ok) throw new Error("保存失敗");
    }

    if (btnSaveSheetId) {
        btnSaveSheetId.addEventListener('click', async () => {
            btnSaveSheetId.disabled = true;
            try {
                await saveSettingInternal("google_sheet_id", settingSheetId.value.trim());
                showSuccess("経理用シートIDを保存しました");
            } catch (e) {
                showError(e.message);
            } finally {
                btnSaveSheetId.disabled = false;
            }
        });
    }

    if (btnSaveSiteSettings) {
        btnSaveSiteSettings.addEventListener('click', async () => {
            btnSaveSiteSettings.disabled = true;
            try {
                await saveSettingInternal("site_sheet_id", settingSiteSheetId.value.trim());
                showSuccess("現場用設定を保存しました");
            } catch (e) {
                showError(e.message);
            } finally {
                btnSaveSiteSettings.disabled = false;
            }
        });
    }

    // Gemini APIキー保存
    const btnSaveGeminiApiKey = document.getElementById('btnSaveGeminiApiKey');
    const settingGeminiApiKey = document.getElementById('settingGeminiApiKey');

    if (btnSaveGeminiApiKey) {
        btnSaveGeminiApiKey.addEventListener('click', async () => {
            const apiKey = settingGeminiApiKey?.value?.trim();
            if (!apiKey) {
                showError("APIキーを入力してください");
                return;
            }

            btnSaveGeminiApiKey.disabled = true;
            try {
                await saveSettingInternal("gemini_api_key", apiKey);
                showSuccess("Gemini APIキーを保存しました");
                settingGeminiApiKey.value = '';
                loadSettings();
            } catch (e) {
                showError(e.message);
            } finally {
                btnSaveGeminiApiKey.disabled = false;
            }
        });
    }

    if (btnUploadCreds) {
        btnUploadCreds.addEventListener('click', async () => {
            const file = settingCredsFile.files[0];
            if (!file) {
                showError("ファイルを選択してください");
                return;
            }

            btnUploadCreds.disabled = true;
            btnUploadCreds.textContent = "アップロード中...";

            const formData = new FormData();
            formData.append("file", file);

            try {
                const res = await fetch('/api/settings/credentials', {
                    method: 'POST',
                    body: formData
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || "アップロード失敗");
                }

                const data = await res.json();
                showSuccess(data.message);
                if (settingCredsPath) settingCredsPath.value = data.path;
                settingCredsFile.value = ""; // Clear

            } catch (e) {
                showError(e.message);
            } finally {
                btnUploadCreds.disabled = false;
                btnUploadCreds.textContent = "💾 保存";
            }
        });
    }

}); // End of DOMContentLoaded

// Global Functions (Window attached)
window.copyToAccountInput = (sType, sKey, code) => {
    const sTypeInput = document.getElementById('newAccountScopeType');
    const keyInput = document.getElementById('newAccountScopeKey');
    const codeInput = document.getElementById('newAccountCode');
    const reasonInput = document.getElementById('newAccountReason');

    if (sTypeInput) sTypeInput.value = sType;

    if (keyInput) {
        if (sType === 'ANY') {
            keyInput.value = '';
            keyInput.disabled = true;
            keyInput.placeholder = '指定不要';
        } else {
            keyInput.value = sKey;
            keyInput.disabled = false;
            keyInput.placeholder = sType === 'DEPT_TYPE' ? 'SGA or COST' : '部門コード';
        }
    }

    if (codeInput) codeInput.value = code;
    if (reasonInput) reasonInput.focus();
};

window.toggleScopeKeyInput = (val) => {
    const keyInput = document.getElementById('newAccountScopeKey');
    if (!keyInput) return;
    if (val === 'ANY') {
        keyInput.value = '';
        keyInput.disabled = true;
        keyInput.placeholder = '指定不要';
    } else {
        keyInput.disabled = false;
        keyInput.placeholder = val === 'DEPT_TYPE' ? 'SGA or COST' : '部門コード';
    }
};

// --- Tax Rule Exceptions ---

window.toggleTaxScopeKeyInput = (val) => {
    const keyInput = document.getElementById('newTaxScopeKey');
    if (!keyInput) return;
    if (val === 'ANY') {
        keyInput.disabled = true;
        keyInput.placeholder = '指定不要';
    } else {
        keyInput.disabled = false;
        keyInput.placeholder = val === 'DEPT_TYPE' ? 'SGA or COST' : '部門コード';
    }
};

window.loadTaxRules = async (vendorCode) => {
    const tbody = document.getElementById('taxRuleListBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" class="loading">Loading...</td></tr>';

    try {
        const res = await fetch(`/api/rules/tax_rules/${vendorCode}`);
        if (!res.ok) throw new Error("Load Failed");
        const list = await res.json();

        if (list.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="muted">ルールなし</td></tr>';
            return;
        }

        tbody.innerHTML = list.map(item => `
            <tr>
                <td>
                    <span class="badge ${item.scope_type === 'DEPT_TYPE' ? 'orange' : ''}">${item.scope_type}</span>
                    ${item.scope_key || '*'}
                </td>
                <td>${escapeHtml(item.expected_tax)}</td>
                <td>${escapeHtml(item.reason || '')}</td>
                <td>
                    <button class="danger xs" onclick="deleteTaxRule(${item.id}, '${vendorCode}')">削除</button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="error">${e.message}</td></tr>`;
    }
};

const btnAddTaxRule = document.getElementById('btnAddTaxRule');
if (btnAddTaxRule) {
    btnAddTaxRule.addEventListener('click', async () => {
        const vendorCode = document.getElementById('editVendorCode').textContent.trim();
        const scopeType = document.getElementById('newTaxScopeType').value;
        const scopeKey = document.getElementById('newTaxScopeKey').value.trim();
        const expectedTax = document.getElementById('newTaxExpected').value.trim();
        const reason = document.getElementById('newTaxReason').value.trim();

        if (!vendorCode || vendorCode === '-') {
            showError("取引先が選択されていません");
            return;
        }
        if (!expectedTax) {
            showError("税区分は必須です");
            return;
        }

        btnAddTaxRule.disabled = true;
        try {
            const res = await fetch("/api/rules/tax_rules", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    vendor_code: vendorCode,
                    scope_type: scopeType,
                    scope_key: scopeKey,
                    expected_tax: expectedTax,
                    reason: reason,
                    updated_by: "user"
                })
            });
            if (!res.ok) throw new Error((await res.json()).detail);

            showSuccess("税区分ルールを追加しました");

            // clear inputs
            document.getElementById('newTaxScopeKey').value = "";
            document.getElementById('newTaxExpected').value = "";
            document.getElementById('newTaxReason').value = "";

            loadTaxRules(vendorCode);
        } catch (e) {
            showError("追加エラー: " + e.message);
        } finally {
            btnAddTaxRule.disabled = false;
        }
    });
}

// --- OCR Logic ---
const btnRunOCR = document.getElementById('btnRunOCR');
const btnRunOCRFast = document.getElementById('btnRunOCRFast');
const btnRefreshOCR = document.getElementById('btnRefreshOCR');
const btnExportExcel = document.getElementById('btnExportExcel');
const ocrListBody = document.getElementById('ocrListBody');
const ocrStatusMsg = document.getElementById('ocrStatusMsg');

// Preview Modal
const ocrPreviewModal = document.getElementById('ocrPreviewModal');
const btnCloseOCRModal = document.getElementById('btnCloseOCRModal');
const ocrPdfFrame = document.getElementById('ocrPdfFrame');

// Detail Elements
const detailApprovalNo = document.getElementById('detailApprovalNo');
const detailVendorName = document.getElementById('detailVendorName');
const detailStatus = document.getElementById('detailStatus');
const detailFileName = document.getElementById('detailFileName');
const detailHasRingi = document.getElementById('detailHasRingi');

// Run OCR
// Run OCR
let ocrPollTimer = null;

function startOCRPolling() {
    if (ocrPollTimer) clearInterval(ocrPollTimer);

    let pollCount = 0;
    const pollTask = async () => {
        pollCount++;
        try {
            const progressRes = await fetch('/api/ocr/progress');
            if (progressRes.ok) {
                const prog = await progressRes.json();

                // ステータスに応じて表示を更新
                const timeInfo = prog.processed_time ? ` (${prog.processed_time})` : '';

                if (prog.status === 'completed') {
                    clearInterval(ocrPollTimer);
                    ocrStatusMsg.innerHTML = `<span style="color:var(--success); font-weight:bold;">✓ ${prog.message}</span>`; // messageには既に時間が含まれている
                    btnRunOCR.disabled = false;
                    if (btnRunOCRFast) btnRunOCRFast.disabled = false;
                    // 結果を自動更新
                    loadOCRResults();
                } else if (prog.status === 'error') {
                    clearInterval(ocrPollTimer);
                    ocrStatusMsg.innerHTML = `<span style="color:var(--error); font-weight:bold;">✗ ${prog.message}</span>`;
                    btnRunOCR.disabled = false;
                    if (btnRunOCRFast) btnRunOCRFast.disabled = false;
                } else if (prog.status === 'running') {
                    // Runningの場合は独自メッセージを組み立てていたので、時間を追加
                    ocrStatusMsg.innerHTML = `<span style="color:var(--accent); font-weight:bold;">Running... ${prog.processed}/${prog.total} files${timeInfo}</span>`;
                } else {
                    ocrStatusMsg.textContent = prog.message || 'Waiting...';
                }
            }
        } catch (e) { }

        // 30分経過したら自動停止 (600回 * 3秒)
        if (pollCount > 600) {
            clearInterval(ocrPollTimer);
            ocrStatusMsg.textContent = 'Running... (Auto-refresh stopped)';
            btnRunOCR.disabled = false;
            if (btnRunOCRFast) btnRunOCRFast.disabled = false;
        }
    };
    pollTask();
    ocrPollTimer = setInterval(pollTask, 3000);
}

async function runOCR(fast) {
    const confirmMsg = fast
        ? '高速解析を実行しますか？（傾き補正なし）'
        : '請求書ファイルの一覧を取得しますか？';
    if (!confirm(confirmMsg)) return;

    btnRunOCR.disabled = true;
    if (btnRunOCRFast) btnRunOCRFast.disabled = true;
    ocrStatusMsg.textContent = fast ? 'Starting fast analysis...' : 'Starting analysis...';

    // 即座にポーリング開始
    startOCRPolling();

    try {
        const url = fast ? '/api/ocr/analyze?fast=true' : '/api/ocr/analyze';
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) throw new Error((await res.json()).detail);

        showSuccess(fast ? '高速OCR解析を開始しました' : 'ファイルスキャンを開始しました');
        // ポーリングは継続

    } catch (e) {
        showError('実行エラー: ' + e.message);
        ocrStatusMsg.textContent = 'エラーが発生しました: ' + e.message;
        if (ocrPollTimer) clearInterval(ocrPollTimer);
        btnRunOCR.disabled = false;
        if (btnRunOCRFast) btnRunOCRFast.disabled = false;
    }
}

if (btnRunOCR) {
    btnRunOCR.addEventListener('click', () => runOCR(false));
}

if (btnRunOCRFast) {
    btnRunOCRFast.addEventListener('click', () => runOCR(true));
}

if (btnExportExcel) {
    btnExportExcel.addEventListener('click', () => {
        window.open('/api/ocr/export', '_blank');
    });
}

// Helper for OCR Scope
const ocrEscapeHtml = (str) => {
    if (!str) return '';
    return str.replace(/[&<>"']/g, function (m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[m];
    });
};

// Refresh Results
async function loadOCRResults() {
    if (!ocrListBody) return;

    ocrListBody.innerHTML = '<tr><td colspan="4" class="loading">Loading...</td></tr>';

    try {
        const res = await fetch('/api/ocr/results');
        if (!res.ok) throw new Error("Failed to load results");
        const data = await res.json();

        ocrListBody.innerHTML = '';

        if (data.length === 0) {
            ocrListBody.innerHTML = '<tr><td colspan="4" style="text-align:center">データがありません</td></tr>';
            return;
        }

        data.forEach(item => {
            const tr = document.createElement('tr');
            const ringiLabel = item.has_ringi ? ' <span class="badge warn" style="font-size:0.7em">稟議</span>' : '';
            tr.innerHTML = `
                <td style="font-size:0.85em">${ocrEscapeHtml(item.approval_no || '-')}</td>
                <td>${ocrEscapeHtml(item.vendor_name || '-')}</td>
                <td><span class="badge dash" style="font-size:0.8em">${ocrEscapeHtml(item.status || '-')}</span></td>
                <td style="font-size:0.8em">
                    <a href="#" class="file-link" style="color:var(--accent); text-decoration:underline; cursor:pointer; word-break:break-all;">
                        ${ocrEscapeHtml(item.file_name || '-')}
                    </a>${ringiLabel}
                </td>
            `;
            tr.querySelector('.file-link').addEventListener('click', (e) => {
                e.preventDefault();
                showOCRDetail(item);
            });
            ocrListBody.appendChild(tr);
        });

        if (ocrStatusMsg) ocrStatusMsg.textContent = `${data.length}件`;

    } catch (e) {
        console.error(e);
        ocrListBody.innerHTML = `<tr><td colspan="4" class="error">読み込みエラー: ${e.message}</td></tr>`;
    }
}

if (btnRefreshOCR) {
    btnRefreshOCR.addEventListener('click', loadOCRResults);
}

// Modal Logic
function showOCRDetail(item) {
    if (!ocrPreviewModal) return;

    if (detailApprovalNo) detailApprovalNo.textContent = item.approval_no || '-';
    if (detailVendorName) detailVendorName.textContent = item.vendor_name || '-';
    if (detailStatus) detailStatus.textContent = item.status || '-';
    if (detailFileName) detailFileName.textContent = item.file_name || '-';
    if (detailHasRingi) detailHasRingi.textContent = item.has_ringi ? 'あり' : 'なし';

    ocrPreviewModal.style.display = 'block';

    if (ocrPdfFrame) ocrPdfFrame.src = `/api/ocr/files/${encodeURIComponent(item.file_name)}`;
}

if (btnCloseOCRModal) {
    btnCloseOCRModal.addEventListener('click', () => {
        ocrPreviewModal.style.display = 'none';
        if (ocrPdfFrame) ocrPdfFrame.src = '';
    });
}

// Tab Change Hook
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        if (btn.dataset.target === 'ocr') {
            // First load or auto refresh
            if (ocrListBody && ocrListBody.innerHTML.includes('未実行')) {
                loadOCRResults();
            }
        }
    });
});

window.deleteTaxRule = async (id, vendorCode) => {
    if (!confirm('このルールを削除しますか？')) return;
    try {
        const res = await fetch(`/api/rules/tax_rules/${id}`, { method: "DELETE" });
        if (!res.ok) throw new Error("Delete Failed");
        showSuccess("削除しました");
        loadTaxRules(vendorCode);
    } catch (e) {
        showError(e.message);
    }
};

// 取引先手動登録 (グローバル関数)
window.saveNewVendor = async () => {
    const vCode = document.getElementById('newVendorCode').value.trim();
    const vName = document.getElementById('newVendorName').value.trim();
    const btn = document.getElementById('btnSaveNewVendor');
    const area = document.getElementById('newVendorArea');
    const ruleSearch = document.getElementById('ruleSearch');

    if (!vCode || !vName) {
        alert("コードと名称は必須です");
        return;
    }

    if (btn) btn.disabled = true;
    try {
        const res = await fetch("/api/master/vendor", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vendor_code: vCode, vendor_name: vName })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "登録失敗");
        }

        alert("取引先を登録しました: " + vName);
        document.getElementById('newVendorCode').value = "";
        document.getElementById('newVendorName').value = "";
        if (area) area.style.display = 'none';

        // Refresh search with new vendor
        if (ruleSearch) {
            ruleSearch.value = vCode;
            // Trigger search button click
            const btnSearch = document.getElementById('btnRuleSearch');
            if (btnSearch) btnSearch.click();
        }

    } catch (e) {
        alert("エラー: " + e.message);
    } finally {
        if (btn) btn.disabled = false;
    }
};

// --- AI設定管理 (追加) ---
document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const aiSettingDialog = document.getElementById('aiSettingDialog');
    const btnAiSetting = document.getElementById('btnAiSetting');
    const btnCloseAiSettingDialog = document.getElementById('btnCloseAiSettingDialog');
    const btnAddAiSetting = document.getElementById('btnAddAiSetting');
    const aiSettingList = document.getElementById('aiSettingList');
    const newAiVendorCode = document.getElementById('newAiVendorCode');
    const newAiFlag = document.getElementById('newAiFlag');

    // Toast Helper (local fallback)
    const showToastLocal = (msg, type = 'info') => {
        const t = document.getElementById('toast');
        if (t) {
            t.textContent = msg;
            t.className = type === 'error' ? 'toast error show' : 'toast show';
            setTimeout(() => t.className = t.className.replace('show', ''), 3000);
        } else {
            alert(msg);
        }
    };

    if (btnAiSetting) {
        btnAiSetting.addEventListener('click', () => {
            if (aiSettingDialog) {
                aiSettingDialog.style.display = 'block';
                loadAiSettings();
            }
        });
    }

    if (btnCloseAiSettingDialog) {
        btnCloseAiSettingDialog.addEventListener('click', () => {
            if (aiSettingDialog) aiSettingDialog.style.display = 'none';
        });
    }

    if (btnAddAiSetting) {
        btnAddAiSetting.addEventListener('click', async () => {
            const vCode = newAiVendorCode.value ? newAiVendorCode.value.trim() : "";
            const flag = newAiFlag.value;

            if (!vCode) {
                showToastLocal("取引先コードを入力してください", "error");
                return;
            }

            try {
                const res = await fetch('/api/master/ai-setting', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vendor_code: vCode, gemini_flag: flag })
                });
                if (!res.ok) throw new Error(await res.text());
                const json = await res.json();
                showToastLocal(json.message);

                newAiVendorCode.value = "";
                newAiFlag.value = "1"; // default reset
                loadAiSettings();

            } catch (e) {
                showToastLocal(e.message, "error");
            }
        });
    }

    async function loadAiSettings() {
        if (!aiSettingList) return;
        aiSettingList.innerHTML = '<em style="color:#888;">読込中...</em>';
        try {
            const res = await fetch('/api/master/ai-setting');
            if (!res.ok) throw new Error("Failed to load");
            const list = await res.json();

            if (list.length === 0) {
                aiSettingList.innerHTML = '<div style="padding:10px;color:#888;">設定されている取引先はありません</div>';
                return;
            }

            const esc = (s) => (s || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));

            let html = '<table class="list-table" style="font-size:0.9em;">';
            html += '<thead><tr><th>コード</th><th>設定</th><th>更新日時</th><th>操作</th></tr></thead><tbody>';

            list.forEach(item => {
                const flagLabel = item.gemini_flag === '1' ? 'Model A' : item.gemini_flag === '2' ? 'Model B' : item.gemini_flag;
                html += `<tr>
                    <td>${esc(item.vendor_code)}</td>
                    <td>${esc(flagLabel)}</td>
                    <td style="font-size:0.8em;color:#999;">${esc(item.updated_at || '-')}</td>
                    <td><button class="secondary sm" onclick="window.removeAiSetting('${esc(item.vendor_code)}')">解除</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            aiSettingList.innerHTML = html;

        } catch (e) {
            aiSettingList.innerHTML = `<div style="color:red;">Error: ${e.message}</div>`;
        }
    }

    window._reloadAiSettings = loadAiSettings;
});

// Global function
window.removeAiSetting = async (vCode) => {
    if (!confirm(`取引先コード ${vCode} のAI設定を解除しますか？`)) return;
    try {
        const res = await fetch('/api/master/ai-setting', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor_code: vCode, gemini_flag: "" })
        });
        if (!res.ok) throw new Error(await res.text());

        const t = document.getElementById('toast');
        if (t) {
            t.textContent = "解除しました";
            t.className = 'toast show';
            setTimeout(() => t.className = t.className.replace('show', ''), 3000);
        }

        if (window._reloadAiSettings) window._reloadAiSettings();

    } catch (e) {
        alert(e.message);
    }
};
// --- AI設定管理 (追加) ---
document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const aiSettingDialog = document.getElementById('aiSettingDialog');
    const btnAiSetting = document.getElementById('btnAiSetting');
    const btnCloseAiSettingDialog = document.getElementById('btnCloseAiSettingDialog');
    const btnAddAiSetting = document.getElementById('btnAddAiSetting');
    const aiSettingList = document.getElementById('aiSettingList');
    const newAiVendorCode = document.getElementById('newAiVendorCode');
    const newAiFlag = document.getElementById('newAiFlag');

    // Toast Helper (local fallback)
    const showToastLocal = (msg, type = 'info') => {
        const t = document.getElementById('toast');
        if (t) {
            t.textContent = msg;
            t.className = type === 'error' ? 'toast error show' : 'toast show';
            setTimeout(() => t.className = t.className.replace('show', ''), 3000);
        } else {
            alert(msg);
        }
    };

    if (btnAiSetting) {
        btnAiSetting.addEventListener('click', () => {
            if (aiSettingDialog) {
                aiSettingDialog.style.display = 'block';
                loadAiSettings();
            }
        });
    }

    if (btnCloseAiSettingDialog) {
        btnCloseAiSettingDialog.addEventListener('click', () => {
            if (aiSettingDialog) aiSettingDialog.style.display = 'none';
        });
    }

    if (btnAddAiSetting) {
        btnAddAiSetting.addEventListener('click', async () => {
            const vCode = newAiVendorCode.value ? newAiVendorCode.value.trim() : "";
            const flag = newAiFlag.value;

            if (!vCode) {
                showToastLocal("取引先コードを入力してください", "error");
                return;
            }

            try {
                const res = await fetch('/api/master/ai-setting', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vendor_code: vCode, gemini_flag: flag })
                });
                if (!res.ok) throw new Error(await res.text());
                const json = await res.json();
                showToastLocal(json.message);

                newAiVendorCode.value = "";
                newAiFlag.value = "1"; // default reset
                loadAiSettings();

            } catch (e) {
                showToastLocal(e.message, "error");
            }
        });
    }

    async function loadAiSettings() {
        if (!aiSettingList) return;
        aiSettingList.innerHTML = '<em style="color:#888;">読込中...</em>';
        try {
            const res = await fetch('/api/master/ai-setting');
            if (!res.ok) throw new Error("Failed to load");
            const list = await res.json();

            if (list.length === 0) {
                aiSettingList.innerHTML = '<div style="padding:10px;color:#888;">設定されている取引先はありません</div>';
                return;
            }

            const esc = (s) => (s || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));

            let html = '<table class="list-table" style="font-size:0.9em;">';
            html += '<thead><tr><th>コード</th><th>設定</th><th>更新日時</th><th>操作</th></tr></thead><tbody>';

            list.forEach(item => {
                const flagLabel = item.gemini_flag === '1' ? 'Model A' : item.gemini_flag === '2' ? 'Model B' : item.gemini_flag;
                html += `<tr>
                    <td>${esc(item.vendor_code)}</td>
                    <td>${esc(flagLabel)}</td>
                    <td style="font-size:0.8em;color:#999;">${esc(item.updated_at || '-')}</td>
                    <td><button class="secondary sm" onclick="window.removeAiSetting('${esc(item.vendor_code)}')">解除</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            aiSettingList.innerHTML = html;

        } catch (e) {
            aiSettingList.innerHTML = `<div style="color:red;">Error: ${e.message}</div>`;
        }
    }

    window._reloadAiSettings = loadAiSettings;
});

// Global function
window.removeAiSetting = async (vCode) => {
    if (!confirm(`取引先コード ${vCode} のAI設定を解除しますか？`)) return;
    try {
        const res = await fetch('/api/master/ai-setting', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor_code: vCode, gemini_flag: "" })
        });
        if (!res.ok) throw new Error(await res.text());

        const t = document.getElementById('toast');
        if (t) {
            t.textContent = "解除しました";
            t.className = 'toast show';
            setTimeout(() => t.className = t.className.replace('show', ''), 3000);
        }

        if (window._reloadAiSettings) window._reloadAiSettings();

    } catch (e) {
        alert(e.message);
    }
};

// --- 設定画面 (追加) ---
document.addEventListener('DOMContentLoaded', () => {
    const settingModelA = document.getElementById('settingModelA');
    const settingModelB = document.getElementById('settingModelB');
    const btnSaveAiModels = document.getElementById('btnSaveAiModels');

    // タブ切り替え検知
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.target === 'settings') {
                loadAiModelSettings();
            }
        });
    });

    async function loadAiModelSettings() {
        if (!settingModelA || !settingModelB) return;
        try {
            const res = await fetch('/api/settings/ai-models');
            if (!res.ok) throw new Error("Failed to load settings");
            const data = await res.json();
            settingModelA.value = data.model_a || "";
            settingModelB.value = data.model_b || "";
        } catch (e) {
            console.error(e);
            alert("設定読み込みエラー: " + e.message);
        }
    }

    if (btnSaveAiModels) {
        btnSaveAiModels.addEventListener('click', async () => {
            const valA = settingModelA.value.trim();
            const valB = settingModelB.value.trim();
            if (!valA || !valB) {
                alert("モデル名を入力してください");
                return;
            }

            if (!confirm("設定を保存しますか？\\n反映にはアプリの再起動が必要です。")) return;

            try {
                const res = await fetch('/api/settings/ai-models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model_a: valA, model_b: valB })
                });
                if (!res.ok) throw new Error(await res.text());
                const json = await res.json();
                alert(json.message);
            } catch (e) {
                alert("保存エラー: " + e.message);
            }
        });
    }

    const btnClearDriveCache = document.getElementById('btnClearDriveCache');
    const driveCacheStatus = document.getElementById('driveCacheStatus');
    if (btnClearDriveCache) {
        btnClearDriveCache.addEventListener('click', async () => {
            if (!confirm("Driveアップロード履歴（キャッシュ）をクリアしますか？\n※Drive側のファイルは削除されません。手動で削除してから実行してください。")) return;

            btnClearDriveCache.disabled = true;
            if (driveCacheStatus) driveCacheStatus.textContent = "クリア中...";
            try {
                const res = await fetch('/api/settings/clear-drive-cache', { method: 'POST' });
                if (!res.ok) throw new Error(await res.text());
                const json = await res.json();
                if (driveCacheStatus) {
                    driveCacheStatus.textContent = `✓ ${json.message}`;
                    driveCacheStatus.style.color = 'var(--success)';
                }
                alert(json.message);
            } catch (e) {
                if (driveCacheStatus) {
                    driveCacheStatus.textContent = `✗ エラー: ${e.message}`;
                    driveCacheStatus.style.color = 'var(--error)';
                }
                alert("クリアエラー: " + e.message);
            } finally {
                btnClearDriveCache.disabled = false;
            }
        });
    }
});


// ============================================================
// 取引先注意事項 (Vendor Notes)
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const _esc = (str) => {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    };

    const noteSelect         = document.getElementById('noteSelect');
    const btnAddVendorNote   = document.getElementById('btnAddVendorNote');
    const btnCreateNoteLabel = document.getElementById('btnCreateNoteLabel');
    const newNoteLabel       = document.getElementById('newNoteLabel');
    const vendorNoteChips    = document.getElementById('vendorNoteChips');
    const noteLabelList      = document.getElementById('noteLabelList');

    if (!noteSelect) return;  // 正マスタータブが存在しない場合はスキップ

    // ---- ラベル一覧を select と ラベルマスタ欄に反映 ----
    async function loadNoteLabels() {
        try {
            const res = await fetch('/api/master/note-labels');
            if (!res.ok) return;
            const labels = await res.json();

            // セレクト更新
            noteSelect.innerHTML = '<option value="">-- ラベルを選択 --</option>';
            labels.forEach(l => {
                const opt = document.createElement('option');
                opt.value = l.id;
                opt.textContent = l.label;
                noteSelect.appendChild(opt);
            });

            // ラベルマスタ欄更新（常時表示・×で削除可）
            if (noteLabelList) {
                noteLabelList.innerHTML = '';
                if (labels.length === 0) {
                    noteLabelList.innerHTML = '<span style="color:var(--muted);font-size:0.85em;">ラベルなし</span>';
                } else {
                    labels.forEach(l => {
                        const chip = document.createElement('span');
                        chip.className = 'note-chip';
                        chip.innerHTML = `${_esc(l.label)} <button class="chip-del" onclick="deleteNoteLabel(${l.id})" title="削除">×</button>`;
                        noteLabelList.appendChild(chip);
                    });
                }
            }
        } catch (e) {
            console.error('loadNoteLabels error:', e);
        }
    }

    // ---- 取引先のノートを表示 ----
    window.loadVendorNotes = async function(vendorCode) {
        if (!vendorNoteChips || !vendorCode || vendorCode === '-') {
            if (vendorNoteChips) vendorNoteChips.innerHTML = '<span style="color:var(--muted);font-size:0.85em;">取引先を選択してください</span>';
            return;
        }
        try {
            const res = await fetch(`/api/master/vendor-notes/${encodeURIComponent(vendorCode)}`);
            if (!res.ok) return;
            const notes = await res.json();
            vendorNoteChips.innerHTML = '';
            if (notes.length === 0) {
                vendorNoteChips.innerHTML = '<span style="color:var(--muted);font-size:0.85em;">注意事項なし</span>';
            } else {
                notes.forEach(n => {
                    const chip = document.createElement('span');
                    chip.className = 'note-chip active';
                    chip.innerHTML = `${_esc(n.label)} <button class="chip-del" onclick="removeVendorNote(${n.id},'${_esc(vendorCode)}')" title="削除">×</button>`;
                    vendorNoteChips.appendChild(chip);
                });
            }
        } catch (e) {
            console.error('loadVendorNotes error:', e);
        }
    };

    // ---- 取引先にラベルを追加 ----
    if (btnAddVendorNote) {
        btnAddVendorNote.addEventListener('click', async () => {
            const vCode = document.getElementById('detailVendorCode')?.textContent?.trim();
            if (!vCode || vCode === '-') { alert('取引先を選択してください'); return; }
            const labelId = parseInt(noteSelect.value);
            if (!labelId) { alert('ラベルを選択してください'); return; }
            try {
                const res = await fetch('/api/master/vendor-notes', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vendor_code: vCode, label_id: labelId })
                });
                if (!res.ok) {
                    const err = await res.json();
                    alert(err.detail || 'エラーが発生しました');
                    return;
                }
                noteSelect.value = '';
                window.loadVendorNotes(vCode);
            } catch (e) { alert('追加エラー: ' + e.message); }
        });
    }

    // ---- 新規ラベル作成 ----
    if (btnCreateNoteLabel) {
        btnCreateNoteLabel.addEventListener('click', async () => {
            const label = newNoteLabel?.value?.trim();
            if (!label) { alert('ラベル名を入力してください'); return; }
            try {
                const res = await fetch('/api/master/note-labels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ label })
                });
                if (!res.ok) {
                    const err = await res.json();
                    alert(err.detail || 'エラーが発生しました');
                    return;
                }
                newNoteLabel.value = '';
                await loadNoteLabels();
                // 作成したラベルをすぐ選択状態にする
                for (const opt of noteSelect.options) {
                    if (opt.textContent === label) { noteSelect.value = opt.value; break; }
                }
            } catch (e) { alert('作成エラー: ' + e.message); }
        });
    }

    // 初期ロード
    loadNoteLabels();
});

// ---- ラベル削除 (グローバル) ----
window.deleteNoteLabel = async function(labelId) {
    if (!confirm('このラベルを削除しますか？\n取引先への紐付きもすべて削除されます。')) return;
    try {
        const res = await fetch(`/api/master/note-labels/${labelId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(await res.text());

        // セレクト＆ラベルマスタ欄を再読込
        const res2 = await fetch('/api/master/note-labels');
        const labels = await res2.json();
        const noteSelect = document.getElementById('noteSelect');
        const noteLabelList = document.getElementById('noteLabelList');

        if (noteSelect) {
            noteSelect.innerHTML = '<option value="">-- ラベルを選択 --</option>';
            labels.forEach(l => {
                const opt = document.createElement('option');
                opt.value = l.id;
                opt.textContent = l.label;
                noteSelect.appendChild(opt);
            });
        }
        if (noteLabelList) {
            noteLabelList.innerHTML = '';
            if (labels.length === 0) {
                noteLabelList.innerHTML = '<span style="color:var(--muted);font-size:0.85em;">ラベルなし</span>';
            } else {
                labels.forEach(l => {
                    const chip = document.createElement('span');
                    chip.className = 'note-chip';
                    chip.innerHTML = `${l.label} <button class="chip-del" onclick="deleteNoteLabel(${l.id})" title="削除">×</button>`;
                    noteLabelList.appendChild(chip);
                });
            }
        }

        // 現在選択中の取引先ノートも更新
        const vCode = document.getElementById('detailVendorCode')?.textContent?.trim();
        if (vCode && vCode !== '-') window.loadVendorNotes(vCode);

    } catch (e) { alert('削除エラー: ' + e.message); }
};

// ---- 取引先ノート削除 (グローバル) ----
window.removeVendorNote = async function(noteId, vendorCode) {
    try {
        const res = await fetch(`/api/master/vendor-notes/${noteId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(await res.text());
        window.loadVendorNotes(vendorCode);
    } catch (e) { alert('削除エラー: ' + e.message); }
};
