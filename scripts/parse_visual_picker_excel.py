"""Parse a visual-picker XLSX into structured JSON + images.

Generic version of the old `parse_aovest_excel.py`. Supports multiple loại hàng
in a single file (1 sheet = 1 nhóm of 1 loại hàng).

Extracts, per sheet:
  - Khối (image of a body part: Cổ, Ve, Thân...) with EMU bbox.
  - Mã vị trí (C1, V3, LT2...) with EMU bbox + the label found in cells.
  - Images (PNG + paired SVG when present) extracted to <out_dir>/positions/<slug>/<nhom>/.
  - JSON file describing all loại hàng -> nhóm -> khối -> mã.

Output JSON shape:
    {
        "loai_hangs": {
            "<slug>": {
                "nhoms": [
                    { "nhom": "<key>", "sheet_name": "...", "khoi": [...], "orphan_textboxes": [...] },
                    ...
                ]
            },
            ...
        }
    }

Usage:
    python scripts/parse_visual_picker_excel.py <xlsx_path> <out_dir>
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
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

# sheet_name -> (loai_hang_slug, nhom_key)
# slug is used in image paths (positions/<slug>/<nhom>/...) and to look up
# the human-readable name via SLUG_TO_TEN_LOAI in the importer.
SHEET_MAP: dict[str, tuple[str, str]] = {
    "AO VEST -CHINH":      ("aovest",  "chinh"),
    "AO VEST - LOT":       ("aovest",  "lot"),
    "AO VEST - NHAN DIEN": ("aovest",  "nhan_dien"),
    "QUAN TAY":            ("quantay", "chinh"),
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
    """Return list of {name, state, sheet_xml_path, drawing_xml_path}."""
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
        rels_path = sheet_xml_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
        drawing_xml_path: Optional[str] = None
        if rels_path in z.namelist():
            srels = ET.fromstring(z.read(rels_path))
            for rr in srels.findall("rel:Relationship", NS):
                if "drawing" in rr.get("Type", ""):
                    t = rr.get("Target")
                    drawing_xml_path = "xl/" + t.lstrip("./").replace("../", "")
        sheets.append({
            "name": name,
            "state": state,
            "sheet_xml_path": sheet_xml_path,
            "drawing_xml_path": drawing_xml_path,
        })
    return sheets


def parse_sheet_cells(z: zipfile.ZipFile, sheet_xml_path: str, shared: list[str]) -> dict[str, str]:
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
    """Return {'pictures': [...], 'textboxes': [...]} with EMU positions."""
    root = ET.fromstring(z.read(drawing_xml_path))
    rels_path = drawing_xml_path.replace("drawings/", "drawings/_rels/") + ".rels"
    rid_to_target: dict[str, str] = {}
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
                "rot": int(rot) / 60000.0 if rot else 0.0,
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


def build_khoi_tables(cells: dict[str, str]) -> list[dict]:
    """Walk the sheet rows. A khoi header row has col A = short prefix (1-3 alpha letters)
    AND col B = khoi name. Codes are in col E, labels in col D.

    Returns list of {prefix, ten_khoi, start_row, end_row, codes: {code: label}}.
    """
    by_row: dict[int, dict[str, str]] = defaultdict(dict)
    for ref, val in cells.items():
        m = re.match(r"^([A-Z]+)(\d+)$", ref)
        if not m:
            continue
        by_row[int(m.group(2))][m.group(1)] = val

    header_rows: list[tuple[int, str, str]] = []
    for row, cols in by_row.items():
        a_val = (cols.get("A") or "").strip()
        b_val = (cols.get("B") or "").strip()
        if not a_val or not b_val:
            continue
        if not re.match(r"^[A-Z]{1,3}$", a_val):
            continue
        if a_val in {"A", "B", "C", "D", "E"}:
            if b_val in {"Tên", "Mã", "Mã ", "Tên ", "Cổ"}:
                if a_val == "C" and b_val == "Cổ":
                    pass
                else:
                    continue
        if b_val in {"Tên", "Mã", "Mã ", "Tên "}:
            continue
        header_rows.append((row, a_val, b_val))

    header_rows.sort(key=lambda x: x[0])

    tables: list[dict] = []
    for i, (hrow, prefix, ten_khoi) in enumerate(header_rows):
        next_hrow = header_rows[i + 1][0] if i + 1 < len(header_rows) else 10**9
        codes: dict[str, str] = {}
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
    """Fallback row-based matcher. Allow image to be anchored a few rows BEFORE its header
    (some Excel layouts position the image above the table). Pick the header whose start_row
    is the largest one ≤ image_from_row + ROW_SLACK_BEFORE."""
    ROW_SLACK_BEFORE = 5
    if image_from_row is None:
        return None
    best = None
    for t in tables:
        if t["start_row"] - ROW_SLACK_BEFORE <= image_from_row:
            if best is None or t["start_row"] > best["start_row"]:
                best = t
    return best


def assign_pictures_to_khois(
    pics: list[dict],
    textboxes: list[dict],
    khoi_tables: list[dict],
) -> list[Optional[dict]]:
    """Match each picture to a khoi table. Strategy:
      1. Pre-bucket textboxes to pictures by bbox containment.
      2. For each picture, derive its dominant textbox prefix (e.g. T1,T2,T3 -> 'T')
         and match to the khoi header with that prefix nearest to the image's from_row.
      3. For unmatched pictures, fall back to row-based match.

    Each khoi can only be assigned to one picture; first picture to claim it wins.
    """
    pic_prefix_counts: list[Counter] = [Counter() for _ in pics]
    for tb in textboxes:
        cx = tb["off_x"] + tb["ext_cx"] / 2
        cy = tb["off_y"] + tb["ext_cy"] / 2
        m = re.match(r"^([A-Z]+)\d+$", tb["text"])
        if not m:
            continue
        for i, pic in enumerate(pics):
            if point_in_bbox(cx, cy, pic):
                pic_prefix_counts[i][m.group(1)] += 1
                break

    used_khoi_ids: set[int] = set()
    pic_khoi: list[Optional[dict]] = [None] * len(pics)

    # First pass: prefix-driven match.
    for i, pic in enumerate(pics):
        if not pic_prefix_counts[i]:
            continue
        top_prefix = pic_prefix_counts[i].most_common(1)[0][0]
        candidates = [
            t for t in khoi_tables
            if t["prefix"] == top_prefix and id(t) not in used_khoi_ids
        ]
        if candidates and pic["from_row"] is not None:
            candidates.sort(key=lambda t: abs(t["start_row"] - pic["from_row"]))
            pic_khoi[i] = candidates[0]
            used_khoi_ids.add(id(candidates[0]))
        elif candidates:
            pic_khoi[i] = candidates[0]
            used_khoi_ids.add(id(candidates[0]))

    # Second pass: row-based fallback for any pic still without a khoi.
    for i, pic in enumerate(pics):
        if pic_khoi[i] is not None:
            continue
        khoi = match_image_to_khoi(pic["from_row"], khoi_tables)
        if khoi and id(khoi) not in used_khoi_ids:
            pic_khoi[i] = khoi
            used_khoi_ids.add(id(khoi))

    return pic_khoi


def point_in_bbox(x: float, y: float, bb: dict) -> bool:
    return bb["off_x"] <= x <= bb["off_x"] + bb["ext_cx"] and \
           bb["off_y"] <= y <= bb["off_y"] + bb["ext_cy"]


def process_sheet(
    z: zipfile.ZipFile,
    sh: dict,
    shared: list[str],
    slug: str,
    nhom_key: str,
    out_dir: Path,
) -> dict:
    """Build the nhom entry for one sheet."""
    cells = parse_sheet_cells(z, sh["sheet_xml_path"], shared)
    khoi_tables = build_khoi_tables(cells)
    drw = parse_drawing(z, sh["drawing_xml_path"])

    pic_khoi = assign_pictures_to_khois(drw["pictures"], drw["textboxes"], khoi_tables)

    TOL_EMU = 200000

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

        img_dir = out_dir / "positions" / slug / nhom_key
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
            rel_path = f"positions/{slug}/{nhom_key}/{fname}"
            if ext == "png":
                png_path = rel_path
            elif ext == "svg":
                svg_path = rel_path
        if pic.get("svg_target"):
            svg_zip = "xl/" + pic["svg_target"].lstrip("./").replace("../", "")
            if svg_zip in z.namelist():
                sfname = f"{base_name}.svg"
                (img_dir / sfname).write_bytes(z.read(svg_zip))
                svg_path = f"positions/{slug}/{nhom_key}/{sfname}"

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

    return {
        "nhom": nhom_key,
        "sheet_name": sh["name"],
        "khoi": khoi_list,
        "orphan_textboxes": [t["text"] for t in orphans],
    }


def build_structure(xlsx_path: str, out_dir: Path) -> dict:
    z = zipfile.ZipFile(xlsx_path)
    shared = read_shared_strings(z)
    sheets = parse_workbook_sheets(z)

    loai_hangs: dict[str, dict] = {}

    for sh in sheets:
        mapping = SHEET_MAP.get(sh["name"])
        if not mapping or sh["state"] != "visible" or not sh["drawing_xml_path"]:
            continue
        slug, nhom_key = mapping
        nhom_entry = process_sheet(z, sh, shared, slug, nhom_key, out_dir)
        loai_hangs.setdefault(slug, {"nhoms": []})["nhoms"].append(nhom_entry)

    return {"loai_hangs": loai_hangs}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: parse_visual_picker_excel.py <xlsx_path> <out_dir>")
        sys.exit(1)
    xlsx = sys.argv[1]
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    data = build_structure(xlsx, out_dir)
    out_json = out_dir / "visual_picker.json"
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_json}")
    for slug, entry in data["loai_hangs"].items():
        print(f"\n[loại hàng slug={slug}]")
        for n in entry["nhoms"]:
            print(f"   nhom={n['nhom']} sheet={n['sheet_name']} khois={len(n['khoi'])}")
            for k in n["khoi"]:
                with_label = sum(1 for h in k["hotspots"] if h["label"])
                print(f"      prefix={k['prefix']:5}  hotspots={len(k['hotspots']):3}  labeled={with_label:3}  img={k['image_png']}")
            if n["orphan_textboxes"]:
                print(f"      ORPHAN textboxes: {n['orphan_textboxes']}")
