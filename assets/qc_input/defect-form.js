// Form SP lỗi: thêm/xoá SP, khối bộ phận, dòng lỗi, dropdown tìm kiếm.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

function addDefectProduct(prefill = null, pendingFailed = false, isExisting = !!prefill) {
    if (!masterBoPhan || masterBoPhan.length === 0) {
        alert('Chưa có danh mục Bộ phận cho loại hàng này.');
        return null;
    }
    const container = document.getElementById('defectProducts');
    const productId = nextUiId();
    const displayIndex = baseSpIndex + container.querySelectorAll('.defect-product').length + 1;
    const product = document.createElement('div');
    product.className = 'defect-product';
    product.dataset.productId = productId;
    product.dataset.displayIndex = displayIndex;
    product.dataset.existing = isExisting ? '1' : '0';
    product.dataset.pendingFailed = pendingFailed ? '1' : '0';
    product.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="label mb-0">Sản phẩm lỗi #${displayIndex}</div>
            <button class="btn btn-outline-danger" style="min-height:44px;" onclick="removeDefectProduct(${productId})"><i class="fas fa-trash me-1"></i>Xóa SP</button>
        </div>
        <div class="bo-phan-blocks d-flex flex-column gap-2"></div>
        <div class="text-end mt-2">
            <button class="btn btn-sm btn-primary" onclick="addBoPhanBlock(${productId})"><i class="fas fa-plus me-1"></i>Thêm Bộ phận</button>
        </div>
    `;
    container.appendChild(product);
    const normalized = normalizeProductPrefill(prefill);
    if (normalized && normalized.bo_phan_items && normalized.bo_phan_items.length) {
        normalized.bo_phan_items.forEach(bp => addBoPhanBlock(productId, bp));
    } else {
        addBoPhanBlock(productId);
    }
    ensureQuickComboPosition(product);
    return product;
}

function removeDefectProduct(productId) {
    const product = document.querySelector(`.defect-product[data-product-id="${productId}"]`);
    if (!product) return;
    const container = product.parentNode;
    const nextSibling = product.nextSibling;
    const seq = ctxSeq;
    product.remove();
    renumberDefectProducts();
    renderOutputDisplay();
    // Cho phép hoàn tác trong vài giây thay vì xoá luôn không hỏi.
    showToast('Đã xoá 1 sản phẩm lỗi', {
        duration: 5000,
        actionLabel: 'Hoàn tác',
        onAction: () => {
            if (isStaleCtx(seq) || !container) return;
            container.insertBefore(product, nextSibling && nextSibling.parentNode === container ? nextSibling : null);
            renumberDefectProducts();
            renderOutputDisplay();
        },
    });
}

function addBoPhanBlock(productId, prefill = null) {
    const product = document.querySelector(`.defect-product[data-product-id="${productId}"]`);
    if (!product) return;
    const list = product.querySelector('.bo-phan-blocks');
    const blockId = nextUiId();
    const displayIndex = list.querySelectorAll('.bo-phan-block').length + 1;
    const block = document.createElement('div');
    block.className = 'defect-item bo-phan-block';
    block.dataset.blockId = blockId;
    block.dataset.displayIndex = displayIndex;
    const useVisual = !!(visualPickerData && visualPickerData.has_visual_picker);
    block.innerHTML = useVisual
        ? renderVpBlockHTML(blockId, productId, displayIndex)
        : renderComboBlockHTML(blockId, productId, displayIndex);
    list.appendChild(block);

    if (useVisual) {
        initVpBlock(block, blockId);
        if (prefill && prefill.bo_phan_id) {
            const prefillNhom = vpFindNhomByBoPhanId(prefill.bo_phan_id);
            if (prefillNhom) {
                vpSelectNhom(blockId, prefillNhom);
            }
            vpSelectKhoi(blockId, prefill.bo_phan_id);
            if (prefill.chi_tiet_id) {
                const khoi = vpGetKhoi((vpBlockState[blockId] || {}).nhom, prefill.bo_phan_id);
                const hotspot = khoi ? (khoi.hotspots || []).find(h => h.chi_tiet_id === prefill.chi_tiet_id) : null;
                if (hotspot) {
                    vpSelectHotspot(blockId, prefill.bo_phan_id, hotspot);
                }
            }
        }
    } else {
        initCombo(block);
        if (prefill && prefill.bo_phan_id) {
            selectComboValue(block.querySelector('.combo-dropdown[data-type="bo-phan"]'), String(prefill.bo_phan_id));
            loadChiTietOptions(block, prefill.bo_phan_id, prefill.chi_tiet_id || null);
        }
    }

    if (prefill && prefill.defects && prefill.defects.length) {
        prefill.defects.forEach(d => addDefectItem(blockId, d));
    } else {
        addDefectItem(blockId);
    }
    ensureQuickComboPosition(product);
}

function renderComboBlockHTML(blockId, productId, displayIndex) {
    return `
        <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="label mb-0">Bộ phận #${displayIndex}</div>
            <button class="btn btn-sm btn-outline-secondary" onclick="removeBoPhanBlock(${productId}, ${blockId})">Xóa</button>
        </div>
        <div class="row g-2">
            <div class="col-12">
                <div class="d-flex align-items-center justify-content-between">
                    <label class="label mb-0">Bộ phận</label>
                    <button type="button" class="btn-mic-inline" onclick="startVoiceField('bo_phan', { blockId: ${blockId} })" title="Voice Bộ phận">
                        <i class="fas fa-microphone"></i>
                    </button>
                </div>
                <div class="combo-dropdown" data-type="bo-phan" data-block-id="${blockId}">
                    <button type="button" class="combo-trigger" onclick="toggleCombo(this)">-- Chọn Bộ phận --</button>
                    <div class="combo-panel">
                        <input type="text" class="combo-search" placeholder="Tìm Bộ phận..." oninput="filterCombo(this)">
                        <div class="combo-list"></div>
                    </div>
                    <select class="sel-bo-phan" style="display:none;"></select>
                </div>
            </div>
            <div class="col-12">
                <div class="d-flex align-items-center justify-content-between">
                    <label class="label mb-0">Chi tiết</label>
                    <button type="button" class="btn-mic-inline" onclick="startVoiceField('chi_tiet', { blockId: ${blockId} })" title="Voice Chi tiết">
                        <i class="fas fa-microphone"></i>
                    </button>
                </div>
                <div class="combo-dropdown" data-type="chi-tiet" data-block-id="${blockId}">
                    <button type="button" class="combo-trigger" onclick="toggleCombo(this)">-- Chọn Chi tiết --</button>
                    <div class="combo-panel">
                        <input type="text" class="combo-search" placeholder="Tìm Chi tiết..." oninput="filterCombo(this)">
                        <div class="combo-list"></div>
                    </div>
                    <select class="sel-chi-tiet" style="display:none;"></select>
                </div>
            </div>
        </div>
        <div class="defect-items d-flex flex-column gap-2 mt-2"></div>
        <div class="text-end mt-2">
            <button class="btn btn-sm btn-primary" onclick="addDefectItem(${blockId})"><i class="fas fa-plus me-1"></i>Thêm lỗi</button>
        </div>
    `;
}

function removeBoPhanBlock(productId, blockId) {
    const product = document.querySelector(`.defect-product[data-product-id="${productId}"]`);
    if (!product) return;
    const block = product.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (block) block.remove();
    const blocks = product.querySelectorAll('.bo-phan-block');
    blocks.forEach((b, idx) => {
        b.dataset.displayIndex = idx + 1;
        const label = b.querySelector('.label');
        if (label) label.textContent = `Bộ phận #${idx + 1}`;
    });
    ensureQuickComboPosition(product);
}

