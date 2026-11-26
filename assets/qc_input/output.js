// Số đã kiểm: +1 Đạt / +1 Lỗi / hoàn tác, chuyền treo, chuyền bệt.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

function renderOutputDisplay() {
    const totalElem = document.getElementById('lblOutputTotal');
    const passedElem = document.getElementById('lblOutputPassed');
    const failedElem = document.getElementById('lblOutputFailed');
    const rateElem = document.getElementById('lblDefectRate');
    const rateMetaElem = document.getElementById('lblDefectRateMeta');
    const rateBox = document.getElementById('defectRateBox');

    let passed, failed, total, rate;
    if (isCurrentPlanFlatLine()) {
        // Tổ sync: Tổng kiểm = Tổng đạt (sync) + lỗi CHƯA sửa. Cuối ngày sửa hết → = Tổng đạt.
        // "Tổng lỗi" vẫn đếm toàn bộ lỗi phát sinh; tỉ lệ = tổng lỗi / tổng kiểm.
        passed = flatOutput?.available ? flatOutput.qty : null;
        failed = flatOutput?.records === 0 ? null : (flatOutput?.defects ?? 0);
        const unreworked = Math.max(0, (flatOutput?.defects ?? 0) - (flatOutput?.reworked ?? 0));
        total = passed == null ? null : passed + unreworked;
        rate = total > 0 && failed != null ? failed / total * 100 : null;
    } else if (isCurrentPlanHangingLine()) {
        passed = hlPassedCount || 0;
        failed = outputFailed || 0;
        const unreworked = Math.max(0, failed - (outputReworked || 0));
        total = passed + unreworked;
        rate = total > 0 ? (failed / total) * 100 : 0;
    } else {
        passed = Math.max(0, (outputTotal || 0) - (outputFailed || 0));
        failed = outputFailed || 0;
        total = outputTotal || 0;
        rate = total > 0 ? (failed / total) * 100 : 0;
    }

    if (totalElem) totalElem.textContent = total ?? '—';
    if (passedElem) passedElem.textContent = passed ?? '—';
    if (failedElem) failedElem.textContent = failed ?? '—';
    if (rateElem) rateElem.textContent = rate == null ? '—' : `${rate.toFixed(2)}%`;
    if (rateBox) rateBox.className = 'defect-rate-chip';
    if (rateElem) rateElem.className = 'defect-rate-chip-value';
    if (rate == null) {
        if (rateMetaElem) rateMetaElem.textContent = total > 0 ? 'Chưa có ghi nhận QC cho ngày báo cáo' : 'Chưa có sản lượng BP dương cho ngày báo cáo';
    } else if (selectedTargetPercent != null) {
        const isPass = rate <= selectedTargetPercent;
        if (rateBox) rateBox.classList.add(isPass ? 'good' : 'bad');
        if (rateElem) rateElem.classList.add(isPass ? 'good' : 'bad');
        if (rateMetaElem) {
            rateMetaElem.textContent = `${isPass ? 'Đạt' : 'Không đạt'} • Mục tiêu ${Number(selectedTargetPercent).toFixed(2)}%`;
        }
    } else if (rateMetaElem) {
        rateMetaElem.textContent = 'Chưa có target';
    }
}

function setOutputDisplay(total, failed, reworked) {
    outputTotal = total || 0;
    outputFailed = failed || 0;
    outputReworked = reworked || 0;
    renderOutputDisplay();
}

function fmtSyncTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const hm = d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    const sameDay = d.toDateString() === new Date().toDateString();
    return sameDay ? hm : `${hm} ${d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })}`;
}

// Dòng nhỏ dưới ô số: nguồn số chuyền treo + giờ cập nhật + nút Làm mới (chỉ chuyền treo, không phải chuyền bệt).
function renderHangingOutputMeta(data, failed) {
    const wrap = document.getElementById('hlOutputMeta');
    const text = document.getElementById('hlOutputMetaText');
    if (!wrap || !text) return;
    const show = isCurrentPlanHangingLine() && !isCurrentPlanFlatLine();
    wrap.style.display = show ? '' : 'none';
    if (!show) return;
    wrap.classList.remove('warn');
    if (failed) {
        wrap.classList.add('warn');
        text.textContent = 'Không đọc được sản lượng chuyền treo';
        return;
    }
    if (!data) { text.textContent = ''; return; }
    const at = fmtSyncTime(data.synced_at);
    if (data.source === 'live') {
        text.textContent = `Sản lượng MES · cập nhật ${at}`;
    } else if (data.live_error) {
        wrap.classList.add('warn');
        text.textContent = at ? `Không kết nối được chuyền treo · số lưu lúc ${at}` : 'Không kết nối được chuyền treo';
    } else {
        text.textContent = at ? `Sản lượng chuyền treo gửi lúc ${at}` : 'Chuyền treo chưa gửi sản lượng ngày này';
    }
}

