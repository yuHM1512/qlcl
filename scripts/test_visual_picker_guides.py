"""Regression checks for the reviewed Co-2 PDF and portable deploy bundle."""
import hashlib
import json
import os
import unittest
from pathlib import Path

import pymupdf

from repair_visual_picker_guides import CODE, code_key, illustration


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'scripts/data/co2_visual_catalog.json'
ASSETS = ROOT / 'scripts/assets/visual_picker'


class CodeTests(unittest.TestCase):
    def test_missing_hyphen_and_accents(self):
        self.assertEqual(code_key('Lư11'), code_key('Lư-11'))
        self.assertEqual(code_key('Co-10'), code_key('Cô-10'))
        self.assertTrue(CODE.fullmatch('Lư11'))

    def test_layer_numbers_stay_distinct(self):
        self.assertEqual(code_key('T(3) - 1'), 't(3)-1')
        self.assertNotEqual(code_key('T(2)-1'), code_key('T(3)-1'))
        self.assertFalse(CODE.fullmatch('11'))


class BundleTests(unittest.TestCase):
    def test_portable_bundle_counts_codes_and_images(self):
        expected = {
            'Áo đồng phục y tế': (4, 50),
            'Quần đồng phục y tế': (3, 37),
            'Quần thể thao': (11, 137),
            'Yếm thể thao': (12, 155),
        }
        bundle = json.loads(BUNDLE.read_text(encoding='utf-8'))
        self.assertEqual({p['name'] for p in bundle['products']}, set(expected))
        for product in bundle['products']:
            blocks = product['blocks']
            self.assertEqual(
                (len(blocks), sum(len(block['hotspots']) for block in blocks)),
                expected[product['name']],
            )
            for block in blocks:
                codes = [spot['code'] for spot in block['hotspots']]
                self.assertEqual(len(codes), len(set(codes)))
                image = ASSETS / block['image_png']
                self.assertTrue(image.is_file(), image)
                self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), block['image_sha256'])

    def test_medical_shirt_contains_co_11(self):
        bundle = json.loads(BUNDLE.read_text(encoding='utf-8'))
        product = next(p for p in bundle['products'] if p['name'] == 'Áo đồng phục y tế')
        matches = [
            (block['name'], spot['label'])
            for block in product['blocks']
            for spot in block['hotspots']
            if spot['code'] == 'Cô-11'
        ]
        self.assertEqual(matches, [('Cổ', 'Can lá cổ')])


PDF = Path(os.environ.get('CO2_PDF', 'E:/Downloads/Co-2.pdf'))


@unittest.skipUnless(PDF.exists(), 'Set CO2_PDF to run source PDF regression tests')
class SourcePDFTests(unittest.TestCase):
    def test_all_thirty_diagrams_are_detected(self):
        expected = [16,15,10,9,10,12,15,22,12,24,9,16,10,18,4,10,6,6,10,17,12,24,9,7,16,10,18,9,7,15]
        with pymupdf.open(PDF) as doc:
            for index, count in enumerate(expected):
                with self.subTest(page=index + 1):
                    clip, labels = illustration(doc[index])
                    self.assertEqual(len(labels), count)
                    self.assertGreater(clip.width, 500)
                    self.assertLess(clip.x1, doc[index].rect.width * .7)

    def test_missing_catalog_codes_exist_in_illustrations(self):
        with pymupdf.open(PDF) as doc:
            _, collar = illustration(doc[0])
            _, detach = illustration(doc[15])
            self.assertIn('co-11', collar)
            self.assertEqual(set(detach), {f'to-{i}' for i in range(1, 11)})
            # The phantom Lu-11 came from covered old text in the table.
            _, back = illustration(doc[2])
            self.assertNotIn('lu-11', back)


if __name__ == '__main__':
    unittest.main()
