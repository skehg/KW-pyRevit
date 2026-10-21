# -*- coding: utf-8 -*-

import json
import copy
import os
import traceback

import clr
import System
from System.Threading.Tasks import Task, TaskScheduler
from Autodesk.Revit.UI import (
    ExternalEvent,
    ExternalEventRequest,
    IExternalEventHandler,
)
from pyrevit import forms, script


try:
    clr.AddReference("Microsoft.Web.WebView2.Wpf")
    clr.AddReference("Microsoft.Web.WebView2.Core")
except Exception as exc:
    raise RuntimeError(
        "Microsoft WebView2 WPF assemblies are not available to Revit: {0}".format(exc)
    )

from core.apply_changes import apply_changes
from core.column_builder import project_rows
from core.element_refs import ReferenceCatalog
from core.extract import extract_rows
from core.revit_view import run_view_action
from core.selection import elements_for_category, resolve_elements_by_id
from core.workbook_builder import build_import_workbook
from core.xlsx_import import diff_xlsx, read_import_plan
from ui.import_dialogs import open_with_shell, pick_xlsx, report_import_issues
from ui.preset_dialogs import save_from_grid
from ui.workflow import run_wizard
from core.types import element_id_value


_OPEN_WINDOWS = []
_LOGGER = script.get_logger()


def _create_webview_environment(web_view, user_data_folder):
    # Resolve Core from the actual WPF control, not a competing add-in's SDK.
    ensure_method = next(
        method for method in web_view.GetType().GetMethods()
        if method.Name == "EnsureCoreWebView2Async"
        and len(method.GetParameters()) > 0
    )
    environment_type = ensure_method.GetParameters()[0].ParameterType
    return environment_type.GetMethod("CreateAsync").Invoke(
        None, System.Array[System.Object]([None, user_data_folder, None])
    )


def _layout_matches(plan, workbook):
    """True when every worksheet in the file maps onto a sheet already in the grid."""
    if not plan["sheets"] or plan.get("parameterMode") != workbook.get("parameterMode"):
        return False
    sheets = {}
    for sheet in workbook.get("sheets") or []:
        try:
            sheets[int(sheet.get("categoryId"))] = sheet
        except (TypeError, ValueError):
            continue
    for entry in plan["sheets"]:
        sheet = sheets.get(int(entry["categoryId"]))
        if sheet is None or not set(entry["parameters"]) <= set(sheet["parameters"]):
            return False
    return True


