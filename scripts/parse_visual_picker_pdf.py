"""Parse a visual-picker PDF (exported from Canva) into structured JSON + images.

Each page represents one bộ phận (khối). Layout per page:
  - Left side: garment image with position-code labels + arrows pointing to dots
  - Right side: detail table mapping mã → tên chi tiết
  - Header: sản phẩm name, bộ phận code/name, lớp (layer) info

Extracts per page:
  - Garment image (PNG) from the embedded PDF image.
  - Table data: bộ phận code, name, and all chi tiết (mã, tên).
  - Hotspot positions: dot markers on the garment, matched to codes via arrow tracing.

Output JSON is compatible with the Excel parser's format so import_visual_picker_to_db.py
works unchanged.

Usage:
    python scripts/parse_visual_picker_pdf.py <pdf_path> <loai_hang_slug> <out_dir>

Example:
    python scripts/parse_visual_picker_pdf.py "Mặt phải.pdf" aokhoac_thethao scripts/out
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber
import pymupdf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CODE_RE = re.compile(r'^[A-Z]+\(\d+\)\s*-\s*\d+$')
BOPHAN_RE = re.compile(r'^([A-Z]+)\((\d+)\)$')
LAYER_RE = re.compile(r'[Ll]ớp\s*(\d+)')
PROX = 12
MAX_ARROW_LEN = 400
DOT_MERGE_PX = 8
DOT_MIN = 3
DOT_MAX = 30
ARROW_DOT_THRESHOLD = 30


def merge_code_words(words: list[dict]) -> list[dict]:
    """Merge adjacent word fragments into full codes.

    pdfplumber sometimes splits "T(3)-1" into "T(3)" + "-1".
    """
    merged = []
    skip = set()
    sorted_words = sorted(words, key=lambda w: (w['top'], w['x0']))
    for i, w in enumerate(sorted_words):
        if i in skip:
            continue
        if BOPHAN_RE.match(w['text'].strip()):
            for j in range(i + 1, min(i + 3, len(sorted_words))):
                if j in skip:
                    continue
                w2 = sorted_words[j]
                if abs(w2['top'] - w['top']) > 5:
                    break
                if w2['x0'] - w['x1'] < 15:
                    combined = w['text'].strip() + w2['text'].strip()
                    if CODE_RE.match(combined):
                        merged.append({
                            'text': combined,
                            'x0': w['x0'],
                            'x1': w2['x1'],
                            'top': min(w['top'], w2['top']),
                            'bottom': max(w['bottom'], w2['bottom']),
                        })
                        skip.add(j)
                        break
            else:
                merged.append(w)
        else:
            merged.append(w)
    return merged


def cluster_dots(page, page_width: float, page_height: float) -> list[tuple[float, float]]:
    """Find small circle/dot markers on the page from curve primitives."""
    raw: list[tuple[float, float]] = []
    for c in page.curves:
        if 'pts' not in c:
            continue
        xs = [p[0] for p in c['pts']]
        ys = [p[1] for p in c['pts']]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if DOT_MIN < w < DOT_MAX and DOT_MIN < h < DOT_MAX:
            raw.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))

    dots: list[tuple[float, float]] = []
    used: set[int] = set()
    for i, (x, y) in enumerate(raw):
        if i in used:
            continue
        cluster = [(x, y)]
        used.add(i)
        for j, (x2, y2) in enumerate(raw):
            if j in used:
                continue
            if abs(x - x2) < DOT_MERGE_PX and abs(y - y2) < DOT_MERGE_PX:
                cluster.append((x2, y2))
                used.add(j)
        dots.append((
            sum(p[0] for p in cluster) / len(cluster),
            sum(p[1] for p in cluster) / len(cluster),
        ))
    return dots


def trace_segments(sx: float, sy: float, lines: list[dict],
                   visited: set[int], depth: int = 0) -> tuple[float, float]:
    """Follow connected line segments from a starting point."""
    if depth > 8:
        return sx, sy
    for i, l in enumerate(lines):
        if i in visited:
            continue
        pts = [(l['x0'], l['top']), (l['x1'], l['bottom'])]
        for pi, (px, py) in enumerate(pts):
            if abs(px - sx) < PROX and abs(py - sy) < PROX:
                visited.add(i)
                ox, oy = pts[1 - pi]
                return trace_segments(ox, oy, lines, visited, depth + 1)
    return sx, sy


def match_codes_to_dots(
    codes: dict[str, dict],
    dots: list[tuple[float, float]],
    arrow_lines: list[dict],
    img_bbox: tuple[float, float, float, float],
) -> dict[str, tuple[float, float]]:
    """Match position-code labels to dot markers via arrow-line tracing."""
    img_x0, img_y0, img_x1, img_y1 = img_bbox
    result: dict[str, tuple[float, float]] = {}
    used_dots: set[int] = set()

    for ct, w in sorted(codes.items(), key=lambda x: x[1]['top']):
        cy = (w['top'] + w['bottom']) / 2
        wcx = (w['x0'] + w['x1']) / 2

        candidates = []
        for i, l in enumerate(arrow_lines):
            if abs(l['top'] - l['bottom']) > 2:
                continue
            ly = (l['top'] + l['bottom']) / 2
            if abs(ly - cy) > 25:
                continue
            line_len = abs(l['x1'] - l['x0'])
            if line_len < 5:
                continue
            ldist = min(abs(l['x0'] - w['x0']), abs(l['x0'] - w['x1']),
                        abs(l['x1'] - w['x0']), abs(l['x1'] - w['x1']))
            if ldist < 120:
                candidates.append((i, l, abs(ly - cy), ldist))

        best_match = None
        for idx, l, _, _ in sorted(candidates, key=lambda x: (x[2], x[3])):
            for ex, ey in [(l['x0'], (l['top'] + l['bottom']) / 2),
                           (l['x1'], (l['top'] + l['bottom']) / 2)]:
                visited = {idx}
                fx, fy = trace_segments(ex, ey, arrow_lines, visited)
                avail = [(d, di) for di, d in enumerate(dots) if di not in used_dots]
                if not avail:
                    continue
                nearest = min(avail, key=lambda x: ((x[0][0] - fx) ** 2 + (x[0][1] - fy) ** 2) ** 0.5)
                nd = ((nearest[0][0] - fx) ** 2 + (nearest[0][1] - fy) ** 2) ** 0.5
                if nd < ARROW_DOT_THRESHOLD and (best_match is None or nd < best_match[2]):
                    best_match = (nearest[0], nearest[1], nd)

        if best_match:
            used_dots.add(best_match[1])
            result[ct] = best_match[0]

    # Fallback: match remaining codes to remaining dots by y-proximity
    unmatched_codes = [ct for ct in codes if ct not in result]
    unmatched_dots = [(d, di) for di, d in enumerate(dots) if di not in used_dots]
    if unmatched_codes and unmatched_dots:
        for ct in sorted(unmatched_codes, key=lambda t: codes[t]['top']):
            cy = (codes[ct]['top'] + codes[ct]['bottom']) / 2
            if not unmatched_dots:
                break
            nearest = min(unmatched_dots,
                          key=lambda x: abs(x[0][1] - cy))
            nd_y = abs(nearest[0][1] - cy)
            if nd_y < 50:
                result[ct] = nearest[0]
                unmatched_dots.remove(nearest)

    return result


def parse_table(page) -> dict:
    """Extract header info and chi tiết table from the page."""
    tables = page.extract_tables()
    if not tables:
        return {}

    main_table = max(tables, key=len)
    info: dict = {
        'san_pham': None,
        'lop': None,
        'bo_phan_code': None,
        'bo_phan_name': None,
        'chi_tiet': [],
    }

    for row in main_table:
        cells = [c.strip() if c else '' for c in row]
        joined = ' '.join(cells)

        if info['san_pham'] is None and any('Sản phẩm' in c for c in cells if c):
            for c in cells:
                if c and c not in ('Sản phẩm', '', 'Bảng chi tiết') and 'Bảng' not in c and 'Lớp' not in c:
                    info['san_pham'] = c.strip()
                    break

        m = LAYER_RE.search(joined)
        if m and info['lop'] is None:
            info['lop'] = int(m.group(1))

        if info['bo_phan_code'] is None:
            for c in cells:
                bm = BOPHAN_RE.match(c.strip()) if c else None
                if bm:
                    info['bo_phan_code'] = c.strip()
                    idx = cells.index(c)
                    if idx + 1 < len(cells) and cells[idx + 1]:
                        info['bo_phan_name'] = cells[idx + 1].strip()
                    break

        if any(c.isdigit() for c in cells if c):
            ma_idx = None
            ten_idx = None
            ma_tong_idx = None
            for i, c in enumerate(cells):
                if c and c.isdigit() and ma_idx is None:
                    ma_idx = i
                elif c and CODE_RE.match(c.replace(' ', '')) and ma_tong_idx is None:
                    ma_tong_idx = i
            if ma_idx is not None and ma_tong_idx is not None:
                ten_str = ''
                for i in range(ma_idx + 1, ma_tong_idx):
                    if cells[i]:
                        ten_str = cells[i].strip()
                        break
                code_text = cells[ma_tong_idx].replace(' ', '').strip()
                if ten_str and code_text:
                    info['chi_tiet'].append({
                        'ma': int(cells[ma_idx]),
                        'ten': ten_str,
                        'ma_tong': code_text,
                    })

    return info


def extract_images_pymupdf(pdf_path: str, page_idx: int, out_dir: Path,
                           slug: str, nhom_key: str, prefix: str,
                           ) -> str | None:
    """Extract the main garment image from a PDF page and save as PNG."""
    doc = pymupdf.open(pdf_path)
    page = doc[page_idx]
    imgs = page.get_images(full=True)
    if not imgs:
        doc.close()
        return None

    best_xref = None
    best_size = 0
    for img_info in imgs:
        xref = img_info[0]
        pix = pymupdf.Pixmap(doc, xref)
        size = pix.width * pix.height
        if size > best_size:
            best_size = size
            best_xref = xref

    if best_xref is None:
        doc.close()
        return None

    pix = pymupdf.Pixmap(doc, best_xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

    img_dir = out_dir / "positions" / slug / nhom_key
    img_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{nhom_key}_{prefix.lower()}_{page_idx + 1}.png"
    out_path = img_dir / fname
    pix.save(str(out_path))
    doc.close()
    return f"positions/{slug}/{nhom_key}/{fname}"


def format_ma_vi_tri(code: str) -> str:
    """Normalize whitespace in code: 'T(2)-1' stays; 'T(2) - 1' -> 'T(2) - 1'."""
    m = re.match(r'^([A-Z]+)\((\d+)\)-(\d+)$', code)
    if m:
        return f"{m.group(1)}({m.group(2)}) - {m.group(3)}"
    return code


def process_page(
    pdf_plumber_page,
    page_idx: int,
    pdf_path: str,
    slug: str,
    out_dir: Path,
) -> dict | None:
    """Process one PDF page into a khoi entry."""
    info = parse_table(pdf_plumber_page)
    if not info.get('bo_phan_code') or not info.get('chi_tiet'):
        return None

    bm = BOPHAN_RE.match(info['bo_phan_code'])
    if not bm:
        return None
    prefix = bm.group(1)
    layer = int(bm.group(2))
    nhom_key = f"lop_{layer}"

    imgs = pdf_plumber_page.images
    if not imgs:
        return None

    main_img = max(imgs, key=lambda i: i['width'] * i['height'])
    img_x0, img_y0 = main_img['x0'], main_img['top']
    img_x1, img_y1 = main_img['x1'], main_img['bottom']
    img_w = img_x1 - img_x0
    img_h = img_y1 - img_y0

    words = merge_code_words(pdf_plumber_page.extract_words())

    image_codes: dict[str, dict] = {}
    table_x_threshold = 1100
    for w in words:
        t = w['text'].replace(' ', '')
        if CODE_RE.match(t) and w['x0'] < table_x_threshold:
            if t not in image_codes:
                image_codes[t] = w

    dots = cluster_dots(pdf_plumber_page,
                        pdf_plumber_page.width, pdf_plumber_page.height)

    all_lines = pdf_plumber_page.lines
    arrow_lines = [l for l in all_lines
                   if abs(l['x1'] - l['x0']) + abs(l['bottom'] - l['top']) < MAX_ARROW_LEN]

    code_to_dot = match_codes_to_dots(
        image_codes, dots, arrow_lines,
        (img_x0, img_y0, img_x1, img_y1),
    )

    chi_tiet_map = {ct['ma_tong']: ct['ten'] for ct in info['chi_tiet']}

    hotspots: list[dict] = []
    for ct in info['chi_tiet']:
        code = ct['ma_tong']
        dot = code_to_dot.get(code)
        if dot:
            x_pct = round((dot[0] - img_x0) / img_w, 5)
            y_pct = round((dot[1] - img_y0) / img_h, 5)
        else:
            x_pct = 0.5
            y_pct = round((ct['ma'] - 0.5) / max(len(info['chi_tiet']), 1), 5)

        hotspots.append({
            'ma': format_ma_vi_tri(code),
            'label': ct['ten'],
            'x_pct': x_pct,
            'y_pct': y_pct,
            'w_pct': 0.04,
            'h_pct': 0.04,
            'rotation': 0.0,
        })

    image_png = extract_images_pymupdf(pdf_path, page_idx, out_dir, slug, nhom_key, prefix)

    n_matched = sum(1 for ct in info['chi_tiet'] if ct['ma_tong'] in code_to_dot)
    n_total = len(info['chi_tiet'])

    return {
        'ten_khoi': info['bo_phan_name'],
        'prefix': prefix,
        'nhom_key': nhom_key,
        'lop': layer,
        'image_emu': {
            'off_x': int(img_x0 * 914400 / 72),
            'off_y': int(img_y0 * 914400 / 72),
            'cx': int(img_w * 914400 / 72),
            'cy': int(img_h * 914400 / 72),
        },
        'image_png': image_png,
        'image_svg': None,
        'hotspots': hotspots,
        '_match_stats': f'{n_matched}/{n_total}',
    }


def build_structure(pdf_path: str, slug: str, out_dir: Path,
                    merge_existing: bool = False) -> dict:
    """Process all pages and build the output structure.

    If merge_existing=True, reads the existing visual_picker.json and preserves
    nhoms/slugs not produced by this PDF (e.g. lop_1 from Excel while PDF adds lop_2+3).
    """
    pdf = pdfplumber.open(pdf_path)
    nhoms: dict[str, list[dict]] = defaultdict(list)

    for page_idx in range(len(pdf.pages)):
        page = pdf.pages[page_idx]
        result = process_page(page, page_idx, pdf_path, slug, out_dir)
        if result is None:
            print(f"  Page {page_idx + 1}: skipped (no data)")
            continue

        nhom_key = result.pop('nhom_key')
        lop = result.pop('lop')
        stats = result.pop('_match_stats')
        nhoms[nhom_key].append(result)
        print(f"  Page {page_idx + 1}: {result['prefix']}({lop}) {result['ten_khoi']}"
              f"  hotspots={stats}  img={result['image_png']}")

    pdf.close()

    existing: dict = {'loai_hangs': {}}
    out_json = out_dir / "visual_picker.json"
    if merge_existing and out_json.exists():
        existing = json.loads(out_json.read_text(encoding='utf-8'))
        print(f"\n  Merging with existing: {out_json}")

    new_nhom_keys = set(nhoms.keys())
    nhom_list = []

    if slug in existing.get('loai_hangs', {}):
        for old_nhom in existing['loai_hangs'][slug].get('nhoms', []):
            if old_nhom['nhom'] not in new_nhom_keys:
                nhom_list.append(old_nhom)
                print(f"  Kept existing nhom: {old_nhom['nhom']} ({len(old_nhom['khoi'])} khoi)")

    for nhom_key in sorted(nhoms.keys()):
        nhom_list.append({
            'nhom': nhom_key,
            'sheet_name': nhom_key,
            'khoi': nhoms[nhom_key],
        })

    nhom_list.sort(key=lambda n: n['nhom'])

    all_loai_hangs = dict(existing.get('loai_hangs', {}))
    all_loai_hangs[slug] = {'nhoms': nhom_list}

    return {'loai_hangs': all_loai_hangs}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    merge = '--merge' in flags

    if len(args) < 3:
        print("Usage: parse_visual_picker_pdf.py [--merge] <pdf_path> <loai_hang_slug> <out_dir>")
        print("Example: parse_visual_picker_pdf.py --merge 'Mặt phải.pdf' aokhoac_thethao scripts/out")
        print("\n  --merge  Keep existing nhoms/slugs in visual_picker.json")
        sys.exit(1)

    pdf_path = args[0]
    slug = args[1]
    out_dir = Path(args[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing: {pdf_path}")
    print(f"Slug: {slug}")
    if merge:
        print("Mode: merge (preserving existing data)")
    data = build_structure(pdf_path, slug, out_dir, merge_existing=merge)

    out_json = out_dir / "visual_picker.json"
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_json}")

    for slug_key, entry in data['loai_hangs'].items():
        print(f"\n[{slug_key}]")
        for n in entry['nhoms']:
            print(f"  nhom={n['nhom']}  khois={len(n['khoi'])}")
            for k in n['khoi']:
                labeled = sum(1 for h in k['hotspots'] if h['label'])
                print(f"    prefix={k['prefix']:5s}  {k['ten_khoi'] or '?':20s}"
                      f"  hotspots={len(k['hotspots']):3d}  labeled={labeled:3d}"
                      f"  img={k['image_png']}")
