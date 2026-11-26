// Visual picker (chọn vị trí lỗi trên hình, áo vest pilot).
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

// ============== Visual Picker (Áo vest pilot) ==============
function vpFindNhomByBoPhanId(boPhanId) {
    if (!visualPickerData || !Array.isArray(visualPickerData.nhoms)) return null;
    for (const nhom of visualPickerData.nhoms) {
        const found = (nhom.khoi || []).find(k => k.bo_phan_id === boPhanId);
        if (found) return nhom.nhom;
    }
    return null;
}

function vpGetHotspotOptions(blockId) {
    const state = vpBlockState[blockId] || {};
    const khoi = vpGetKhoi(state.nhom, state.bo_phan_id);
    if (!khoi) return [];
    return (khoi.hotspots || []).map(h => ({
        value: String(h.chi_tiet_id),
        label: `${h.ma_vi_tri || ''}. ${h.label || ''}`.trim()
    }));
}

function renderVpBlockHTML(blockId, productId, displayIndex) {
    const nhomTabs = (visualPickerData.nhoms || []).map((n, idx) => `
        <button type="button" class="vp-nhom-tab${idx === 0 ? ' active' : ''}"
                data-nhom-key="${esc(n.nhom)}"
                onclick="vpSelectNhom(${blockId}, this.dataset.nhomKey)">${esc(n.label)}</button>
    `).join('');
    return `
        <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="label mb-0">Bộ phận #${displayIndex}</div>
            <button class="btn btn-sm btn-outline-secondary" onclick="removeBoPhanBlock(${productId}, ${blockId})">Xóa</button>
        </div>
        <div class="vp-wrap">
            <div class="vp-nhom-tabs" data-vp-tabs>${nhomTabs}</div>
            <div class="vp-selection-bar" data-vp-selection style="display:none;">
                <span class="vp-sel-code" data-vp-sel-code></span>
                <span data-vp-sel-label></span>
                <button class="vp-sel-clear" type="button" onclick="vpClearSelection(${blockId})">
                    <i class="fas fa-times-circle me-1"></i>Đổi vị trí
                </button>
            </div>
            <div class="vp-khoi-grid" data-vp-grid></div>
            <!-- Hidden: keeps the existing value/quick-combo plumbing; the table below replaces it. -->
            <div class="combo-dropdown" data-type="vp-chi-tiet" data-block-id="${blockId}" style="display:none;">
                <button type="button" class="combo-trigger" onclick="toggleCombo(this)">-- Chọn Mã vị trí --</button>
                <div class="combo-panel">
                    <input type="text" class="combo-search" oninput="filterCombo(this)">
                    <div class="combo-list"></div>
                </div>
                <select class="sel-vp-chi-tiet" style="display:none;"></select>
            </div>
            <div class="vp-stage-empty" data-vp-empty>Chọn 1 khối phía trên để chọn vị trí lỗi</div>
            <!-- Same layout as the QLCL PDF sheet: illustration | detail table -->
            <div class="vp-sheet" data-vp-sheet style="display:none;">
                <div class="vp-sheet-head">
                    <span class="vp-sheet-code" data-vp-sheet-code></span>
                    <span class="vp-sheet-name" data-vp-sheet-name></span>
                    <span class="vp-sheet-hint">Chạm mã trên hình hoặc dòng trong bảng</span>
                </div>
                <div class="vp-sheet-body">
                    <div class="vp-stage" data-vp-stage></div>
                    <div class="vp-table-wrap" data-vp-table-wrap>
                        <table class="vp-table">
                            <thead><tr><th>Mã tổng</th><th>Chi tiết</th></tr></thead>
                            <tbody data-vp-tbody></tbody>
                        </table>
                    </div>
                </div>
            </div>
            <select class="sel-bo-phan" style="display:none;"></select>
            <select class="sel-chi-tiet" style="display:none;"></select>
        </div>
        <div class="defect-items d-flex flex-column gap-2 mt-2"></div>
        <div class="text-end mt-2">
            <button class="btn btn-sm btn-primary" onclick="addDefectItem(${blockId})"><i class="fas fa-plus me-1"></i>Thêm lỗi</button>
        </div>
    `;
}

