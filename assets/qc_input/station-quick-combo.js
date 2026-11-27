// Chọn cụm/trạm và combo lỗi nhanh (Lũy kế / Trong ngày).
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

function normalizeStationList(raw) {
    if (Array.isArray(raw)) return raw.filter(x => !!x);
    if (typeof raw === 'string') {
        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) return parsed.filter(x => !!x);
        } catch (e) {}
    }
    return [];
}

function getStationFieldLabel() {
    return stationMode === 'cluster' ? 'Cụm' : 'Trạm';
}

function getLegacyStationOptions() {
    const items = normalizeStationList(userStationsRaw);
    return items.length ? items : stationOptions.slice();
}

// Công đoạn được phân công cho QC ở đúng MONo của kế hoạch đang chọn (từ chuyền treo).
function getSelectedPlanAssignedStations() {
    const plan = availablePlans.find(p => p.id == selectedPlanId);
    const mono = plan && plan.mono;
    return mono ? normalizeStationList(userPlanStations[mono]) : [];
}

function getPlanStationOptions() {
    const planStations = getSelectedPlanAssignedStations();
    if (planStations.length) {
        return planStations;
    }
    const assignedStations = normalizeStationList(userStationsRaw);
    if (assignedStations.length) {
        return assignedStations;
    }
    if (stationMode === 'cluster') {
        return Array.isArray(clusterOptions) ? clusterOptions.slice() : [];
    }
    return getLegacyStationOptions();
}

function updateInlineStationSelector() {
    const picker = document.getElementById('inlineStationPicker');
    const labelEl = document.getElementById('inlineStationLabel');
    const hintEl = document.getElementById('inlineStationHint');
    const selectEl = document.getElementById('inlineStationSelect');
    if (!picker || !labelEl || !hintEl || !selectEl) return;

    if (stationMode !== 'cluster') {
        picker.style.display = 'none';
        selectEl.innerHTML = '<option value="">-- Chọn --</option>';
        return;
    }

    picker.style.display = 'flex';
    labelEl.textContent = getStationFieldLabel();
    const hasAssignedStations = normalizeStationList(userStationsRaw).length > 0;
    hintEl.textContent = stationList.length
        ? (hasAssignedStations ? 'Hệ thống tự nhận trạm theo QC.' : 'QC XNV2 tự chọn cụm để ghi nhận số liệu.')
        : 'Loại hàng này chưa có cụm được cấu hình.';
    selectEl.innerHTML = `<option value="">-- Chọn ${getStationFieldLabel()} --</option>`;
    stationList.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st;
        opt.textContent = st;
        selectEl.appendChild(opt);
    });
    selectEl.value = selectedStation || '';
}

function renderStationSelector() {
    const card = document.getElementById('stationCard');
    const valueEl = document.getElementById('stationValue');
    const optionsEl = document.getElementById('stationOptions');
    const hintEl = document.getElementById('stationHint');
    if (!card || !valueEl || !optionsEl || !hintEl) return;

    stationList = getPlanStationOptions();
    if (selectedStation && !stationList.includes(selectedStation)) {
        selectedStation = '';
    }

    if (stationMode === 'cluster') {
        card.style.display = 'none';
        updateInlineStationSelector();
        if (stationList.length === 1 && !selectedStation) {
            selectedStation = stationList[0];
            updateInlineStationSelector();
        }
        return;
    }

    updateInlineStationSelector();

    if (!stationList.length) {
        card.style.display = 'none';
        selectedStation = '';
        return;
    }

    card.style.display = 'block';
    optionsEl.innerHTML = '';
    hintEl.textContent = '';

    if (stationList.length === 1) {
        selectedStation = stationList[0];
        valueEl.textContent = selectedStation;
        optionsEl.style.display = 'none';
        hintEl.textContent = 'Hệ thống tự nhận trạm theo QC.';
        return;
    }

    valueEl.textContent = selectedStation || 'Chưa chọn';
    optionsEl.style.display = 'flex';
    stationList.forEach(st => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'station-chip' + (st === selectedStation ? ' active' : '');
        btn.textContent = st;
        btn.addEventListener('click', () => {
            setSelectedStation(st);
        });
        optionsEl.appendChild(btn);
    });
    const usingFallback = Object.keys(userPlanStations).length > 0 && !getSelectedPlanAssignedStations().length;
    hintEl.textContent = usingFallback
        ? 'Chọn trạm để nhập dữ liệu (MONo này chưa có phân công từ MES).'
        : 'Chọn trạm để nhập dữ liệu.';
}

