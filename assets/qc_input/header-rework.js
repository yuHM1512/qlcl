// Đổi ngày báo cáo, định dạng hiển thị, tab Nhập liệu/Rework, nút back + đăng xuất.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

async function onReportDateChange(value, opts = {}) {
    if (!value) return;
    const inp = document.getElementById('reportDateInput');
    if (value === reportDateStr) {
        // Không đổi ngày (VD bấm "Về hôm nay" khi đang ở hôm nay) → không xoá dữ liệu đang nhập.
        reportDateFollowsToday = value === todayStr();
        updateDateWarning();
        return;
    }
    if (!opts.skipConfirm && hasUnsavedData()
        && !confirm('Bạn đang có sản phẩm lỗi chưa lưu. Đổi ngày sẽ mất dữ liệu này. Tiếp tục?')) {
        if (inp) inp.value = reportDateStr;
        return;
    }
    reportDateStr = value;
    reworkDateStr = value;
    reportDateFollowsToday = value === todayStr();
    updateDateWarning();
    const seq = bumpCtx();
    resetEntryState();
    try {
        await loadMasterMaLoiOptions();
        if (selectedLoaiHangId) {
            await loadProductVisualCatalog(selectedLoaiHangId);
        }
    } catch (e) {
        console.error(e);
        showToast('Không tải được danh mục lỗi theo ngày báo cáo. Vui lòng thử lại.', { type: 'error' });
    }
    if (isStaleCtx(seq)) return;
    // Cập nhật label trong compact plan header (nếu đang có kế hoạch được chọn)
    const lbl = document.getElementById('lblReportDateCompact');
    if (lbl) lbl.textContent = fmtDate(value);
    // Reload dữ liệu nếu đang ở màn hình nhập liệu
    if (document.getElementById('inputDataArea').style.display !== 'none' && selectedPlanId) {
        const station = getActiveStation();
        if (station || stationList.length === 0) {
            loadExistingEntry();
            fetchOutputTotal();
            fetchHangingOutput();
        }
        if (currentWorkTab === 'rework') fetchInlineReworkData();
        loadPosSummary();
        loadQuickDefectCombos();
        loadQuickDefectCombosToday();
    }
}

async function loadProductVisualCatalog(loaiHangId) {
    const params = new URLSearchParams({
        loai_hang_id: String(loaiHangId),
        date: reportDateStr,
    });
    const [bpRes, vpRes] = await Promise.all([
        fetch(`/api/dm/bo-phan?${params.toString()}`),
        fetch(`/api/qc/visual-picker?${params.toString()}`),
    ]);
    if (!bpRes.ok || !vpRes.ok) {
        throw new Error('Không thể tải danh mục vị trí theo ngày báo cáo.');
    }
    const bpData = await bpRes.json();
    const vpData = await vpRes.json();
    masterBoPhan = bpData.rows || [];
    visualPickerData = vpData && vpData.has_visual_picker ? vpData : null;
    vpBlockState = {};
    chiTietOptionsByBlock = {};
}

function resetReportDateToToday() {
    const today = todayStr();
    const inp = document.getElementById('reportDateInput');
    if (inp) inp.value = today;
    onReportDateChange(today);
}

function fmtDate(val) {
    if (!val) return '--';
    try {
        const d = new Date(val);
        if (isNaN(d.getTime())) return '--';
        return d.toLocaleDateString('vi-VN');
    } catch (e) {
        return '--';
    }
}

function fmtNumber(val) {
    const num = Number(val);
    return Number.isFinite(num) ? num.toLocaleString('vi-VN') : '--';
}

function formatPlanDisplay(plan) {
    if (!plan) return '--';
    const parts = [];
    if (plan.ma_hang) parts.push(plan.ma_hang);
    if (plan.ngay_rc) parts.push(fmtDate(plan.ngay_rc));
    if (plan.san_luong != null && plan.san_luong !== '') {
        const num = Number(plan.san_luong);
        parts.push(Number.isFinite(num) ? num.toLocaleString('vi-VN') : plan.san_luong);
    }
    if (parts.length >= 2) return parts.join(' - ');
    return plan.ke_hoach || '--';
}

function normalizePoInfo(poInfo) {
    return Array.isArray(poInfo) ? poInfo : [];
}

