"""Reviewed corrections for Co-2.pdf; preview by default, commit with --apply.

Page 1 repeats Cô-10 in row 11. Page 16 omits all combined codes.
Pages 2/3 contain obsolete text hidden beneath later edits. These corrections
are based on the rendered tables, not their overlapping extracted text.
Existing detail IDs remain stable; the obsolete Lu-11 is removed only when
unused by qc_defect (its only referencing table).
"""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from repair_visual_picker_guides import ROOT, code_key

LABELS = {
    'Thân trước': {
        'Th-1': 'Đường can vai', 'Th-3': 'Vòng nách',
        'Th-14': 'Diễu xẻ lai', 'Th-15': 'Bọ xẻ lai',
    },
    'Lưng': {
        'Lư-1': 'Vòng cổ', 'Lư-5': 'Can sóng lưng', 'Lư-6': 'Diễu sóng lưng',
        'Lư-7': 'Đô lưng', 'Lư-8': 'Diễu đô lưng', 'Lư-9': 'Xếp ly lưng',
        'Lư-10': 'Chít ly lưng',
    },
}
DETACH = [
    'Dây kéo tháo ống', 'Can dây kéo tháo ống', 'Diễu dây kéo tháo ống',
    'Bọ dây kéo tháo ống', 'Nẹp che dây kéo tháo ống',
    'Diễu nẹp che dây kéo tháo ống', 'Bọ nẹp che dây kéo tháo ống',
    'Lai quần ngắn', 'Diễu lai quần ngắn', 'Can nẹp lai quần ngắn',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    with psycopg2.connect(os.environ['DATABASE_URL']) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM dm_bo_phan WHERE loai_hang_id IN '
                        '(SELECT id FROM dm_loai_hang WHERE ten_loai = ANY(%s)) ORDER BY id FOR UPDATE',
                        (['Áo đồng phục y tế', 'Quần thể thao'],))
            backup = [dict(r) for r in cur.fetchall()]
            for row in backup:
                cur.execute('SELECT * FROM dm_chi_tiet WHERE bo_phan_id=%s FOR UPDATE', (row['id'],))
                row['hotspots'] = [dict(r) for r in cur.fetchall()]
            out = ROOT / 'scripts/out/guided_pdf'
            out.mkdir(parents=True, exist_ok=True)
            if args.apply:
                path = out / f'co2_before_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
                path.write_text(json.dumps(backup, ensure_ascii=False, indent=2, default=str), encoding='utf8')
                print(f'Backup: {path}')

            def block(product, name):
                cur.execute('SELECT bp.id FROM dm_bo_phan bp JOIN dm_loai_hang lh '
                            'ON lh.id=bp.loai_hang_id WHERE lh.ten_loai=%s AND bp.ten_bo_phan=%s',
                            (product, name))
                found = cur.fetchall()
                if len(found) != 1:
                    raise ValueError(f'Expected one {product}: {name}')
                return found[0]['id']

            def add(bp, code, label):
                cur.execute('SELECT id FROM dm_chi_tiet WHERE bo_phan_id=%s AND ma_vi_tri=%s', (bp, code))
                if cur.fetchone():
                    return
                cur.execute('INSERT INTO dm_chi_tiet '
                            '(bo_phan_id,ten_chi_tiet,ma_vi_tri,x_pct,y_pct,w_pct,h_pct,rotation) '
                            'VALUES (%s,%s,%s,.5,.5,.04,.04,0)', (bp, label, code))
                print(f'ADD {code}: {label}')

            add(block('Áo đồng phục y tế', 'Cổ'), 'Cô-11', 'Can lá cổ')
            for name, labels in LABELS.items():
                bp = block('Áo đồng phục y tế', name)
                cur.execute('SELECT id,ma_vi_tri,ten_chi_tiet FROM dm_chi_tiet WHERE bo_phan_id=%s', (bp,))
                details = {code_key(r['ma_vi_tri']): r for r in cur.fetchall()}
                for code, label in labels.items():
                    old = details[code_key(code)]
                    if old['ten_chi_tiet'] != label:
                        cur.execute('UPDATE dm_chi_tiet SET ten_chi_tiet=%s WHERE id=%s', (label, old['id']))
                        print(f'LABEL {name} {code}: {old["ten_chi_tiet"]} -> {label}')
                if name == 'Lưng' and 'lu-11' in details:
                    obsolete = details['lu-11']['id']
                    cur.execute('SELECT COUNT(*) AS n FROM qc_defect WHERE chi_tiet_id=%s', (obsolete,))
                    if cur.fetchone()['n']:
                        raise ValueError('Obsolete Lu-11 has historical defects; requires explicit migration')
                    cur.execute('DELETE FROM dm_chi_tiet WHERE id=%s', (obsolete,))
                    print('REMOVE unused Lu-11 from hidden old PDF text (visible table ends at Lư-10)')

            cur.execute('SELECT id FROM dm_loai_hang WHERE ten_loai=%s', ('Quần thể thao',))
            product_id = cur.fetchone()['id']
            cur.execute('SELECT id FROM dm_bo_phan WHERE loai_hang_id=%s AND ten_bo_phan=%s',
                        (product_id, 'Cụm tháo ống'))
            existing = cur.fetchone()
            if existing:
                bp = existing['id']
            else:
                # Insert between Cụm thắt lưng and Cụm mở ống, preserving other IDs.
                cur.execute('SELECT sort_order FROM dm_bo_phan WHERE id=%s', (block('Quần thể thao', 'Cụm mở ống'),))
                order = cur.fetchone()['sort_order']
                cur.execute('UPDATE dm_bo_phan SET sort_order=sort_order+1 WHERE loai_hang_id=%s AND sort_order>=%s',
                            (product_id, order))
                cur.execute('INSERT INTO dm_bo_phan (loai_hang_id,ten_bo_phan,nhom,sort_order) '
                            'VALUES (%s,%s,%s,%s) RETURNING id', (product_id, 'Cụm tháo ống', 'chinh', order))
                bp = cur.fetchone()['id']
            for i, label in enumerate(DETACH, 1):
                add(bp, f'Tô-{i}', label)
            if args.apply:
                conn.commit()
                print('Committed. Run repair_visual_picker_guides.py for images/label coordinates.')
            else:
                conn.rollback()
                print('Preview only: rolled back all changes. Add --apply to commit.')


if __name__ == '__main__':
    main()
