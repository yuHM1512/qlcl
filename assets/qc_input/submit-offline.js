// Lưu báo cáo lỗi, hàng chờ offline + tự gửi lại. Nạp cuối cùng (chạy code lúc tải trang).
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

// ============ Camera Capture per Block (disabled) ============
const blockImagePaths = {};  // blockId -> image_path (relative)
/*
function onCameraCapture(blockId, inputElem) {
    const file = inputElem.files && inputElem.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        document.getElementById('cameraTriggerArea_' + blockId).style.display = 'none';
        document.getElementById('cameraPreviewArea_' + blockId).style.display = 'block';
        document.getElementById('cameraPreviewImg_' + blockId).src = e.target.result;
        document.getElementById('cameraBadge_' + blockId).style.display = 'none';
        document.getElementById('cameraActions_' + blockId).style.display = 'flex';
        // Clear any previous upload for this block
        delete blockImagePaths[blockId];
        // Auto-upload latest image (no confirm required)
        confirmCameraImage(blockId);
    };
    reader.readAsDataURL(file);
}

async function confirmCameraImage(blockId) {
    const input = document.getElementById('cameraInput_' + blockId);
    const file = input.files && input.files[0];
    if (!file) { alert('Không có hình ảnh để tải lên.'); return; }

    // Show uploading state
    document.getElementById('cameraUploading_' + blockId).style.display = 'flex';
    document.getElementById('cameraActions_' + blockId).style.display = 'none';

    try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch('/api/qc/upload-sp-image', { method: 'POST', body: formData });
        if (!res.ok) throw new Error('Upload failed');
        const data = await res.json();
        blockImagePaths[blockId] = data.image_path;

        // Show success
        document.getElementById('cameraUploading_' + blockId).style.display = 'none';
        document.getElementById('cameraBadge_' + blockId).style.display = 'flex';
        document.getElementById('cameraActions_' + blockId).innerHTML = `
            <button type="button" class="btn btn-outline-secondary btn-sm" onclick="retakeCamera(${blockId})" style="flex:1;"><i class="fas fa-redo me-1"></i>Chá»¥p láº¡i</button>
        `;
        document.getElementById('cameraActions_' + blockId).style.display = 'flex';
        showSpeechToast('Đã lưu hình ảnh!');
    } catch (e) {
        console.error(e);
        document.getElementById('cameraUploading_' + blockId).style.display = 'none';
        document.getElementById('cameraActions_' + blockId).style.display = 'flex';
        alert('Lỗi khi tải hình ảnh lên server.');
    }
}

function retakeCamera(blockId) {
    delete blockImagePaths[blockId];
    const input = document.getElementById('cameraInput_' + blockId);
    input.value = '';
    document.getElementById('cameraPreviewArea_' + blockId).style.display = 'none';
    document.getElementById('cameraTriggerArea_' + blockId).style.display = 'block';
    document.getElementById('cameraBadge_' + blockId).style.display = 'none';
    document.getElementById('cameraActions_' + blockId).innerHTML = `
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="retakeCamera(${blockId})"><i class="fas fa-redo me-1"></i>Chá»¥p láº¡i</button>
    `;
}
*/
let isSubmittingReport = false;