async function fetchHangingOutput(options = {}) {
    if (!selectedPlanId || !isCurrentPlanHangingLine()) return;
    const planId = selectedPlanId, day = reportDateStr;
    try {
        const params = new URLSearchParams({ plan_id: selectedPlanId, date: reportDateStr });
        if (options.refresh) params.append('refresh', 'true');
        const res = await fetch(`/api/qc/hanging-output?${params.toString()}`);
        const data = await res.json();
        if (selectedPlanId != planId || reportDateStr !== day) return;
        if (!res.ok) throw new Error('Không đọc được sản lượng');
        if (isCurrentPlanFlatLine()) {
            flatOutput = data;
            renderOutputDisplay();
            return;
        }
        if (data.available) {
            hlPassedCount = data.qty || 0;
            renderOutputDisplay();
        }
        renderHangingOutputMeta(data, false);
    } catch (e) {
        if (selectedPlanId == planId && reportDateStr === day) {
            if (isCurrentPlanFlatLine()) {
                flatOutput = null;
                renderOutputDisplay();
            } else {
                renderHangingOutputMeta(null, true);
            }
        }
        console.error('[hanging-output]', e);
    }
}

async function refreshHangingOutput() {
    const btn = document.getElementById('btnHlOutputRefresh');
    if (btn) { btn.disabled = true; btn.classList.add('spinning'); }
    try {
        await fetchHangingOutput({ refresh: true });
    } finally {
        if (btn) { btn.disabled = false; btn.classList.remove('spinning'); }
    }
}

function startHlAutoRefresh() {
    stopHlAutoRefresh();
    renderHangingOutputMeta(null, false);
    if (isCurrentPlanHangingLine()) {
        fetchHangingOutput();
        // Không gọi API khi tab bị ẩn / màn hình tắt.
        hlAutoRefreshTimer = setInterval(() => { if (!document.hidden) fetchHangingOutput(); }, 30_000);
    }
}

function stopHlAutoRefresh() {
    if (hlAutoRefreshTimer) { clearInterval(hlAutoRefreshTimer); hlAutoRefreshTimer = null; }
}