function addDefectItem(blockId, prefill = null) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const list = block.querySelector('.defect-items');
    const itemId = nextUiId();
    const nextIndex = list.querySelectorAll('.defect-item').length + 1;
    const item = document.createElement('div');
    item.className = 'defect-item';
    item.dataset.itemId = itemId;
    item.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="label mb-0">Lỗi #${nextIndex}</div>
            <button class="btn btn-sm btn-outline-secondary" onclick="removeDefectItem(${blockId}, ${itemId})">Xóa</button>
        </div>
        <div class="row g-2">
            <div class="col-12">
                <div class="d-flex align-items-center justify-content-between">
                    <label class="label mb-0">Mã lỗi</label>
                    <button type="button" class="btn-mic-inline" onclick="startVoiceField('ma_loi', { itemId: ${itemId} })" title="Voice Mã lỗi">
                        <i class="fas fa-microphone"></i>
                    </button>
                </div>
                <div class="combo-dropdown" data-type="ma-loi" data-item-id="${itemId}">
                    <button type="button" class="combo-trigger" onclick="toggleCombo(this)">-- Chọn Mã lỗi --</button>
                    <div class="combo-panel">
                        <input type="text" class="combo-search" placeholder="Tìm Mã lỗi..." oninput="filterCombo(this)">
                        <div class="combo-list"></div>
                    </div>
                    <select class="sel-ma-loi" style="display:none;" onchange="onMaLoiChange(${itemId}, this)"></select>
                </div>
            </div>
            <div class="col-12">
                <div class="d-flex align-items-center justify-content-between">
                    <label class="label mb-0">Mức độ</label>
                    <button type="button" class="btn-mic-inline" onclick="startVoiceField('muc_do', { itemId: ${itemId} })" title="Voice Mức độ">
                        <i class="fas fa-microphone"></i>
                    </button>
                </div>
                <select class="form-select sel-muc-do"></select>
            </div>
        </div>
    `;
    list.appendChild(item);
    initCombo(item);
    item.querySelector('.sel-muc-do').innerHTML = '<option value="">-- Chọn Mức độ --</option>';

    if (prefill && prefill.ma_loi_id && prefill.mo_ta_loi_id) {
        selectComboValue(item.querySelector('.combo-dropdown[data-type="ma-loi"]'), `${prefill.ma_loi_id}|${prefill.mo_ta_loi_id}`);
        applyMucDoOptions(item, prefill.muc_do || null);
    }
}

function removeDefectItem(blockId, itemId) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const item = block.querySelector(`.defect-item[data-item-id="${itemId}"]`);
    if (item) item.remove();
    const items = block.querySelectorAll('.defect-item');
    items.forEach((it, idx) => {
        const label = it.querySelector('.label');
        if (label) label.textContent = `Lỗi #${idx + 1}`;
    });
    updateQuickComboPositionFromBlock(block);
}