// Thu thập SP lỗi mới từ form. Trả về null nếu thiếu trường (đã cuộn tới + tô đỏ chỗ thiếu).
function collectDefectProducts() {
    const defectProductsEls = document.querySelectorAll('.defect-product');
    const defect_products = [];
    for (let product of defectProductsEls) {
        if (product.dataset.existing === '1') continue;
        const boPhanBlocks = product.querySelectorAll('.bo-phan-block');
        if (!boPhanBlocks || boPhanBlocks.length === 0) {
            flagInvalid(product, 'Mỗi Sản phẩm lỗi cần ít nhất 1 Bộ phận.');
            return null;
        }
        const defects = [];
        for (let block of boPhanBlocks) {
            const selBp = block.querySelector('.sel-bo-phan');
            const selCt = block.querySelector('.sel-chi-tiet');
            const bpId = selBp ? selBp.value : '';
            const ctId = selCt ? selCt.value : '';
            if (!bpId || !ctId) {
                flagInvalid(block, 'Chọn Bộ phận và Chi tiết cho block được tô đỏ.');
                return null;
            }
            const defectItems = block.querySelectorAll('.defect-item');
            if (!defectItems || defectItems.length === 0) {
                flagInvalid(block, 'Mỗi Bộ phận cần ít nhất 1 lỗi.');
                return null;
            }
            for (let item of defectItems) {
                const selMl = item.querySelector('.sel-ma-loi');
                const mlVal = selMl ? selMl.value : '';
                const mucDoElem = item.querySelector('.sel-muc-do');
                const mucDo = mucDoElem ? mucDoElem.value : '';
                if (!mlVal) {
                    flagInvalid(item, 'Chọn Mã lỗi cho lỗi được tô đỏ.');
                    return null;
                }
                if (!mucDo && (!mucDoElem || mucDoElem.dataset.skip !== '1')) {
                    flagInvalid(item, 'Chọn Mức độ cho lỗi được tô đỏ.');
                    return null;
                }
                const parts = mlVal.split('|');
                const maLoiId = parseInt(parts[0]);
                const moTaLoiId = parseInt(parts[1]);
                const selectedMaLoi = masterMaLoiOptions.find(opt => opt.ma_loi_id === maLoiId && opt.mo_ta_loi_id === moTaLoiId) || {};
                defects.push({
                    bo_phan_id: parseInt(bpId),
                    chi_tiet_id: parseInt(ctId),
                    ma_loi_id: maLoiId,
                    mo_ta_loi_id: moTaLoiId,
                    muc_do: mucDo,
                    catalog_id: selectedMaLoi.catalog_id || null,
                    ma_loi_code: selectedMaLoi.ten_ma || null,
                    mo_ta_loi: selectedMaLoi.ten_mo_ta || null,
                    nhom_loi: selectedMaLoi.ten_nhom || null,
                    image_path: blockImagePaths[block.dataset.blockId] || null
                });
            }
        }
        defect_products.push({ defects: defects });
    }
    return defect_products;
}

function clearSubmittedEntry(savedCount, lastSpIndex) {
    if (Number.isFinite(lastSpIndex) && lastSpIndex > 0) baseSpIndex = lastSpIndex;
    else baseSpIndex += savedCount;
    resetEntryStateKeepIndex();
}

// Giống resetEntryState nhưng giữ baseSpIndex (dùng sau khi lưu thành công / đưa vào hàng chờ).
function resetEntryStateKeepIndex() {
    const keep = baseSpIndex;
    resetEntryState();
    baseSpIndex = keep;
}

async function submitReport() {
    if (isSubmittingReport) return;
    const planId = selectedPlanId;
    if (!planId) { alert('Vui lòng chọn Kế hoạch!'); return; }
    if (!ensureStationSelected()) return;
    const station = getActiveStation();

    const defect_products = collectDefectProducts();
    if (!defect_products) return;
    if (defect_products.length === 0) {
        showToast('Chưa có Sản phẩm lỗi mới để lưu.', { type: 'warn' });
        return;
    }
    // Sang ngày mới mà vẫn đang theo "hôm nay" → hỏi trước khi ghi vào ngày cũ.
    if (reportDateFollowsToday && reportDateStr !== todayStr()
        && !confirm(`Đã sang ngày ${fmtDate(todayStr())}. Vẫn lưu cho ngày ${fmtDate(reportDateStr)}?`)) {
        return;
    }
    const payload = {
        plan_id: parseInt(planId),
        date: reportDateStr,
        station: station,
        defect_products: defect_products,
        pending_failed_count: getPendingFailedCount(),
        append_only: true,
        client_request_id: newRequestId()
    };

    const btn = document.getElementById('btnSubmitReport');
    const originalBtnHtml = btn.innerHTML;
    const restoreBtn = () => {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
        btn.style.background = '';
    };
    isSubmittingReport = true;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i> ĐANG LƯU...';

    try {
        const res = await fetch('/api/qc/error-log-sp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            const data = await res.json().catch(() => ({}));
            btn.innerHTML = '<i class="fas fa-check me-2"></i> THÀNH CÔNG!';
            btn.style.background = '#10b981';
            clearSubmittedEntry(defect_products.length, Number(data.last_sp_index));
            await fetchOutputTotal();
            loadPosSummary();
            loadQuickDefectCombos();
            loadQuickDefectCombosToday();
            setTimeout(restoreBtn, 800);
        } else {
            const err = await res.json().catch(() => ({}));
            if (res.status === 409) {
                alert(err.detail || 'Kế hoạch đã bị đóng bởi quản lý. Vui lòng chọn kế hoạch khác.');
                backToPlanSelection(true);
            } else if (res.status >= 500) {
                // Lỗi máy chủ tạm thời → đưa vào hàng chờ, tự gửi lại sau (an toàn nhờ client_request_id).
                queueOfflinePayload(payload, defect_products.length);
            } else {
                showToast('Lỗi: ' + (err.detail || 'Không thể lưu.'), { type: 'error', duration: 5000 });
            }
            restoreBtn();
        }
    } catch (e) {
        // Mất mạng (hoặc mất response): request có thể đã tới server — client_request_id giúp
        // lần gửi lại không bị ghi trùng.
        console.error(e);
        queueOfflinePayload(payload, defect_products.length);
        restoreBtn();
    } finally {
        isSubmittingReport = false;
    }
}