async function fetchOutputTotal() {
    if (!selectedPlanId) return;
    const station = getActiveStation();
    if (!station && (stationMode === 'cluster' || stationList.length > 1)) {
        setOutputDisplay(0, 0);
        return;
    }
    const seq = ctxSeq;
    const reqSeq = ++outputReqSeq;
    try {
        const params = new URLSearchParams({ plan_id: selectedPlanId, date: reportDateStr });
        if (station) params.append('station', station);
        const res = await fetch(`/api/qc/output-sp?${params.toString()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        // Bỏ qua nếu đã đổi ngữ cảnh hoặc có thao tác +1/-1 mới hơn đang/đã gửi.
        if (isStaleCtx(seq) || reqSeq !== outputReqSeq) return;
        setOutputDisplay(data.total || 0, data.failed_count || 0, data.reworked_count || 0);
        if (isCurrentPlanFlatLine()) await fetchHangingOutput();
    } catch (e) {
        console.error(e);
    }
}

async function postOutputDelta(delta, ctx = null) {
    // ctx: ngữ cảnh lúc bấm +1 (dùng cho Hoàn tác). Đã đổi kế hoạch/cụm/ngày → bỏ qua.
    if (ctx && isStaleCtx(ctx.seq)) {
        showToast('Đã đổi kế hoạch/cụm/ngày — không hoàn tác được nữa.', { type: 'warn' });
        return false;
    }
    const seq = ctxSeq;
    const reqSeq = ++outputReqSeq;
    const body = {
        plan_id: parseInt(selectedPlanId),
        date: reportDateStr,
        station: getActiveStation(),
        delta: delta,
        status: 'Passed',
        client_request_id: newRequestId(),
    };
    // Hiển thị ngay (optimistic), đối chiếu lại khi server trả về.
    outputTotal = Math.max(0, (outputTotal || 0) + delta);
    renderOutputDisplay();
    if (navigator.vibrate) { try { navigator.vibrate(30); } catch (e) {} }

    const send = () => fetch('/api/qc/output-sp-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    let res;
    try {
        try {
            res = await send();
        } catch (netErr) {
            // Mất mạng thoáng qua: gửi lại 1 lần với cùng client_request_id (server tự bỏ trùng).
            await new Promise(r => setTimeout(r, 1500));
            res = await send();
        }
        if (res.status === 409) {
            const err = await res.json().catch(() => ({}));
            alert(err.detail || 'Kế hoạch đã bị đóng bởi quản lý. Vui lòng chọn kế hoạch khác.');
            backToPlanSelection(true);
            return false;
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!isStaleCtx(seq) && reqSeq === outputReqSeq) {
            setOutputDisplay(data.total || 0, data.failed_count || 0, outputReworked);
        }
        loadPosSummary();
        return true;
    } catch (e) {
        console.error(e);
        if (!isStaleCtx(seq)) {
            showToast(delta > 0 ? 'Chưa ghi được +1 Đạt — kiểm tra wifi rồi bấm lại.' : 'Chưa hoàn tác được — vui lòng thử lại.', { type: 'error', duration: 4000 });
            fetchOutputTotal(); // đồng bộ lại số thật từ server
        }
        return false;
    }
}

async function adjustOutputStatus(status) {
    if (!selectedPlanId) { alert('Vui lòng chọn Kế hoạch!'); return; }
    if (!ensureStationSelected()) return;
    if (status === 'Failed') {
        const product = addDefectProduct(null, true);
        if (!product) return;
        renderOutputDisplay();
        setTimeout(() => {
            product.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 50);
        return;
    }
    const ctx = { seq: ctxSeq };
    const ok = await postOutputDelta(1);
    if (ok && !isStaleCtx(ctx.seq)) {
        showToast('Đã +1 Đạt', {
            type: 'success',
            duration: 5000,
            actionLabel: 'Hoàn tác',
            onAction: () => postOutputDelta(-1, ctx).then(done => { if (done) showToast('Đã hoàn tác 1 sản phẩm Đạt'); }),
        });
    }
 }

 function loaiPillClass(loai) {
     const s = (loai || '').toLowerCase();
     if (s.includes('đại trà')) return 'mass';
     if (s.includes('nghiêm')) return 'serious';
     return 'multi';
 }

 function getCurrentBucketLabel() {
     try {
         const parts = new Intl.DateTimeFormat('en-GB', {
             timeZone: 'Asia/Bangkok',
             hour: '2-digit',
             minute: '2-digit',
             hour12: false
         }).formatToParts(new Date());
         const hh = Number(parts.find(p => p.type === 'hour')?.value || 0);
         const mm = Number(parts.find(p => p.type === 'minute')?.value || 0);
         const mins = hh * 60 + mm;
         if (mins < (9 * 60 + 30)) return '7H30 - 9H30';
         if (mins < (11 * 60 + 30)) return '9H30 - 11H30';
         if (mins < (14 * 60 + 30)) return '12H30 - 14H30';
         if (mins < (16 * 60 + 30)) return '14H30 - 16H30';
         return 'Sau 16H30';
     } catch (e) {
         return '';
     }
 }

 function renderBucketBlock(b, opts = {}) {
     const items = b.items || [];
     const has = items.length > 0;
     const meta = `
        <span class="pos-stat-chip">Kiểm ${b.output_total || 0}</span>
        <span class="pos-stat-chip">Lỗi ${b.defect_total || 0}</span>
        <span class="pos-stat-chip">TL ${Number(b.defect_rate || 0).toFixed(2)}%</span>
     `;
     const table = has ? `
         <div class="table-responsive mt-2">
             <table class="table table-sm mb-0 pos-table">
                 <thead>
                     <tr>
                         <th style="width: 160px;">Loại lỗi</th>
                         <th>Vị trí</th>
                         <th class="text-center" style="width: 64px;">HĐKP</th>
                         <th class="text-end" style="width: 84px;">Số lượng</th>
                     </tr>
                 </thead>
                 <tbody>
                     ${items.map((it) => `
                         <tr>
                             <td><span class="pos-pill ${loaiPillClass(it.loai_loi)}">${esc(it.loai_loi)}</span></td>
                             <td class="text-muted pos-vi-tri">${esc(it.vi_tri)}</td>
                             <td class="text-center">
                                 <span class="hdkp-check ${it.has_hdkp ? 'done' : ''}">${it.has_hdkp ? '✓' : ''}</span>
                             </td>
                             <td class="text-end fw-bold">${Number(it.qty) || 0}</td>
                         </tr>
                     `).join('')}
                 </tbody>
             </table>
         </div>
     ` : `<div class="pos-empty mt-2">Không có cảnh báo lỗi trong khung giờ này.</div>`;
     return `
         <div class="pos-bucket">
             <div class="pos-bucket-header">
                 <span class="pos-badge">${esc(b.time_bucket)}</span>
                 <span class="pos-bucket-meta pos-bucket-stats">${meta}</span>
             </div>
             ${table}
         </div>
     `;
 }

 function renderPosSummary(data) {
     const card = document.getElementById('posSummaryCard');
     const wrap = document.getElementById('posSummaryContainer');
     if (!card || !wrap) return;
     const buckets = data?.buckets || [];
     card.style.display = 'block';
     if (!buckets.length) {
         wrap.innerHTML = '<div class="pos-empty">Chưa có dữ liệu.</div>';
         return;
     }
     const currentLabel = getCurrentBucketLabel();
     const currentIdx = currentLabel ? buckets.findIndex(x => x.time_bucket === currentLabel) : -1;
     const focusIdx = currentIdx >= 0 ? currentIdx : 0;
     const currentBucket = buckets[focusIdx];
     const otherBuckets = buckets.filter((_, i) => i !== focusIdx);

     const toggleId = `posOtherBuckets`;
     const toggleBtnId = `posToggleBtn`;
     const otherHtml = otherBuckets.length ? `
         <div class="d-flex justify-content-center">
             <button type="button" class="pos-toggle" id="${toggleBtnId}">
                 <span class="material-symbols-outlined" id="${toggleBtnId}-icon">expand_more</span>
                 <span id="${toggleBtnId}-label">Xem mốc khác</span>
             </button>
         </div>
         <div id="${toggleId}" class="d-none mt-2">
             <div class="d-flex flex-column gap-2">
                 ${otherBuckets.map(b => renderBucketBlock(b)).join('')}
             </div>
         </div>
     ` : '';

     wrap.innerHTML = `
         <div class="d-flex flex-column gap-2">
             ${renderBucketBlock(currentBucket)}
             ${otherHtml}
         </div>
     `;

     const btn = document.getElementById(toggleBtnId);
     if (btn) {
         btn.addEventListener('click', () => {
             const panel = document.getElementById(toggleId);
             const icon = document.getElementById(`${toggleBtnId}-icon`);
             const label = document.getElementById(`${toggleBtnId}-label`);
             if (!panel) return;
             const isOpen = !panel.classList.contains('d-none');
             panel.classList.toggle('d-none', isOpen);
             if (icon) icon.textContent = isOpen ? 'expand_more' : 'expand_less';
             if (label) label.textContent = isOpen ? 'Xem mốc khác' : 'Ẩn mốc khác';
         });
     }
 }

 async function loadPosSummary() {
     const card = document.getElementById('posSummaryCard');
     const wrap = document.getElementById('posSummaryContainer');
     if (!card || !wrap) return;
     if (!selectedPlanId) {
         card.style.display = 'none';
         return;
     }
     const st = getActiveStation();
     if (!stationList.length && stationMode === 'cluster') {
         card.style.display = 'block';
         wrap.innerHTML = '<div class="pos-empty">Loại hàng này chưa được cấu hình Cụm.</div>';
         return;
     }
     if (!st && (stationMode === 'cluster' || stationList.length > 1)) {
         card.style.display = 'block';
         wrap.innerHTML = `<div class="pos-empty">Vui lòng chọn ${getStationFieldLabel()} để xem thống kê.</div>`;
         return;
     }
     try {
         const params = new URLSearchParams({ plan_id: selectedPlanId, date: reportDateStr });
         if (st) params.append('station', st);
         const seq = ctxSeq;
         const res = await fetch(`/api/qc/input/pos-summary?${params.toString()}`);
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (isStaleCtx(seq)) return;
         renderPosSummary(data);
     } catch (e) {
         console.error(e);
         card.style.display = 'block';
         wrap.innerHTML = '<div class="pos-empty">Lỗi tải thống kê.</div>';
     }
 }

 function normalizeProductPrefill(prefill) {
     if (!prefill) return null;
     if (prefill.bo_phan_items && prefill.bo_phan_items.length) return prefill;
    const grouped = {};
    (prefill.defects || []).forEach(d => {
        const key = `${d.bo_phan_id || ''}|${d.chi_tiet_id || ''}`;
        if (!grouped[key]) {
            grouped[key] = {
                bo_phan_id: d.bo_phan_id,
                chi_tiet_id: d.chi_tiet_id,
                defects: []
            };
        }
        grouped[key].defects.push({
            ma_loi_id: d.ma_loi_id,
            mo_ta_loi_id: d.mo_ta_loi_id,
            muc_do: d.muc_do
        });
    });
    return { bo_phan_items: Object.values(grouped) };
}
