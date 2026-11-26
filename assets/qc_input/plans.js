// Khởi động trang, danh sách kế hoạch, chọn kế hoạch, reset trạng thái nhập.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

document.addEventListener('DOMContentLoaded', async () => {
    // Khởi tạo date picker ngày báo cáo
    initReportDatePicker();

    const reworkDateFilter = document.getElementById('reworkDateFilter');
    if (reworkDateFilter) {
        reworkDateFilter.value = reworkDateStr;
    }
    await loadPlans();
    await loadMasterMaLoiOptions();
    refreshQuickComboDropdowns();
    initSpeechRecognition();
    if (getOfflineQueue().length) showOfflineBanner(true);
});

async function loadPlans(options = {}) {
    try {
        const params = new URLSearchParams();
        if (userDonVi) params.append('don_vi', userDonVi);
        if (userBoPhan) {
            params.append('bo_phan', userBoPhan);
        }
        params.append('only_active', 'true');
        const res = await fetch(`/api/prod-plan?${params.toString()}`);
        const data = await res.json();
        availablePlans = data.rows || [];
        renderPlansList();
    } catch (e) {
        console.error(e);
        document.getElementById('loadingPlansMsg').innerText = "Lỗi tải danh sách kế hoạch!";
    }
}

const RECENT_PLANS_KEY = 'qlcl_recent_plans_' + userDonVi + '_' + userBoPhan;
const MAX_RECENT = 3;

function getRecentPlanIds() {
    try { return JSON.parse(localStorage.getItem(RECENT_PLANS_KEY) || '[]'); } catch (e) { return []; }
}
function saveRecentPlanId(planId) {
    try {
        let ids = getRecentPlanIds().filter(id => id !== planId);
        ids.unshift(planId);
        if (ids.length > MAX_RECENT) ids = ids.slice(0, MAX_RECENT);
        localStorage.setItem(RECENT_PLANS_KEY, JSON.stringify(ids));
    } catch (e) {}
}

function renderPlanCard(p) {
    return `
    <div class="card-lite plan-select-card" style="cursor: pointer;" onclick="selectPlan(${Number(p.id)})" data-plan-id="${Number(p.id)}">
        <div class="plan-select-main">
            <div style="flex: 1 1 auto;">
                <div class="plan-select-title">${esc(p.ma_hang || '--')}</div>
                <div class="plan-select-customer">${esc(p.khach_hang || '--')}</div>
            </div>
            <div class="plan-select-badge">${esc(String(p.bo_phan || '--').replace('Tổ ', ''))}</div>
        </div>
        <div class="po-panel">
            <div class="po-panel-title">Danh sách PO & SL</div>
            ${renderPoLines(p.po_info, p.ke_hoach || 'Chưa có PO')}
        </div>
        <div class="plan-select-footer">
            <div>
                <div class="plan-select-date-label">Ngày sản xuất</div>
                <div class="plan-select-date-value">${fmtDate(p.ngay_rc)}</div>
            </div>
            <div class="text-end">
                <div class="plan-select-action">
                    <span>Báo số</span>
                    <i class="fas fa-chevron-right"></i>
                </div>
            </div>
        </div>
    </div>
    `;
}

function renderRecentPlans() {
    const section = document.getElementById('recentPlansSection');
    const container = document.getElementById('recentPlansList');
    if (!section || !container) return;
    const recentIds = getRecentPlanIds();
    const recentPlans = recentIds.map(id => availablePlans.find(p => p.id === id)).filter(Boolean);
    if (!recentPlans.length) { section.style.display = 'none'; return; }
    section.style.display = 'block';
    container.innerHTML = recentPlans.map(p => `
        <div class="card-lite" style="cursor:pointer; padding:0.75rem 1rem; border:1.5px solid #dbeafe; background:linear-gradient(135deg,#eff6ff 0%,#fff 60%); border-radius:14px;" onclick="selectPlan(${p.id})">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:0.75rem;">
                <div style="min-width:0;">
                    <div style="font-weight:800; font-size:1rem; color:#1e40af;">${esc(p.ma_hang || '--')}</div>
                    <div style="font-size:0.78rem; color:#64748b; font-weight:600;">${esc(p.khach_hang || '--')} · ${esc(String(p.bo_phan || '--').replace('Tổ ',''))} · ${fmtDate(p.ngay_rc)}</div>
                </div>
                <i class="fas fa-chevron-right" style="color:#93c5fd; font-size:0.85rem;"></i>
            </div>
        </div>
    `).join('');
}