function queueOfflinePayload(payload, savedCount) {
    savePayloadOffline(payload);
    // Xoá form ngay để QC không bấm lưu lại lần nữa (nguyên nhân ghi trùng trước đây).
    clearSubmittedEntry(savedCount, NaN);
    showToast('Mất kết nối — đã lưu tạm trên máy, sẽ tự gửi khi có mạng.', { type: 'warn', duration: 5000 });
}

// ========== Offline retry ==========
// Key theo mã NV để tablet dùng chung không gửi bản ghi của QC trước dưới tên QC sau.
const OFFLINE_QUEUE_KEY = 'qlcl_offline_queue:' + (pageContext.ma_nv || 'unknown');
const LEGACY_OFFLINE_QUEUE_KEY = 'qlcl_offline_queue';
let isRetryingOfflineQueue = false;

// Hàng chờ cũ (trước khi tách theo mã NV, chưa có client_request_id) → chuyển sang key mới.
(function migrateLegacyOfflineQueue() {
    try {
        const legacy = JSON.parse(localStorage.getItem(LEGACY_OFFLINE_QUEUE_KEY) || '[]');
        if (!legacy.length) return;
        if (!confirm(`Máy này còn ${legacy.length} lần lưu lỗi chưa gửi từ phiên trước (không rõ QC nào nhập).\n\nOK = gửi dưới tài khoản của bạn\nHủy = bỏ các bản ghi này`)) {
            localStorage.removeItem(LEGACY_OFFLINE_QUEUE_KEY);
            return;
        }
        const current = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || '[]');
        legacy.forEach(item => {
            if (item && item.payload && !item.payload.client_request_id) {
                item.payload.client_request_id = newRequestId();
            }
        });
        localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(current.concat(legacy)));
        localStorage.removeItem(LEGACY_OFFLINE_QUEUE_KEY);
    } catch (e) { console.error(e); }
})();

function savePayloadOffline(payload) {
    try {
        const queue = getOfflineQueue();
        if (!queue.some(item => item.payload && item.payload.client_request_id === payload.client_request_id)) {
            queue.push({ payload, savedAt: new Date().toISOString() });
        }
        localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
    } catch (e) { console.error('Không lưu được offline:', e); }
    showOfflineBanner(true);
}

function getOfflineQueue() {
    try { return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || '[]'); } catch (e) { return []; }
}

function clearOfflineQueue() {
    try { localStorage.removeItem(OFFLINE_QUEUE_KEY); } catch (e) {}
    showOfflineBanner(false);
}

