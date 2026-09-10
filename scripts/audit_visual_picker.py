"""Read-only audit of the live picker catalog and its served images.

Run: python scripts/audit_visual_picker.py --base-url http://localhost:8008
Writes a reviewable JSON report; does not guess or overwrite coordinates.
"""
import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from repair_visual_picker_guides import ROOT, code_key


def audit(base_url, effective_date=None):
    def get(path):
        with urlopen(base_url + path, timeout=30) as response:
            return response.read()

    products = json.loads(get('/api/qc/visual-picker/loai-hang-list'))['rows']
    report = {'checked_at': datetime.now().isoformat(), 'base_url': base_url,
              'effective_date': effective_date, 'products': []}
    urls = set()
    for product in products:
        params = {'loai_hang_id': product['id']}
        if effective_date:
            params['date'] = effective_date
        data = json.loads(get('/api/qc/visual-picker?' + urlencode(params)))
        entry = dict(product, blocks=0, hotspots=0, duplicate_codes=[], invalid_coordinates=[], missing_images=[])
        for group in data['nhoms']:
            for block in group['khoi']:
                entry['blocks'] += 1
                entry['hotspots'] += len(block['hotspots'])
                counts = Counter(code_key(h['ma_vi_tri'] or '') for h in block['hotspots'])
                entry['duplicate_codes'].extend({'block': block['ten_khoi'], 'code': code, 'count': count}
                                                for code, count in counts.items() if count > 1)
                for key in ('image_png', 'image_svg'):
                    if block[key]:
                        urls.add(block[key])
                if not block['image_png']:
                    entry['missing_images'].append(block['ten_khoi'])
                for h in block['hotspots']:
                    x, y = h['x_pct'], h['y_pct']
                    # Origins may legitimately be negative for labels at an edge.
                    # Audit the center the UI actually renders, not just x/y.
                    if x is None or y is None:
                        invalid = True
                        cx = cy = None
                    else:
                        cx, cy = x + (h['w_pct'] or 0) / 2, y + (h['h_pct'] or 0) / 2
                        invalid = not (0 <= cx <= 1 and 0 <= cy <= 1)
                    if invalid:
                        entry['invalid_coordinates'].append(dict(block=block['ten_khoi'], nhom=group['nhom'],
                            id=h['chi_tiet_id'], code=h['ma_vi_tri'], center_x=cx, center_y=cy))
        report['products'].append(entry)

    def check_image(url):
        try:
            body = get(url)
            if not (body.startswith(b'\x89PNG') or b'<svg' in body[:1000]):
                return {'url': url, 'error': 'Unexpected image content'}
        except Exception as exc:
            return {'url': url, 'error': str(exc)}
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        report['image_errors'] = [error for error in pool.map(check_image, sorted(urls)) if error]
    report['images_checked'] = len(urls)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8008')
    parser.add_argument('--date', help='Business date in YYYY-MM-DD')
    parser.add_argument('--output', type=Path, default=ROOT / 'scripts/out/guided_pdf/catalog_audit.json')
    args = parser.parse_args()
    report = audit(args.base_url.rstrip('/'), args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    for p in report['products']:
        print(f"{p['ten_loai']}: {p['blocks']} blocks, {p['hotspots']} spots, "
              f"{len(p['duplicate_codes'])} duplicate codes, {len(p['invalid_coordinates'])} centers outside image")
    print(f"Images: {report['images_checked']}; errors: {len(report['image_errors'])}; report: {args.output}")


if __name__ == '__main__':
    main()
