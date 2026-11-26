// Nhập lỗi bằng giọng nói.
// Script thường (không phải module): dùng chung global scope với các file khác của trang,
// thứ tự nạp khai báo trong templates/qc_input_sp.html.

function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        const btn = document.getElementById('btnMic');
        if (btn) btn.disabled = true;
        showSpeechToast('Trình duyệt không hỗ trợ nhận diện giọng nói.');
        return;
    }
    recognition = new SpeechRecognition();
    recognition.lang = 'vi-VN';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
        isListening = true;
        updateMicUi(true);
        showSpeechToast('Bắt đầu ghi âm... vui lòng đọc');
    };
    recognition.onend = () => {
        isListening = false;
        updateMicUi(false);
    };
    recognition.onerror = () => {
        isListening = false;
        updateMicUi(false);
        showSpeechToast('Không nghe rõ, vui lòng thử lại.');
    };
    recognition.onresult = async (event) => {
        const transcript = event.results[0][0].transcript || '';
        await handleVoiceInput(transcript);
        recognition.stop();
    };
}

function toggleVoiceInput() {
    if (!recognition) return;
    if (isListening) return;
    recognition.start();
    if (navigator.vibrate) navigator.vibrate(40);
}

function updateMicUi(listening) {
    const btn = document.getElementById('btnMic');
    if (!btn) return;
    if (listening) btn.classList.add('listening');
    else btn.classList.remove('listening');
}

function showSpeechToast(message) {
    const toast = document.getElementById('speechToast');
    if (!toast) return;
    toast.textContent = message;
    toast.style.display = 'block';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { toast.style.display = 'none'; }, 1800);
}

function startVoiceField(field, ctx) {
    voiceTarget = { field, ...ctx };
    toggleVoiceInput();
}