function renderPlansList() {
    const container = document.getElementById('plansList');
    document.getElementById('loadingPlansMsg').style.display = 'none';
    renderRecentPlans();

    const searchInput = document.getElementById('planSearchInput');
    if (searchInput) searchInput.value = '';

    if (availablePlans.length === 0) {
        container.innerHTML = `
            <div class="text-center p-4 bg-white rounded shadow-sm border">
                <i class="fas fa-clipboard-list fa-3x text-muted mb-3 opacity-50"></i>
                <h6 class="text-muted fw-bold">CHƯA CÓ KẾ HOẠCH NÀO</h6>
                <p class="small text-muted mb-0">Không tìm thấy kế hoạch nào cho ${userDonVi} - ${userBoPhan}</p>
            </div>
        `;
        return;
    }

    container.innerHTML = availablePlans.map(p => renderPlanCard(p)).join('');
}

function filterPlans() {
    const raw = (document.getElementById('planSearchInput')?.value || '').trim().toLowerCase();
    const container = document.getElementById('plansList');
    if (!raw) {
        container.innerHTML = availablePlans.map(p => renderPlanCard(p)).join('');
        return;
    }
    const terms = raw.split(/\s+/);
    const filtered = availablePlans.filter(p => {
        const haystack = [p.ma_hang, p.khach_hang, p.ke_hoach, p.bo_phan, p.loai_hang,
            ...(Array.isArray(p.po_info) ? p.po_info.map(po => po?.po || po?.code || '') : [])
        ].join(' ').toLowerCase();
        return terms.every(t => haystack.includes(t));
    });
    if (!filtered.length) {
        container.innerHTML = `<div class="text-center text-muted my-3"><i class="fas fa-search me-1"></i> Không tìm thấy kế hoạch phù hợp.</div>`;
        return;
    }
    container.innerHTML = filtered.map(p => renderPlanCard(p)).join('');
}

async function syncQtcnPlans(options = {}) {
    try {
        const res = await fetch('/api/prod-plan/sync-qtcn', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            if (!options.silent) {
                alert(data.detail || 'Không thể đồng bộ kế hoạch.');
            }
            return null;
        }
        if (!options.silent) {
            alert(`Đồng bộ xong. Thêm ${data.inserted || 0}, cập nhật ${data.updated || 0}, ngừng hiệu lực ${data.deactivated || 0}, bỏ qua ${data.skipped || 0}.`);
            await loadPlans();
        }
        return data;
    } catch (e) {
        if (!options.silent) {
            alert('Lỗi kết nối máy chủ khi đồng bộ.');
        }
        return null;
    }
}

async function syncFlatLinePlans(options = {}) {
    try {
        const res = await fetch('/api/prod-plan/sync-flat-line', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            if (!options.silent) {
                alert(data.detail || 'Không thể đồng bộ kế hoạch Chuyền bệt.');
            }
            return null;
        }
        if (!options.silent) {
            alert(`Đồng bộ Chuyền bệt xong. Thêm ${data.inserted || 0}, cập nhật ${data.updated || 0}, ngừng hiệu lực ${data.deactivated || 0}, bỏ qua ${data.skipped || 0}.`);
            await loadPlans();
        }
        return data;
    } catch (e) {
        if (!options.silent) {
            alert('Lỗi kết nối máy chủ khi đồng bộ Chuyền bệt.');
        }
        return null;
    }
}