function initCombo(scope) {
    scope.querySelectorAll('.combo-dropdown').forEach(combo => {
        const type = combo.dataset.type;
        if (type === 'bo-phan') {
            const options = masterBoPhan.map(bp => ({ value: String(bp.id), label: bp.ten_bo_phan }));
            setComboOptions(combo, options, '-- Chọn Bộ phận --');
        }
        if (type === 'ma-loi') {
            const options = masterMaLoiOptions.map(opt => ({
                value: `${opt.ma_loi_id}|${opt.mo_ta_loi_id}`,
                label: opt.label
            }));
            setComboOptions(combo, options, '-- Chọn Mã lỗi --');
        }
        if (type === 'chi-tiet') {
            setComboOptions(combo, [], '-- Chọn Chi tiết --');
        }
        if (type === 'vp-chi-tiet') {
            setComboOptions(combo, [], '-- Chọn Mã vị trí --');
        }
    });

    // no-op for voice context in this mode
}

async function onBoPhanChange(blockId, selectElem) {
    const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
    if (!block) return;
    const bpId = selectElem.value;
    await loadChiTietOptions(block, bpId, null);
}

async function loadChiTietOptions(block, bpId, selectedId) {
    if (!bpId) {
        setComboOptions(block.querySelector('.combo-dropdown[data-type="chi-tiet"]'), [], '-- Chọn Chi tiết --');
        return;
    }
    try {
        setComboOptions(block.querySelector('.combo-dropdown[data-type="chi-tiet"]'), [], 'Đang tải...');
        const res = await fetch(`/api/dm/chi-tiet?bo_phan_id=${bpId}`);
        const data = await res.json();
        chiTietOptionsByBlock[block.dataset.blockId] = data.rows || [];
        const options = (data.rows || []).map(ct => ({ value: String(ct.id), label: ct.ten_chi_tiet }));
        setComboOptions(block.querySelector('.combo-dropdown[data-type="chi-tiet"]'), options, '-- Chọn Chi tiết --');
        if (selectedId) {
            selectComboValue(block.querySelector('.combo-dropdown[data-type="chi-tiet"]'), String(selectedId));
        }
    } catch (e) { console.error(e); }
}

function onMaLoiChange(itemId, selectElem) {
    const item = document.querySelector(`.defect-item[data-item-id="${itemId}"]`);
    if (!item) return;
    applyMucDoOptions(item, null);
}

function toggleCombo(btn) {
    const combo = btn.closest('.combo-dropdown');
    const panel = combo.querySelector('.combo-panel');
    closeAllCombos();
    panel.classList.add('open');
    // Do not auto-focus search to avoid auto-opening keyboard on mobile.
}

