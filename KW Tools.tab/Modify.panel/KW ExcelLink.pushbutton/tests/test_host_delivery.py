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

    def test_refresh_resolves_saved_ids_and_drops_deleted_elements(self):
        with open(os.path.join(ROOT, "core", "selection.py"), encoding="utf-8") as stream:
            selection_tree = ast.parse(stream.read())
        resolver = next(node for node in selection_tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "resolve_elements_by_id")
        resolver_namespace = {"make_element_id": int}
        exec(compile(ast.Module(body=[resolver], type_ignores=[]),
                     "selection.resolve_elements_by_id", "exec"), resolver_namespace)
        with open(os.path.join(ROOT, "ui", "host.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        host_class = next(node for node in tree.body
                          if isinstance(node, ast.ClassDef)
                          and node.name == "_WorkbookEventHandler")
        method = next(node for node in host_class.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_refresh")
        kept = types.SimpleNamespace(Id=10, category_id=5)
        received = []
        namespace = {
            "resolve_elements_by_id": resolver_namespace["resolve_elements_by_id"],
            "element_id_value": lambda element_id: element_id,
            "ReferenceCatalog": lambda doc: "catalog",
            "elements_for_category": lambda elements, category_id: [
                element for element in elements if element.category_id == category_id
            ],
            "extract_rows": lambda doc, elements, mode, parameters, catalog: (
                received.extend(elements) or ["row"]
            ),
            "project_rows": lambda rows, columns, catalog: ["refreshed"],
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     "host._refresh", "exec"), namespace)
        deleted_stale_reference = object()
        handler = types.SimpleNamespace(
            source_elements=[kept, deleted_stale_reference],
            source_element_ids=[10, 20],
            workbook={
                "_sourceElementIds": [10, 20],
                "parameterMode": "Instances Mode",
                "sheets": [{
                    "categoryId": 5, "parameters": ["Mark"], "columns": ["column"],
                }],
            },
        )
        document = types.SimpleNamespace(
            GetElement=lambda element_id: {10: kept}.get(element_id)
        )

        removed = namespace["_refresh"](handler, document)

        self.assertEqual(removed, 1)
        self.assertEqual(handler.source_elements, [kept])
        self.assertEqual(handler.source_element_ids, [10])
        self.assertEqual(handler.workbook["_sourceElementIds"], [10])
        self.assertEqual(received, [kept])
        self.assertEqual(handler.workbook["sheets"][0]["rows"], ["refreshed"])

    def dispatch_close(self, pending=None, event_pending=False):
        with open(os.path.join(ROOT, "ui", "host.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        host = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExcelLinkHost")
        method = next(node for node in host.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_on_web_message")
        namespace = {"json": json, "_LOGGER": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     "host._on_web_message", "exec"), namespace)
        window = Mock()
        window._handler.pending = pending
        window._external_event.IsPending = event_pending
        args = types.SimpleNamespace(WebMessageAsJson=json.dumps({"type": "close"}))
        namespace["_on_web_message"](window, None, args)
        return window

    def test_close_message_closes_the_host_without_a_revit_request(self):
        window = self.dispatch_close()
        window.Close.assert_called_once_with()
        window._queue_revit_request.assert_not_called()
        window._post.assert_not_called()

    def test_close_is_rejected_while_a_revit_operation_is_pending(self):
        for pending, event_pending in [({"type": "apply"}, False), (None, True)]:
            with self.subTest(pending=pending, event_pending=event_pending):
                window = self.dispatch_close(pending, event_pending)
                window.Close.assert_not_called()
                response = window._post.call_args.args[0]
                self.assertEqual(response["type"], "error")
                self.assertIn("Wait for the current Revit operation", response["message"])


if __name__ == "__main__":
    unittest.main()
