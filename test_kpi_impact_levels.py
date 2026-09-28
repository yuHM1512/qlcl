import ast
import unittest
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parent
NEW_OPTIONS = (
    "Ảnh hưởng đến MTCL công ty",
    "Chưa ảnh hưởng đến MTCL công ty",
    "Ảnh hưởng đến MTCL phòng",
    "Chưa ảnh hưởng đến MTCL phòng",
)
LEGACY_OPTIONS = (
    "Ảnh hưởng đến MTCL công ty/phòng",
    "Chưa ảnh hưởng đến MTCL công ty/phòng",
)


class KPIImpactLevelTests(unittest.TestCase):
    def test_create_and_edit_forms_offer_four_split_options(self):
        input_html = (ROOT / "templates" / "kpi_input.html").read_text(encoding="utf-8")
        view_html = (ROOT / "templates" / "view_kpi.html").read_text(encoding="utf-8")

        for option in NEW_OPTIONS:
            self.assertIn(option, input_html)
            self.assertIn(option, view_html)
        for legacy_option in LEGACY_OPTIONS:
            self.assertNotIn(legacy_option, input_html)
            self.assertNotIn(legacy_option, view_html)

    def test_migration_maps_legacy_values_to_department(self):
        migration_name = "migrate_kpi_impact_level_20260928.sql"
        migration = (ROOT / "db" / migration_name).read_text(encoding="utf-8")
        main_source = (ROOT / "main.py").read_text(encoding="utf-8-sig")

        self.assertIn(f'"{migration_name}"', main_source)
        self.assertIn(
            "WHEN 'Ảnh hưởng đến MTCL công ty/phòng' THEN 'Ảnh hưởng đến MTCL phòng'",
            migration,
        )
        self.assertIn(
            "WHEN 'Chưa ảnh hưởng đến MTCL công ty/phòng' THEN 'Chưa ảnh hưởng đến MTCL phòng'",
            migration,
        )

    def test_api_normalizes_legacy_labels_and_rejects_unknown_values(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(main_source)
        wanted_names = {"KPI_IMPACT_LEVEL_OPTIONS", "LEGACY_KPI_IMPACT_LEVEL_MAP"}
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in wanted_names
                for target in node.targets
            ):
                nodes.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name == "normalize_kpi_impact_level":
                nodes.append(node)

        class FakeHTTPException(Exception):
            def __init__(self, status_code, detail):
                self.status_code = status_code
                self.detail = detail

        namespace = {
            "Any": Any,
            "Optional": Optional,
            "HTTPException": FakeHTTPException,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
        normalize = namespace["normalize_kpi_impact_level"]

        self.assertEqual(normalize(LEGACY_OPTIONS[0]), NEW_OPTIONS[2])
        self.assertEqual(normalize(LEGACY_OPTIONS[1]), NEW_OPTIONS[3])
        self.assertEqual(normalize(f"  {NEW_OPTIONS[0]}  "), NEW_OPTIONS[0])
        self.assertIsNone(normalize(""))
        with self.assertRaises(FakeHTTPException) as error:
            normalize("Giá trị không hợp lệ")
        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