async function loadClusterOptions(loaiHangId) {
    selectedLoaiHangId = loaiHangId || null;
    clusterOptions = [];
    if (!selectedLoaiHangId || !isFlexibleQcUnit) return;
    try {
        const params = new URLSearchParams({ loai_hang_id: selectedLoaiHangId, active_only: 'true' });
        const res = await fetch(`/api/dm/qc-cum?${params.toString()}`);
        const data = await res.json();
        clusterOptions = (data.rows || []).map(r => (r.ten_cum || '').trim()).filter(Boolean);
    } catch (e) {
        console.error(e);
        clusterOptions = [];
    }
}

function onInlineStationChange(value) {
    setSelectedStation(value);
}

function setSelectedStation(station) {
    const next = station || '';
    if (next !== selectedStation && hasUnsavedData()
        && !confirm('Bạn đang có sản phẩm lỗi chưa lưu. Đổi cụm/trạm sẽ mất dữ liệu này. Tiếp tục?')) {
        renderStationSelector(); // trả dropdown về giá trị cũ
        return;
    }
    selectedStation = next;
    bumpCtx();
    renderStationSelector();
    // Reset counts and current defects on station change
    resetEntryState();
    setOutputDisplay(0, 0);
    loadExistingEntry();
    fetchOutputTotal();
    loadPosSummary();
    loadQuickDefectCombos();
    loadQuickDefectCombosToday();
    if (currentWorkTab === 'rework') fetchInlineReworkData();
}

function getActiveStation() {
    if (selectedStation) return selectedStation;
    if (stationList.length === 1) return stationList[0];
    return '';
}

function ensureStationSelected() {
    const station = getActiveStation();
    const fieldLabel = getStationFieldLabel();
    if (!stationList.length && stationMode === 'cluster') {
        alert(`Loại hàng này chưa được cấu hình ${fieldLabel}.`);
        return false;
    }
    if (!station && (stationMode === 'cluster' || stationList.length > 1)) {
        alert(`Vui lòng chọn ${fieldLabel} trước khi nhập dữ liệu.`);
        return false;
    }
    return true;
}

function getQuickComboHint() {
    const station = getActiveStation();
    const needsStation = !station && (stationMode === 'cluster' || stationList.length > 1);
    if (needsStation) return `Chọn ${getStationFieldLabel()} để tải top combo lỗi.`;
    if (quickComboMode === 'today') {
        if (!quickDefectCombosToday.length) return 'Chưa có lỗi nào trong ngày.';
        return 'Chọn combo đã ghi nhận trong ngày.';
    }
    if (!quickDefectCombos.length) return 'Chưa có lịch sử lỗi phù hợp cho lựa chọn này.';
    return `Chọn combo để tự điền vào vị trí trống gần nhất.`;
}

function getActiveQuickCombos() {
    return quickComboMode === 'today' ? quickDefectCombosToday : quickDefectCombos;
}

function getQuickComboOptionsHtml() {
    const combos = getActiveQuickCombos();
    const placeholder = quickComboMode === 'today'
        ? (combos.length ? '-- Chọn dạng lỗi trong ngày --' : '-- Chưa có lỗi trong ngày --')
        : (combos.length ? '-- Chọn nhanh dạng lỗi --' : '-- Chưa có combo lịch sử --');
    const options = [`<option value="">${placeholder}</option>`];
    combos.forEach((combo, idx) => {
        const qty = Number(combo.defect_qty || 0);
        const qtyLabel = qty > 0 ? ` (${qty})` : '';
        options.push(`<option value="${idx}">${esc(combo.label || '--')}${qtyLabel}</option>`);
    });
    return options.join('');
}