function formatSpIndex(index) {
    if (!index && index !== 0) return '--';
    return String(index).padStart(2, '0');
}

function renderPoLines(poInfo, emptyText = 'Chưa có PO') {
    const items = normalizePoInfo(poInfo);
    if (!items.length) {
        return `<div class="text-muted small">${esc(emptyText)}</div>`;
    }
    return items.map(item => {
        if (item && typeof item === 'object') {
            const po = item.po || item.code || item.name || '--';
            const qty = item.quantity != null && item.quantity !== '' ? fmtNumber(item.quantity) : '--';
            return `<div class="po-line"><span class="po-code">${esc(po)}</span><span class="po-qty">${esc(qty)}</span></div>`;
        }
        return `<div class="po-line"><span class="po-code">${esc(String(item || '').trim())}</span><span class="po-qty">--</span></div>`;
    }).join('');
}

function switchWorkTab(tab) {
    currentWorkTab = tab === 'rework' ? 'rework' : 'input';
    const isRework = currentWorkTab === 'rework';
    const qcPane = document.getElementById('qcInputPane');
    const reworkPane = document.getElementById('reworkPane');
    const tabInput = document.getElementById('tabQcInput');
    const tabRework = document.getElementById('tabRework');
    const footerSave = document.getElementById('footerSave');
    if (qcPane) qcPane.style.display = isRework ? 'none' : '';
    if (reworkPane) reworkPane.style.display = isRework ? 'block' : 'none';
    if (tabInput) tabInput.classList.toggle('active', !isRework);
    if (tabRework) tabRework.classList.toggle('active', isRework);
    if (footerSave) footerSave.style.display = isRework ? 'none' : 'block';
    if (isRework) {
        fetchInlineReworkData();
    }
}


function renderInlineReworkData(rows) {
    const container = document.getElementById('reworkInlineDataArea');
    if (!container) return;
    container.innerHTML = '';

    if (!rows || rows.length === 0) {
        container.innerHTML = `
            <div class="text-center my-4 p-4 bg-white rounded shadow-sm border">
                <i class="fas fa-check-circle fa-3x text-success mb-3 opacity-75"></i>
                <h6 class="text-muted fw-bold">CHƯA CÓ SẢN PHẨM LỖI</h6>
                <p class="small text-muted mb-0">Kế hoạch này chưa có sản phẩm lỗi cần kiểm lại.</p>
            </div>
        `;
        return;
    }

    const list = document.createElement('div');
    list.className = 'd-flex flex-column gap-3';

    rows.forEach(r => {
        const card = document.createElement('div');
        card.id = `inline-row-${r.error_log_sp_id}-${r.sp_index}`;
        card._row = r;
        fillInlineReworkCard(card, r);
        list.appendChild(card);
    });

    container.appendChild(list);
}

function fillInlineReworkCard(card, r) {
        const done = !!r.rework_done;
        card.className = `rework-card ${done ? 'done' : 'pending'}`;

        const statusHtml = done
            ? `<span class="status-pill status-ok">Đã sửa</span>`
            : `<span class="status-pill status-pending">Chưa sửa</span>`;

        const btnHtml = done
            ? `<button class="btn btn-sm btn-outline-secondary btn-verify" onclick="updateInlineRework(${r.error_log_sp_id}, ${r.sp_index}, false)"><i class="fas fa-undo me-1"></i> Hoàn tác</button>`
            : `<button class="btn btn-sm btn-success btn-verify" onclick="updateInlineRework(${r.error_log_sp_id}, ${r.sp_index}, true)"><i class="fas fa-check me-1"></i> Xác nhận</button>`;

        const defects = (r.defect_list || []).filter(Boolean);
        const defectHtml = defects.length
            ? defects.map(d => `<div class="defect-item">${esc(d)}</div>`).join('')
            : `<div class="defect-item text-muted">Chưa có mô tả lỗi.</div>`;

        card.innerHTML = `
            <div class="action-row">
                <span class="sp-tag">#SP${formatSpIndex(r.sp_index)}</span>
                ${statusHtml}
            </div>
            <div class="meta-grid">
                <div class="meta-label">Kế hoạch</div>
                <div><strong>${esc(r.ke_hoach || '--')}</strong></div>
                <div class="meta-label">Mã hàng</div>
                <div>${esc(r.ma_hang || '--')}</div>
                <div class="meta-label">Lỗi</div>
                <div class="defect-list">${defectHtml}</div>
            </div>
            <div class="action-row">
                <div class="text-muted small">Tổng lỗi: <strong>${Number(r.defect_items) || 0}</strong></div>
                ${btnHtml}
            </div>
        `;
}

