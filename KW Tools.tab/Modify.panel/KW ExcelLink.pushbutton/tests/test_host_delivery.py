"""Exercise host delivery without loading WPF or opening Revit dialogs."""
import ast
import json
import os
import types
import unittest
from unittest.mock import Mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class HostInitializationTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "ui", "host.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        host = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExcelLinkHost")
        methods = [node for node in host.body if isinstance(node, ast.FunctionDef)
                   and node.name in (
                       "_on_environment_created", "_initialization_failed",
                       "_on_initialized", "_on_closed",
                   )]
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_create_webview_environment")
        self.windows = []
        self.namespace = {
            "_LOGGER": Mock(), "_OPEN_WINDOWS": self.windows,
            "traceback": types.SimpleNamespace(format_exc=lambda: "test traceback"),
            "System": types.SimpleNamespace(
                Object=object, Array={object: list},
            ),
        }
        exec(compile(ast.Module(body=[helper] + methods, type_ignores=[]),
                     "host.initialization", "exec"), self.namespace)
        self.host = Mock()
        self.host._closed = False
        self.task = Mock()
        self.environment = object()
        self.task.GetAwaiter.return_value.GetResult.return_value = self.environment

    def test_environment_uses_core_type_from_actual_control(self):
        unrelated_method = Mock()
        unrelated_method.Name = "Dispose"
        ensure_method = Mock()
        ensure_method.Name = "EnsureCoreWebView2Async"
        environment_type = Mock()
        ensure_method.GetParameters.return_value = [
            types.SimpleNamespace(ParameterType=environment_type)
        ]
        self.host.webView.GetType.return_value.GetMethods.return_value = [
            unrelated_method, ensure_method
        ]
        task = self.namespace["_create_webview_environment"](
            self.host.webView, "browser-data"
        )
        environment_type.GetMethod.assert_called_once_with("CreateAsync")
        factory = environment_type.GetMethod.return_value
        factory.Invoke.assert_called_once_with(None, [None, "browser-data", None])
        self.assertIs(task, factory.Invoke.return_value)

    def test_environment_is_passed_explicitly_to_control(self):
        self.namespace["_on_environment_created"](self.host, self.task)
        self.host.webView.EnsureCoreWebView2Async.assert_called_once_with(
            self.environment
        )
        self.host._initialization_failed.assert_not_called()

    def test_close_during_environment_creation_does_not_restart_browser(self):
        self.host._closed = True
        self.namespace["_on_environment_created"](self.host, self.task)
        self.task.GetAwaiter.return_value.GetResult.assert_called_once_with()
        self.host.webView.EnsureCoreWebView2Async.assert_not_called()

    def test_environment_failure_is_reported(self):
        self.task.GetAwaiter.return_value.GetResult.side_effect = RuntimeError("SDK")
        self.namespace["_on_environment_created"](self.host, self.task)
        self.host._initialization_failed.assert_called_once_with("test traceback")
        self.host.webView.EnsureCoreWebView2Async.assert_not_called()

    def test_synchronous_control_failure_is_reported(self):
        self.host.webView.EnsureCoreWebView2Async.side_effect = RuntimeError("SDK")
        self.namespace["_on_environment_created"](self.host, self.task)
        self.host._initialization_failed.assert_called_once_with("test traceback")

    def test_initialization_failure_prints_details_and_closes_once(self):
        self.namespace["_initialization_failed"](self.host, "SDK mismatch")
        self.host.output.print_code.assert_called_once_with("SDK mismatch")
        self.host.Close.assert_called_once_with()
        self.host.Close.reset_mock()
        self.host._closed = True
        self.namespace["_initialization_failed"](self.host, "late failure")
        self.host.Close.assert_not_called()

    def test_failed_initialization_event_reports_original_exception(self):
        exception = Mock()
        exception.ToString.return_value = "MissingMethodException details"
        args = types.SimpleNamespace(IsSuccess=False, InitializationException=exception)
        self.namespace["_on_initialized"](self.host, None, args)
        self.host._initialization_failed.assert_called_once_with(
            "MissingMethodException details"
        )

    def test_late_initialization_event_is_ignored_after_close(self):
        self.host._closed = True
        self.namespace["_on_initialized"](self.host, None, Mock())
        self.host._initialization_failed.assert_not_called()
        self.host.webView.CoreWebView2.Navigate.assert_not_called()

    def test_close_releases_browser_event_and_window_reference(self):
        self.windows.append(self.host)
        self.namespace["_on_closed"](self.host, None, None)
        self.assertTrue(self.host._closed)
        self.host.webView.Dispose.assert_called_once_with()
        self.host._external_event.Dispose.assert_called_once_with()
        self.assertEqual(self.windows, [])

    def test_browser_disposal_error_still_releases_event_and_reference(self):
        self.windows.append(self.host)
        self.host.webView.Dispose.side_effect = RuntimeError("dispose")
        with self.assertRaisesRegex(RuntimeError, "dispose"):
            self.namespace["_on_closed"](self.host, None, None)
        self.host._external_event.Dispose.assert_called_once_with()
        self.assertEqual(self.windows, [])

    def test_constructor_defers_initialization_until_loaded(self):
        with open(os.path.join(ROOT, "ui", "host.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        host = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExcelLinkHost")
        constructor = next(node for node in host.body if isinstance(node, ast.FunctionDef)
                           and node.name == "__init__")
        calls = [node for node in ast.walk(constructor) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node.func, ast.Attribute)
                             and node.func.attr == "EnsureCoreWebView2Async"
                             for node in calls))
        self.assertTrue(any(isinstance(node, ast.AugAssign)
                            and isinstance(node.target, ast.Attribute)
                            and node.target.attr == "Loaded"
                            for node in constructor.body))


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
            "attach_type_names": lambda doc, rows, catalog: [],
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

    def dispatch_close(self, pending=None, event_pending=False, message_type="close"):
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
        args = types.SimpleNamespace(WebMessageAsJson=json.dumps({"type": message_type}))
        namespace["_on_web_message"](window, None, args)
        return window

    def test_zoom_reset_only_changes_requesting_windows_zoom(self):
        other_window = Mock()
        other_window.webView.ZoomFactor = 1.75
        window = self.dispatch_close(
            pending={"type": "apply"}, event_pending=True, message_type="resetZoom"
        )
        self.assertEqual(window.webView.ZoomFactor, 1.0)
        self.assertEqual(other_window.webView.ZoomFactor, 1.75)
        window._queue_revit_request.assert_not_called()
        window.Close.assert_not_called()
        window._post.assert_not_called()

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
