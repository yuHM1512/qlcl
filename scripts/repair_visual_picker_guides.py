"""Restore PDF illustration layers without deleting catalog IDs or defect links.

Usage (preview first; add --apply to update the selected product):
  python scripts/repair_visual_picker_guides.py Co-2.pdf "Áo đồng phục y tế" ao_dpyt

Unlike extracting an image xref, rendering the illustration cell preserves PDF
clipping, vector leader lines, dots and labels. Existing hotspot IDs and labels
are retained. Hotspots are aligned with the printed codes, not guessed dots.
Requires pymupdf, psycopg2-binary and python-dotenv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
import pymupdf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CODE = re.compile(r"^[^\W\d_]+(?:\(\d+\))?-?\d+$", re.UNICODE)


def code_key(value):
    key = ''.join(c for c in unicodedata.normalize('NFD', value)
                  if not unicodedata.combining(c)).lower().replace(' ', '')
    # Some printed labels omit the separator (e.g. Lư11 on PDF pages 8/20).
    return re.sub(r'(?<=[a-zđ)])(?=\d+$)', '-', key)


def illustration(page):
    """Find the merged illustration cell from table geometry, not image bounds.

    Embedded image bounds can extend beyond both their clipping mask and page.
    The largest cell containing position labels is the illustration panel.
    """
    words = page.get_text('words')
    candidates = []
    for table in page.find_tables().tables:
        for cell in table.cells:
            rect = pymupdf.Rect(cell)
            labels = [w for w in words if CODE.fullmatch(w[4])
                      and rect.contains(pymupdf.Rect(w[:4]))]
            if len(labels) >= 2:
                candidates.append((rect.get_area(), rect, labels))
    if not candidates:
        raise ValueError(f'Page {page.number + 1}: no illustration cell')
    _, rect, labels = max(candidates, key=lambda c: c[0])
    # Exclude the table border; keep the complete illustration coordinate frame.
    clip = pymupdf.Rect(rect.x0 + 2, rect.y0 + 2, rect.x1 - 2, rect.y1 - 2)
    anchors = {}
    for x0, y0, x1, y1, code, *_ in labels:
        key = code_key(code)
        if key in anchors:
            raise ValueError(f'Page {page.number + 1}: duplicate visual code {code}')
        anchors[key] = ((x0 + x1) / 2 - clip.x0, (y0 + y1) / 2 - clip.y0)
    return clip, anchors


def prepare(pdf_path, product, slug, blocks, output, anchor_references=()):
    result = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            lines = page.get_text().splitlines()
            if product.casefold() not in [line.casefold() for line in lines[:4]]:
                continue
            matches = [b for b in blocks if b['ten_bo_phan'] in lines[:14]]
            if len(matches) != 1:
                raise ValueError(f'Page {page.number + 1}: ambiguous product block')
            block = matches[0]
            clip, anchors = illustration(page)
            references_used = []
            for target_page, code, reference_page, align_code in anchor_references:
                if int(target_page) != page.number + 1:
                    continue
                key, align = code_key(code), code_key(align_code)
                if key in anchors:
                    raise ValueError(f'Anchor {code} already exists on page {target_page}')
                _, reference = illustration(doc[int(reference_page) - 1])
                # Explicitly reviewed matching diagrams only; never automatic inference.
                anchors[key] = tuple(anchors[align][i] + reference[key][i] - reference[align][i]
                                     for i in (0, 1))
                references_used.append(dict(code=code, reference_page=int(reference_page), align_code=align_code))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False)
            # Use actual pixel bounds: MuPDF rounds the clip to integer pixels.
            x_origin, y_origin = pix.x / 2, pix.y / 2
            width, height = pix.width / 2, pix.height / 2
            png = pix.tobytes('png')
            digest = hashlib.sha256(png).hexdigest()[:12]
            relative = f"positions/{slug}/{block['nhom']}/guide_{block['id']}_{digest}.png"
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
            updates, unmatched = [], []
            for spot in block['hotspots']:
                anchor = anchors.get(code_key(spot['ma_vi_tri'] or ''))
                if anchor is None:
                    unmatched.append(spot['ma_vi_tri'])
                    continue
                # The editor/QC UI interpret x/y as the hotspot rectangle origin.
                # A narrow rectangle allows labels close to the left/right edge.
                w, h = .04, .04
                x = (anchor[0] + clip.x0 - x_origin) / width - w / 2
                y = (anchor[1] + clip.y0 - y_origin) / height - h / 2
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    raise ValueError(f'Out-of-bounds label: {spot["ma_vi_tri"]}')
                updates.append(dict(id=spot['id'], x_pct=x, y_pct=y, w_pct=w, h_pct=h))
            result.append(dict(bo_phan_id=block['id'], ten_khoi=block['ten_bo_phan'],
                               page=page.number + 1, image_png=relative,
                               updates=updates, unmatched=unmatched,
                               reference_anchors=references_used))
    if {b['id'] for b in blocks} != {r['bo_phan_id'] for r in result} or len(result) != len(blocks):
        raise ValueError('PDF pages do not match all existing product blocks')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('product')
    parser.add_argument('slug')
    parser.add_argument('--output', type=Path, default=ROOT / 'scripts/out/guided_pdf')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--anchor-reference', nargs=4, action='append', default=[],
                        metavar=('PAGE', 'CODE', 'REFERENCE_PAGE', 'ALIGN_CODE'),
                        help='Explicit reviewed anchor from a matching diagram, aligned by an existing code')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_]+', args.slug):
        parser.error('slug must contain only lowercase letters, numbers and underscores')
    load_dotenv(ROOT / '.env')
    with psycopg2.connect(os.environ['DATABASE_URL']) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT id FROM dm_loai_hang WHERE ten_loai = %s', (args.product,))
            products = cur.fetchall()
            if len(products) != 1:
                raise ValueError('Expected one existing product')
            cur.execute('SELECT * FROM dm_bo_phan WHERE loai_hang_id = %s AND nhom IS NOT NULL ORDER BY sort_order, id',
                        (products[0]['id'],))
            blocks = [dict(b) for b in cur.fetchall()]
            if not blocks:
                raise ValueError('Product has no existing blocks to repair')
            for block in blocks:
                cur.execute('SELECT * FROM dm_chi_tiet WHERE bo_phan_id = %s ORDER BY id', (block['id'],))
                block['hotspots'] = [dict(s) for s in cur.fetchall()]
            result = prepare(args.pdf, args.product, args.slug, blocks, args.output, args.anchor_reference)
            manifest = args.output / f'{args.slug}_guides.json'
            manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            for entry in result:
                print(f"{entry['ten_khoi']}: {len(entry['updates'])} labels aligned; "
                      f"no PDF label: {entry['unmatched']}")
            if not args.apply:
                print(f'Preview: {manifest}; add --apply to update existing rows.')
                return
            # Back up every original row before changing only images/coordinates.
            backup = args.output / f"{args.slug}_before_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
            backup.write_text(json.dumps(blocks, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            storage = Path(os.environ['IMAGES_STORAGE_DIR'])
            for entry in result:
                target = storage / entry['image_png']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(args.output / entry['image_png'], target)
                cur.execute('UPDATE dm_bo_phan SET image_png = %s, image_svg = NULL WHERE id = %s',
                            (entry['image_png'], entry['bo_phan_id']))
                for spot in entry['updates']:
                    cur.execute('UPDATE dm_chi_tiet SET x_pct=%s, y_pct=%s, w_pct=%s, h_pct=%s WHERE id=%s',
                                (spot['x_pct'], spot['y_pct'], spot['w_pct'], spot['h_pct'], spot['id']))
            conn.commit()
            print(f'Applied. Original IDs/labels preserved. Backup: {backup}')


if __name__ == '__main__':
    main()
