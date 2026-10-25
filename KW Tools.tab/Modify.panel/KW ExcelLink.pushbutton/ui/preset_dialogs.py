# -*- coding: utf-8 -*-
"""pyRevit dialogs for choosing, saving and managing ExcelLink presets."""

import os

from pyrevit import forms, script

from core import presets

TITLE = "KW ExcelLink"
SELECTION_MODES = (
    "Selected Elements", "Current View", "Entire Project File", "Entire Model"
)


def choose_preset(title="Load preset"):
    items = _list_presets()
    if not items:
        forms.alert(
            "No presets saved yet. Open a grid and use Save Preset.", title=TITLE
        )
        return None
    from ui.preset_browser import PresetBrowserWindow
    dialog = PresetBrowserWindow(items, title)
    dialog.ShowDialog()
    return dialog.selected


def _list_presets():
    issues = []
    items = presets.list_presets(issues)
    if issues:
        forms.alert(
            "Some presets or locations could not be read:\n\n{0}".format(
                "\n".join(issues)
            ), title=TITLE,
        )
    return items


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

    subfolder = _choose_user_subfolder(workbook)
    if subfolder is None:
        return None

    selection_mode = workbook.get("selectionMode")
    if selection_mode == "Entire Project":
        selection_mode = "Entire Project File"
    if selection_mode not in SELECTION_MODES:
        selection_mode = forms.SelectFromList.show(
            list(SELECTION_MODES),
            title="Which elements should this preset load?",
            button_name="Save",
            multiselect=False,
        )
        if not selection_mode:
            return None

    path = presets.preset_path(name, subfolder=subfolder)
    if os.path.exists(path) and not forms.alert(
        "A User preset already exists at:\n{0}\n\nReplace it?".format(path),
        title=TITLE, yes=True, no=True,
    ):
        return None

    preset = presets.preset_from_workbook(workbook, layouts, name, selection_mode)
    path = presets.save_preset(preset, subfolder=subfolder)
    item = {
        "source": presets.SOURCE_USER,
        "relativePath": os.path.relpath(path, presets.user_folder()),
    }
    default = presets.default_preset()
    if (not default or presets.preset_reference(default) != item) and forms.alert(
        "Open '{0}' by default from the first wizard step?".format(name),
        title=TITLE, yes=True, no=True,
    ):
        presets.set_default_preset(item)
    workbook["presetRelativePath"] = item["relativePath"]
    workbook["presetSource"] = presets.SOURCE_USER
    return name, path


def _choose_user_subfolder(workbook):
    root_label = "[User root]"
    new_label = "[New subfolder...]"
    relative = workbook.get("presetRelativePath") or ""
    suggested = os.path.dirname(relative)
    folders = presets.user_subfolders()
    if suggested and suggested not in folders:
        folders.append(suggested)
    options = [root_label] + sorted(folders, key=lambda path: path.lower()) + [new_label]
    choice = forms.ask_for_one_item(
        options, title="Save in User presets",
        prompt="User location: {0}".format(presets.user_folder()),
        default=suggested or root_label,
    )
    if not choice:
        return None
    if choice == new_label:
        relative = forms.ask_for_string(
            default=suggested,
            prompt="Folder path relative to User location (for example Doors\\Audits):",
            title="New User preset subfolder",
        )
        return relative.strip() if relative and relative.strip() else None
    return "" if choice == root_label else choice


_SET_DEFAULT = "Set default preset"
_CLEAR_DEFAULT = "Clear default preset"
_DELETE = "Delete User presets"
_SET_ENTERPRISE = "Set Enterprise location (read-only)"
_CLEAR_ENTERPRISE = "Clear Enterprise location"
_SET_USER = "Set User location"
_OPEN_FOLDER = "Open User location"


def manage_presets():
    try:
        _manage_presets()
    except (IOError, OSError, ValueError) as exc:
        script.get_logger().error("Could not manage ExcelLink presets: {0}".format(exc))
        forms.alert("Could not manage presets:\n{0}".format(exc), title=TITLE)


def _manage_presets():
    default = presets.default_preset()
    enterprise = presets.enterprise_folder()
    actions = [_SET_DEFAULT]
    if presets.load_settings().get("defaultPreset"):
        actions.append(_CLEAR_DEFAULT)
    actions.extend([_DELETE, _SET_ENTERPRISE, _SET_USER])
    if enterprise:
        actions.append(_CLEAR_ENTERPRISE)
    actions.append(_OPEN_FOLDER)
    status = "Default: {0} | Enterprise: {1} | User: {2}".format(
        presets.preset_label(default) if default else "none / unavailable",
        enterprise or "not configured", presets.user_folder(),
    )
    action = forms.SelectFromList.show(
        actions, title="Manage presets - " + status, button_name="Run",
        multiselect=False,
    )
    if action == _SET_DEFAULT:
        item = choose_preset("Choose the default preset")
        if item:
            presets.set_default_preset(item)
    elif action == _CLEAR_DEFAULT:
        presets.set_default_preset(None)
    elif action == _DELETE:
        items = [
            item for item in _list_presets()
            if item["source"] == presets.SOURCE_USER
        ]
        if not items:
            forms.alert("No User presets to delete. Enterprise presets are read-only.",
                        title=TITLE)
            return
        labels = [presets.preset_label(item) for item in items]
        picked = forms.SelectFromList.show(
            labels, title="Choose User presets to delete", button_name="Delete",
            multiselect=True,
        )
        if not picked:
            return
        if isinstance(picked, (str, type(u""))):
            picked = [picked]
        selected = [items[labels.index(label)] for label in picked if label in labels]
        if not selected:
            return
        names = u"\n".join(
            presets.preset_label(item)
            for item in selected
        )
        if forms.alert(
            u"Delete these preset(s)?\n\n{0}".format(names),
            title=TITLE, yes=True, no=True,
        ):
            for item in selected:
                presets.delete_preset(item)
    elif action == _SET_ENTERPRISE:
        folder = forms.pick_folder(title="Enterprise presets location (read-only)")
        if folder:
            presets.set_enterprise_folder(folder)
    elif action == _CLEAR_ENTERPRISE:
        presets.set_enterprise_folder(None)
    elif action == _SET_USER:
        folder = forms.pick_folder(title="User presets location")
        if folder and forms.alert(
            "Use this User location?\n{0}\n\nExisting presets are not moved. "
            "Copy them in Windows Explorer if needed.".format(folder),
            title=TITLE, yes=True, no=True,
        ):
            presets.set_user_folder(folder)
    elif action == _OPEN_FOLDER:
        folder = presets.ensure_user_folder()
        from ui.import_dialogs import open_with_shell

        open_with_shell(folder)