function initVpBlock(block, blockId) {
    // Default to first nhom and render khoi grid
    const firstNhom = (visualPickerData.nhoms && visualPickerData.nhoms[0]) ? visualPickerData.nhoms[0].nhom : null;
    vpBlockState[blockId] = { nhom: firstNhom, bo_phan_id: null, chi_tiet_id: null };
    initCombo(block);
    if (firstNhom) renderVpKhoiGrid(block, blockId, firstNhom);
}

function vpGetNhom(nhomKey) {
    return (visualPickerData.nhoms || []).find(n => n.nhom === nhomKey);
}

function vpGetKhoi(nhomKey, boPhanId) {
    const n = vpGetNhom(nhomKey);
    if (!n) return null;
    return n.khoi.find(k => k.bo_phan_id === boPhanId);
}

function renderVpKhoiGrid(block, blockId, nhomKey) {
    const grid = block.querySelector('[data-vp-grid]');
    if (!grid) return;
    const n = vpGetNhom(nhomKey);
    if (!n) { grid.innerHTML = ''; return; }
    const currentBp = (vpBlockState[blockId] || {}).bo_phan_id;
    grid.innerHTML = n.khoi.map(k => `
        <div class="vp-khoi-card${k.bo_phan_id === currentBp ? ' active' : ''}"
             data-bo-phan-id="${k.bo_phan_id}"
             onclick="vpSelectKhoi(${blockId}, ${k.bo_phan_id})">
            <img src="${esc(k.image_png)}" alt="${esc(k.ten_khoi)}" loading="lazy">
            <div class="vp-khoi-name">${esc(k.ten_khoi)}</div>
        </div>
    `).join('');
}

function vpSelectNhom(blockId, nhomKey) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    // Update tab active state
    block.querySelectorAll('.vp-nhom-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.nhomKey === nhomKey);
    });
    vpBlockState[blockId] = vpBlockState[blockId] || {};
    vpBlockState[blockId].nhom = nhomKey;
    renderVpKhoiGrid(block, blockId, nhomKey);
    // If switching nhom away from a selected khoi, keep selection but stage may not match — just leave selection bar
}

function vpSelectKhoi(blockId, boPhanId) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const state = vpBlockState[blockId] = vpBlockState[blockId] || {};
    state.bo_phan_id = boPhanId;
    const khoi = vpGetKhoi(state.nhom, boPhanId);
    if (!khoi) return;
    const selectedStillExists = (khoi.hotspots || []).some(h => h.chi_tiet_id === state.chi_tiet_id);
    if (!selectedStillExists) {
        state.chi_tiet_id = null;
    }
    // Update active card
    block.querySelectorAll('.vp-khoi-card').forEach(c => {
        c.classList.toggle('active', parseInt(c.dataset.boPhanId) === boPhanId);
    });
    const selBp = block.querySelector('.sel-bo-phan');
    const selCt = block.querySelector('.sel-chi-tiet');
    if (selBp) {
        selBp.innerHTML = `<option value="${boPhanId}" selected>${boPhanId}</option>`;
        selBp.value = String(boPhanId);
    }
    if (selCt && !state.chi_tiet_id) {
        selCt.innerHTML = '';
        selCt.value = '';
    }
    vpRefreshChiTietCombo(blockId);
    if (!state.chi_tiet_id) {
        const bar = block.querySelector('[data-vp-selection]');
        if (bar) bar.style.display = 'none';
    }
    // Render the PDF-style sheet: header, illustration, detail table
    const sheet = block.querySelector('[data-vp-sheet]');
    const empty = block.querySelector('[data-vp-empty]');
    if (empty) empty.style.display = 'none';
    sheet.style.display = '';
    sheet.dataset.nhom = state.nhom || '';
    sheet.querySelector('[data-vp-sheet-code]').textContent = vpBlockCode(khoi);
    sheet.querySelector('[data-vp-sheet-name]').textContent = khoi.ten_khoi || '';
    vpRenderTable(block, blockId, khoi);
    const stage = block.querySelector('[data-vp-stage]');
    const imgSrc = khoi.image_svg || khoi.image_png;
    stage.innerHTML = `
        <div class="vp-img-holder" data-vp-holder>
            <img src="${esc(imgSrc)}" alt="${esc(khoi.ten_khoi)}" data-vp-img>
        </div>
    `;
    // After image loads, position hotspots (so we have its rendered width/height)
    const img = stage.querySelector('img');
    const placeHotspots = () => positionVpHotspots(block, blockId, khoi);
    if (img.complete) placeHotspots();
    else img.addEventListener('load', placeHotspots, { once: true });
    // Re-layout on resize
    if (!block._vpResizeBound) {
        block._vpResizeBound = true;
        const handler = () => {
            const cur = vpBlockState[blockId];
            if (!cur || !cur.bo_phan_id) return;
            const k = vpGetKhoi(cur.nhom, cur.bo_phan_id);
            if (k) positionVpHotspots(block, blockId, k);
        };
        window.addEventListener('resize', handler);
    }
}

