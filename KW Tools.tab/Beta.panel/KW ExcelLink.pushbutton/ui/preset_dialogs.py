# -*- coding: utf-8 -*-
"""pyRevit dialogs for choosing, saving and managing ExcelLink presets."""

import os

from pyrevit import forms, script

from core import presets

TITLE = "KW ExcelLink"
SELECTION_MODES = ("Selected Elements", "Current View", "Entire Model")


def choose_preset(title="Load preset"):
    items = presets.list_presets()
    if not items:
        forms.alert(
            "No presets saved yet. Open a grid and use Save Preset.", title=TITLE
        )
        return None
    labels = [presets.preset_label(item) for item in items]
    picked = forms.SelectFromList.show(
        labels, title=title, button_name="Select", multiselect=False
    )
    if not picked:
        return None
    return items[labels.index(picked)]


def report_preset_issues(name, issues):
    if not issues:
        return
    output = script.get_output()
    output.print_md("## KW ExcelLink preset notes")
    output.print_md("Preset: `{0}`".format(name))
    lines = []
    for issue in issues:
        location = [issue.get("sheet") or ""]
        if issue.get("column"):
            location.append(issue["column"])
        lines.append(u"{0}: {1}".format(u" / ".join(location), issue.get("message")))
    output.print_code(u"\n".join(lines))


def save_from_grid(workbook, layouts):
    """Ask for a name (and location) and save the grid as a preset.

    Returns (name, path), or None when the user cancelled.
    """
    current = workbook.get("presetName") or ""
    name = forms.ask_for_string(
        default=current,
        prompt="Preset name (saves categories, parameters, mode, layout, filters and column formulas):",
        title="Save ExcelLink preset",
    )
    name = (name or "").strip()
    if not name:
        return None
    presets.safe_file_name(name)

    source = presets.SOURCE_PERSONAL
    if presets.shared_folder():
        choice = forms.alert(
            "Where should '{0}' be saved?".format(name),
            title=TITLE,
            options=["My presets", "Shared presets folder"],
        )
        if not choice:
            return None
        if choice == "Shared presets folder":
            source = presets.SOURCE_SHARED

    selection_mode = workbook.get("selectionMode")
    if selection_mode not in SELECTION_MODES:
        selection_mode = forms.SelectFromList.show(
            list(SELECTION_MODES),
            title="Which elements should this preset load?",
            button_name="Save",
            multiselect=False,
        )
        if not selection_mode:
            return None

    path = presets.preset_path(name, source)
    if os.path.exists(path) and not forms.alert(
        "A preset named '{0}' already exists. Replace it?".format(name),
        title=TITLE, yes=True, no=True,
    ):
        return None

    preset = presets.preset_from_workbook(workbook, layouts, name, selection_mode)
    path = presets.save_preset(preset, source)
    default_name = presets.default_preset_name()
    if (default_name or "").lower() != name.lower() and forms.alert(
        "Open '{0}' by default from the first wizard step?".format(name),
        title=TITLE, yes=True, no=True,
    ):
        presets.set_default_preset(name)
    return name, path


_SET_DEFAULT = "Set default preset"
_CLEAR_DEFAULT = "Clear default preset"
_DELETE = "Delete a preset"
_SET_SHARED = "Set shared presets folder"
_CLEAR_SHARED = "Stop using shared presets folder"
_OPEN_FOLDER = "Open my presets folder"


def manage_presets():
    default_name = presets.default_preset_name()
    shared = presets.shared_folder()
    actions = [_SET_DEFAULT]
    if default_name:
        actions.append(_CLEAR_DEFAULT)
    actions.extend([_DELETE, _SET_SHARED])
    if shared:
        actions.append(_CLEAR_SHARED)
    actions.append(_OPEN_FOLDER)
    status = "Default: {0} | Shared folder: {1}".format(
        default_name or "none", shared or "none"
    )
    action = forms.SelectFromList.show(
        actions, title="Manage presets - " + status, button_name="Run",
        multiselect=False,
    )
    if action == _SET_DEFAULT:
        item = choose_preset("Choose the default preset")
        if item:
            presets.set_default_preset(item["name"])
    elif action == _CLEAR_DEFAULT:
        presets.set_default_preset(None)
    elif action == _DELETE:
        item = choose_preset("Choose a preset to delete")
        if item and forms.alert(
            "Delete preset '{0}'?\n{1}".format(item["name"], item["path"]),
            title=TITLE, yes=True, no=True,
        ):
            presets.delete_preset(item)
    elif action == _SET_SHARED:
        folder = forms.pick_folder(title="Shared ExcelLink presets folder")
        if folder:
            presets.set_shared_folder(folder)
    elif action == _CLEAR_SHARED:
        presets.set_shared_folder(None)
    elif action == _OPEN_FOLDER:
        folder = presets.personal_folder()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        from ui.import_dialogs import open_with_shell

        open_with_shell(folder)
