# -*- coding: utf-8 -*-
__title__         = "Text Count"
__min_revit_ver__ = 2021
__version__       = 1.0
__beta__ = True
__doc__ = """Date    = 30.07.2026
_____________________________________________________________________
Description:
Places text notes with an auto-incrementing counter.
_____________________________________________________________________
How-To:
- Run the command
- choose a text type and enter the desired counter settings
- click Place Text, pick a point in the view, and repeat for more notes
_____________________________________________________________________
Author: KoalaBIM Team"""

import os
import traceback
import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from pyrevit import revit, forms, script as _pyscript
from Autodesk.Revit.DB import FilteredElementCollector, TextNote, TextNoteType, Plane, SketchPlane, BuiltInParameter


_SESSION_ENV_PREFIX = "TextCount"
_SESSION_SETTING_DEFAULTS = {
    "text_type": "",
    "prefix": "",
    "start": "1",
    "increment": "1",
    "suffix": "",
}


def _session_key(name):
    return "{}_{}".format(_SESSION_ENV_PREFIX, name)


def load_session_settings():
    """Load tool settings that persist only for the current Revit session."""
    settings = dict(_SESSION_SETTING_DEFAULTS)
    for name in _SESSION_SETTING_DEFAULTS:
        try:
            saved = _pyscript.get_envvar(_session_key(name))
            if saved is not None:
                settings[name] = str(saved)
        except Exception:
            pass
    return settings


def save_session_setting(name, value):
    """Save a single setting for the current Revit session."""
    try:
        _pyscript.set_envvar(_session_key(name), "" if value is None else str(value))
    except Exception:
        pass


