"""Parse 'Số hoá Endline.xlsx' -> structured JSON for Áo vest visual picker.

Extracts:
  - Per sheet (Chính / Lót / Nhận diện):
      - Khối (image of a body part: Cổ, Ve, Thân...) with EMU bbox.
      - Mã vị trí (C1, V3, LT2...) with EMU bbox + the label found in cells.
  - Images (PNG + SVG) extracted to an output dir.
  - JSON file describing nhóm -> khối -> mã with normalized hotspot coords.

Usage:
    python scripts/parse_aovest_excel.py <xlsx_path> <out_dir>
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

NS = {
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

NHOM_MAP = {
    "AO VEST -CHINH": "chinh",
    "AO VEST - LOT": "lot",
    "Bản sao của AO VEST 1 (3)": "nhan_dien",
}


def read_shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall("x:si", NS):
        out.append("".join(t.text or "" for t in si.iter(f"{{{NS['x']}}}t")))
    return out


def parse_workbook_sheets(z: zipfile.ZipFile) -> list[dict]:
    """Return list of {name, sheet_xml_path, drawing_xml_path}."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wb_rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in wb_rels.findall("rel:Relationship", NS)}

    sheets = []
    for s in wb.findall("x:sheets/x:sheet", NS):
        name = s.get("name")
        state = s.get("state") or "visible"
        rid = s.get(f"{{{NS['r']}}}id")
        target = rid_to_target.get(rid, "")
        sheet_xml_path = "xl/" + target if not target.startswith("xl/") else target
        # Drawing rel
        rels_path = sheet_xml_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
        drawing_xml_path: Optional[str] = None
        if rels_path in z.namelist():
            srels = ET.fromstring(z.read(rels_path))
            for rr in srels.findall("rel:Relationship", NS):
                if "drawing" in rr.get("Type", ""):
                    t = rr.get("Target")
                    # normalize ../drawings/drawing1.xml -> xl/drawings/drawing1.xml
                    drawing_xml_path = "xl/" + t.lstrip("./").replace("../", "")
        sheets.append({
            "name": name,
            "state": state,
            "sheet_xml_path": sheet_xml_path,
            "drawing_xml_path": drawing_xml_path,
        })
    return sheets


def parse_sheet_cells(z: zipfile.ZipFile, sheet_xml_path: str, shared: list[str]) -> dict[str, str]:
    """Return mapping {cell_ref: value}, e.g. {'B5': 'Lá cổ'}."""
    root = ET.fromstring(z.read(sheet_xml_path))
    out: dict[str, str] = {}
    for c in root.iter(f"{{{NS['x']}}}c"):
        ref = c.get("r")
        t = c.get("t")
        v_el = c.find("x:v", NS)
        is_el = c.find("x:is", NS)
        val: Optional[str] = None
        if t == "s" and v_el is not None and v_el.text is not None:
            try:
                idx = int(v_el.text)
                val = shared[idx] if 0 <= idx < len(shared) else None
            except ValueError:
                val = None
        elif t == "inlineStr" and is_el is not None:
            val = "".join(tt.text or "" for tt in is_el.iter(f"{{{NS['x']}}}t"))
        elif v_el is not None:
            val = v_el.text
        if val:
            out[ref] = val
    return out