function normalizeText(text) {
    return (text || '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9\s]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function parseVietnameseNumber(text) {
    const t = normalizeText(text);
    if (!t) return null;
    if (/^\d+$/.test(t)) return parseInt(t, 10);
    const map = {
        khong: 0, mot: 1, motj: 1, hai: 2, ba: 3, bon: 4, tu: 4, nam: 5,
        lam: 5, sau: 6, bay: 7, tam: 8, chin: 9, muoi: 10
    };
    const parts = t.split(' ');
    if (parts.length === 1 && map[parts[0]] !== undefined) return map[parts[0]];
    if (parts.length === 2 && parts[0] === 'muoi' && map[parts[1]] !== undefined) return 10 + map[parts[1]];
    if (parts.length === 2 && map[parts[0]] !== undefined && parts[1] === 'muoi') return map[parts[0]] * 10;
    if (parts.length === 3 && map[parts[0]] !== undefined && parts[1] === 'muoi' && map[parts[2]] !== undefined) {
        return map[parts[0]] * 10 + map[parts[2]];
    }
    return null;
}

function parseMaLoiCode(segment) {
    const t = normalizeText(segment);
    const direct = t.match(/c\s*(\d{1,3})/);
    if (direct) return `c${direct[1]}`;
    const idx = t.indexOf('xe');
    if (idx >= 0) {
        const tail = t.slice(idx + 2).trim();
        const num = parseVietnameseNumber(tail);
        if (num !== null) return `c${num}`;
    }
    return null;
}

function getBestMatch(options, text, labelKey = 'label') {
    const needle = normalizeText(text);
    if (!needle) return { match: null, ambiguous: false };

    const exact = [];
    const partial = [];
    options.forEach(opt => {
        const label = normalizeText(opt[labelKey] || '');
        if (!label) return;
        if (label === needle) {
            exact.push(opt);
        } else if (label.includes(needle) || needle.includes(label)) {
            partial.push(opt);
        }
    });

    if (exact.length === 1) return { match: exact[0], ambiguous: false };
    if (exact.length > 1) return { match: exact[0], ambiguous: true };
    if (partial.length === 1) return { match: partial[0], ambiguous: false };
    if (partial.length > 1) return { match: null, ambiguous: true };
    return { match: null, ambiguous: false };
}

async function handleVoiceInput(text) {
    if (!text || !voiceTarget) return;
    showSpeechToast(`Đã nghe: ${text}`);
    const field = voiceTarget.field;

    if (field === 'bo_phan') {
        const blockId = voiceTarget.blockId;
        const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
        if (!block) return;
        const bpResult = getBestMatch(masterBoPhan.map(bp => ({ value: String(bp.id), label: bp.ten_bo_phan })), text);
        if (bpResult.match) {
            selectComboValue(block.querySelector('.combo-dropdown[data-type="bo-phan"]'), bpResult.match.value);
            await onBoPhanChange(blockId, block.querySelector('.sel-bo-phan'));
            block.classList.add('pulse-success');
            setTimeout(() => block.classList.remove('pulse-success'), 600);
        } else if (bpResult.ambiguous) {
            showSpeechToast('Có nhiều Bộ phận trùng, vui lòng đọc đầy đủ hơn.');
        } else {
            showSpeechToast('Không tìm thấy Bộ phận phù hợp.');
        }
    }

    if (field === 'chi_tiet') {
        const blockId = voiceTarget.blockId;
        const block = document.querySelector(`.bo-phan-block[data-block-id="${blockId}"]`);
        if (!block) return;
        const options = (chiTietOptionsByBlock[blockId] || []).map(ct => ({ value: String(ct.id), label: ct.ten_chi_tiet }));
        const ctResult = getBestMatch(options, text);
        if (ctResult.match) {
            selectComboValue(block.querySelector('.combo-dropdown[data-type="chi-tiet"]'), ctResult.match.value);
            block.classList.add('pulse-success');
            setTimeout(() => block.classList.remove('pulse-success'), 600);
        } else if (ctResult.ambiguous) {
            showSpeechToast('Có nhiều Chi tiết trùng, vui lòng đọc đầy đủ hơn.');
        } else {
            showSpeechToast('Không tìm thấy Chi tiết phù hợp.');
        }
    }

    if (field === 'ma_loi') {
        const itemId = voiceTarget.itemId;
        const item = document.querySelector(`.defect-item[data-item-id="${itemId}"]`);
        if (!item) return;
        const code = parseMaLoiCode(text);
        let match = null;
        if (code) {
            match = masterMaLoiOptions.find(opt => normalizeText(opt.label).includes(code));
        }
        if (!match) {
            const mlResult = getBestMatch(masterMaLoiOptions, text);
            match = mlResult.match;
            if (!match && mlResult.ambiguous) {
                showSpeechToast('Có nhiều Mã lỗi trùng, vui lòng đọc đầy đủ hơn.');
                voiceTarget = null;
                return;
            }
        }
        if (match) {
            selectComboValue(item.querySelector('.combo-dropdown[data-type="ma-loi"]'), `${match.ma_loi_id}|${match.mo_ta_loi_id}`);
            applyMucDoOptions(item, null);
            item.classList.add('pulse-success');
            setTimeout(() => item.classList.remove('pulse-success'), 600);
        } else {
            showSpeechToast('Không tìm thấy Mã lỗi phù hợp.');
        }
    }

    if (field === 'muc_do') {
        const itemId = voiceTarget.itemId;
        const item = document.querySelector(`.defect-item[data-item-id="${itemId}"]`);
        if (!item) return;
        const sel = item.querySelector('.sel-muc-do');
        const opts = Array.from(sel.options).map(o => ({ value: o.value, label: o.textContent }));
        const mdResult = getBestMatch(opts, text);
        if (mdResult.match) {
            sel.value = mdResult.match.value;
            item.classList.add('pulse-success');
            setTimeout(() => item.classList.remove('pulse-success'), 600);
        } else if (mdResult.ambiguous) {
            showSpeechToast('Có nhiều Mức độ trùng, vui lòng đọc rõ hơn.');
        } else {
            showSpeechToast('Không tìm thấy Mức độ phù hợp.');
        }
    }

    voiceTarget = null;
}
