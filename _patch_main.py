"""Patch main.py to add upload-sp-image endpoint."""
import sys

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The new endpoint to insert
new_endpoint = '''

@app.post("/api/qc/upload-sp-image")
async def api_qc_upload_sp_image(file: UploadFile = File(...)):
    """Upload anh chup san pham loi QC (SP mode)."""
    import uuid
    sub_dir = os.path.join(IMAGES_STORAGE_DIR, "qc_sp")
    os.makedirs(sub_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "photo.jpg")[1] or ".jpg"
    unique_name = f"{datetime.now().strftime(\'%Y%m%d_%H%M%S\')}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = os.path.join(sub_dir, unique_name)
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_path = f"qc_sp/{unique_name}"
    return {"status": "ok", "image_path": relative_path, "url": f"/api/images/{relative_path}"}

'''

# Find the anchor: the return of error-log-sp POST endpoint
anchor = '    return {"status": "ok", "id": log_id, "updated": updated}'
# Also need to handle \r\n
anchor_r = anchor + '\r\n'
anchor_n = anchor + '\n'

if anchor_r in content:
    content = content.replace(anchor_r, anchor + '\n' + new_endpoint, 1)
    print("Inserted after anchor (CRLF)")
elif anchor_n in content:
    content = content.replace(anchor_n, anchor + '\n' + new_endpoint, 1)
    print("Inserted after anchor (LF)")
else:
    print("ERROR: anchor not found!")
    sys.exit(1)

# Now also patch the INSERT INTO qc_defect to include image_path
old_insert = """INSERT INTO public.qc_defect
                        (error_log_sp_id, sp_index, bo_phan_id, chi_tiet_id, ma_loi_id, mo_ta_loi_id, muc_do, lap_lai_3)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""

new_insert = """INSERT INTO public.qc_defect
                        (error_log_sp_id, sp_index, bo_phan_id, chi_tiet_id, ma_loi_id, mo_ta_loi_id, muc_do, lap_lai_3, image_path)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""

if old_insert in content:
    content = content.replace(old_insert, new_insert, 1)
    print("Patched INSERT to include image_path column")
else:
    print("WARNING: INSERT anchor not found, trying with different whitespace...")
    # Try to find it with more flexible matching
    import re
    pattern = r'INSERT INTO public\.qc_defect\s*\(\s*error_log_sp_id,\s*sp_index,\s*bo_phan_id,\s*chi_tiet_id,\s*ma_loi_id,\s*mo_ta_loi_id,\s*muc_do,\s*lap_lai_3\s*\)\s*VALUES\s*\(\s*%s,\s*%s,\s*%s,\s*%s,\s*%s,\s*%s,\s*%s,\s*%s\s*\)'
    match = re.search(pattern, content)
    if match:
        content = content[:match.start()] + new_insert + content[match.end():]
        print("Patched INSERT (regex match)")
    else:
        print("ERROR: Could not find INSERT statement to patch")

# Also patch the VALUES tuple to include d.get("image_path")
old_values = """(
                            log_id,
                            base_index + idx,
                            d.get("bo_phan_id"),
                            d.get("chi_tiet_id"),
                            d.get("ma_loi_id"),
                            d.get("mo_ta_loi_id"),
                            d.get("muc_do"),
                            d.get("lap_lai_3", False),
                        )"""

new_values = """(
                            log_id,
                            base_index + idx,
                            d.get("bo_phan_id"),
                            d.get("chi_tiet_id"),
                            d.get("ma_loi_id"),
                            d.get("mo_ta_loi_id"),
                            d.get("muc_do"),
                            d.get("lap_lai_3", False),
                            d.get("image_path"),
                        )"""

if old_values in content:
    content = content.replace(old_values, new_values, 1)
    print("Patched VALUES tuple to include image_path")
else:
    print("WARNING: VALUES tuple not found exactly, trying flexible match...")
    # Try normalized
    old_norm = old_values.replace('\r\n', '\n')
    if old_norm in content:
        content = content.replace(old_norm, new_values.replace('\r\n', '\n'), 1)
        print("Patched VALUES tuple (LF)")
    else:
        print("ERROR: Could not find VALUES tuple to patch")

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("All patches applied successfully!")
