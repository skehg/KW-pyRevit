"""Round-trip ExcelLink's two-row XLSX schema without Revit dependencies."""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import xlsx_export, xlsx_import

for _module in (xlsx_export, xlsx_import):
    _module.basestring = str
    _module.unicode = str
    _module.long = int


PARAMETER_KEY = '["shared:width-guid","autodesk.spec.aec:length-2.0.0","Double"]'
PARAMETER_USAGE = {
    "name": "Width",
    "displayName": "Width [Length; shared]",
    "identity": "shared:width-guid",
    "specTypeId": "autodesk.spec.aec:length-2.0.0",
    "dataType": "Length",
    "storageType": "Double",
    "guid": "width-guid",
    "builtin": None,
    "isType": False,
    "isInstance": True,
    "categoryIds": [1, 2],
    "categoryNames": ["Walls", "Doors"],
    "categoryCount": 2,
    "totalCategories": 2,
}


def make_workbook(layout="combined", value=10.0, title="Width (Instance)"):
    combined = layout == "combined"
    categories = [
        {"categoryId": 1, "categoryKey": "category:walls", "name": "Walls"},
        {"categoryId": 2, "categoryKey": "category:doors", "name": "Doors"},
    ] if combined else [
        {"categoryId": 1, "categoryKey": "category:walls", "name": "Walls"},
    ]
    category_key = "combined:category:doors|category:walls" if combined \
        else "category:walls"
    columns = [
        {"title": "Element ID", "field": "ElementId", "visible": False,
         "dataType": "Integer"},
        {"title": "Unique ID", "field": "UniqueId", "visible": False,
         "dataType": "Text"},
        {"title": "Category", "field": "Category", "visible": False,
         "dataType": "Text", "columnType": "category"},
        {
            "title": title, "field": "p0_instance", "columnType": "parameter",
            "parameterKey": PARAMETER_KEY, "parameterName": "Width",
            "parameterIdentity": PARAMETER_USAGE["identity"],
            "dataType": "Length", "specTypeId": PARAMETER_USAGE["specTypeId"],
            "target": "instance", "storageType": "Double", "unit": "mm",
            "referenceKind": None, "options": None, "parameterGuid": "width-guid",
            "parameterBuiltin": None, "editable": True, "disabled": False,
        },
    ]
    row = {
        "ElementId": 5,
        "UniqueId": "element-unique-id",
        "Category": "Walls",
        "p0_instance": value,
        "p0_instance__metadata": {
            "parameterIdentity": PARAMETER_USAGE["identity"],
            "parameterGuid": "width-guid",
            "parameterBuiltin": None,
            "specTypeId": PARAMETER_USAGE["specTypeId"],
            "storageType": "Double",
            "referenceKind": None,
            "options": None,
            "unit": "mm",
        },
    }
    return {
        "gridLayout": layout,
        "parameterMode": "instances",
        "sheets": [{
            "name": "Combined" if combined else "Walls",
            "sheetKey": category_key,
            "categoryId": None if combined else 1,
            "categoryKey": category_key,
            "categories": categories,
            "parameters": [PARAMETER_KEY],
            "parameterUsage": {PARAMETER_KEY: dict(PARAMETER_USAGE)},
            "columns": columns,
            "rows": [row],
        }],
    }


class XlsxRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(os.path.dirname(__file__), "_xlsx_roundtrip.xlsx")

    def tearDown(self):
        for path in (self.path, self.path + ".rewrite"):
            if os.path.exists(path):
                os.remove(path)

    def test_readonly_derived_identity_and_field_options_roundtrip(self):
        from core.optional_fields import derived_descriptors
        workbook = make_workbook()
        sheet = workbook["sheets"][0]
        descriptor = next(item for item in derived_descriptors()
                          if item["key"] == "derived:internal_0")
        usage = dict(PARAMETER_USAGE, **descriptor)
        usage["fieldOptions"] = {
            "coordinates": True, "usefulFields": False, "filterFalsePositives": False}
        sheet["parameters"] = [descriptor["key"]]
        sheet["parameterUsage"] = {descriptor["key"]: usage}
        column = sheet["columns"][-1]
        column.update(parameterKey=descriptor["key"], parameterName=descriptor["name"],
                      parameterIdentity=descriptor["identity"], specTypeId=descriptor["specTypeId"],
                      parameterGuid=None, disabled=True, editable=False)
        xlsx_export.write_xlsx(workbook, self.path)
        plan = xlsx_import.read_import_plan(self.path)
        restored = plan["sheets"][0]["parameterUsage"][descriptor["key"]]
        self.assertEqual(restored["fieldOptions"], usage["fieldOptions"])
        self.assertEqual(restored["derivedGroup"], "coordinates")
        sheet["rows"][0]["p0_instance"] += 1
        diff = xlsx_import.diff_xlsx(workbook, self.path)
        self.assertEqual(diff["updates"], [])

    def test_combined_two_row_export_plan_and_identity_based_diff(self):
        exported = make_workbook(value=12.5, title="Renamed display label")
        xlsx_export.write_xlsx(exported, self.path)

        reader = xlsx_import._XlsxReader(self.path)
        try:
            sheets = reader.sheets()
            data_name, data_part = next(item for item in sheets
                                        if item[0] != xlsx_export.META_SHEET_NAME)
            rows = reader.rows(data_part)
            self.assertEqual(rows[0][3], "Length [mm]")
            self.assertEqual(rows[1][3], "Renamed display label")
            self.assertEqual(rows[2][3], 12.5)
            data_xml = reader.archive.read(data_part).decode("utf-8")
            self.assertIn('ySplit="2"', data_xml)
            self.assertIn('topLeftCell="A3"', data_xml)
            self.assertIn('autoFilter ref="A2:D3"', data_xml)
            self.assertRegex(data_xml, r'<col min="3" max="3" width="[^"]+" customWidth="1"/>')
        finally:
            reader.close()

        plan = xlsx_import.read_import_plan(self.path)
        self.assertEqual(plan["gridLayout"], "combined")
        self.assertEqual(plan["sheets"][0]["sheetName"], "Combined")
        self.assertEqual(plan["sheets"][0]["sheetKey"],
                         "combined:category:doors|category:walls")
        self.assertIsNone(plan["sheets"][0]["categoryId"])
        self.assertEqual(plan["sheets"][0]["categories"], [
            {"categoryId": 1, "categoryKey": "category:walls", "name": "Walls"},
            {"categoryId": 2, "categoryKey": "category:doors", "name": "Doors"},
        ])
        self.assertEqual(plan["sheets"][0]["parameterKeys"], [PARAMETER_KEY])
        self.assertEqual(plan["sheets"][0]["uniqueIds"], ["element-unique-id"])

        current = make_workbook(value=10.0, title="Current grid title")
        diff = xlsx_import.diff_xlsx(current, self.path)
        self.assertEqual(diff["summary"]["changed"], 1)
        change = diff["updates"][0]
        self.assertEqual(change["value"], 12.5)
        self.assertEqual(change["parameterKey"], PARAMETER_KEY)
        self.assertEqual(change["parameterIdentity"], PARAMETER_USAGE["identity"])
        self.assertEqual(change["specTypeId"], PARAMETER_USAGE["specTypeId"])
        self.assertEqual(change["parameterGuid"], "width-guid")

    def test_separate_layout_roundtrips_single_category_identity(self):
        xlsx_export.write_xlsx(make_workbook(layout="separate"), self.path)
        plan = xlsx_import.read_import_plan(self.path)
        self.assertEqual(plan["gridLayout"], "separate")
        self.assertEqual(plan["sheets"][0]["categoryId"], 1)
        self.assertEqual(plan["sheets"][0]["categoryKey"], "category:walls")

    def test_picker_order_and_row_order_do_not_change_parameter_targets(self):
        key_a = '["shared:a","spec:length","Double"]'
        key_b = '["shared:b","spec:length","Double"]'

        def usage(name, identity):
            return {
                "name": name, "displayName": name, "identity": identity,
                "specTypeId": "spec:length", "dataType": "Length",
                "storageType": "Double", "guid": identity, "builtin": None,
                "isType": False, "isInstance": True,
                "categoryIds": [1, 2], "categoryNames": ["Walls", "Doors"],
                "categoryCount": 2, "totalCategories": 2,
            }

        usages = {key_a: usage("Width", "shared:a"),
                  key_b: usage("Height", "shared:b")}

        def parameter_column(key, field, name):
            return {
                "title": name + " (Instance)", "field": field,
                "columnType": "parameter", "parameterKey": key,
                "parameterName": name, "parameterIdentity": usages[key]["identity"],
                "specTypeId": "spec:length", "dataType": "Length",
                "target": "instance", "storageType": "Double", "unit": "mm",
                "editable": True, "disabled": False,
            }

        def row(element_id, unique_id, value_a, value_b, field_a, field_b):
            result = {
                "ElementId": element_id, "UniqueId": unique_id,
                "Category": "Walls" if element_id == 1 else "Doors",
                field_a: value_a, field_b: value_b,
            }
            for key, field in ((key_a, field_a), (key_b, field_b)):
                result[field + "__metadata"] = {
                    "parameterIdentity": usages[key]["identity"],
                    "parameterGuid": usages[key]["guid"],
                    "parameterBuiltin": None, "specTypeId": "spec:length",
                    "storageType": "Double", "referenceKind": None,
                    "options": None, "unit": "mm",
                }
            return result

        categories = [
            {"categoryId": 1, "categoryKey": "category:walls", "name": "Walls"},
            {"categoryId": 2, "categoryKey": "category:doors", "name": "Doors"},
        ]
        sheet_key = "combined:category:doors|category:walls"
        exported = {
            "gridLayout": "combined", "parameterMode": "instances",
            "sheets": [{
                "name": "Combined", "sheetKey": sheet_key,
                "categoryId": None, "categoryKey": sheet_key,
                "categories": categories, "parameters": [key_b, key_a],
                "parameterUsage": usages,
                "columns": [
                    {"title": "Element ID", "field": "ElementId", "visible": False,
                     "dataType": "Integer"},
                    {"title": "Unique ID", "field": "UniqueId", "visible": False,
                     "dataType": "Text"},
                    {"title": "Category", "field": "Category", "visible": False,
                     "dataType": "Text"},
                    parameter_column(key_b, "p0_instance", "Height"),
                    parameter_column(key_a, "p1_instance", "Width"),
                ],
                "rows": [
                    row(2, "element-2", 20.0, 201.0, "p1_instance", "p0_instance"),
                    row(1, "element-1", 11.0, 100.0, "p1_instance", "p0_instance"),
                ],
            }],
        }
        xlsx_export.write_xlsx(exported, self.path)

        current = {
            "gridLayout": "combined", "parameterMode": "instances",
            "sheets": [{
                "name": "Combined", "sheetKey": sheet_key,
                "categoryId": None, "categoryKey": sheet_key,
                "columns": [
                    {"title": "Element ID", "field": "ElementId", "visible": False,
                     "dataType": "Integer"},
                    {"title": "Unique ID", "field": "UniqueId", "visible": False,
                     "dataType": "Text"},
                    {"title": "Category", "field": "Category", "visible": True,
                     "dataType": "Text"},
                    parameter_column(key_a, "p0_instance", "Width"),
                    parameter_column(key_b, "p1_instance", "Height"),
                ],
                "parameterUsage": usages,
                "rows": [
                    row(1, "element-1", 10.0, 100.0, "p0_instance", "p1_instance"),
                    row(2, "element-2", 20.0, 200.0, "p0_instance", "p1_instance"),
                ],
            }],
        }
        diff = xlsx_import.diff_xlsx(current, self.path)
        changes = dict(
            (change["parameterKey"], change) for change in diff["updates"]
        )
        self.assertEqual(set(changes), {key_a, key_b})
        self.assertEqual(changes[key_a]["field"], "p0_instance")
        self.assertEqual(changes[key_a]["uniqueId"], "element-1")
        self.assertEqual(changes[key_a]["value"], 11.0)
        self.assertEqual(changes[key_b]["field"], "p1_instance")
        self.assertEqual(changes[key_b]["uniqueId"], "element-2")
        self.assertEqual(changes[key_b]["value"], 201.0)

    def test_rejects_malformed_typed_header(self):
        metadata_columns = [
            {"field": "UniqueId", "dataType": "Text", "unit": None},
            {"field": "p0_instance", "dataType": "Length", "unit": "mm"},
        ]
        valid_rows = [
            {0: "Text", 1: "Length [mm]"},
            {0: "Unique ID", 1: "Width"},
        ]
        xlsx_import._validate_worksheet_headers(
            valid_rows, metadata_columns, "Combined"
        )
        invalid_rows = [
            {0: "Text", 1: "Length"},
            {0: "Unique ID", 1: "Width"},
        ]
        with self.assertRaisesRegex(ValueError, "data type/unit header"):
            xlsx_import._validate_worksheet_headers(
                invalid_rows, metadata_columns, "Combined"
            )

    def test_rejects_workbook_without_supported_hidden_schema(self):
        xlsx_export.write_xlsx(make_workbook(), self.path)
        import zipfile

        rewritten = self.path + ".rewrite"
        with zipfile.ZipFile(self.path, "r") as source:
            with zipfile.ZipFile(rewritten, "w") as target:
                for name in source.namelist():
                    if name.endswith("sheet2.xml"):
                        continue
                    target.writestr(name, source.read(name))
        os.remove(self.path)
        os.rename(rewritten, self.path)
        with self.assertRaisesRegex(ValueError, "valid hidden"):
            xlsx_import.read_import_plan(self.path)

    def test_rejects_unknown_hidden_schema_version(self):
        import zipfile

        xlsx_export.write_xlsx(make_workbook(), self.path)
        rewritten = self.path + ".rewrite"
        reader = xlsx_import._XlsxReader(self.path)
        try:
            metadata_part = next(
                part for _name, part in reader.sheets()
                if _name == xlsx_export.META_SHEET_NAME
            )
        finally:
            reader.close()
        with zipfile.ZipFile(self.path, "r") as source:
            with zipfile.ZipFile(rewritten, "w") as target:
                for name in source.namelist():
                    content = source.read(name)
                    if name == metadata_part:
                        content = content.replace(
                            b'xml:space="preserve">2</t>',
                            b'xml:space="preserve">99</t>', 1,
                        )
                    target.writestr(name, content)
        os.remove(self.path)
        os.rename(rewritten, self.path)
        with self.assertRaisesRegex(ValueError, "schema version"):
            xlsx_import.read_import_plan(self.path)


if __name__ == "__main__":
    unittest.main()
