# -*- coding: utf-8 -*-

import clr

from pyrevit import revit, forms, script as _pyscript
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

import utils


clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from System.Drawing import Point, Size
from System.Windows.Forms import (
    Button,
    CheckBox,
    DialogResult,
    Form,
    FormBorderStyle,
    FormStartPosition,
    Label,
    TextBox,
)


_ENV_PREFIX = "ShapeMap2Session"
_ENV_KEYS = {
    "include_source_vertices": _ENV_PREFIX + ".include_source_vertices",
    "include_source_boundary": _ENV_PREFIX + ".include_source_boundary",
    "include_source_internal": _ENV_PREFIX + ".include_source_internal",
    "boundary_grid_mm": _ENV_PREFIX + ".boundary_grid_mm",
    "internal_grid_mm": _ENV_PREFIX + ".internal_grid_mm",
    "match_level_offset": _ENV_PREFIX + ".match_level_offset",
    "additional_z_offset_mm": _ENV_PREFIX + ".additional_z_offset_mm",
}


def _to_bool(value, default_value):
    if value is None:
        return bool(default_value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return bool(default_value)


def _get_envvar(key, default_value):
    try:
        value = _pyscript.get_envvar(key)
        if value is None:
            return default_value
        return value
    except Exception:
        return default_value


def _set_envvar(key, value):
    try:
        _pyscript.set_envvar(key, "" if value is None else str(value))
    except Exception:
        pass


def _load_session_options():
    return {
        "include_source_vertices": _to_bool(_get_envvar(_ENV_KEYS["include_source_vertices"], "True"), True),
        "include_source_boundary": _to_bool(_get_envvar(_ENV_KEYS["include_source_boundary"], "True"), True),
        "include_source_internal": _to_bool(_get_envvar(_ENV_KEYS["include_source_internal"], "True"), True),
        "boundary_grid_mm": str(_get_envvar(_ENV_KEYS["boundary_grid_mm"], "0")),
        "internal_grid_mm": str(_get_envvar(_ENV_KEYS["internal_grid_mm"], "0")),
        "match_level_offset": _to_bool(_get_envvar(_ENV_KEYS["match_level_offset"], "True"), True),
        "additional_z_offset_mm": str(_get_envvar(_ENV_KEYS["additional_z_offset_mm"], "0")),
    }


def _save_session_options(options):
    _set_envvar(_ENV_KEYS["include_source_vertices"], options.get("include_source_vertices", True))
    _set_envvar(_ENV_KEYS["include_source_boundary"], options.get("include_source_boundary", True))
    _set_envvar(_ENV_KEYS["include_source_internal"], options.get("include_source_internal", True))
    _set_envvar(_ENV_KEYS["boundary_grid_mm"], options.get("boundary_grid_mm", "0"))
    _set_envvar(_ENV_KEYS["internal_grid_mm"], options.get("internal_grid_mm", "0"))
    _set_envvar(_ENV_KEYS["match_level_offset"], options.get("match_level_offset", True))
    _set_envvar(_ENV_KEYS["additional_z_offset_mm"], options.get("additional_z_offset_mm", "0"))


class _ShapeHostSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return utils.is_supported_host(element)

    def AllowReference(self, reference, point):
        return False


def _pick_supported_element(prompt):
    uidoc = __revit__.ActiveUIDocument
    if uidoc is None:
        return None

    pick_filter = _ShapeHostSelectionFilter()

    try:
        with forms.WarningBar(title=prompt):
            picked_ref = uidoc.Selection.PickObject(ObjectType.Element, pick_filter, prompt)
    except Exception:
        return None

    if picked_ref is None:
        return None

    try:
        return uidoc.Document.GetElement(picked_ref.ElementId)
    except Exception:
        return None


class ShapeMapDialog(Form):
    def __init__(self, title, source=None, destination=None, preset_options=None):
        Form.__init__(self)
        self.Text = title
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition = FormStartPosition.CenterScreen
        self.ClientSize = Size(640, 470)
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.source = source
        self.destination = destination
        self.options = None
        self.pick_action = None

        if preset_options is None:
            preset_options = {}

        y = 12

        self._add_title("Element Selection", y)
        y += 28
        self.lbl_source = self._add_value_label("Source: {0}".format(self._element_label(self.source)), y)
        self.btn_pick_source = self._add_button("Pick Source", 500, y - 2, self.on_pick_source)
        y += 28
        self.lbl_dest = self._add_value_label("Destination: {0}".format(self._element_label(self.destination)), y)
        self.btn_pick_dest = self._add_button("Pick Destination", 500, y - 2, self.on_pick_destination)

        y += 40
        self._add_title("Source Point Inclusion", y)
        y += 28
        self.chk_src_vertices = self._add_checkbox(
            "Match Source Vertex Points",
            y,
            bool(preset_options.get("include_source_vertices", True)),
        )
        y += 24
        self.chk_src_boundary = self._add_checkbox(
            "Match Source Boundary Points",
            y,
            bool(preset_options.get("include_source_boundary", True)),
        )
        y += 24
        self.chk_src_internal = self._add_checkbox(
            "Match Source Internal Points",
            y,
            bool(preset_options.get("include_source_internal", True)),
        )

        y += 34
        self._add_title("Grid Sampling", y)
        y += 28
        self.txt_boundary_grid = self._add_labeled_textbox(
            "Boundary Grid Size (mm)  [0 = disabled]",
            y,
            str(preset_options.get("boundary_grid_mm", "0")),
        )
        y += 30
        self.txt_internal_grid = self._add_labeled_textbox(
            "Internal Grid Size (mm)  [0 = disabled]",
            y,
            str(preset_options.get("internal_grid_mm", "0")),
        )

        y += 34
        self._add_title("Elevation Controls", y)
        y += 28
        self.chk_level = self._add_checkbox(
            "Match Source Level + Level Offset",
            y,
            bool(preset_options.get("match_level_offset", True)),
        )
        y += 28
        self.txt_additional_z = self._add_labeled_textbox(
            "Additional Z Offset (mm)",
            y,
            str(preset_options.get("additional_z_offset_mm", "0")),
        )

        self.btn_ok = self._add_button("OK", 440, 430, self.on_ok)
        self.btn_cancel = self._add_button("Cancel", 530, 430, self.on_cancel)

    def _add_title(self, text, y):
        lbl = Label()
        lbl.Text = text
        lbl.Location = Point(12, y)
        lbl.Size = Size(380, 20)
        self.Controls.Add(lbl)
        return lbl

    def _add_value_label(self, text, y):
        lbl = Label()
        lbl.Text = text
        lbl.Location = Point(18, y)
        lbl.Size = Size(470, 20)
        self.Controls.Add(lbl)
        return lbl

    def _add_checkbox(self, text, y, default):
        cb = CheckBox()
        cb.Text = text
        cb.Checked = default
        cb.Location = Point(18, y)
        cb.Size = Size(360, 20)
        self.Controls.Add(cb)
        return cb

    def _add_button(self, text, x, y, handler):
        btn = Button()
        btn.Text = text
        btn.Location = Point(x, y)
        btn.Size = Size(110, 24)
        btn.Click += handler
        self.Controls.Add(btn)
        return btn

    def _add_labeled_textbox(self, label, y, default_text):
        lbl = Label()
        lbl.Text = label
        lbl.Location = Point(18, y)
        lbl.Size = Size(380, 20)
        self.Controls.Add(lbl)

        txt = TextBox()
        txt.Text = default_text
        txt.Location = Point(410, y - 2)
        txt.Size = Size(170, 20)
        self.Controls.Add(txt)
        return txt

    def _element_label(self, element):
        if element is None:
            return "<not selected>"
        try:
            cat = element.Category.Name
        except Exception:
            cat = "Element"
        return "{0} (Id: {1})".format(cat, element.Id.IntegerValue)

    def _capture_preset_options(self):
        return {
            "include_source_vertices": bool(self.chk_src_vertices.Checked),
            "include_source_boundary": bool(self.chk_src_boundary.Checked),
            "include_source_internal": bool(self.chk_src_internal.Checked),
            "boundary_grid_mm": (self.txt_boundary_grid.Text or "0").strip() or "0",
            "internal_grid_mm": (self.txt_internal_grid.Text or "0").strip() or "0",
            "match_level_offset": bool(self.chk_level.Checked),
            "additional_z_offset_mm": (self.txt_additional_z.Text or "0").strip() or "0",
        }

    def on_pick_source(self, sender, args):
        self.options = self._capture_preset_options()
        self.pick_action = "source"
        self.DialogResult = DialogResult.Retry
        self.Close()

    def on_pick_destination(self, sender, args):
        self.options = self._capture_preset_options()
        self.pick_action = "destination"
        self.DialogResult = DialogResult.Retry
        self.Close()

    def _parse_nonnegative_mm(self, txt, field_name):
        try:
            value = float((txt.Text or "").strip())
        except Exception:
            raise Exception("{0} must be a numeric value.".format(field_name))
        if value < 0.0:
            raise Exception("{0} cannot be negative.".format(field_name))
        return value

    def on_ok(self, sender, args):
        if self.source is None or self.destination is None:
            forms.alert("Please pick both source and destination elements.")
            return

        if self.source.Id == self.destination.Id:
            forms.alert("Source and destination must be different elements.")
            return

        try:
            boundary_mm = self._parse_nonnegative_mm(self.txt_boundary_grid, "Boundary Grid Size")
            internal_mm = self._parse_nonnegative_mm(self.txt_internal_grid, "Internal Grid Size")
            additional_mm = float((self.txt_additional_z.Text or "").strip())
        except Exception as ex:
            forms.alert(str(ex))
            return

        self.options = {
            "include_source_vertices": bool(self.chk_src_vertices.Checked),
            "include_source_boundary": bool(self.chk_src_boundary.Checked),
            "include_source_internal": bool(self.chk_src_internal.Checked),
            "boundary_grid_mm": boundary_mm,
            "internal_grid_mm": internal_mm,
            "boundary_grid_ft": 0.0 if boundary_mm == 0.0 else utils.mm_to_internal(boundary_mm),
            "internal_grid_ft": 0.0 if internal_mm == 0.0 else utils.mm_to_internal(internal_mm),
            "match_level_offset": bool(self.chk_level.Checked),
            "additional_z_offset_mm": additional_mm,
            "additional_z_offset_ft": utils.mm_to_internal(additional_mm),
        }

        _save_session_options(self.options)

        self.DialogResult = DialogResult.OK
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()


def show_shape_map_dialog(title):
    source = None
    destination = None
    options = _load_session_options()

    while True:
        dlg = ShapeMapDialog(title, source=source, destination=destination, preset_options=options)
        result = dlg.ShowDialog()

        if result == DialogResult.OK:
            return {
                "source": dlg.source,
                "destination": dlg.destination,
                "options": dlg.options,
            }

        if result != DialogResult.Retry:
            return None

        # Preserve current in-dialog settings while re-entering pick mode.
        if dlg.options:
            options.update(dlg.options)

        if dlg.pick_action == "source":
            picked = _pick_supported_element("Pick source element")

            if picked is not None:
                source = picked
            continue

        if dlg.pick_action == "destination":
            picked = _pick_supported_element("Pick destination element")

            if picked is not None:
                destination = picked
            continue

        return None
