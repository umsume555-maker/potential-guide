document.addEventListener('DOMContentLoaded', () => {
    // Only init if the tab exists
    const tab = document.getElementById('tab-reconcile');
    if (!tab) return;

    loadVendors();

    // Event Listeners
    document.getElementById('btnRefreshReconcileVendors').addEventListener('click', loadVendors);
    document.getElementById('btnInitTemplate').addEventListener('click', showInitTemplateDialog);
    document.getElementById('btnSaveTemplateInit').addEventListener('click', saveTemplateInit);
    document.getElementById('btnRunReconcile').addEventListener('click', runReconcile);
    document.getElementById('btnSyncSheetReconcile').addEventListener('click', syncToSheet);

    loadDepartments();
    loadTargetVendors();

    document.getElementById('btnAddTargetVendor').addEventListener('click', addTargetVendor);

    // Auto-refresh Monthly Status on change
    const onConditionChange = () => {
        const v = document.getElementById('reconcileVendorSelect').value;
        const m = document.getElementById('reconcileMonth').value;
        if (v && m && v !== "Loading..." && v !== "") {
            renderMonthlyStatus(v, m);
        } else {
            document.getElementById('monthlyStatusArea').style.display = 'none';
        }
    };
    document.getElementById('reconcileVendorSelect').addEventListener('change', onConditionChange);
    document.getElementById('reconcileMonth').addEventListener('change', onConditionChange);
});

async function loadVendors() {
    const select = document.getElementById('reconcileVendorSelect');
    select.innerHTML = '<option>Loading...</option>';

    try {
        const response = await fetch('/api/reconcile/vendors');
        const data = await response.json();

        // Sort: Configured first, then by Code
        cachedVendors = data.sort((a, b) => {
            if (a.has_template !== b.has_template) {
                return a.has_template ? -1 : 1;
            }
            return a.vendor_code.localeCompare(b.vendor_code);
        });

        renderVendorOptions(cachedVendors);

        // Toggle Init Button based on selection
        select.addEventListener('change', () => {
            const selectedOpt = select.options[select.selectedIndex];
            if (!selectedOpt.value) {
                document.getElementById('btnInitTemplate').style.display = 'none';
                document.getElementById('reconcileFileTypeBadge').textContent = '-';
                return;
            }

            const needsInit = selectedOpt.dataset.needsInit === "true";
            const btn = document.getElementById('btnInitTemplate');
            btn.style.display = 'inline-block';
            btn.textContent = needsInit ? '初期設定' : '設定変更';

            document.getElementById('reconcileFileTypeBadge').textContent = needsInit ? '-' : (selectedOpt.text.match(/\[(.*?)\]/) || [])[1] || '-';
        });

        // Setup Filter
        setupSearchFilter('reconcileVendorFilter', 'reconcileVendorSelect', cachedVendors, (v) => {
            const hasTemplate = v.has_template ? `[${v.file_type}]` : `[未設定]`;
            return {
                value: v.vendor_code,
                text: `${v.vendor_name} (${v.vendor_code}) ${hasTemplate}`,
                dataset: { needsInit: !v.has_template }
            };
        });

    } catch (e) {
        console.error(e);
        select.innerHTML = '<option>Error loading vendors</option>';
    }
}

function showInitTemplateDialog() {
    const select = document.getElementById('reconcileVendorSelect');
    if (!select.value) return;

    const vendorCode = select.value;
    document.getElementById('initTemplateVendorCode').value = vendorCode;

    // Find vendor config in cachedVendors (global)
    const vendor = cachedVendors.find(v => v.vendor_code === vendorCode);

    // Reset fields default
    document.getElementById('initTemplateFileType').value = 'excel';
    document.getElementById('initTemplateDeptColumn').value = '';
    document.getElementById('initTemplateAmountColumn').value = '';
    document.getElementById('initTemplateHeaderRow').value = '1';

    // Populate if config exists
    if (vendor && vendor.config) {
        const c = vendor.config;
        document.getElementById('initTemplateFileType').value = c.file_type || 'excel';

        if (c.file_type === 'excel') {
            document.getElementById('initTemplateDeptColumn').value = c.excel_dept_column || '';
            document.getElementById('initTemplateAmountColumn').value = c.excel_amount_column || '';
            document.getElementById('initTemplateHeaderRow').value = c.excel_header_row || '1';
        } else if (c.file_type === 'pdf') {
            document.getElementById('initTemplateDeptColumn').value = c.pdf_dept_column || '';
            document.getElementById('initTemplateAmountColumn').value = c.pdf_amount_column || '';
        }
    }

    document.getElementById('initTemplateDialog').style.display = 'block';
}