class _WorkbookEventHandler(IExternalEventHandler):
    def __init__(self, window, workbook, source_elements, document):
        self.window = window
        self.workbook = workbook
        self.source_elements = source_elements
        self.source_element_ids = list(
            workbook.get("_sourceElementIds")
            or [element_id_value(element.Id) for element in source_elements or []]
        )
        self.document = document
        self.pending = None

    def GetName(self):
        return "KW ExcelLink workbook operations"

    def Execute(self, application):
        request = self.pending
        self.pending = None
        if request is None:
            return
        try:
            doc = application.ActiveUIDocument.Document
            if not doc.Equals(self.document):
                raise RuntimeError(
                    "Switch back to the document used to open this ExcelLink workbook."
                )
            if request["type"] == "apply":
                result = apply_changes(doc, request.get("changes", []))
                removed = self._refresh(doc)
                self.window._post({
                    "type": "applied",
                    "result": result,
                    "workbook": self.workbook,
                    "removedElements": removed,
                })
            elif request["type"] == "import":
                self._import(doc, request["path"])
            elif request["type"] == "back":
                draft = copy.deepcopy(self.workbook)
                for sheet, layout in zip(draft["sheets"], request.get("layouts") or []):
                    sheet["layout"] = layout
                self.window.Hide()
                try:
                    result = run_wizard(
                        application.ActiveUIDocument, doc, draft,
                        self.source_elements, int(request.get("sheetIndex") or 0),
                    )
                finally:
                    self.window.Show()
                    self.window.Activate()
                if result is None:
                    self.window._post({"type": "wizardCancelled"})
                    return
                workbook, self.source_elements = result
                self.source_element_ids = list(workbook.get("_sourceElementIds") or [])
                self.workbook.clear()
                self.workbook.update(workbook)
                self.window._post({
                    "type": "workbook",
                    "workbook": self.workbook,
                    "wizardRebuilt": True,
                    "importUpdates": self.workbook.pop("importUpdates", None),
                    "importSummary": self.workbook.pop("importSummary", None),
                })
            elif request["type"] == "revitView":
                try:
                    message = run_view_action(
                        application.ActiveUIDocument,
                        request.get("mode"),
                        request.get("elementIds"),
                        request.get("typeIds"),
                        self.source_elements,
                    )
                except ValueError as exc:
                    # Expected situations (wrong view type, nothing visible) need no traceback.
                    self.window._post({"type": "error", "message": str(exc)})
                    return
                self.window._post({"type": "revitViewDone", "message": message})
            else:
                removed = self._refresh(doc)
                self.window._post({
                    "type": "workbook",
                    "workbook": self.workbook,
                    "removedElements": removed,
                })
        except Exception as exc:
            details = traceback.format_exc()
            _LOGGER.error("KW ExcelLink Revit operation failed:\n{0}".format(details))
            output = script.get_output()
            output.print_md("## KW ExcelLink {0} failed".format(request.get("type")))
            output.print_code(details)
            self.window._post({
                "type": "error",
                "message": "{0} (full traceback in the pyRevit output window)".format(exc),
            })

    def _import(self, doc, path):
        file_name = os.path.basename(path)
        plan = read_import_plan(path)
        layout_replaced = not _layout_matches(plan, self.workbook)
        if layout_replaced:
            workbook, source_elements, issues, missing = build_import_workbook(doc, path)
            report_import_issues(path, issues, missing)
            if workbook is None:
                raise RuntimeError(
                    "None of the rows in {0} match elements in this model.".format(file_name)
                )
            updates = workbook.pop("importUpdates")
            summary = workbook.pop("importSummary")
            # The window holds the same dict, so replace its contents in place.
            self.workbook.clear()
            self.workbook.update(workbook)
            self.source_elements = source_elements
            self.source_element_ids = list(workbook.get("_sourceElementIds") or [])
        else:
            removed = self._refresh(doc)
            diff = diff_xlsx(self.workbook, path)
            updates, summary = diff["updates"], diff["summary"]
            report_import_issues(path, plan["issues"] + diff["issues"])
            self.workbook["importFile"] = file_name
        self.window._post({
            "type": "workbook",
            "workbook": self.workbook,
            "importUpdates": updates,
            "importSummary": summary,
            "layoutReplaced": layout_replaced,
            "removedElements": 0 if layout_replaced else removed,
        })

    def _refresh(self, doc):
        self.source_elements, removed = resolve_elements_by_id(
            doc, self.source_element_ids
        )
        self.source_element_ids = [
            element_id_value(element.Id) for element in self.source_elements
        ]
        self.workbook["_sourceElementIds"] = list(self.source_element_ids)
        catalog = ReferenceCatalog(doc)
        for sheet in self.workbook["sheets"]:
            elements = elements_for_category(
                self.source_elements, sheet["categoryId"]
            )
            rows = extract_rows(
                doc,
                elements,
                self.workbook["parameterMode"],
                sheet["parameters"],
                catalog,
            )
            columns = sheet["columns"]
            sheet["rows"] = project_rows(rows, columns, catalog)
        return removed