def parse_drawing(z: zipfile.ZipFile, drawing_xml_path: str) -> dict:
    """Return {'pictures': [{rid, off_x, off_y, ext_cx, ext_cy, from_row, to_row}], 'textboxes': [...]}."""
    root = ET.fromstring(z.read(drawing_xml_path))
    rels_path = drawing_xml_path.replace("drawings/", "drawings/_rels/") + ".rels"
    rid_to_target: dict[str, str] = {}
    rid_to_svg: dict[str, str] = {}  # PNG rid -> SVG target (if paired)
    if rels_path in z.namelist():
        rrels = ET.fromstring(z.read(rels_path))
        for r in rrels.findall("rel:Relationship", NS):
            rid_to_target[r.get("Id")] = r.get("Target")

    pics: list[dict] = []
    sps: list[dict] = []

    for anchor in root.iter(f"{{{NS['xdr']}}}twoCellAnchor"):
        from_el = anchor.find("xdr:from", NS)
        to_el = anchor.find("xdr:to", NS)
        from_row = int(from_el.find("xdr:row", NS).text) if from_el is not None and from_el.find("xdr:row", NS) is not None else None
        to_row = int(to_el.find("xdr:row", NS).text) if to_el is not None and to_el.find("xdr:row", NS) is not None else None

        pic = anchor.find("xdr:pic", NS)
        sp = anchor.find("xdr:sp", NS)
        if pic is not None:
            xfrm = pic.find("xdr:spPr/a:xfrm", NS)
            if xfrm is None:
                continue
            off = xfrm.find("a:off", NS)
            ext = xfrm.find("a:ext", NS)
            blip = pic.find("xdr:blipFill/a:blip", NS)
            rid = blip.get(f"{{{NS['r']}}}embed") if blip is not None else None
            target = rid_to_target.get(rid)
            # Check for paired SVG inside <asvg:svgBlip>
            svg_target = None
            if blip is not None:
                for ext_el in blip.iter(f"{{{NS['a']}}}ext"):
                    for ch in ext_el:
                        rid_svg = ch.get(f"{{{NS['r']}}}embed")
                        if rid_svg and rid_svg in rid_to_target:
                            t = rid_to_target[rid_svg]
                            if t.lower().endswith(".svg"):
                                svg_target = t
            pics.append({
                "rid": rid,
                "target": target,
                "svg_target": svg_target,
                "from_row": from_row,
                "to_row": to_row,
                "off_x": int(off.get("x")),
                "off_y": int(off.get("y")),
                "ext_cx": int(ext.get("cx")),
                "ext_cy": int(ext.get("cy")),
            })
        elif sp is not None:
            xfrm = sp.find("xdr:spPr/a:xfrm", NS)
            if xfrm is None:
                continue
            off = xfrm.find("a:off", NS)
            ext = xfrm.find("a:ext", NS)
            rot = xfrm.get("rot")
            txt_runs: list[str] = []
            for t_el in sp.iter(f"{{{NS['a']}}}t"):
                if t_el.text:
                    txt_runs.append(t_el.text)
            text = "".join(txt_runs).strip()
            if not text:
                continue
            sps.append({
                "text": text,
                "off_x": int(off.get("x")),
                "off_y": int(off.get("y")),
                "ext_cx": int(ext.get("cx")),
                "ext_cy": int(ext.get("cy")),
                "rot": int(rot) / 60000.0 if rot else 0.0,  # OOXML rot is 60000ths of a degree
            })

    return {"pictures": pics, "textboxes": sps}


def col_letters_to_idx(s: str) -> int:
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def idx_to_col_letters(idx: int) -> str:
    s = ""
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def find_label_for_code(cells: dict[str, str], code: str) -> Optional[str]:
    """Layout: D_n='Lá cổ', E_n='C1'. Label is in the column immediately to the LEFT of the code cell."""
    for ref, val in cells.items():
        if val.strip() == code:
            m = re.match(r"([A-Z]+)(\d+)", ref)
            if not m:
                continue
            col_letters, row = m.group(1), m.group(2)
            left_col = idx_to_col_letters(col_letters_to_idx(col_letters) - 1)
            label = cells.get(f"{left_col}{row}")
            if label:
                return label.strip()
    return None


def build_khoi_tables(cells: dict[str, str]) -> list[dict]:
    """Walk the sheet rows. A khoi header row has col A = short prefix (1-3 alpha letters)
    AND col B = khoi name. The table extends downward until the next header row or until
    col C/E has no more numeric rows.

    Returns list of {prefix, ten_khoi, start_row, end_row, codes: {code: label}}.
    """
    # Index cells by row
    by_row: dict[int, dict[str, str]] = defaultdict(dict)
    for ref, val in cells.items():
        m = re.match(r"^([A-Z]+)(\d+)$", ref)
        if not m:
            continue
        by_row[int(m.group(2))][m.group(1)] = val

    # Detect headers
    header_rows: list[tuple[int, str, str]] = []  # (row, prefix, ten_khoi)
    for row, cols in by_row.items():
        a_val = (cols.get("A") or "").strip()
        b_val = (cols.get("B") or "").strip()
        if not a_val or not b_val:
            continue
        # Filter: prefix must be short uppercase letters; ten_khoi must be non-numeric
        if not re.match(r"^[A-Z]{1,3}$", a_val):
            continue
        if a_val in {"A", "B", "C", "D", "E"}:  # column letters mistaken as prefix
            # Filter out if b_val is something like "Tên" which means this is itself a label row
            if b_val in {"Tên", "Mã", "Mã ", "Tên ", "Cổ"}:
                # 'C' + 'Cổ' is a real header — keep it
                if a_val == "C" and b_val == "Cổ":
                    pass
                else:
                    continue
        # Filter sub-headers like A_n='Mã ' (col label, not a prefix)
        if b_val in {"Tên", "Mã", "Mã ", "Tên "}:
            continue
        # Looks like a header
        header_rows.append((row, a_val, b_val))

    header_rows.sort(key=lambda x: x[0])

    tables: list[dict] = []
    for i, (hrow, prefix, ten_khoi) in enumerate(header_rows):
        next_hrow = header_rows[i + 1][0] if i + 1 < len(header_rows) else 10**9
        codes: dict[str, str] = {}
        # Codes are in column E for chinh/lot/nhan_dien layouts; labels in column D
        for r in range(hrow, min(next_hrow, hrow + 200)):
            cols = by_row.get(r, {})
            e_val = (cols.get("E") or "").strip()
            d_val = (cols.get("D") or "").strip()
            if e_val and re.match(r"^[A-Z]{1,3}\d+$", e_val):
                if d_val:
                    codes[e_val] = d_val
        tables.append({
            "prefix": prefix,
            "ten_khoi": ten_khoi,
            "start_row": hrow,
            "end_row": next_hrow - 1,
            "codes": codes,
        })
    return tables