async function fetchInlineReworkData() {
    const container = document.getElementById('reworkInlineDataArea');
    if (!container) return;
    if (!selectedPlanId) {
        container.innerHTML = `
            <div class="text-center my-4 p-4 bg-white rounded shadow-sm border">
                <i class="fas fa-clipboard-check fa-3x text-muted mb-3 opacity-50"></i>
                <p class="small text-muted mb-0">Chọn kế hoạch để tải danh sách kiểm lại.</p>
            </div>
        `;
        return;
    }
    container.innerHTML = `
        <div class="text-center text-muted my-5">
            <i class="fas fa-spinner fa-spin fa-2x mb-3"></i>
            <p>Đang tải dữ liệu kiểm lại...</p>
        </div>
    `;
    try {
        const seq = ++inlineReworkReqSeq;
        const params = new URLSearchParams({ date_str: reworkDateStr, plan_id: selectedPlanId });
        const station = getActiveStation();
        if (station) params.append('station', station);
        const res = await fetch(`/api/qc/rework-2?${params.toString()}`);
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        if (seq !== inlineReworkReqSeq) return;
        renderInlineReworkData(data.rows || []);
    } catch (e) {
        console.error(e);
        container.innerHTML = `
            <div class="text-center text-danger my-5">
                <i class="fas fa-exclamation-triangle fa-2x mb-3"></i>
                <p>Lỗi tải dữ liệu kiểm lại. Vui lòng thử lại.</p>
            </div>
        `;
    }
}

function onReworkDateChange(value) {
    reworkDateStr = value || reportDateStr;
    if (currentWorkTab === 'rework') {
        fetchInlineReworkData();
    }
}

async function updateInlineRework(logId, spIndex, done) {
    const card = document.getElementById(`inline-row-${logId}-${spIndex}`);
    const btn = card ? card.querySelector('.btn-verify') : null;
    if (btn) {
        if (btn.disabled) return; // chặn bấm đúp
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Đang lưu';
    }
    try {
        const res = await fetch(`/api/qc/rework-2/${logId}/${spIndex}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rework_done: done })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Update failed');
        }
        // Cập nhật đúng thẻ vừa bấm, không tải lại cả danh sách (giữ vị trí cuộn).
        if (card && card._row) {
            card._row.rework_done = done;
            fillInlineReworkCard(card, card._row);
        } else {
            await fetchInlineReworkData();
        }
        fetchOutputTotal(); // số "lỗi chưa sửa" ảnh hưởng tổng kiểm của chuyền treo/bệt
    } catch (e) {
        console.error(e);
        showToast('Lỗi khi cập nhật trạng thái kiểm lại: ' + e.message, { type: 'error', duration: 4000 });
        if (card && card._row) fillInlineReworkCard(card, card._row);
    }
}

// Nút back trên header: đang nhập liệu → về danh sách kế hoạch; còn lại → trang chủ.
// (Trước đây trỏ /qc, nhưng với role QC /qc lại redirect về chính trang này.)
function onHeaderBack(event) {
    if (document.getElementById('inputDataArea').style.display !== 'none') {
        if (event) event.preventDefault();
        backToPlanSelection();
        return false;
    }
    return true;
}

async function logout() {
    const msg = hasUnsavedData()
        ? 'Bạn đang có dữ liệu chưa lưu. Đăng xuất sẽ mất dữ liệu này. Tiếp tục?'
        : 'Đăng xuất khỏi tài khoản?';
    if (!confirm(msg)) return;
    skipUnloadGuard = true;
    try {
        const res = await fetch('/logout', { method: 'POST' });
        if (res.redirected) window.location.href = res.url;
        else window.location.href = '/login';
    } catch (e) {
        window.location.href = '/login';
    }
}
