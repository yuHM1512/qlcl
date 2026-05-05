"""Patch qc_input_sp.html to add camera capture feature per bo-phan-block."""

with open('templates/qc_input_sp.html', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# 1) Add CSS for camera capture UI (before </style>)
# ============================================================
camera_css = """
        /* Camera capture styles */
        .camera-section { margin-top: 0.75rem; }
        .camera-trigger {
            width: 100%;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 1rem;
            background: #f8fafc;
            color: #64748b;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .camera-trigger:hover { border-color: #2563eb; color: #2563eb; background: #eff6ff; }
        .camera-trigger i { font-size: 1.2rem; }
        .camera-preview-area {
            position: relative;
            border-radius: 12px;
            overflow: hidden;
            border: 2px solid #e2e8f0;
        }
        .camera-preview-area img {
            width: 100%;
            max-height: 240px;
            object-fit: cover;
            display: block;
        }
        .camera-actions {
            display: flex;
            gap: 0.5rem;
            padding: 0.5rem;
            background: rgba(255,255,255,0.95);
        }
        .camera-actions .btn { flex: 1; border-radius: 10px; font-weight: 700; font-size: 0.85rem; }
        .camera-badge-ok {
            position: absolute;
            top: 8px;
            right: 8px;
            background: #10b981;
            color: #fff;
            border-radius: 999px;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }
        .camera-uploading {
            position: absolute;
            inset: 0;
            background: rgba(255,255,255,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: #2563eb;
        }
"""

content = content.replace('    </style>', camera_css + '    </style>', 1)
print("1) CSS injected")

# ============================================================
# 2) Modify addBoPhanBlock to include camera section
# ============================================================
# Find the existing block innerHTML and add camera section before the "Thêm lỗi" button
old_block_end = """<div class="defect-items d-flex flex-column gap-2 mt-2"></div>
            <div class="text-end mt-2">
                <button class="btn btn-sm btn-primary" onclick="addDefectItem(${blockId})"><i class="fas fa-plus me-1"></i>Thêm lỗi</button>
            </div>"""

new_block_end = """<div class="defect-items d-flex flex-column gap-2 mt-2"></div>
            <div class="text-end mt-2">
                <button class="btn btn-sm btn-primary" onclick="addDefectItem(${blockId})"><i class="fas fa-plus me-1"></i>Thêm lỗi</button>
            </div>
            <div class="camera-section" id="cameraSection_${blockId}">
                <input type="file" accept="image/*" capture="environment" id="cameraInput_${blockId}" style="display:none;" onchange="onCameraCapture(${blockId}, this)">
                <div id="cameraTriggerArea_${blockId}">
                    <button type="button" class="camera-trigger" onclick="document.getElementById('cameraInput_${blockId}').click()">
                        <i class="fas fa-camera"></i> Chụp hình minh hoạ lỗi
                    </button>
                </div>
                <div id="cameraPreviewArea_${blockId}" style="display:none;">
                    <div class="camera-preview-area">
                        <img id="cameraPreviewImg_${blockId}" src="" alt="Preview">
                        <div id="cameraBadge_${blockId}" class="camera-badge-ok" style="display:none;"><i class="fas fa-check"></i></div>
                        <div id="cameraUploading_${blockId}" class="camera-uploading" style="display:none;"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải...</div>
                        <div class="camera-actions" id="cameraActions_${blockId}">
                            <button type="button" class="btn btn-success btn-sm" onclick="confirmCameraImage(${blockId})"><i class="fas fa-check me-1"></i>Sử dụng hình ảnh</button>
                            <button type="button" class="btn btn-outline-secondary btn-sm" onclick="retakeCamera(${blockId})"><i class="fas fa-redo me-1"></i>Chụp lại</button>
                        </div>
                    </div>
                </div>
            </div>"""

if old_block_end in content:
    content = content.replace(old_block_end, new_block_end, 1)
    print("2) Camera section added to bo-phan-block template")
else:
    print("WARNING: Could not find block end template, trying flexible...")
    # Try with different quote styles
    old_alt = old_block_end.replace("'", '"')
    if old_alt in content:
        content = content.replace(old_alt, new_block_end.replace("'", '"'), 1)
        print("2) Camera section added (alt quotes)")
    else:
        print("ERROR: Block template not found!")

# ============================================================
# 3) Add camera JavaScript functions before submitReport
# ============================================================
camera_js = """
    // ============ Camera Capture per Block ============
    const blockImagePaths = {};  // blockId -> image_path (relative)

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
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick="retakeCamera(${blockId})" style="flex:1;"><i class="fas fa-redo me-1"></i>Chụp lại</button>
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
            <button type="button" class="btn btn-success btn-sm" onclick="confirmCameraImage(${blockId})"><i class="fas fa-check me-1"></i>Sử dụng hình ảnh</button>
            <button type="button" class="btn btn-outline-secondary btn-sm" onclick="retakeCamera(${blockId})"><i class="fas fa-redo me-1"></i>Chụp lại</button>
        `;
    }

"""

# Insert before the submitReport function
anchor_submit = '    async function submitReport() {'
if anchor_submit in content:
    content = content.replace(anchor_submit, camera_js + anchor_submit, 1)
    print("3) Camera JS functions injected")
else:
    print("ERROR: submitReport anchor not found!")

# ============================================================
# 4) Modify submitReport to include image_path per defect
# ============================================================
# Find where defects are pushed and add image_path
old_push = """defects.push({
                        bo_phan_id: parseInt(bpId),
                        chi_tiet_id: parseInt(ctId),
                        ma_loi_id: maLoiId,
                        mo_ta_loi_id: moTaLoiId,
                        muc_do: mucDo
                    });"""

new_push = """defects.push({
                        bo_phan_id: parseInt(bpId),
                        chi_tiet_id: parseInt(ctId),
                        ma_loi_id: maLoiId,
                        mo_ta_loi_id: moTaLoiId,
                        muc_do: mucDo,
                        image_path: blockImagePaths[block.dataset.blockId] || null
                    });"""

if old_push in content:
    content = content.replace(old_push, new_push, 1)
    print("4) submitReport patched to include image_path")
else:
    print("WARNING: defects.push not found exactly, trying flexible...")
    # Try without exact spacing
    import re
    pattern = r'defects\.push\(\{\s*bo_phan_id:\s*parseInt\(bpId\),\s*chi_tiet_id:\s*parseInt\(ctId\),\s*ma_loi_id:\s*maLoiId,\s*mo_ta_loi_id:\s*moTaLoiId,\s*muc_do:\s*mucDo\s*\}\);'
    match = re.search(pattern, content)
    if match:
        content = content[:match.start()] + new_push + content[match.end():]
        print("4) submitReport patched (regex)")
    else:
        print("ERROR: Could not find defects.push")

with open('templates/qc_input_sp.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nAll frontend patches applied successfully!")
