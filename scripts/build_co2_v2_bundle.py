"""Build the portable Co-2 v2 visual bundle from the reviewed PDF.

Usage:
    python scripts/build_co2_v2_bundle.py "E:/Downloads/Co-2 (1).pdf"

Writes scripts/data/co2_v2_visual_catalog.json and the rendered illustration
PNGs under scripts/assets/visual_picker/positions/<slug>/v2/. The deploy step
(scripts/deploy_co2_v2_visual_catalog.py) needs only those files, not the PDF.

The PDF contains earlier text hidden beneath later edits. Only text that is
actually painted last (not covered by a later fill) is read. Details come from
the table (stt + name); position codes are formed as <block prefix>-<stt> and
cross-checked against the table "Mã tổng" column and the printed image labels.
Every disagreement must be listed in SOURCE_FIXES/LABEL_FIXES below, otherwise
the build stops.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import unicodedata
from pathlib import Path

import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "scripts/data/co2_v2_visual_catalog.json"
ASSET_ROOT = ROOT / "scripts/assets/visual_picker"
SCALE = 2  # render scale; 2x keeps printed codes legible on tablets
VERSION_CODE = "co2-v2"
VERSION_NAME = "Visual Co-2 lần 2"

PRODUCTS = {
    "ao_dpyt": "Áo đồng phục y tế",
    "quan_dpyt": "Quần đồng phục y tế",
    "quan_thethao": "Quần thể thao",
    "yem_thethao": "Yếm thể thao",
    "aokhoac_thethao": "Áo khoác thể thao nhiều lớp",
}

# page -> (product slug, nhom, block name, code prefix printed on the image)
# Page 9 repeats page 5; page 56 is an artwork sheet; page 57+ is not used.
PAGES = {
    1: ("ao_dpyt", "chinh", "Cổ", "Cô"),
    2: ("ao_dpyt", "chinh", "Thân trước", "Th"),
    3: ("ao_dpyt", "chinh", "Lưng", "Lư"),
    4: ("ao_dpyt", "chinh", "Tay", "Ta"),
    5: ("quan_dpyt", "chinh", "Nhãn mác", "Nh"),
    6: ("quan_dpyt", "chinh", "Lưng", "Lư"),
    7: ("quan_dpyt", "chinh", "Thân", "Th"),
    8: ("quan_dpyt", "chinh", "Ống", "Ôn"),
    10: ("quan_thethao", "chinh", "Lưng", "Lư"),
    11: ("quan_thethao", "chinh", "Thân", "Th"),
    12: ("quan_thethao", "chinh", "Ống", "Ôn"),
    13: ("quan_thethao", "chinh", "Barget", "Ba"),
    14: ("quan_thethao", "chinh", "Túi trước", "Tt"),
    15: ("quan_thethao", "chinh", "Túi sau", "Ts"),
    16: ("quan_thethao", "chinh", "Túi đùi", "Tđ"),
    17: ("quan_thethao", "chinh", "Cụm thắt lưng", "Tl"),
    18: ("quan_thethao", "chinh", "Cụm tháo ống", "Tô"),
    19: ("quan_thethao", "chinh", "Cụm mở ống", "Mô"),
    20: ("quan_thethao", "chinh", "Cụm chỉnh lai", "Cl"),
    21: ("quan_thethao", "chinh", "Nhãn mác", "Nh(1)"),
    22: ("yem_thethao", "chinh", "Yếm", "Yê"),
    23: ("yem_thethao", "chinh", "Lưng", "Lư"),
    24: ("yem_thethao", "chinh", "Thân", "Th"),
    25: ("yem_thethao", "chinh", "Ống", "Ôn"),
    26: ("yem_thethao", "chinh", "Barget", "Ba"),
    27: ("yem_thethao", "chinh", "Cụm dây kéo yếm", "Ky"),
    28: ("yem_thethao", "chinh", "Túi trước", "Tt"),
    29: ("yem_thethao", "chinh", "Túi sau", "Ts"),
    30: ("yem_thethao", "chinh", "Túi đùi", "Tđ"),
    31: ("yem_thethao", "chinh", "Cụm chỉnh eo", "Ce"),
    32: ("yem_thethao", "chinh", "Cụm chỉnh ống", "Cô"),
    33: ("yem_thethao", "chinh", "Lót", "Lo"),
    34: ("yem_thethao", "chinh", "Nhãn mác", "Nh(1)"),
    35: ("aokhoac_thethao", "lop_1", "Mũ", "Mu(1)"),
    36: ("aokhoac_thethao", "lop_1", "Cổ", "Cô(1)"),
    37: ("aokhoac_thethao", "lop_1", "Tà", "Tà(1)"),
    38: ("aokhoac_thethao", "lop_1", "Thân trước", "Th(1)"),
    39: ("aokhoac_thethao", "lop_1", "Lưng", "Lư(1)"),
    40: ("aokhoac_thethao", "lop_1", "Tay", "Ta(1)"),
    41: ("aokhoac_thethao", "lop_1", "Túi ngực", "Tn(1)"),
    42: ("aokhoac_thethao", "lop_1", "Túi tay", "Tt(1)"),
    43: ("aokhoac_thethao", "lop_1", "Túi sau", "Ts"),
    44: ("aokhoac_thethao", "lop_1", "Nhãn mác", "Nh(1)"),
    45: ("aokhoac_thethao", "lop_2", "Thân trước", "Th(2)"),
    46: ("aokhoac_thethao", "lop_2", "Lưng", "Lư(2)"),
    47: ("aokhoac_thethao", "lop_2", "Tay", "Ta(2)"),
    48: ("aokhoac_thethao", "lop_2", "Nhãn mác", "Nh(1)"),
    49: ("aokhoac_thethao", "lop_3", "Cổ", "Cô(3)"),
    50: ("aokhoac_thethao", "lop_3", "Thân trước", "Th(3)"),
    51: ("aokhoac_thethao", "lop_3", "Tay", "Ta(3)"),
    52: ("aokhoac_thethao", "lop_3", "Lưng", "Lư(3)"),
    53: ("aokhoac_thethao", "lop_3", "Túi ngực", "Tn(3)"),
    54: ("aokhoac_thethao", "lop_3", "Túi tay", "Tt(3)"),
    55: ("aokhoac_thethao", "lop_3", "Nhãn mác", "Nh(1)"),
}

# Reviewed disagreements between the table "Mã tổng" column and the row number.
# (page, stt) -> code printed in the table (code used = prefix-stt).
SOURCE_FIXES = {
    (1, 11): "Cô-10",       # Can lá cổ: duplicated Cô-10; image shows Cô-11
    (21, 15): "Nh(1)-14",   # Hình in: duplicated Nh(1)-14; image shows Nh(1)-15
    (34, 15): "Nh(1)-14",
    (44, 15): "Nh(1)-14",
    (48, 15): "Nh(1)-14",
    (55, 15): "Nh(1)-14",
}
# Pages whose "Mã tổng" column still uses an old prefix (image uses the new one).
TABLE_PREFIX_ALIAS = {49: "C(3)"}
# Pages where some named rows have an empty "Mã tổng" cell (code = prefix-stt).
TABLE_CODE_BLANK_OK = {49: {7, 8, 9}}
# Reviewed image-label corrections: page -> {printed label key: real code key}.
# Keys are normalised (no accents/spaces/parentheses). A list value renames the
# n-th occurrence (top-to-bottom) of a duplicated label.
LABEL_FIXES = {
    46: {"c2-%d" % i: "lu2-%d" % i for i in range(1, 9)},   # image still uses old C(2)
    47: {"t2-%d" % i: "ta2-%d" % i for i in range(1, 9)},   # image still uses old T(2)
    51: {"ta3-1": ["ta3-1", "ta3-2"]},                       # 2nd "Ta(3)-1" is Ta(3)-2
    52: {"l3-7": "lu3-7"},                                   # printed "L(3)-7"
    # Image numbering skips 5 (QLCL confirmed 2026-11-25: printed 6 => row 5, 7 => row 6).
    37: {"ta1-6": "ta1-5", "ta1-7": "ta1-6"},
}
# Printed labels that have no table row (cannot be selected until QLCL adds it).
KNOWN_UNMAPPED_LABELS: set = set()
# Labels missing from a drawing, placed from an identical reviewed diagram:
# page -> [(missing code key, reference page, align code key)].
# Page 23 (Yếm/Lưng) has the leader line to the button but no "Lư-7" text; the
# same waistband drawing on page 10 (Quần thể thao/Lưng) prints it.
ANCHOR_REFERENCES = {23: [("lu-7", 10, "lu-6")]}

LABEL_RE = re.compile(r"^[^\W\d_]+\(?\d?\)*\s*-?\s*\d+$", re.UNICODE)


def key(code: str) -> str:
    k = "".join(c for c in unicodedata.normalize("NFD", code) if not unicodedata.combining(c))
    k = k.lower().replace("đ", "d").replace(" ", "").replace("(", "").replace(")", "")
    if "-" not in k:  # e.g. "Lư11" printed without the separator
        k = re.sub(r"(?<=[a-z])(?=\d+$)", "-", k)
    return k


def visible_spans(page):
    """Spans that are painted and not covered by a later opaque fill."""
    # Edits are covered with filled rectangles (redrawn table cells). Images and
    # illustration paths are not treated as covers: their reported bbox ignores
    # clipping masks and often spans the table. seqno == texttrace seqno.
    page_area = page.rect.get_area()

    def is_rect(d):
        items = d["items"]
        if len(items) == 1 and items[0][0] in ("re", "qu"):
            return True
        return 3 <= len(items) <= 5 and all(
            it[0] == "l" and (abs(it[1].x - it[2].x) < .5 or abs(it[1].y - it[2].y) < .5)
            for it in items)

    def is_cover(d):
        r = pymupdf.Rect(d["rect"])
        white = all(c > 0.95 for c in d["fill"])
        # Coloured rectangles only count when they lie in the table half;
        # illustration backgrounds can spill into it under a clipping mask.
        return white or r.x0 >= page.rect.width * 0.6

    fills = [(d["seqno"], pymupdf.Rect(d["rect"])) for d in page.get_drawings()
             if d.get("fill") is not None and d["type"] in ("f", "fs") and is_rect(d)
             and pymupdf.Rect(d["rect"]).get_area() < page_area * 0.5 and is_cover(d)]
    spans = []
    for s in page.get_texttrace():
        text = "".join(chr(c[0]) for c in s["chars"])
        if not text.strip() or s.get("opacity", 1) == 0 or s["type"] == 3:
            continue
        rect = pymupdf.Rect(s["bbox"])
        center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        if any(i > s["seqno"] and r.contains(center) for i, r in fills):
            continue
        spans.append({"rect": rect, "text": text, "cy": center.y})
    return spans


def join_words(spans):
    """Join adjacent spans on one baseline (labels use two colours)."""
    out = []
    for s in sorted(spans, key=lambda s: (round(s["cy"]), s["rect"].x0)):
        prev = out[-1] if out else None
        gap = s["rect"].x0 - prev["rect"].x1 if prev else None
        # "Ta(3) -1" is printed with a space before the dash.
        limit = 7 if prev and (s["text"].lstrip().startswith("-") or prev["text"].rstrip().endswith(")")) else 3
        if prev and abs(prev["cy"] - s["cy"]) < 3 and -1 <= gap < limit:
            prev["text"] += s["text"]
            prev["rect"] |= s["rect"]
        else:
            out.append({"rect": pymupdf.Rect(s["rect"]), "text": s["text"], "cy": s["cy"]})
    for w in out:
        w["text"] = w["text"].strip()
    return out


def illustration_cell(page, boundary, first_row_y):
    """Inner rectangle of the merged illustration cell (excluding its borders)."""
    verticals, horizontals = [], []
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if r.width < 3 and r.height > 200 and boundary - 60 < r.x0 < boundary + 5:
            verticals.append(r.x0)
        if r.height < 3 and r.width > 300 and r.x0 < boundary:
            horizontals.append(r.y0)
    right = min(verticals) if verticals else boundary - 25
    # Border under the "Bộ phận" row: the closest line just below it (long
    # leader lines further down must not be mistaken for it).
    below = [y for y in horizontals if first_row_y < y < first_row_y + 30]
    top = min(below) if below else first_row_y + 18
    # Bottom border is stripped from the bitmap afterwards (strip_border_lines).
    return pymupdf.Rect(8, top + 3, right - 3, page.rect.height - 8)


def strip_border_lines(img, keep_right=0, keep_bottom=0, max_depth=80):
    """Crop away table border lines that run along the edges of the bitmap."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()

    def dark_ratio_row(y):
        return sum(1 for x in range(0, w, 2) if px[x, y] < 200) / (w / 2)

    def dark_ratio_col(x):
        return sum(1 for y in range(0, h, 2) if px[x, y] < 200) / (h / 2)

    def first_line(positions, ratio):
        """Position just past the first dark line run met while scanning."""
        found = None
        for p in positions:
            if ratio(p) > 0.6:
                found = p
            elif found is not None:
                return found
        return found

    # The page bottom sits below the table, so its border can be ~60px deep.
    b = first_line(range(h - 1, max(h - 1 - max_depth * 2, 0), -1), dark_ratio_row)
    bottom = b if b is not None and b >= keep_bottom else h
    t = first_line(range(0, min(max_depth, h)), dark_ratio_row)
    top = t + 1 if t is not None else 0
    r = first_line(range(w - 1, max(w - 1 - max_depth, 0), -1), dark_ratio_col)
    # A label printed across the border wins over removing the border.
    right = r if r is not None and r >= keep_right else w
    return img.crop((0, top, right, bottom)), top


