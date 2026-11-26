// Ngữ cảnh trang, tiện ích dùng chung (esc, toast, ngày VN), biến trạng thái toàn cục.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

const pageContextEl = document.getElementById('pageContext');
const pageContext = pageContextEl ? JSON.parse(pageContextEl.textContent || '{}') : {};

// ========== Tiện ích dùng chung ==========
// Escape chuỗi trước khi chèn vào innerHTML (dữ liệu kế hoạch đến từ Google Sheets / chuyền treo / QTCN).
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

// Ngày hôm nay theo giờ Việt Nam, không phụ thuộc múi giờ thiết bị.
function todayVN() {
    return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(new Date());
}

function newRequestId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
    return Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
}

let _uiIdSeq = 0;
function nextUiId() {
    _uiIdSeq += 1;
    return Date.now() * 1000 + (_uiIdSeq % 1000);
}

// Mỗi lần đổi kế hoạch / cụm / ngày → tăng ctxSeq; response của ngữ cảnh cũ bị bỏ qua.
let ctxSeq = 0;
function bumpCtx() {
    ctxSeq += 1;
    if (typeof hideToast === 'function') hideToast();
    return ctxSeq;
}
function isStaleCtx(seq) { return seq !== ctxSeq; }

// Toast nhỏ ở cuối màn hình, có thể kèm nút hành động (VD: Hoàn tác).
let _toastTimer = null;
function showToast(message, opts = {}) {
    let el = document.getElementById('appToast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'appToast';
        el.className = 'app-toast';
        document.body.appendChild(el);
    }
    el.className = `app-toast show ${opts.type || ''}`;
    el.innerHTML = `<span>${esc(message)}</span>`;
    if (opts.actionLabel && typeof opts.onAction === 'function') {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = opts.actionLabel;
        btn.onclick = () => { hideToast(); opts.onAction(); };
        el.appendChild(btn);
    }
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(hideToast, opts.duration || 3000);
}
function hideToast() {
    const el = document.getElementById('appToast');
    if (el) el.classList.remove('show');
}

// Đánh dấu trường thiếu: cuộn tới + viền đỏ, thay cho alert() không chỉ chỗ.
function flagInvalid(el, message) {
    if (!el) { showToast(message, { type: 'error' }); return; }
    const target = el.closest('.bo-phan-block, .defect-item, .defect-product') || el;
    target.classList.add('field-invalid');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => target.classList.remove('field-invalid'), 2500);
    showToast(message, { type: 'error' });
}
const userDonVi = pageContext.don_vi || "";
const userBoPhan = pageContext.bo_phan || "";
const userStationsRaw = pageContext.station || [];
const isFlexibleQcUnit = userDonVi === 'XNV2';
const stationOptions = ["QC kiểm thành phẩm", "QC vỏ", "QC trước seam", "QC sau seam"];

let availablePlans = [];
let masterBoPhan = [];
let masterMaLoiOptions = [];
let chiTietOptionsByBlock = {};
let selectedPlanId = null;
let visualPickerData = null;     // { has_visual_picker, nhoms: [...] } when loại hàng đã số hoá
let vpBlockState = {};           // blockId -> { nhom, bo_phan_id }
let outputTotal = 0;
let outputFailed = 0;
let outputReworked = 0;
let hlPassedCount = 0;
let flatOutput = null;
let hlAutoRefreshTimer = null;
let selectedTargetPercent = null;
// Thứ tự các request đọc/ghi số đã kiểm — chỉ áp dụng kết quả của request mới nhất,
// tránh số "nhảy lùi" khi response về không theo thứ tự trên wifi chậm.
let outputReqSeq = 0;
let inlineReworkReqSeq = 0;
let baseSpIndex = 0;
let currentWorkTab = 'input';
let recognition = null;
let isListening = false;
let voiceTarget = null;
let selectedStation = '';
let stationList = [];
let stationMode = isFlexibleQcUnit ? 'cluster' : 'legacy';
let selectedLoaiHangId = null;
let clusterOptions = [];
let quickDefectCombos = [];
let quickDefectCombosToday = [];
let quickComboMode = 'history';

// Ngày báo cáo — mặc định hôm nay (giờ VN), có thể đổi qua picker
function todayStr() {
    return todayVN();
}
let reportDateStr = todayStr();
let reworkDateStr = reportDateStr;
// Ngày "hôm nay" tại thời điểm QC đang theo — dùng để tự chuyển ngày khi để máy qua đêm.
let reportDateFollowsToday = true;

// Khởi tạo giá trị cho input date picker
function initReportDatePicker() {
    const inp = document.getElementById('reportDateInput');
    if (inp) inp.value = reportDateStr;
    updateDateWarning();
}

function updateDateWarning() {
    const banner = document.getElementById('dateWarningBanner');
    if (!banner) return;
    const isToday = reportDateStr === todayStr();
    banner.style.display = isToday ? 'none' : 'flex';
    const txt = document.getElementById('dateWarningText');
    if (txt) txt.textContent = fmtDate(reportDateStr);
}

// Khi màn hình được mở lại (tablet để qua đêm), nếu QC đang theo "hôm nay"
// mà ngày đã đổi → tự chuyển sang ngày mới (nếu không có dữ liệu chưa lưu).
function syncReportDateWithToday() {
    const today = todayStr();
    if (reportDateFollowsToday && reportDateStr !== today) {
        if (hasUnsavedData()) {
            updateDateWarning();
            showToast('Đã sang ngày mới. Lưu dữ liệu đang nhập rồi bấm "Về hôm nay".', { type: 'warn', duration: 6000 });
            return;
        }
        const inp = document.getElementById('reportDateInput');
        if (inp) inp.value = today;
        onReportDateChange(today, { skipConfirm: true });
        showToast(`Đã chuyển ngày báo cáo sang ${fmtDate(today)}`, { type: 'warn', duration: 4000 });
    } else {
        updateDateWarning();
    }
}
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncReportDateWithToday();
});
window.addEventListener('focus', syncReportDateWithToday);