class ExcelLinkHost(forms.WPFWindow):
    def __init__(self, uidoc, workbook, source_elements):
        xaml_path = os.path.join(os.path.dirname(__file__), "host.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        self.uidoc = uidoc
        self.workbook = workbook
        self.output = script.get_output()
        self._last_xlsx_path = None
        self._closed = False
        self.Title = "KW ExcelLink - {0}".format(uidoc.Document.Title)
        self._handler = _WorkbookEventHandler(
            self, workbook, source_elements, uidoc.Document
        )
        self._external_event = ExternalEvent.Create(self._handler)
        self.webView.CoreWebView2InitializationCompleted += self._on_initialized
        self.Closed += self._on_closed
        self.Loaded += self._on_loaded

    def _on_loaded(self, sender, args):
        self.Loaded -= self._on_loaded
        try:
            user_data_folder = os.path.join(
                System.Environment.GetFolderPath(
                    System.Environment.SpecialFolder.LocalApplicationData
                ),
                "KW", "ExcelLink", "WebView2",
            )
            System.IO.Directory.CreateDirectory(user_data_folder)
            self._environment_task = _create_webview_environment(
                self.webView, user_data_folder
            )
            self._environment_continuation = (
                self._environment_task.ContinueWith.Overloads[
                    System.Action[Task], TaskScheduler
                ](
                    System.Action[Task](self._on_environment_created),
                    TaskScheduler.FromCurrentSynchronizationContext(),
                )
            )
        except Exception:
            self._initialization_failed(traceback.format_exc())

    def _on_environment_created(self, task):
        try:
            environment = task.GetAwaiter().GetResult()
            if not self._closed:
                self.webView.EnsureCoreWebView2Async(environment)
        except Exception:
            self._initialization_failed(traceback.format_exc())

    def _initialization_failed(self, details):
        _LOGGER.error("WebView2 initialization failed:\n{0}".format(details))
        self.output.print_md("## KW ExcelLink WebView2 initialization failed")
        self.output.print_md(
            "The complete initialization exception is shown below and can be copied."
        )
        self.output.print_code(details)
        if not self._closed:
            self.Close()

    def _on_initialized(self, sender, args):
        if self._closed:
            return
        if not args.IsSuccess:
            exception = args.InitializationException
            details = (
                exception.ToString()
                if exception is not None
                else "WebView2 initialization failed without exception details."
            )
            self._initialization_failed(details)
            return
        self.webView.CoreWebView2.WebMessageReceived += self._on_web_message
        web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
        self.webView.CoreWebView2.Navigate(
            System.Uri(os.path.abspath(os.path.join(web_dir, "index.html"))).AbsoluteUri
        )

    def _on_web_message(self, sender, args):
        try:
            request = json.loads(str(args.WebMessageAsJson))
            message_type = request.get("type")
            if message_type == "ready":
                # Imported differences are offered once; Reload shows plain Revit values.
                self._post({
                    "type": "workbook",
                    "workbook": self.workbook,
                    "importUpdates": self.workbook.pop("importUpdates", None),
                    "importSummary": self.workbook.pop("importSummary", None),
                })
            elif message_type == "clientError":
                message = request.get("message") or "Unknown grid error."
                _LOGGER.error("KW ExcelLink web grid failed: {0}".format(message))
                self.output.print_md("## KW ExcelLink web grid failed")
                self.output.print_code(message)
            elif message_type == "apply":
                self._queue_revit_request(request)
            elif message_type == "reload":
                self._queue_revit_request({"type": "reload"})
            elif message_type == "save":
                self._save_workbook(request.get("workbook"))
            elif message_type == "import":
                path = pick_xlsx(self._last_xlsx_path)
                if not path:
                    self._post({"type": "importCancelled"})
                    return
                self._last_xlsx_path = path
                self._queue_revit_request({"type": "import", "path": path})
            elif message_type == "savePreset":
                self._save_preset(request.get("layouts") or [])
            elif message_type == "revitView":
                self._queue_revit_request(request)
            elif message_type == "back":
                self._queue_revit_request(request)
            elif message_type == "close":
                if self._handler.pending is not None or self._external_event.IsPending:
                    raise RuntimeError(
                        "Wait for the current Revit operation to finish before closing ExcelLink."
                    )
                self.Close()
            else:
                raise ValueError("Unsupported message type: {0}".format(message_type))
        except Exception as exc:
            _LOGGER.exception("KW ExcelLink received an invalid web message.")
            self._post({"type": "error", "message": str(exc)})

    def _queue_revit_request(self, request):
        if self._handler.pending is not None or self._external_event.IsPending:
            raise RuntimeError("A Revit operation is already in progress.")
        self._handler.pending = request
        try:
            request_status = self._external_event.Raise()
            if request_status not in (
                ExternalEventRequest.Accepted,
                ExternalEventRequest.Pending,
            ):
                self._handler.pending = None
                raise RuntimeError(
                    "Revit did not accept the ExcelLink request ({0}).".format(
                        request_status
                    )
                )
        except Exception:
            self._handler.pending = None
            raise

    def _save_workbook(self, workbook):
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import DialogResult, SaveFileDialog

        if not isinstance(workbook, dict) or not isinstance(workbook.get("sheets"), list):
            raise ValueError("The web grid did not provide a valid workbook.")
        dialog = SaveFileDialog()
        dialog.Filter = (
            "Excel workbook (*.xlsx)|*.xlsx|"
            "ExcelLink workbook (*.json)|*.json"
        )
        dialog.FilterIndex = 1
        dialog.DefaultExt = "xlsx"
        dialog.AddExtension = True
        dialog.OverwritePrompt = True
        dialog.FileName = "ExcelLink-workbook.xlsx"
        if self._last_xlsx_path:
            dialog.InitialDirectory = os.path.dirname(self._last_xlsx_path)
            dialog.FileName = os.path.basename(self._last_xlsx_path)
        if dialog.ShowDialog() != DialogResult.OK:
            return
        from core.persistence import save_workbook

        snapshot = dict(workbook)
        snapshot.pop("_sourceElementIds", None)
        snapshot.pop("_documentKey", None)
        save_workbook(snapshot, dialog.FileName)
        opened = False
        if dialog.FileName.lower().endswith(".xlsx"):
            self._last_xlsx_path = dialog.FileName
            if forms.alert(
                "Workbook saved:\n{0}\n\nOpen it in Excel now?".format(dialog.FileName),
                title="KW ExcelLink", yes=True, no=True, warn_icon=False,
            ):
                try:
                    open_with_shell(dialog.FileName)
                    opened = True
                except Exception:
                    details = traceback.format_exc()
                    _LOGGER.error("Could not open the saved workbook:\n{0}".format(details))
                    self.output.print_md("## KW ExcelLink could not open the saved workbook")
                    self.output.print_code(details)
        self._post({"type": "saved", "path": dialog.FileName, "opened": opened})

    def _save_preset(self, layouts):
        workbook = self._handler.workbook
        try:
            saved = save_from_grid(workbook, layouts)
        except Exception as exc:
            details = traceback.format_exc()
            _LOGGER.error("KW ExcelLink could not save the preset:\n{0}".format(details))
            self.output.print_md("## KW ExcelLink preset save failed")
            self.output.print_code(details)
            self._post({"type": "error", "message": "Preset not saved: {0}".format(exc)})
            return
        if saved is None:
            self._post({"type": "presetCancelled"})
            return
        name, path = saved
        workbook["presetName"] = name
        for sheet, layout in zip(workbook.get("sheets") or [], layouts):
            sheet["layout"] = layout
        self._post({"type": "presetSaved", "name": name, "path": path})

    def _post(self, payload):
        try:
            core = self.webView.CoreWebView2
            if core is None:
                raise RuntimeError("The ExcelLink web view is not initialized.")
            core.PostWebMessageAsJson(json.dumps(
                payload, ensure_ascii=False, allow_nan=False
            ))
        except Exception as exc:
            details = traceback.format_exc()
            _LOGGER.error("KW ExcelLink could not notify the web grid:\n{0}".format(details))
            self.output.print_md("## KW ExcelLink could not load the web grid")
            self.output.print_code(details)
            forms.alert(
                "ExcelLink could not send data to the grid:\n\n{0}\n\n"
                "See the pyRevit output window for the full error.".format(exc),
                title="KW ExcelLink",
            )

    def _on_closed(self, sender, args):
        self._closed = True
        try:
            self.webView.Dispose()
        finally:
            try:
                self._external_event.Dispose()
            finally:
                if self in _OPEN_WINDOWS:
                    _OPEN_WINDOWS.remove(self)


def show_workbook(uidoc, workbook, source_elements):
    window = ExcelLinkHost(uidoc, workbook, source_elements)
    _OPEN_WINDOWS.append(window)
    window.Show()
    return window