def parse_page(page, pno):
    slug, nhom, block_name, prefix = PAGES[pno]
    spans = visible_spans(page)
    hdr_ma = [s for s in spans if s["text"].strip() == "Mã" and s["rect"].x0 > page.rect.width * 0.45]
    hdr_tong = [s for s in spans if s["text"].strip() == "Mã tổng"]
    if len(hdr_ma) != 1 or len(hdr_tong) != 1:
        raise ValueError(f"p{pno}: table header not found")
    hdr_ma, hdr_tong = hdr_ma[0], hdr_tong[0]
    boundary = hdr_ma["rect"].x0 - 12          # illustration | table
    code_col = hdr_tong["rect"].x0 - 12        # name | Mã tổng
    stt_cx = (hdr_ma["rect"].x0 + hdr_ma["rect"].x1) / 2
    head_y = hdr_ma["rect"].y1

    rows = []
    for s in spans:
        cx = (s["rect"].x0 + s["rect"].x1) / 2
        if s["cy"] > head_y and abs(cx - stt_cx) < 22 and s["text"].strip().isdigit():
            rows.append((int(s["text"]), s["cy"]))
    rows.sort(key=lambda r: r[1])
    if [r[0] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"p{pno}: row numbers not sequential: {[r[0] for r in rows]}")

    details = []
    for stt, cy in rows:
        same = [s for s in spans if abs(s["cy"] - cy) < 6]
        name = " ".join(s["text"].strip() for s in sorted(same, key=lambda s: s["rect"].x0)
                        if stt_cx + 22 < s["rect"].x0 < code_col)
        table_code = "".join(s["text"] for s in same if s["rect"].x0 >= code_col).strip()
        if not name and not table_code:
            continue  # numbered but empty template row
        code = f"{prefix}-{stt}"
        expected_table = SOURCE_FIXES.get((pno, stt))
        if pno in TABLE_PREFIX_ALIAS:
            expected_table = f"{TABLE_PREFIX_ALIAS[pno]}-{stt}"
        if not table_code and stt in TABLE_CODE_BLANK_OK.get(pno, ()):
            pass
        elif key(table_code) != key(code) and key(table_code) != key(expected_table or ""):
            raise ValueError(f"p{pno} row {stt}: table code {table_code!r} != {code!r}")
        if not name:
            raise ValueError(f"p{pno} row {stt}: empty name")
        details.append({"stt": stt, "code": code, "label": re.sub(r"\s+", " ", name),
                        "table_code": table_code, "row_cy": cy})

    first_row_y = rows[0][1]
    bp_spans = [s for s in spans if abs(s["cy"] - first_row_y) < 6 and s["rect"].x1 < boundary]
    bp_text = " ".join(s["text"].strip() for s in sorted(bp_spans, key=lambda s: s["rect"].x0))

    illu_top = first_row_y + 10
    words = join_words([s for s in spans if s["rect"].x1 < boundary and s["cy"] > illu_top])
    labels = [w for w in words if LABEL_RE.match(w["text"])]
    fixes = LABEL_FIXES.get(pno, {})
    seen, anchors = {}, {}
    for w in sorted(labels, key=lambda w: (w["cy"], w["rect"].x0)):
        k = key(w["text"])
        fix = fixes.get(k)
        if isinstance(fix, list):
            n = seen.get(k, 0)
            seen[k] = n + 1
            k = fix[n]
        elif fix:
            k = fix
        # Printed text that is not exactly the final code gets repainted.
        w["repaint"] = key(w["text"]) != k or not re.fullmatch(r"[^\W\d_]+(\(\d\))?-\d+", w["text"].replace(" ", ""))
        if k in anchors:
            raise ValueError(f"p{pno}: duplicate image label {w['text']!r}")
        anchors[k] = w
    return {
        "page": pno, "slug": slug, "nhom": nhom, "block": block_name, "prefix": prefix,
        "bp_text": bp_text, "details": details, "anchors": anchors,
        "clip": illustration_cell(page, boundary, first_row_y),
    }