def match_image_to_khoi(image_from_row: Optional[int], tables: list[dict]) -> Optional[dict]:
    """Return the khoi table whose start_row is the largest one ≤ image_from_row.
    If image_from_row is None, return None."""
    if image_from_row is None:
        return None
    best = None
    for t in tables:
        # xdr rows are 0-based; sheet rows are 1-based. Use start_row-1 for comparison? Actually xdr <row> elements are zero-indexed.
        if t["start_row"] - 1 <= image_from_row:
            if best is None or t["start_row"] > best["start_row"]:
                best = t
    return best


def point_in_bbox(x: float, y: float, bb: dict) -> bool:
    return bb["off_x"] <= x <= bb["off_x"] + bb["ext_cx"] and \
           bb["off_y"] <= y <= bb["off_y"] + bb["ext_cy"]


def build_structure(xlsx_path: str, out_dir: Path) -> dict:
    z = zipfile.ZipFile(xlsx_path)
    shared = read_shared_strings(z)
    sheets = parse_workbook_sheets(z)

    nhoms: list[dict] = []

    TOL_EMU = 200000  # ~0.55cm tolerance for nearest-image assignment

    for sh in sheets:
        nhom_key = NHOM_MAP.get(sh["name"])
        if not nhom_key or sh["state"] != "visible" or not sh["drawing_xml_path"]:
            continue
        cells = parse_sheet_cells(z, sh["sheet_xml_path"], shared)
        khoi_tables = build_khoi_tables(cells)
        drw = parse_drawing(z, sh["drawing_xml_path"])

        # 1. Match each picture to a khoi table (by anchor row)
        pic_khoi: list[Optional[dict]] = []
        for pic in drw["pictures"]:
            pic_khoi.append(match_image_to_khoi(pic["from_row"], khoi_tables))

        # 2. Bucket textboxes into images: first by bbox containment, then by nearest edge ≤ TOL
        def edge_dist(cx: float, cy: float, bb: dict) -> float:
            dx = max(0, bb["off_x"] - cx, cx - (bb["off_x"] + bb["ext_cx"]))
            dy = max(0, bb["off_y"] - cy, cy - (bb["off_y"] + bb["ext_cy"]))
            return (dx * dx + dy * dy) ** 0.5

        khoi_buckets: dict[int, list[dict]] = defaultdict(list)
        orphans: list[dict] = []
        for tb in drw["textboxes"]:
            cx = tb["off_x"] + tb["ext_cx"] / 2
            cy = tb["off_y"] + tb["ext_cy"] / 2
            assigned = None
            for i, pic in enumerate(drw["pictures"]):
                if point_in_bbox(cx, cy, pic):
                    # Also require the code prefix matches the khoi prefix (to disambiguate overlapping khois)
                    khoi = pic_khoi[i]
                    if khoi:
                        m = re.match(r"^([A-Z]+)\d+$", tb["text"])
                        if m and m.group(1) == khoi["prefix"]:
                            assigned = i
                            break
                    else:
                        assigned = i
                        break
            if assigned is None:
                # Fallback: nearest image with matching prefix within tolerance
                m = re.match(r"^([A-Z]+)\d+$", tb["text"])
                code_prefix = m.group(1) if m else None
                candidates: list[tuple[int, float]] = []
                for i, pic in enumerate(drw["pictures"]):
                    khoi = pic_khoi[i]
                    if khoi and code_prefix and khoi["prefix"] != code_prefix:
                        continue
                    candidates.append((i, edge_dist(cx, cy, pic)))
                candidates.sort(key=lambda x: x[1])
                if candidates and candidates[0][1] <= TOL_EMU:
                    assigned = candidates[0][0]
            if assigned is None:
                orphans.append(tb)
            else:
                khoi_buckets[assigned].append(tb)

        # 3. For each image build the khoi entry
        khoi_list: list[dict] = []
        for i, pic in enumerate(drw["pictures"]):
            codes_in = khoi_buckets.get(i, [])
            khoi = pic_khoi[i]
            if not codes_in and not khoi:
                continue
            prefix = khoi["prefix"] if khoi else "?"
            ten_khoi = khoi["ten_khoi"] if khoi else None
            local_codes = khoi["codes"] if khoi else {}

            hotspots: list[dict] = []
            for tb in codes_in:
                rel_x = (tb["off_x"] - pic["off_x"]) / pic["ext_cx"]
                rel_y = (tb["off_y"] - pic["off_y"]) / pic["ext_cy"]
                rel_w = tb["ext_cx"] / pic["ext_cx"]
                rel_h = tb["ext_cy"] / pic["ext_cy"]
                code = tb["text"]
                # Lookup label in the matched khoi's local dict (avoid cross-khoi label confusion)
                label = local_codes.get(code)
                hotspots.append({
                    "ma": code,
                    "label": label,
                    "x_pct": round(rel_x, 5),
                    "y_pct": round(rel_y, 5),
                    "w_pct": round(rel_w, 5),
                    "h_pct": round(rel_h, 5),
                    "rotation": round(tb["rot"], 2),
                })

            def code_sort(h):
                m = re.match(r"^([A-Z]+)(\d+)$", h["ma"] or "")
                return (m.group(1) if m else h["ma"], int(m.group(2)) if m else 0)
            hotspots.sort(key=code_sort)

            # Extract image files
            img_dir = out_dir / "positions" / "aovest" / nhom_key
            img_dir.mkdir(parents=True, exist_ok=True)
            target = pic["target"] or ""
            zip_path = "xl/" + target.lstrip("./").replace("../", "")
            ext = zip_path.rsplit(".", 1)[-1].lower()
            base_name = f"{nhom_key}_{prefix.lower()}_{i + 1}"
            png_path = None
            svg_path = None
            if zip_path in z.namelist():
                fname = f"{base_name}.{ext}"
                (img_dir / fname).write_bytes(z.read(zip_path))
                if ext == "png":
                    png_path = f"positions/aovest/{nhom_key}/{fname}"
                elif ext == "svg":
                    svg_path = f"positions/aovest/{nhom_key}/{fname}"
            # Also extract paired SVG if present
            if pic.get("svg_target"):
                svg_zip = "xl/" + pic["svg_target"].lstrip("./").replace("../", "")
                if svg_zip in z.namelist():
                    sfname = f"{base_name}.svg"
                    (img_dir / sfname).write_bytes(z.read(svg_zip))
                    svg_path = f"positions/aovest/{nhom_key}/{sfname}"

            khoi_list.append({
                "ten_khoi": ten_khoi,
                "prefix": prefix,
                "image_emu": {
                    "off_x": pic["off_x"], "off_y": pic["off_y"],
                    "cx": pic["ext_cx"], "cy": pic["ext_cy"],
                },
                "image_png": png_path,
                "image_svg": svg_path,
                "hotspots": hotspots,
            })

        nhoms.append({
            "nhom": nhom_key,
            "sheet_name": sh["name"],
            "khoi": khoi_list,
            "orphan_textboxes": [t["text"] for t in orphans],
        })

    return {"loai_hang": "Áo vest", "nhoms": nhoms}