async function saveTemplateInit() {
    const vendorCode = document.getElementById('initTemplateVendorCode').value;
    const fileType = document.getElementById('initTemplateFileType').value;
    const deptCol = document.getElementById('initTemplateDeptColumn').value;
    const amountCol = document.getElementById('initTemplateAmountColumn').value;
    const headerRow = document.getElementById('initTemplateHeaderRow').value;

    if (!fileType) {
        alert("ファイルタイプを選択してください");
        return;
    }

    const formData = new FormData();
    formData.append('vendor_code', vendorCode);
    formData.append('file_type', fileType);
    if (deptCol) formData.append('dept_column', deptCol);
    if (amountCol) formData.append('amount_column', amountCol);
    if (headerRow) formData.append('header_row', headerRow);

    try {
        const res = await fetch('/api/reconcile/init_template', {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error(await res.text());

        alert("テンプレートを初期化しました。設定ファイルで列名を調整してください。");
        document.getElementById('initTemplateDialog').style.display = 'none';
        loadVendors();
    } catch (e) {
        alert("エラー: " + e.message);
    }
}

// Global variable to store last result details
let lastReconcileDetails = [];

async function runReconcile(e) {
    e.preventDefault();

    const month = document.getElementById('reconcileMonth').value;
    const vendor = document.getElementById('reconcileVendorSelect').value;
    const files = document.getElementById('reconcileFiles').files;

    if (!month || !vendor || files.length === 0) {
        alert("必須項目（月、取引先、ファイル）を入力してください");
        return;
    }

    const btn = document.getElementById('btnRunReconcile');
    const statusMsg = document.getElementById('reconcileStatusMsg');
    const resultArea = document.getElementById('reconcileResultArea');
    const btnSync = document.getElementById('btnSyncSheet');
    const syncStatus = document.getElementById('syncStatus');

    btn.disabled = true;
    btnSync.disabled = true;
    syncStatus.textContent = "";

    statusMsg.textContent = "実行中... (抽出・紐付け・突合)";
    statusMsg.style.color = "blue";
    resultArea.style.display = 'none';

    const formData = new FormData();
    formData.append('base_month', month);
    formData.append('vendor_code', vendor);
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    try {
        const res = await fetch('/api/reconcile/run', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Unknown error");
        }

        const data = await res.json();

        statusMsg.textContent = "完了しました";
        statusMsg.style.color = "green";

        // Store details for Sync
        lastReconcileDetails = data.details || [];
        btnSync.disabled = false;
        syncStatus.textContent = "※先にチェックを実行してください (完了済み)";

        // Show Record Summary
        document.getElementById('recCountExtracted').textContent = data.summary.extracted;
        document.getElementById('recCountMatched').textContent = data.summary.matched;
        document.getElementById('recCountRows').textContent = data.summary.reconciled_rows;

        // Render Unmapped Items
        renderUnmappedItems(data.unmapped_items, vendor);

        // Render Mapped Items
        renderMappedItems(data.mapped_items, vendor);

        // Setup Download Link
        const dlLink = document.getElementById('reconcileDownloadLink');
        dlLink.href = `/api/reconcile/download/${data.filename}`;
        dlLink.textContent = `📥 ダウンロード (${data.filename})`;

        resultArea.style.display = 'block';

        // Refresh Monthly Status
        renderMonthlyStatus(vendor, month);

    } catch (e) {
        statusMsg.textContent = "エラーが発生しました: " + e.message;
        statusMsg.style.color = "red";
    } finally {
        btn.disabled = false;
    }
}

async function syncToSheet() {
    const vendor = document.getElementById('reconcileVendorSelect').value;
    const month = document.getElementById('reconcileMonth').value;
    const btn = document.getElementById('btnSyncSheetReconcile');
    const statusMsg = document.getElementById('reconcileStatusMsg');

    if (!vendor || !month || !lastReconcileDetails) {
        alert("データが不足しています。先に突合を実行してください。");
        return;
    }

    if (!confirm("現場案内用スプレッドシートを更新しますか？\n（「申請なし」の事業所は「ズレ」として反映されます）")) {
        return;
    }

    btn.disabled = true;
    statusMsg.textContent = "更新中...";

    const formData = new FormData();
    formData.append('vendor_code', vendor);
    formData.append('base_month', month);
    formData.append('details', JSON.stringify(lastReconcileDetails));

    try {
        const res = await fetch('/api/reconcile/sync_sheet', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || "Unknown error");
        }

        let msg = "更新完了: ";
        if (data.details) {
            msg += `${data.details.rows_written}行 更新`;
        }
        statusMsg.textContent = msg;
        statusMsg.style.color = "green";
        alert(msg);

    } catch (e) {
        console.error(e);
        const errDetail = e.stack || e.message;
        statusMsg.textContent = "エラー: " + e.message;
        statusMsg.style.color = "red";
        alert("シート更新エラー:\n" + errDetail);
    } finally {
        btn.disabled = false;
    }
}

let cachedDepartments = [];
async function loadDepartments() {
    try {
        const res = await fetch('/api/reconcile/departments');
        cachedDepartments = await res.json();
    } catch (e) {
        console.error("Failed to load departments", e);
    }
}

const renderItemRow = (tbody, name, vendorCode, initialCandidates = []) => {
    const tr = document.createElement('tr');

    // Create options
    const createOptions = (list) => list.map(d => `<option value="${d.code}">${d.name} (${d.code})</option>`).join('');
    const optionsHtml = createOptions(cachedDepartments);

    tr.innerHTML = `
        <td>${name}</td>
        <td>
            <div style="margin-bottom:8px;">
                <label style="font-size:0.8em; color:var(--text-secondary);">部門候補 1 (Main)</label>
                <input type="text" class="dept-filter-1" placeholder="🔍 検索..." 
                       style="width:100%; margin-bottom:4px; font-size:0.8em; padding:4px; background:var(--bg-secondary); color:var(--text); border:1px solid var(--line); border-radius:4px;">
                <select class="dept-select-1" style="width:100%">
                    <option value="">-- 選択 --</option>
                    ${optionsHtml}
                </select>
            </div>
            <div>
                <label style="font-size:0.8em; color:var(--text-secondary);">部門候補 2 (Sub/任意)</label>
                <input type="text" class="dept-filter-2" placeholder="🔍 検索..." 
                       style="width:100%; margin-bottom:4px; font-size:0.8em; padding:4px; background:var(--bg-secondary); color:var(--text); border:1px solid var(--line); border-radius:4px;">
                <select class="dept-select-2" style="width:100%">
                    <option value="">-- 未設定 --</option>
                    ${optionsHtml}
                </select>
            </div>
        </td>
        <td style="vertical-align: top; padding-top: 24px;">
            <button type="button" class="primary sm btn-register">登録</button>
        </td>
    `;

    // Set initial values from candidates
    const sel1 = tr.querySelector('.dept-select-1');
    const sel2 = tr.querySelector('.dept-select-2');
    if (initialCandidates && initialCandidates.length > 0) sel1.value = initialCandidates[0] || "";
    if (initialCandidates && initialCandidates.length > 1) sel2.value = initialCandidates[1] || "";

    // Local Filter Logic
    const setupLocalFilter = (filterClass, selectClass) => {
        const input = tr.querySelector(filterClass);
        const select = tr.querySelector(selectClass);
        const createOpts = (list) => list.map(d => `<option value="${d.code}">${d.name} (${d.code})</option>`).join('');

        input.addEventListener('input', () => {
            const keyword = input.value.toLowerCase();
            const filteredDepts = cachedDepartments.filter(d =>
                d.name.toLowerCase().includes(keyword) || d.code.toLowerCase().includes(keyword)
            );
            const defaultOpt = selectClass.includes('2') ? '<option value="">-- 未設定 --</option>' : '<option value="">-- 選択 --</option>';
            select.innerHTML = defaultOpt + createOpts(filteredDepts);

            // Restore value if present in filtered list, else clear? 
            // Actually standard behavior is to reset if not found, but we want to keep selection if possible.
            // But here we reconstruct innerHTML, so value is lost unless we restore it.
            // Simple approach: just let it reset for now as user is searching for new value.
        });
    };

    setupLocalFilter('.dept-filter-1', '.dept-select-1');
    setupLocalFilter('.dept-filter-2', '.dept-select-2');

    // Register Event
    const btn = tr.querySelector('.btn-register');
    btn.addEventListener('click', async () => {
        const s1 = tr.querySelector('.dept-select-1');
        const s2 = tr.querySelector('.dept-select-2');

        if (!s1.value) {
            alert("事業所(候補1)を選択してください");
            return;
        }
        await registerSynonym(vendorCode, name, s1.value, s2.value, btn);
    });

    tbody.appendChild(tr);
};

function renderUnmappedItems(items, vendorCode) {
    const area = document.getElementById('unmappedArea');
    const tbody = document.getElementById('unmappedListBody');
    tbody.innerHTML = '';

    if (!items || items.length === 0) {
        area.style.display = 'none';
        return;
    }
    area.style.display = 'block';

    items.forEach(name => {
        renderItemRow(tbody, name, vendorCode, []);
    });
}

function renderMappedItems(items, vendorCode) {
    const area = document.getElementById('mappedArea');
    const tbody = document.getElementById('mappedListBody');
    if (!area || !tbody) return;
    tbody.innerHTML = '';

    if (!items || items.length === 0) {
        area.style.display = 'none';
        return;
    }
    area.style.display = 'block';

    items.forEach(item => {
        // item: { raw_name, candidate_codes, mapped_code }
        renderItemRow(tbody, item.raw_name, vendorCode, item.candidate_codes);
    });
}

async function registerSynonym(vendorCode, rawName, deptCode1, deptCode2, btnElement) {
    // Prevent UI 'UNMAPPED ' prefix from being saved
    if (rawName.startsWith("UNMAPPED ")) {
        rawName = rawName.replace("UNMAPPED ", "").trim();
    }
    const formData = new FormData();
    formData.append('vendor_code', vendorCode);
    formData.append('raw_name', rawName);
    formData.append('dept_code', deptCode1);
    if (deptCode2) {
        formData.append('dept_code_2', deptCode2);
    }

    try {
        btnElement.disabled = true;
        btnElement.textContent = "...";

        const res = await fetch('/api/reconcile/synonyms', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) throw new Error(await res.text());

        // Success: Remove row or change status
        const tr = btnElement.closest('tr');
        tr.style.opacity = '0.5';
        btnElement.textContent = "済";

    } catch (e) {
        alert("登録エラー: " + e.message);
        btnElement.disabled = false;
        btnElement.textContent = "登録";
    }
}

function renderVendorOptions(vendors) {
    const select = document.getElementById('reconcileVendorSelect');
    select.innerHTML = '<option value="">-- 取引先を選択 --</option>';

    vendors.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.vendor_code;
        opt.textContent = `${v.vendor_name} (${v.vendor_code})`;
        if (v.has_template) {
            opt.textContent += ` [${v.file_type}]`;
        } else {
            opt.textContent += ` [未設定]`;
            opt.dataset.needsInit = "true";
        }
        select.appendChild(opt);
    });
    updateInitButtonState();
}