LABEL_GREEN = (0, 150, 70)
LABEL_BLUE = (35, 60, 235)
# The PDF embeds only subsets of Faustina-Bold, so use a serif with full
# Vietnamese coverage for repainted labels.
FONT_CANDIDATES = ["C:/Windows/Fonts/timesbd.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]


def repaint_labels(img, pix, parsed):
    """Paint the corrected code over mis-printed/missing labels (same 2-colour style)."""
    from PIL import ImageDraw, ImageFont
    font_path = next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)
    draw = ImageDraw.Draw(img)
    done = []
    for d in parsed["details"]:
        a = parsed["anchors"].get(key(d["code"]))
        if not a or not (a.get("repaint") or a.get("reference")):
            continue
        r = a["rect"]
        box = [(r.x0 - pix.x / SCALE) * SCALE - 2, (r.y0 - pix.y / SCALE) * SCALE - 1,
               (r.x1 - pix.x / SCALE) * SCALE + 2, (r.y1 - pix.y / SCALE) * SCALE + 1]
        size = int((box[3] - box[1]) * 0.78)
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        head, num = d["code"].rsplit("-", 1)
        tw = draw.textlength(head + "-" + num, font=font)
        box[2] = max(box[2], box[0] + tw + 4)
        draw.rectangle(box, fill="white")
        x, y = box[0] + 2, box[1] + (box[3] - box[1] - size) / 2 - size * 0.1
        draw.text((x, y), head, font=font, fill=LABEL_GREEN)
        draw.text((x + draw.textlength(head, font=font), y), "-" + num, font=font, fill=LABEL_BLUE)
        a["rect"] = pymupdf.Rect(r.x0, r.y0, r.x0 + (box[2] - box[0]) / SCALE - 1, r.y1)
        done.append(d["code"])
    return done