function closeAllCombos() {
    document.querySelectorAll('.combo-panel.open').forEach(p => p.classList.remove('open'));
}

function filterCombo(inputElem) {
    const combo = inputElem.closest('.combo-dropdown');
    const type = combo.dataset.type;
    const kw = (inputElem.value || '').toLowerCase();
    let list = [];
    if (type === 'bo-phan') {
        list = masterBoPhan.map(bp => ({ value: String(bp.id), label: bp.ten_bo_phan }));
    } else if (type === 'chi-tiet') {
        const blockId = combo.dataset.blockId;
        const raw = chiTietOptionsByBlock[blockId] || [];
        list = raw.map(ct => ({ value: String(ct.id), label: ct.ten_chi_tiet }));
    } else if (type === 'vp-chi-tiet') {
        list = vpGetHotspotOptions(combo.dataset.blockId);
    } else if (type === 'ma-loi') {
        list = masterMaLoiOptions.map(opt => ({ value: `${opt.ma_loi_id}|${opt.mo_ta_loi_id}`, label: opt.label }));
    }
    const filtered = list.filter(o => (o.label || '').toLowerCase().includes(kw));
    setComboOptions(combo, filtered, combo.querySelector('.combo-trigger').textContent || '-- Chọn --', false);
}

function setComboOptions(combo, options, placeholder, resetTrigger = true) {
    if (!combo) return;
    const list = combo.querySelector('.combo-list');
    const sel = combo.querySelector('select');
    const trigger = combo.querySelector('.combo-trigger');
    list.innerHTML = '';
    sel.innerHTML = '';
    combo.dataset.placeholder = placeholder;
    if (resetTrigger) trigger.textContent = placeholder;
    options.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.label;
        sel.appendChild(opt);

        const item = document.createElement('div');
        item.className = 'combo-item';
        item.textContent = o.label;
        item.addEventListener('click', () => {
            sel.value = o.value;
            trigger.textContent = o.label;
            combo.querySelector('.combo-panel').classList.remove('open');
            if (combo.dataset.type === 'bo-phan') {
                onBoPhanChange(combo.dataset.blockId, sel);
            } else if (combo.dataset.type === 'vp-chi-tiet') {
                onVpChiTietChange(combo.dataset.blockId, sel);
            } else if (combo.dataset.type === 'ma-loi') {
                onMaLoiChange(combo.dataset.itemId, sel);
            }
            updateQuickComboPositionFromBlock(combo.closest('.bo-phan-block'));
        });
        list.appendChild(item);
    });
}

function selectComboValue(combo, value) {
    if (!combo) return;
    const sel = combo.querySelector('select');
    const trigger = combo.querySelector('.combo-trigger');
    sel.value = value;
    const option = Array.from(sel.options).find(o => o.value === value);
    trigger.textContent = option ? option.textContent : (combo.dataset.placeholder || '-- Chọn --');
}

function getSelectedComboValue(combo, fallbackSelect) {
    const triggerText = (combo?.querySelector('.combo-trigger')?.textContent || '').trim();
    if (!triggerText || triggerText.startsWith('--')) return '';
    const sel = combo?.querySelector('select') || fallbackSelect;
    return sel?.value || '';
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.combo-dropdown')) {
        closeAllCombos();
    }
});

function applyMucDoOptions(item, prefillValue) {
    const selMucDo = item.querySelector('.sel-muc-do');
    selMucDo.innerHTML = '<option value="">-- Chọn Mức độ --</option>';
    selMucDo.dataset.skip = '';
    const mlVal = item.querySelector('.sel-ma-loi').value;
    if (!mlVal) return;
    const [maId, moTaId] = mlVal.split('|').map(v => parseInt(v));
    const found = masterMaLoiOptions.find(o => o.ma_loi_id === maId && o.mo_ta_loi_id === moTaId);
    const mucDo = found ? found.muc_do : null;
    if (!mucDo || typeof mucDo !== 'object') {
        selMucDo.dataset.skip = '1';
        return;
    }
    const levels = Object.keys(mucDo);
    levels.forEach(level => {
        const opt = document.createElement('option');
        opt.value = level;
        opt.textContent = level;
        selMucDo.appendChild(opt);
    });
    if (prefillValue) {
        selMucDo.value = prefillValue;
    } else if (levels.length === 1) {
        selMucDo.value = levels[0];
    }
}