function positionVpHotspots(block, blockId, khoi) {
    const holder = block.querySelector('[data-vp-holder]');
    if (!holder) return;
    // Clear previous hotspots (keep image)
    holder.querySelectorAll('.vp-hotspot').forEach(h => h.remove());
    const state = vpBlockState[blockId] || {};
    const labelsInImage = !!(visualPickerData && visualPickerData.labels_in_image);
    (khoi.hotspots || []).forEach(h => {
        if (h.x_pct == null || h.y_pct == null) return;  // table-only code
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.dataset.chiTietId = h.chi_tiet_id;
        dot.title = `${h.ma_vi_tri || ''} · ${h.label || ''}`;
        dot.setAttribute('aria-label', dot.title);
        if (labelsInImage) {
            // Code is printed on the image (PDF sheet): transparent tap area over it.
            dot.className = 'vp-hotspot vp-hotspot-box';
            dot.style.left = `${h.x_pct * 100}%`;
            dot.style.top = `${h.y_pct * 100}%`;
            dot.style.width = `${(h.w_pct || 0.04) * 100}%`;
            dot.style.height = `${(h.h_pct || 0.04) * 100}%`;
        } else {
            dot.className = 'vp-hotspot';
            dot.textContent = h.ma_vi_tri;
            // x_pct / y_pct là tọa độ TOP-LEFT của text box (đã normalize 0..1 theo image bbox).
            // Đặt hotspot tại tâm của text box: left = x + w/2, top = y + h/2
            const cx = (h.x_pct + (h.w_pct || 0) / 2) * 100;
            const cy = (h.y_pct + (h.h_pct || 0) / 2) * 100;
            dot.style.left = `calc(${cx}% - 14px)`;
            dot.style.top = `calc(${cy}% - 11px)`;
        }
        if (state.chi_tiet_id === h.chi_tiet_id) dot.classList.add('active');
        dot.addEventListener('click', () => vpSelectHotspot(blockId, khoi.bo_phan_id, h));
        holder.appendChild(dot);
    });
}

function vpSelectHotspot(blockId, boPhanId, hotspot) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const state = vpBlockState[blockId] = vpBlockState[blockId] || {};
    state.bo_phan_id = boPhanId;
    state.chi_tiet_id = hotspot.chi_tiet_id;
    // Set values on hidden selects (so submitReport reads them as before)
    const selBp = block.querySelector('.sel-bo-phan');
    const selCt = block.querySelector('.sel-chi-tiet');
    selBp.innerHTML = `<option value="${boPhanId}" selected>${boPhanId}</option>`;
    selCt.innerHTML = `<option value="${hotspot.chi_tiet_id}" selected>${hotspot.chi_tiet_id}</option>`;
    selBp.value = String(boPhanId);
    selCt.value = String(hotspot.chi_tiet_id);
    selectComboValue(block.querySelector('.combo-dropdown[data-type="vp-chi-tiet"]'), String(hotspot.chi_tiet_id));
    // Highlight the code on the image and its row in the table
    vpMarkActive(block, hotspot.chi_tiet_id);
    // Show selection bar
    const bar = block.querySelector('[data-vp-selection]');
    bar.style.display = 'flex';
    bar.querySelector('[data-vp-sel-code]').textContent = hotspot.ma_vi_tri || '';
    bar.querySelector('[data-vp-sel-label]').textContent = hotspot.label || '';
    // Subtle confirmation
    block.classList.add('pulse-success');
    setTimeout(() => block.classList.remove('pulse-success'), 600);
    updateQuickComboPositionFromBlock(block);
}