function renderQuickComboSelect(productId) {
    const combos = getActiveQuickCombos();
    const isHistory = quickComboMode === 'history';
    const isToday = quickComboMode === 'today';
    return `
        <div class="quick-combo-row" data-product-id="${productId}">
            <div class="d-flex mb-1" style="gap:0;">
                <button type="button" class="btn btn-sm quick-combo-tab ${isHistory ? 'btn-primary' : 'btn-outline-primary'}" onclick="switchQuickComboMode('history')" style="border-radius:.375rem 0 0 .375rem; flex:1; font-size:.72rem; padding:4px 6px;">Lũy kế</button>
                <button type="button" class="btn btn-sm quick-combo-tab ${isToday ? 'btn-primary' : 'btn-outline-primary'}" onclick="switchQuickComboMode('today')" style="border-radius:0 .375rem .375rem 0; flex:1; font-size:.72rem; padding:4px 6px;">Trong ngày</button>
            </div>
            <select class="form-select quick-combo-select" onchange="onQuickComboSelect(${productId}, this)" ${combos.length ? '' : 'disabled'}>
                ${getQuickComboOptionsHtml()}
            </select>
            <div class="quick-combo-hint">${getQuickComboHint()}</div>
        </div>
    `;
}

function refreshQuickComboDropdowns() {
    document.querySelectorAll('.defect-product[data-pending-failed="1"]').forEach(product => {
        ensureQuickComboPosition(product, true);
    });
}

function isProductUsingQuickCombo(product) {
    return product && product.dataset.pendingFailed === '1' && product.dataset.existing !== '1';
}

function ensureQuickComboPosition(productOrId, refresh = false) {
    const product = typeof productOrId === 'string' || typeof productOrId === 'number'
        ? document.querySelector(`.defect-product[data-product-id="${productOrId}"]`)
        : productOrId;
    if (!isProductUsingQuickCombo(product)) return;
    const list = product.querySelector('.bo-phan-blocks');
    if (!list) return;
    const productId = product.dataset.productId;
    let row = product.querySelector('.quick-combo-row');
    if (!row) {
        const wrap = document.createElement('div');
        wrap.innerHTML = renderQuickComboSelect(productId).trim();
        row = wrap.firstElementChild;
    } else if (refresh) {
        const wrap = document.createElement('div');
        wrap.innerHTML = renderQuickComboSelect(productId).trim();
        row.replaceWith(wrap.firstElementChild);
        row = product.querySelector('.quick-combo-row');
    }

    const blocks = Array.from(list.querySelectorAll('.bo-phan-block'));
    const filledBlocks = blocks.filter(block => !isBlockEmptyForQuickCombo(block));
    const anchor = filledBlocks[filledBlocks.length - 1] || null;
    if (anchor) {
        anchor.insertAdjacentElement('afterend', row);
    } else if (blocks.length) {
        list.insertBefore(row, blocks[0]);
    } else {
        list.appendChild(row);
    }
}

function updateQuickComboPositionFromBlock(block) {
    const product = block?.closest('.defect-product');
    if (!product) return;
    ensureQuickComboPosition(product);
}

async function loadQuickDefectCombos() {
    quickDefectCombos = [];
    const station = getActiveStation();
    if (!selectedPlanId || (!station && (stationMode === 'cluster' || stationList.length > 1))) {
        refreshQuickComboDropdowns();
        return;
    }
    refreshQuickComboDropdowns();
    try {
        const params = new URLSearchParams({ plan_id: selectedPlanId, station: station || '', date: reportDateStr });
        const seq = ctxSeq;
        const res = await fetch(`/api/qc/input/quick-defect-combos?${params.toString()}`);
        const data = await res.json();
        if (isStaleCtx(seq)) return;
        if (!res.ok) throw new Error(data.detail || 'API Error');
        quickDefectCombos = data.rows || [];
        refreshQuickComboDropdowns();
    } catch (e) {
        console.error(e);
        quickDefectCombos = [];
        refreshQuickComboDropdowns();
    }
}