function updateInitButtonState() {
    const select = document.getElementById('reconcileVendorSelect');
    const selectedOpt = select.options[select.selectedIndex];

    if (!selectedOpt || !selectedOpt.value) {
        document.getElementById('btnInitTemplate').style.display = 'none';
        document.getElementById('reconcileFileTypeBadge').textContent = '-';
        return;
    }

    const needsInit = selectedOpt.dataset.needsInit === "true";
    const btn = document.getElementById('btnInitTemplate');
    btn.style.display = 'inline-block';
    btn.textContent = needsInit ? '初期設定' : '設定変更';

    document.getElementById('reconcileFileTypeBadge').textContent = needsInit ? '-' : (selectedOpt.text.match(/\[(.*?)\]/) || [])[1] || '-';
}

function setupSearchFilter(inputId, selectId, dataList, mapFunc) {
    const input = document.getElementById(inputId);
    const select = document.getElementById(selectId);
    if (!input || !select) return;

    input.addEventListener('input', () => {
        const keyword = input.value.toLowerCase();

        const filtered = dataList.filter(item => {
            const text = JSON.stringify(item).toLowerCase();
            return text.includes(keyword);
        });

        select.innerHTML = '<option value="">-- 選択 --</option>';
        filtered.forEach(item => {
            const mapped = mapFunc(item);
            const opt = document.createElement('option');
            opt.value = mapped.value;
            opt.textContent = mapped.text;
            if (mapped.dataset) {
                if (mapped.dataset.needsInit) opt.dataset.needsInit = mapped.dataset.needsInit;
            }
            select.appendChild(opt);
        });

        select.dispatchEvent(new Event('change'));
    });
}