function showOfflineBanner(show) {
    let banner = document.getElementById('offlineBanner');
    if (show) {
        const count = getOfflineQueue().length;
        if (!count) { if (banner) banner.hidden = true; return; }
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'offlineBanner';
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:1100;background:#fbbf24;color:#78350f;text-align:center;padding:8px 16px;font-size:0.88rem;font-weight:700;display:flex;align-items:center;justify-content:center;gap:8px;';
            document.body.appendChild(banner);
        }
        banner.hidden = false;
        const busy = isRetryingOfflineQueue;
        banner.innerHTML = `<i class="fas fa-wifi" style="opacity:0.6;"></i> Có ${count} lần lưu đang chờ gửi <button onclick="retryOfflineQueue()" ${busy ? 'disabled' : ''} style="background:#78350f;color:#fef3c7;border:none;border-radius:8px;padding:6px 14px;min-height:40px;font-weight:700;font-size:0.85rem;margin-left:6px;cursor:pointer;">${busy ? 'Đang gửi...' : 'Gửi lại'}</button>`;
    } else {
        if (banner) banner.hidden = true;
    }
}

async function retryOfflineQueue() {
    if (isRetryingOfflineQueue) return;
    const queue = getOfflineQueue();
    if (!queue.length) { showOfflineBanner(false); return; }
    isRetryingOfflineQueue = true;
    showOfflineBanner(true);
    const MAX_SERVER_ERROR_ATTEMPTS = 5;
    const doneIds = new Set();      // đã gửi xong hoặc bị từ chối → bỏ khỏi hàng chờ
    const failedIds = new Set();    // lỗi 5xx → tăng số lần thử
    const rejected = [];
    let sent = 0;
    try {
        for (const item of queue) {
            if (item.payload && !item.payload.client_request_id) item.payload.client_request_id = newRequestId();
            const rid = item.payload && item.payload.client_request_id;
            try {
                const res = await fetch('/api/qc/error-log-sp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(item.payload)
                });
                if (res.ok) {
                    sent += 1;
                    doneIds.add(rid);
                } else if (res.status >= 500) {
                    if ((item.attempts || 0) + 1 >= MAX_SERVER_ERROR_ATTEMPTS) {
                        doneIds.add(rid);
                        rejected.push(`Máy chủ lỗi ${res.status} sau ${MAX_SERVER_ERROR_ATTEMPTS} lần thử`);
                    } else {
                        failedIds.add(rid);
                    }
                } else if (res.status !== 401) {
                    // 4xx (kế hoạch đã đóng, dữ liệu không hợp lệ...) → gửi lại cũng không được, bỏ khỏi hàng chờ.
                    const err = await res.json().catch(() => ({}));
                    rejected.push(err.detail || `Lỗi ${res.status}`);
                    doneIds.add(rid);
                }
                // 401 (hết phiên) / lỗi mạng → giữ nguyên để thử lại sau
            } catch (e) { /* mất mạng → giữ lại */ }
        }
    } finally {
        isRetryingOfflineQueue = false;
    }
    // Đọc lại hàng chờ hiện tại: trong lúc gửi, QC có thể vừa lưu thêm bản mới vào hàng chờ.
    const latest = getOfflineQueue()
        .filter(item => !doneIds.has(item.payload && item.payload.client_request_id))
        .map(item => {
            const rid = item.payload && item.payload.client_request_id;
            return failedIds.has(rid) ? { ...item, attempts: (item.attempts || 0) + 1 } : item;
        });
    if (latest.length) {
        try { localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(latest)); } catch (e) {}
        showOfflineBanner(true);
    } else {
        clearOfflineQueue();
    }
    if (rejected.length) {
        alert(`Có ${rejected.length} lần lưu bị máy chủ từ chối và đã bỏ khỏi hàng chờ:\n- ${rejected.join('\n- ')}`);
    } else if (sent) {
        showToast(`Đã gửi ${sent} lần lưu đang chờ`, { type: 'success' });
    }
    if (sent && selectedPlanId) {
        await fetchOutputTotal();
        loadExistingEntry();
        loadPosSummary();
    }
}

window.addEventListener('online', () => {
    if (getOfflineQueue().length) retryOfflineQueue();
});
// Còn hàng chờ từ lần mở trước → hiện banner và thử gửi.
if (getOfflineQueue().length) {
    showOfflineBanner(true);
    if (navigator.onLine) setTimeout(retryOfflineQueue, 2000);
}