async function loadQuickDefectCombosToday() {
    quickDefectCombosToday = [];
    const station = getActiveStation();
    if (!selectedPlanId || (!station && (stationMode === 'cluster' || stationList.length > 1))) {
        refreshQuickComboDropdowns();
        return;
    }
    try {
        const params = new URLSearchParams({ plan_id: selectedPlanId, station: station || '', date: reportDateStr });
        const seq = ctxSeq;
        const res = await fetch(`/api/qc/input/quick-defect-combos-today?${params.toString()}`);
        const data = await res.json();
        if (isStaleCtx(seq)) return;
        if (!res.ok) throw new Error(data.detail || 'API Error');
        quickDefectCombosToday = data.rows || [];
        if (quickComboMode === 'today') refreshQuickComboDropdowns();
    } catch (e) {
        console.error(e);
        quickDefectCombosToday = [];
        if (quickComboMode === 'today') refreshQuickComboDropdowns();
    }
}

function switchQuickComboMode(mode) {
    if (quickComboMode === mode) return;
    quickComboMode = mode;
    if (mode === 'today' && !quickDefectCombosToday.length) {
        loadQuickDefectCombosToday();
    }
    refreshQuickComboDropdowns();
}

function normalizeMucDoText(value) {
    return (value || '')
        .toString()
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '');
}

function getPreferredMucDoFromMap(mucDo) {
    if (!mucDo || typeof mucDo !== 'object') return '';
    const levels = Object.keys(mucDo);
    if (!levels.length) return '';
    if (levels.length === 1) return levels[0];

    const scoreLevel = (level) => {
        const raw = normalizeMucDoText(level);
        const num = raw.match(/\d+/);
        if (num) return Number(num[0]);
        if (raw.includes('nghiem') || raw.includes('nang') || raw.includes('cao') || raw.includes('high') || raw.includes('severe') || raw.includes('critical')) return 100;
        if (raw.includes('trung') || raw.includes('medium')) return 50;
        if (raw.includes('nhe') || raw.includes('thap') || raw.includes('low')) return 10;
        return 0;
    };

    return levels
        .map((level, idx) => ({ level, idx, score: scoreLevel(level) }))
        .sort((a, b) => (b.score - a.score) || (b.idx - a.idx))[0].level;
}

async function onQuickComboSelect(productId, selectElem) {
    const index = selectElem.value;
    selectElem.value = '';
    if (index === '') return;
    await applyQuickDefectCombo(productId, Number(index));
}

async function applyQuickDefectCombo(productId, index) {
    const combo = getActiveQuickCombos()[index];
    if (!combo) return;
    if (!ensureStationSelected()) return;

    const preferredMucDo = getPreferredMucDoFromMap(combo.muc_do);
    const product = document.querySelector(`.defect-product[data-product-id="${productId}"]`);
    if (!product) return;
    const block = await getQuickComboTargetBlock(product, combo);
    if (!block) return;
    await fillQuickComboBlock(block, combo, preferredMucDo);
    ensureQuickComboPosition(product);

    block.classList.add('pulse-success');
    block.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => block.classList.remove('pulse-success'), 600);
}

function isBlockEmptyForQuickCombo(block) {
    const bpVal = getSelectedComboValue(block.querySelector('.combo-dropdown[data-type="bo-phan"]'), block.querySelector('.sel-bo-phan'));
    const ctVal = getSelectedComboValue(block.querySelector('.combo-dropdown[data-type="chi-tiet"], .combo-dropdown[data-type="vp-chi-tiet"]'), block.querySelector('.sel-chi-tiet'));
    const hasMaLoi = Array.from(block.querySelectorAll('.defect-items .defect-item'))
        .some(item => !!getSelectedComboValue(item.querySelector('.combo-dropdown[data-type="ma-loi"]'), item.querySelector('.sel-ma-loi')));
    return !bpVal && !ctVal && !hasMaLoi;
}