async function selectPlan(planId) {
    if (hasUnsavedData() && !confirm('Bạn đang có dữ liệu chưa lưu. Chuyển kế hoạch sẽ mất dữ liệu này. Tiếp tục?')) return;
    selectedPlanId = planId;
    saveRecentPlanId(planId);
    const plan = availablePlans.find(p => p.id == planId);
    selectedStation = '';
    stationList = [];
    clusterOptions = [];
    selectedLoaiHangId = null;

    document.getElementById('planSelectionArea').style.display = 'none';
    document.getElementById('inputDataArea').style.display = 'block';
    document.getElementById('headerBackBtn').style.visibility = 'visible';
    document.getElementById('footerSave').style.display = 'block';

    document.getElementById('lblSelectedPlanCompact').textContent = formatPlanDisplay(plan);
    document.getElementById('lblSelectedMaHangCompact').textContent = plan.ma_hang || '--';
    document.getElementById('lblSelectedKhachHangCompact').textContent = plan.khach_hang || '--';
    document.getElementById('lblSelectedLoaiHangCompact').textContent = plan.loai_hang || '--';
    document.getElementById('lblSelectedBoPhanCompact').textContent = plan.bo_phan || '--';
    document.getElementById('lblSelectedNgayCompact').textContent = fmtDate(plan.ngay_rc);
    document.getElementById('lblSelectedSanLuongCompact').textContent = fmtNumber(plan.san_luong);

    // Hiển thị ngày báo cáo trong compact header
    const lblDate = document.getElementById('lblReportDateCompact');
    if (lblDate) lblDate.textContent = fmtDate(reportDateStr);

    // Nhận diện kế hoạch từ chuyền treo → ẩn "+1 Đạt"
    const isHangingLine = ['hanging_line','flat_line_sheet'].includes(plan.source_system);
    flatOutput = null;
    const btnPlusDat = document.getElementById('btnPlusDat');
    if (btnPlusDat) {
        btnPlusDat.style.display = isHangingLine ? 'none' : '';
        // Tooltip giải thích khi ẩn (nếu cần debug)
        btnPlusDat.title = isHangingLine
            ? 'Sản lượng lấy tự động từ dashboard sản xuất'
            : '';
    }
    // Hiện/ẩn badge "Chuyền treo"
    const badgeWrap = document.getElementById('hangingBadgeWrap');
    if (badgeWrap) badgeWrap.style.display = isHangingLine ? '' : 'none';
    if (badgeWrap) badgeWrap.querySelector('.hanging-badge').textContent = plan.source_system === 'flat_line_sheet' ? 'Chuyền bệt · BP / 2 giờ' : 'Chuyền treo';

    switchWorkTab(currentWorkTab);

    resetEntryState();
    hlPassedCount = 0;
    setOutputDisplay(0, 0);
    startHlAutoRefresh();
    const seq = bumpCtx();

    try {
        const lhRes = await fetch('/api/dm/loai-hang');
        const lhData = await lhRes.json();
        if (isStaleCtx(seq)) return;
        const lh = lhData.rows.find(l => l.ten_loai === plan.loai_hang);
        if (lh) {
            selectedLoaiHangId = lh.id;
            selectedTargetPercent = lh.target_percent != null ? Number(lh.target_percent) : null;
            renderOutputDisplay();
            await loadProductVisualCatalog(lh.id);
            if (isStaleCtx(seq)) return;
            await loadClusterOptions(lh.id);
            if (isStaleCtx(seq)) return;
            renderStationSelector();
            if (getActiveStation()) {
                await loadExistingEntry();
                await fetchOutputTotal();
                await loadQuickDefectCombos();
                loadQuickDefectCombosToday();
            } else {
                setOutputDisplay(0, 0);
                refreshQuickComboDropdowns();
            }
        } else {
            masterBoPhan = [];
            visualPickerData = null;
            selectedTargetPercent = null;
            clusterOptions = [];
            renderOutputDisplay();
            renderStationSelector();
            quickDefectCombos = [];
            quickDefectCombosToday = [];
            refreshQuickComboDropdowns();
            alert('Cảnh báo: Loại hàng này chưa được định nghĩa trong danh mục master!');
        }
        loadPosSummary();
    } catch (e) { console.error(e); }
}

function hasUnsavedData() {
    const products = document.querySelectorAll('.defect-product');
    for (const p of products) {
        if (p.dataset.existing !== '1') return true;
    }
    return false;
}