def extract_svg_pairs(z: zipfile.ZipFile, out_dir: Path, struct: dict) -> None:
    """Pair each PNG with its sibling SVG by checking <asvg:svgBlip> in drawing XMLs.

    The drawing references the PNG via r:embed; the SVG is referenced via asvg:svgBlip r:embed
    inside the same blip extLst. We re-scan to attach SVG path.
    """
    # Build mapping: rid_png_path_in_zip -> rid_svg_path_in_zip per drawing
    pass  # left intentionally — current MVP extracts PNG which is enough for picker; SVG can be added later


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: parse_aovest_excel.py <xlsx_path> <out_dir>")
        sys.exit(1)
    xlsx = sys.argv[1]
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    data = build_structure(xlsx, out_dir)
    out_json = out_dir / "aovest_visual_picker.json"
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_json}")
    # Summary
    for n in data["nhoms"]:
        print(f"\n[{n['nhom']}] sheet={n['sheet_name']} khois={len(n['khoi'])}")
        for k in n["khoi"]:
            with_label = sum(1 for h in k["hotspots"] if h["label"])
            print(f"   prefix={k['prefix']:5}  hotspots={len(k['hotspots']):3}  labeled={with_label:3}  img={k['image_png']}")
        if n["orphan_textboxes"]:
            print(f"   ORPHAN textboxes (no image): {n['orphan_textboxes']}")