// === Target Vendors Management ===
async function loadTargetVendors() {
    const tbody = document.getElementById('targetVendorListBody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;">読込中...</td></tr>';

    try {
        const res = await fetch('/api/reconcile/target_vendors');
        if (!res.ok) throw new Error("Failed to load");
        const vendors = await res.json();

        tbody.innerHTML = '';
        if (vendors.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--muted)">登録なし</td></tr>';
            return;
        }

        vendors.forEach(v => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${v.vendor_code}</td>
                <td>${v.vendor_name}</td>
                <td style="text-align:center;">
                    <button class="danger xs" onclick="deleteTargetVendor('${v.vendor_code}')">削除</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="3" style="color:red;">エラー発生</td></tr>';
    }
}

async function addTargetVendor() {
    const codeInp = document.getElementById('targetVendorCode');
    const nameInp = document.getElementById('targetVendorName');
    const code = codeInp.value.trim();
    const name = nameInp.value.trim();

    if (!code || !name) {
        alert("コードと取引先名を入力してください");
        return;
    }

    const formData = new FormData();
    formData.append('vendor_code', code);
    formData.append('vendor_name', name);

    try {
        const res = await fetch('/api/reconcile/target_vendors', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.status === 'error') {
            alert("エラー: " + data.message);
        } else {
            codeInp.value = '';
            nameInp.value = '';
            loadTargetVendors();

            // If currently selected vendor matches, refresh monthly status
            const currentVendor = document.getElementById('reconcileVendorSelect').value;
            if (currentVendor === code) {
                const month = document.getElementById('reconcileMonth').value;
                if (month) renderMonthlyStatus(code, month);
            }
        }
    } catch (e) {
        alert("通信エラー");
    }
}

async function deleteTargetVendor(code) {
    if (!confirm(`取引先コード ${code} を対象から削除しますか？`)) return;

    try {
        const res = await fetch(`/api/reconcile/target_vendors/${code}`, {
            method: 'DELETE'
        });
        loadTargetVendors();

        // Refresh monthly status if selected
        const currentVendor = document.getElementById('reconcileVendorSelect').value;
        const month = document.getElementById('reconcileMonth').value;
        if (currentVendor === code && month) {
            renderMonthlyStatus(code, month);
        }
    } catch (e) {
        alert("通信エラー");
    }
}

// === Monthly Status ===
async function renderMonthlyStatus(vendorCode, baseMonth) {
    const area = document.getElementById('monthlyStatusArea');
    const tbody = document.getElementById('monthlyStatusBody');
    if (!area || !tbody) return;

    if (!vendorCode || !baseMonth) {
        area.style.display = 'none';
        return;
    }

    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">読込中...</td></tr>';
    area.style.display = 'block';

    try {
        const res = await fetch(`/api/reconcile/monthly_status?vendor_code=${vendorCode}&base_month=${baseMonth}`);
        if (!res.ok) throw new Error("API Error");
        const list = await res.json();

        tbody.innerHTML = '';
        if (list.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--muted)">実績データなし</td></tr>';
            return;
        }

        list.forEach(item => {
            const tr = document.createElement('tr');

            // Monthly Mark
            const isMonthlyHtml = item.is_monthly === "毎月"
                ? '<span class="badge" style="background:var(--accent); color:white;">毎月</span>'
                : '<span style="color:#ccc;">-</span>';

            // Amount Format
            const amtStr = item.payment_amount ? parseInt(item.payment_amount).toLocaleString() : "-";

            // Status badge
            let statusBadge = '-';
            if (item.status === 'OK') statusBadge = '<span class="badge" style="background:#d4edda; color:#155724;">OK</span>';
            else if (item.status === 'MISSING') statusBadge = '<span class="badge" style="background:#f8d7da; color:#721c24;">MISSING</span>';
            else if (item.status) statusBadge = `<span class="badge">${item.status}</span>`;

            tr.innerHTML = `
                <td>${item.dept_code}</td>
                <td>${item.dept_name}</td>
                <td style="text-align:center;">${isMonthlyHtml}</td>
                <td style="text-align:right;">${amtStr}</td>
                <td style="text-align:center;">${statusBadge}</td>
            `;
            tbody.appendChild(tr);
        });

    } catch (e) {
        console.error(e);
        tbody.innerHTML = '<tr><td colspan="5" style="color:red;">読込エラー</td></tr>';
    }
}
