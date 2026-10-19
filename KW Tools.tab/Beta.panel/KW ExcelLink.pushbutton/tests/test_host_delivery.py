"""Exercise host delivery without loading WPF or opening Revit dialogs."""
import ast
import json
import os
import types
import unittest
from unittest.mock import Mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class HostDeliveryTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "ui", "host.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        host = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExcelLinkHost")
        method = next(node for node in host.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_post")
        self.forms = Mock()
        namespace = {
            "json": json, "_LOGGER": Mock(), "forms": self.forms,
            "traceback": types.SimpleNamespace(format_exc=lambda: "test traceback"),
        }
        module = ast.Module(body=[method], type_ignores=[])
        exec(compile(module, "host._post", "exec"), namespace)
        self.deliver = namespace["_post"]
        self.core = Mock()
        self.host = types.SimpleNamespace(
            webView=types.SimpleNamespace(CoreWebView2=self.core), output=Mock()
        )

    def test_modeless_command_declares_persistent_engine(self):
        with open(os.path.join(ROOT, "script.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        setting = next(node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name)
                               and target.id == "__persistentengine__"
                               for target in node.targets))
        self.assertIs(ast.literal_eval(setting.value), True)
        with open(os.path.join(ROOT, "bundle.yaml"), encoding="utf-8") as stream:
            self.assertIn("engine:\n  persistent: true", stream.read())

    def test_workbook_and_filters_are_sent_as_valid_json(self):
        payload = {"type": "workbook", "workbook": {"sheets": [{
            "layout": {"filters": {"advanced": {"join": "and", "rules": [
                {"title": "Mark (Instance)", "op": "startsWith", "value": "D"}
            ]}}}
        }]}}
        self.deliver(self.host, payload)
        encoded = self.core.PostWebMessageAsJson.call_args.args[0]
        self.assertEqual(json.loads(encoded), payload)
        self.forms.alert.assert_not_called()

    def test_invalid_numeric_json_is_reported_and_not_sent(self):
        self.deliver(self.host, {"value": float("nan")})
        self.core.PostWebMessageAsJson.assert_not_called()
        self.forms.alert.assert_called_once()
        self.host.output.print_code.assert_called_once()

    def test_unicode_cells_columns_and_filter_values_are_not_ascii_encoded(self):
        payload = {"type": "workbook", "workbook": {"sheets": [{
            "name": u"Portes - Caf\u00e9",
            "columns": [{"title": u"D\u00e9signation (Instance)"}],
            "rows": [{"value": u"R\u00e9sum\u00e9 \u2013 \u6771\u4eac"}],
            "layout": {"filters": {"advanced": {"join": "and", "rules": [
                {"title": u"D\u00e9signation (Instance)", "op": "contains",
                 "value": u"Caf\u00e9"}
            ]}}},
        }]}}
        self.deliver(self.host, payload)
        encoded = self.core.PostWebMessageAsJson.call_args.args[0]
        self.assertEqual(json.loads(encoded), payload)
        self.assertIn(u"Caf\u00e9", encoded)
        self.assertIn(u"\u6771\u4eac", encoded)
        self.forms.alert.assert_not_called()

    def test_unavailable_webview_is_reported(self):
        self.host.webView.CoreWebView2 = None
        self.deliver(self.host, {"type": "workbook"})
        self.forms.alert.assert_called_once()

    def test_failed_delivery_is_reported(self):
        self.core.PostWebMessageAsJson.side_effect = RuntimeError("delivery failed")
        self.deliver(self.host, {"type": "workbook"})
        self.forms.alert.assert_called_once()
        self.assertIn("delivery failed", self.forms.alert.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