// Số SP lỗi mới (mỗi lần "+1 Lỗi" tạo đúng 1 SP) — tính từ DOM thay vì giữ biến đếm riêng
// để không bao giờ lệch với số SP thực tế gửi lên.
function getPendingFailedCount() {
    return document.querySelectorAll('.defect-product[data-pending-failed="1"]:not([data-existing="1"])').length;
}

// Xoá toàn bộ trạng thái nhập liệu đang dở — gọi ở mọi chỗ đổi ngữ cảnh (kế hoạch/cụm/ngày).
function resetEntryState() {
    const container = document.getElementById('defectProducts');
    if (container) container.innerHTML = '';
    chiTietOptionsByBlock = {};
    vpBlockState = {};
    baseSpIndex = 0;
}

let skipUnloadGuard = false;
window.addEventListener('beforeunload', function(e) {
    if (!skipUnloadGuard && hasUnsavedData()) { e.preventDefault(); e.returnValue = ''; }
});

function backToPlanSelection(force = false) {
    if (!force && hasUnsavedData() && !confirm('Bạn đang có dữ liệu chưa lưu. Quay lại sẽ mất dữ liệu này. Tiếp tục?')) return;
    bumpCtx();
    resetEntryState();
    stopHlAutoRefresh();
    document.getElementById('inputDataArea').style.display = 'none';
    document.getElementById('headerBackBtn').style.visibility = 'hidden';
    document.getElementById('planSelectionArea').style.display = 'block';
    selectedPlanId = null;
    selectedStation = '';
    stationList = [];
    clusterOptions = [];
    selectedLoaiHangId = null;
    selectedTargetPercent = null;
    quickDefectCombos = [];
    quickDefectCombosToday = [];
    hlPassedCount = 0;
    setOutputDisplay(0, 0);
    currentWorkTab = 'input';
    switchWorkTab('input');
    document.getElementById('footerSave').style.display = 'none';
    const stationCard = document.getElementById('stationCard');
    if (stationCard) stationCard.style.display = 'none';
    updateInlineStationSelector();
    refreshQuickComboDropdowns();
}

async function loadExistingEntry() {
    if (!selectedPlanId) return;
    const station = getActiveStation();
    if (!station && (stationMode === 'cluster' || stationList.length > 1)) return;
    const seq = ctxSeq;
    try {
        const params = new URLSearchParams({ plan_id: selectedPlanId, date: reportDateStr });
        if (station) params.append('station', station);
        const res = await fetch(`/api/qc/error-log-sp?${params.toString()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (isStaleCtx(seq)) return;
        // Chỉ đọc số thứ tự SP lớn nhất đã lưu để đánh số "#SP" tiếp theo.
        // Không xoá form ở đây — việc reset do resetEntryState() đảm nhiệm khi đổi ngữ cảnh.
        const products = (data.exists && data.data && data.data.defect_products) || [];
        baseSpIndex = products.reduce((mx, p) => Math.max(mx, Number(p.product_no) || 0), 0);
        renumberDefectProducts();
    } catch (e) {
        console.error(e);
    }
}

function renumberDefectProducts() {
    document.querySelectorAll('.defect-product').forEach((p, idx) => {
        p.dataset.displayIndex = idx + 1;
        const label = p.querySelector('.label');
        if (label) label.textContent = `Sản phẩm lỗi #${baseSpIndex + idx + 1}`;
    });
}

async function loadMasterMaLoiOptions() {
    try {
        const params = new URLSearchParams({ date: reportDateStr });
        const res = await fetch(`/api/dm/ma-loi-options?${params.toString()}`);
        const data = await res.json();
        masterMaLoiOptions = data.rows || [];
    } catch (e) { console.error(e); }
}

function isCurrentPlanHangingLine() {
    if (!selectedPlanId) return false;
    const plan = availablePlans.find(p => p.id == selectedPlanId);
    return plan && ['hanging_line','flat_line_sheet'].includes(plan.source_system);
}

function isCurrentPlanFlatLine() {
    return availablePlans.find(p => p.id == selectedPlanId)?.source_system === 'flat_line_sheet';
}