def render(page, parsed):
    clip = pymupdf.Rect(parsed["clip"])
    rects = [a["rect"] for a in parsed["anchors"].values()]
    if rects:  # labels may be printed across the cell border
        clip.x1 = max(clip.x1, max(r.x1 for r in rects) + 6)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=clip, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    parsed["repainted"] = repaint_labels(img, pix, parsed)
    keep_right = keep_bottom = 0
    if rects:
        keep_right = int((max(r.x1 for r in rects) + 4 - pix.x / SCALE) * SCALE)
        keep_bottom = int((max(r.y1 for r in rects) + 4 - pix.y / SCALE) * SCALE)
    img, shift_y = strip_border_lines(img, keep_right, keep_bottom)
    # Trim white margins, keeping every label inside.
    gray = img.convert("L").point(lambda v: 255 if v < 240 else 0)
    bbox = gray.getbbox() or (0, 0, img.width, img.height)
    pad = 14
    box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
           min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
    img = img.crop(box)
    ox = pix.x / SCALE + box[0] / SCALE   # page coordinates of the crop origin
    oy = pix.y / SCALE + (shift_y + box[1]) / SCALE
    w, h = img.width / SCALE, img.height / SCALE
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), (ox, oy, w, h), img.size


def build(pdf_path: Path):
    doc = pymupdf.open(pdf_path)
    products = {slug: {"name": name, "version_code": VERSION_CODE,
                       "version_name": VERSION_NAME, "blocks": []}
                for slug, name in PRODUCTS.items()}
    report = []
    for pno in sorted(PAGES):
        page = doc[pno - 1]
        parsed = parse_page(page, pno)
        for missing_key, ref_pno, align_key in ANCHOR_REFERENCES.get(pno, []):
            if missing_key in parsed["anchors"]:
                raise ValueError(f"p{pno}: {missing_key} is printed now; drop the reference")
            ref = parse_page(doc[ref_pno - 1], ref_pno)["anchors"]
            base, r_from, r_to = parsed["anchors"][align_key]["rect"], ref[align_key]["rect"], ref[missing_key]["rect"]
            dx, dy = r_to.x0 - r_from.x0, r_to.y0 - r_from.y0
            parsed["anchors"][missing_key] = {
                "rect": pymupdf.Rect(base.x0 + dx, base.y0 + dy, base.x0 + dx + r_to.width, base.y0 + dy + r_to.height),
                "text": ref[missing_key]["text"], "cy": base.y0 + dy, "reference": ref_pno}
        png, (ox, oy, w, h), size = render(page, parsed)
        digest = hashlib.sha256(png).hexdigest()
        rel = f"positions/{parsed['slug']}/v2/{parsed['nhom']}/p{pno:02d}_{digest[:12]}.png"
        target = ASSET_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            for old in target.parent.glob(f"p{pno:02d}_*.png"):
                old.unlink()
            target.write_bytes(png)

        hotspots, missing = [], []
        for d in parsed["details"]:
            a = parsed["anchors"].get(key(d["code"]))
            spot = {"code": d["code"], "label": d["label"], "rotation": 0}
            if a is None:
                # Not printed on the image: selectable from the table only.
                missing.append(d["code"])
                spot.update(x_pct=None, y_pct=None, w_pct=None, h_pct=None)
            else:
                r = a["rect"]
                r = pymupdf.Rect(r.x0 - 3, r.y0 - 2, r.x1 + 3, r.y1 + 2)
                if not (ox - 4 <= r.x0 and r.x1 <= ox + w + 4 and oy - 4 <= r.y0 and r.y1 <= oy + h + 4):
                    raise ValueError(f"p{pno}: label {d['code']} falls outside the cropped image")
                spot.update(
                    x_pct=round(max(0.0, (r.x0 - ox) / w), 5),
                    y_pct=round(max(0.0, (r.y0 - oy) / h), 5),
                    w_pct=round(min(1.0, r.width / w), 5),
                    h_pct=round(min(1.0, r.height / h), 5),
                )
            hotspots.append(spot)
        table_keys = {key(d["code"]) for d in parsed["details"]}
        extra = sorted(k for k in parsed["anchors"] if k not in table_keys)
        unexpected = [k for k in extra if (pno, k) not in KNOWN_UNMAPPED_LABELS]
        if unexpected:
            raise ValueError(f"p{pno}: image labels without table row: {unexpected}")

        product = products[parsed["slug"]]
        product["blocks"].append({
            "name": parsed["block"], "group": parsed["nhom"], "prefix": parsed["prefix"],
            "sort_order": len(product["blocks"]) + 1, "page": pno,
            "image_png": rel, "image_sha256": digest, "image_size": list(size),
            "hotspots": hotspots,
        })
        report.append(f"p{pno:02d} {PRODUCTS[parsed['slug']][:22]:22} {parsed['nhom']:6} "
                      f"{parsed['block']:16} [{parsed['bp_text']}] rows={len(hotspots):2} "
                      f"on_image={len(hotspots) - len(missing):2}"
                      + (f" table_only={missing}" if missing else "")
                      + (f" repainted={parsed['repainted']}" if parsed["repainted"] else "")
                      + (f" image_only={extra}" if extra else ""))
    bundle = {"format_version": 2, "source_file": pdf_path.name,
              "products": list(products.values())}
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(report))
    for p in bundle["products"]:
        print(f"{p['name']}: {len(p['blocks'])} blocks, "
              f"{sum(len(b['hotspots']) for b in p['blocks'])} codes")
    print(f"Bundle: {BUNDLE_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    build(ap.parse_args().pdf)