function vpRefreshChiTietCombo(blockId) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const combo = block.querySelector('.combo-dropdown[data-type="vp-chi-tiet"]');
    if (!combo) return;
    const options = vpGetHotspotOptions(blockId);
    setComboOptions(combo, options, options.length ? '-- Chọn Mã vị trí --' : '-- Chưa có Mã vị trí --');
    const state = vpBlockState[blockId] || {};
    if (state.chi_tiet_id) {
        selectComboValue(combo, String(state.chi_tiet_id));
    }
}

function onVpChiTietChange(blockId, selectElem) {
    const state = vpBlockState[blockId] || {};
    if (!state.bo_phan_id || !selectElem.value) return;
    const khoi = vpGetKhoi(state.nhom, state.bo_phan_id);
    if (!khoi) return;
    const hotspot = (khoi.hotspots || []).find(h => String(h.chi_tiet_id) === String(selectElem.value));
    if (hotspot) {
        vpSelectHotspot(blockId, state.bo_phan_id, hotspot);
    }
}

function vpClearSelection(blockId) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const state = vpBlockState[blockId] = vpBlockState[blockId] || {};
    state.chi_tiet_id = null;
    block.querySelector('.sel-bo-phan').innerHTML = '';
    block.querySelector('.sel-chi-tiet').innerHTML = '';
    selectComboValue(block.querySelector('.combo-dropdown[data-type="vp-chi-tiet"]'), '');
    vpMarkActive(block, null);
    const bar = block.querySelector('[data-vp-selection]');
    bar.style.display = 'none';
}

// "Th-12" -> ["Th", 12]; also handles old codes like "TS1" / "L(1) - 10".
function vpSplitCode(code) {
    const m = String(code || '').match(/^(.*?)[\s-]*(\d+)\s*$/);
    return m ? [m[1].trim(), parseInt(m[2], 10)] : [String(code || ''), 0];
}

function vpSortedHotspots(khoi) {
    return (khoi.hotspots || []).slice().sort((a, b) => {
        const [pa, na] = vpSplitCode(a.ma_vi_tri);
        const [pb, nb] = vpSplitCode(b.ma_vi_tri);
        return pa.localeCompare(pb) || na - nb || a.chi_tiet_id - b.chi_tiet_id;
    });
}

// Block code shown in the sheet header, e.g. "Th(1)" (PDF "Mã bộ phận").
function vpBlockCode(khoi) {
    const first = vpSortedHotspots(khoi)[0];
    return first ? vpSplitCode(first.ma_vi_tri)[0] : '';
}

function vpRenderTable(block, blockId, khoi) {
    const tbody = block.querySelector('[data-vp-tbody]');
    if (!tbody) return;
    const state = vpBlockState[blockId] || {};
    tbody.innerHTML = '';
    vpSortedHotspots(khoi).forEach(h => {
        const tr = document.createElement('tr');
        tr.dataset.chiTietId = h.chi_tiet_id;
        if (state.chi_tiet_id === h.chi_tiet_id) tr.classList.add('active');
        const code = document.createElement('td');
        code.className = 'vp-td-code';
        code.textContent = h.ma_vi_tri || '';
        const name = document.createElement('td');
        name.textContent = h.label || '';
        if (h.x_pct == null) {
            const note = document.createElement('span');
            note.className = 'vp-td-note';
            note.textContent = 'không có trên hình';
            name.appendChild(note);
        }
        tr.append(code, name);
        tr.addEventListener('click', () => vpSelectHotspot(blockId, khoi.bo_phan_id, h));
        tbody.appendChild(tr);
    });
}

function vpMarkActive(block, chiTietId) {
    const id = chiTietId == null ? null : String(chiTietId);
    block.querySelectorAll('.vp-hotspot').forEach(d => d.classList.toggle('active', d.dataset.chiTietId === id));
    let activeRow = null;
    block.querySelectorAll('[data-vp-tbody] tr').forEach(tr => {
        const on = tr.dataset.chiTietId === id;
        tr.classList.toggle('active', on);
        if (on) activeRow = tr;
    });
    // Keep the selected row visible inside the scrollable table only.
    const wrap = block.querySelector('[data-vp-table-wrap]');
    if (activeRow && wrap) {
        const top = activeRow.offsetTop, bottom = top + activeRow.offsetHeight;
        if (top < wrap.scrollTop + 30) wrap.scrollTop = Math.max(0, top - 30);
        else if (bottom > wrap.scrollTop + wrap.clientHeight) wrap.scrollTop = bottom - wrap.clientHeight;
    }
}