class TextCountWindow(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__), "TextCount.xaml")
        forms.WPFWindow.__init__(self, xaml_path)

        self._text_type_map = {}
        self._settings = None
        self._current_value = None
        self._session_settings = load_session_settings()

        self._bind_controls()
        self._load_text_types()
        self._set_defaults()

    def _find_named_element(self, element, name):
        if element is None:
            return None

        try:
            return element.FindName(name)
        except Exception:
            pass

        try:
            if getattr(element, "Name", None) == name:
                return element
        except Exception:
            pass

        return None

    def _bind_controls(self):
        self.cboTextType = self._find_named_element(self, "cboTextType")
        self.txtPrefix = self._find_named_element(self, "txtPrefix")
        self.txtStart = self._find_named_element(self, "txtStart")
        self.txtIncrement = self._find_named_element(self, "txtIncrement")
        self.txtSuffix = self._find_named_element(self, "txtSuffix")
        self.lblPreview = self._find_named_element(self, "lblPreview")
        self.lblStatus = self._find_named_element(self, "lblStatus")
        self.btnPlace = self._find_named_element(self, "btnPlace")
        self.btnClose = self._find_named_element(self, "btnClose")

        missing = []
        for name, control in [("cboTextType", self.cboTextType), ("txtPrefix", self.txtPrefix), ("txtStart", self.txtStart),
                              ("txtIncrement", self.txtIncrement), ("txtSuffix", self.txtSuffix), ("lblPreview", self.lblPreview),
                              ("lblStatus", self.lblStatus), ("btnPlace", self.btnPlace), ("btnClose", self.btnClose)]:
            if control is None:
                missing.append(name)

        if missing:
            raise RuntimeError("Could not bind controls: {}".format(", ".join(missing)))

        self.btnPlace.Click += self.on_place_text
        self.btnClose.Click += self.on_close
        self.cboTextType.SelectionChanged += self._persist_settings
        self.txtPrefix.TextChanged += self._persist_settings
        self.txtStart.TextChanged += self._persist_settings
        self.txtIncrement.TextChanged += self._persist_settings
        self.txtSuffix.TextChanged += self._persist_settings

    def _set_defaults(self):
        self.txtStart.Text = self._session_settings.get("start") or "1"
        self.txtIncrement.Text = self._session_settings.get("increment") or "1"
        self.txtPrefix.Text = self._session_settings.get("prefix") or ""
        self.txtSuffix.Text = self._session_settings.get("suffix") or ""

        saved_text_type = self._session_settings.get("text_type") or ""
        if saved_text_type in self._text_type_map:
            self.cboTextType.SelectedItem = saved_text_type
        elif self.cboTextType.Items.Count:
            self.cboTextType.SelectedIndex = 0

        self.lblPreview.Text = "Next value: {}".format(self.txtStart.Text or "1")
        self.lblStatus.Text = "Choose a text type and click Place Text."

        self._persist_settings(None, None)

    def _load_text_types(self):
        if revit is None or revit.doc is None:
            return

        text_types = []
        collector = FilteredElementCollector(revit.doc)
        collector = collector.OfClass(TextNoteType)
        collector = collector.WhereElementIsElementType()

        for item in collector.ToElements():
            if item is None:
                continue

            try:
                name = revit.query.get_name(item)
            except Exception:
                name = None

            if not name:
                try:
                    name = item.Name
                except Exception:
                    name = None

            if not name:
                try:
                    name = item.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                    if name is not None and hasattr(name, "AsString"):
                        name = name.AsString()
                except Exception:
                    name = None

            if not name:
                name = "Unnamed"
            else:
                try:
                    name = str(name)
                except Exception:
                    name = "Unnamed"

            if name not in self._text_type_map:
                self._text_type_map[name] = item
                text_types.append(name)

        for name in sorted(text_types, key=lambda x: x.lower()):
            self.cboTextType.Items.Add(name)

        if self.cboTextType.Items.Count:
            self.cboTextType.SelectedIndex = 0

    def _looks_numeric(self, value):
        value = (value or "").strip()
        if not value:
            return False
        for char in value:
            if char not in "0123456789":
                return False
        return True

    def _looks_alpha(self, value):
        value = (value or "").strip()
        if not value:
            return False
        for char in value:
            if not ("A" <= char <= "Z" or "a" <= char <= "z"):
                return False
        return True

    def _validate_counter(self, value):
        value = (value or "").strip()
        return bool(value and (self._looks_numeric(value) or self._looks_alpha(value)))

    def _next_value(self, value, increment):
        value = (value or "").strip()
        if not value:
            value = "1"

        if self._looks_numeric(value):
            width = len(value)
            number = int(value)
            return str(number + increment).zfill(width)

        letters = list(value.upper())
        for _ in range(increment):
            index = len(letters) - 1
            while index >= 0:
                if letters[index] != "Z":
                    letters[index] = chr(ord(letters[index]) + 1)
                    break
                letters[index] = "A"
                index -= 1
            else:
                letters.insert(0, "A")

        return "".join(letters)

    def _persist_settings(self, sender, args):
        try:
            selected_name = self.cboTextType.SelectedItem
            save_session_setting("text_type", selected_name if selected_name is not None else "")
            save_session_setting("prefix", self.txtPrefix.Text)
            save_session_setting("start", self.txtStart.Text)
            save_session_setting("increment", self.txtIncrement.Text)
            save_session_setting("suffix", self.txtSuffix.Text)
        except Exception:
            pass

    def _read_settings(self):
        if revit is None or revit.doc is None or revit.uidoc is None:
            forms.alert("This tool must be run inside Revit.", title="Text Count")
            return None

        selected_name = self.cboTextType.SelectedItem
        if selected_name is None:
            forms.alert("Please choose a text type.", title="Text Count")
            return None

        text_type = self._text_type_map.get(selected_name)
        if text_type is None:
            forms.alert("The selected text type could not be resolved.", title="Text Count")
            return None

        start_value = (self.txtStart.Text or "").strip() or "1"
        if not self._validate_counter(start_value):
            forms.alert("Start value must be numeric or alphabetic.", title="Text Count")
            return None

        increment_text = (self.txtIncrement.Text or "").strip() or "1"
        try:
            increment = int(increment_text)
        except Exception:
            forms.alert("Increment amount must be a whole number.", title="Text Count")
            return None

        if increment <= 0:
            forms.alert("Increment amount must be greater than zero.", title="Text Count")
            return None

        prefix = self.txtPrefix.Text or ""
        suffix = self.txtSuffix.Text or ""

        return {
            "text_type": text_type,
            "prefix": prefix,
            "suffix": suffix,
            "start": start_value,
            "increment": increment,
        }

    def _build_text(self, value, prefix, suffix):
        text = ""
        if prefix:
            text += prefix
        text += value
        if suffix:
            text += suffix
        return text

    def _ensure_view_work_plane(self, view):
        if view is None:
            raise RuntimeError("No active view is available.")

        if getattr(view, "SketchPlane", None) is not None:
            return True

        normal = view.ViewDirection
        origin = view.Origin
        plane = Plane.CreateByNormalAndOrigin(normal, origin)
        sketch_plane = SketchPlane.Create(revit.doc, plane)
        view.SketchPlane = sketch_plane
        return True

    def _update_preview(self, value):
        if self._settings is None:
            self.lblPreview.Text = "Next value: {}".format(value)
            return

        preview_text = self._build_text(value, self._settings["prefix"], self._settings["suffix"])
        self.lblPreview.Text = "Next value: {}".format(preview_text)

    def _show_revit_status(self, message):
        try:
            if getattr(revit, "uiapp", None) is not None:
                revit.uiapp.SetStatusBarMessage(message)
        except Exception:
            pass

    def _clear_revit_status(self):
        try:
            if getattr(revit, "uiapp", None) is not None:
                revit.uiapp.SetStatusBarMessage("")
        except Exception:
            pass

    def _is_cancelled_selection(self, exc):
        if exc is None:
            return False
        text = str(exc).lower()
        return any(token in text for token in ["cancel", "canceled", "cancelled", "esc", "escape", "aborted", "abort"])

    def _place_at_point(self, view, point, settings):
        text_value = self._current_value
        text_to_place = self._build_text(text_value, settings["prefix"], settings["suffix"])

        with revit.Transaction("Place text count"):
            self._ensure_view_work_plane(view)
            TextNote.Create(
                revit.doc,
                view.Id,
                point,
                text_to_place,
                settings["text_type"].Id,
            )

        self._current_value = self._next_value(text_value, settings["increment"])
        self._update_preview(self._current_value)
        self.lblStatus.Text = "Placed: {}".format(text_to_place)

    def on_place_text(self, sender, args):
        self.lblStatus.Text = "Starting placement..."
        try:
            settings = self._settings or self._read_settings()
            if settings is None:
                return

            if self._settings is None:
                self._settings = settings
                self._current_value = settings["start"]

            view = revit.uidoc.ActiveView or revit.doc.ActiveView
            if view is None:
                forms.alert("No active view is available.", title="Text Count")
                return

            try:
                with revit.Transaction("Prepare text count work plane"):
                    self._ensure_view_work_plane(view)
            except Exception as exc:
                self.lblStatus.Text = "Work plane setup failed: {}".format(exc)
                forms.alert("Text Count could not prepare a work plane for this view:\n{}\n\n{}".format(exc, traceback.format_exc()), title="Text Count")
                return

            self.Hide()
            self._show_revit_status("Text Count: pick points. Press Esc to return.")
            self.lblStatus.Text = "Pick a point in the view. Press Esc to finish."

            while True:
                try:
                    point = revit.uidoc.Selection.PickPoint("Pick a point to place the text")
                except Exception as exc:
                    if self._is_cancelled_selection(exc):
                        self.lblStatus.Text = "Placement cancelled."
                        break
                    raise

                try:
                    self._place_at_point(view, point, settings)
                except Exception as exc:
                    self.lblStatus.Text = "Placement failed: {}".format(exc)
                    forms.alert("Text Count placement failed:\n{}\n\n{}".format(exc, traceback.format_exc()), title="Text Count")
                    break
        except Exception as exc:
            if self._is_cancelled_selection(exc):
                self.lblStatus.Text = "Placement cancelled."
            else:
                self.lblStatus.Text = "Placement failed: {}".format(exc)
                forms.alert("Text Count placement failed:\n{}\n\n{}".format(exc, traceback.format_exc()), title="Text Count")
        finally:
            self._clear_revit_status()
            self.Show()
            self.Activate()

    def on_close(self, sender, args):
        self.Close()

    def show(self):
        self.ShowDialog()


def main():
    try:
        window = TextCountWindow()
        window.show()
    except Exception as exc:
        forms.alert("Text Count failed:\n{}\n\n{}".format(exc, traceback.format_exc()), title="Text Count")


main()