async function getQuickComboTargetBlock(product, combo) {
    const existingEmpty = Array.from(product.querySelectorAll('.bo-phan-block'))
        .find(block => isBlockEmptyForQuickCombo(block));
    if (existingEmpty) return existingEmpty;
    addBoPhanBlock(product.dataset.productId, {
        bo_phan_id: combo.bo_phan_id,
        chi_tiet_id: combo.chi_tiet_id,
        defects: []
    });
    const blocks = product.querySelectorAll('.bo-phan-block');
    return blocks[blocks.length - 1] || null;
}

async function fillQuickComboBlock(block, combo, preferredMucDo) {
    const blockId = block.dataset.blockId;
    if (visualPickerData && visualPickerData.has_visual_picker) {
        const prefillNhom = vpFindNhomByBoPhanId(combo.bo_phan_id);
        if (prefillNhom) vpSelectNhom(blockId, prefillNhom);
        vpSelectKhoi(blockId, combo.bo_phan_id);
        const khoi = vpGetKhoi((vpBlockState[blockId] || {}).nhom, combo.bo_phan_id);
        const hotspot = khoi ? (khoi.hotspots || []).find(h => h.chi_tiet_id === combo.chi_tiet_id) : null;
        if (hotspot) vpSelectHotspot(blockId, combo.bo_phan_id, hotspot);
    } else {
        selectComboValue(block.querySelector('.combo-dropdown[data-type="bo-phan"]'), String(combo.bo_phan_id));
        await loadChiTietOptions(block, combo.bo_phan_id, combo.chi_tiet_id);
    }

    let item = Array.from(block.querySelectorAll('.defect-items .defect-item'))
        .find(it => !getSelectedComboValue(it.querySelector('.combo-dropdown[data-type="ma-loi"]'), it.querySelector('.sel-ma-loi')));
    if (!item) {
        addDefectItem(blockId);
        const items = block.querySelectorAll('.defect-items .defect-item');
        item = items[items.length - 1];
    }
    const resolvedMaLoi = resolveQuickComboMaLoi(combo);
    if (!resolvedMaLoi) {
        alert(`Không tìm thấy mã lỗi ${combo.ten_ma || ''} trong bộ lỗi đang áp dụng.`);
        return;
    }
    selectComboValue(item.querySelector('.combo-dropdown[data-type="ma-loi"]'), `${resolvedMaLoi.ma_loi_id}|${resolvedMaLoi.mo_ta_loi_id}`);
    applyMucDoOptions(item, preferredMucDo);
}

function normalizeDefectCode(code) {
    return (code || '').toString().trim().toUpperCase();
}

function resolveQuickComboMaLoi(combo) {
    const maId = Number(combo.ma_loi_id);
    const moTaId = Number(combo.mo_ta_loi_id);
    let found = masterMaLoiOptions.find(opt => opt.ma_loi_id === maId && opt.mo_ta_loi_id === moTaId);
    if (found) return found;

    const code = normalizeDefectCode(combo.ten_ma);
    if (!code) return null;
    found = masterMaLoiOptions.find(opt => normalizeDefectCode(opt.ten_ma) === code);
    if (found) return found;

    if (/^S\d+$/.test(code)) {
        found = masterMaLoiOptions.find(opt => normalizeDefectCode(opt.ten_ma) === `E${code.slice(1)}`);
        if (found) return found;
    }
    if (/^F\d+$/.test(code)) {
        found = masterMaLoiOptions.find(opt => normalizeDefectCode(opt.ten_ma) === `O${code.slice(1)}`);
        if (found) return found;
    }
    return null;
}
