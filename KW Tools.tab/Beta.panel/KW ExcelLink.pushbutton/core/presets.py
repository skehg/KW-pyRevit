# -*- coding: utf-8 -*-
"""Named grid presets stored per user (and optionally in a shared folder).

A preset records the wizard choices (selection mode, parameter mode,
categories and ordered parameters) plus column layout, filters and formula
templates. It contains no element data, so it can be reused in any project.
"""

import io
import json
import os
import re

PRESET_VERSION = 1
SOURCE_PERSONAL = "personal"
SOURCE_SHARED = "shared"
_EXTENSION = ".json"


def _app_data_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(root, "KW", "ExcelLink")


def personal_folder():
    return os.path.join(_app_data_dir(), "presets")


def _settings_path():
    return os.path.join(_app_data_dir(), "settings.json")


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.loads(handle.read())


def _write_json(path, data):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    if not isinstance(text, type(u"")):
        text = text.decode("utf-8")
    temp_path = path + ".tmp"
    with io.open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.path.exists(path):
        os.remove(path)
    os.rename(temp_path, path)


def load_settings():
    try:
        settings = _read_json(_settings_path())
    except (IOError, OSError, ValueError):
        settings = {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings):
    _write_json(_settings_path(), settings)


def shared_folder():
    folder = load_settings().get("sharedFolder")
    return folder or None


def set_shared_folder(folder):
    settings = load_settings()
    if folder:
        settings["sharedFolder"] = folder
    else:
        settings.pop("sharedFolder", None)
    save_settings(settings)


def folder_for(source):
    return shared_folder() if source == SOURCE_SHARED else personal_folder()


def safe_file_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        raise ValueError("Enter a preset name.")
    return cleaned + _EXTENSION


def _list_folder(folder, source):
    presets = []
    if not folder or not os.path.isdir(folder):
        return presets
    for file_name in sorted(os.listdir(folder)):
        if not file_name.lower().endswith(_EXTENSION):
            continue
        path = os.path.join(folder, file_name)
        try:
            data = _read_json(path)
        except (IOError, OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("sheets"), list):
            continue
        presets.append({
            "name": data.get("name") or file_name[:-len(_EXTENSION)],
            "path": path,
            "source": source,
        })
    return presets


def list_presets():
    """Personal presets first; shared presets with the same name are hidden."""
    personal = _list_folder(personal_folder(), SOURCE_PERSONAL)
    names = set(item["name"].lower() for item in personal)
    shared = [
        item for item in _list_folder(shared_folder(), SOURCE_SHARED)
        if item["name"].lower() not in names
    ]
    return sorted(personal + shared, key=lambda item: item["name"].lower())


def preset_label(item):
    return item["name"] + (" [shared]" if item["source"] == SOURCE_SHARED else "")


def find_preset(name):
    for item in list_presets():
        if item["name"].lower() == (name or "").lower():
            return item
    return None


def load_preset(path):
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("sheets"), list):
        raise ValueError("{0} is not an ExcelLink preset.".format(path))
    if int(data.get("version") or 0) > PRESET_VERSION:
        raise ValueError(
            "{0} was saved by a newer version of ExcelLink.".format(path)
        )
    return data


def preset_path(name, source=SOURCE_PERSONAL):
    folder = folder_for(source)
    if not folder:
        raise ValueError("No shared presets folder is configured.")
    return os.path.join(folder, safe_file_name(name))


def save_preset(preset, source=SOURCE_PERSONAL):
    path = preset_path(preset["name"], source)
    _write_json(path, preset)
    return path


def delete_preset(item):
    os.remove(item["path"])
    if (default_preset_name() or "").lower() == item["name"].lower():
        set_default_preset(None)


def default_preset_name():
    return load_settings().get("defaultPreset") or None


def set_default_preset(name):
    settings = load_settings()
    if name:
        settings["defaultPreset"] = name
    else:
        settings.pop("defaultPreset", None)
    save_settings(settings)


def category_display_name(label):
    """Strip the ' [id]' suffix the wizard adds to category labels."""
    return re.sub(r"\s*\[-?\d+\]$", "", label or "")


def preset_from_workbook(workbook, layouts, name, selection_mode):
    sheets = []
    for index, sheet in enumerate(workbook.get("sheets") or []):
        layout = layouts[index] if index < len(layouts or []) else None
        sheets.append({
            "categoryKey": sheet.get("categoryKey"),
            "categoryName": category_display_name(sheet.get("name")),
            "parameters": list(sheet.get("parameters") or []),
            "layout": _clean_layout(layout),
        })
    return {
        "version": PRESET_VERSION,
        "name": name,
        "selectionMode": selection_mode,
        "parameterMode": workbook.get("parameterMode"),
        "sheets": sheets,
    }


def _clean_layout(layout):
    layout = layout if isinstance(layout, dict) else {}
    widths = {}
    for title, width in (layout.get("widths") or {}).items():
        try:
            widths[title] = int(round(float(width)))
        except (TypeError, ValueError):
            continue
    sort = []
    for item in layout.get("sort") or []:
        if isinstance(item, dict) and item.get("title") and item.get("dir") in ("asc", "desc"):
            sort.append({"title": item["title"], "dir": item["dir"]})
    return {
        "widths": widths, "sort": sort,
        "filters": _clean_filters(layout.get("filters")),
        "formulas": _clean_formulas(layout.get("formulas")),
    }


_SHOW_OPTIONS = ("all", "pending", "notPending", "editable", "readOnly", "typeRows", "instanceRows")
_FILTER_OPERATORS = (
    "contains", "notContains", "equals", "notEquals", "startsWith", "endsWith",
    "gt", "gte", "lt", "lte", "between", "empty", "notEmpty", "wildcard", "regex",
)


def _is_text(value):
    return isinstance(value, (str, type(u"")))


def _clean_formulas(formulas):
    """Column templates carry title bindings, never element data or results."""
    result = {}
    if not isinstance(formulas, dict):
        return result
    for title, rule in formulas.items():
        if not _is_text(title) or not isinstance(rule, dict):
            continue
        expression = rule.get("expression")
        columns = rule.get("columns")
        if (not _is_text(expression) or not expression.strip().startswith("=")
                or not isinstance(columns, list)
                or not all(_is_text(column) for column in columns)):
            continue
        result[title] = {
            "expression": expression.strip(),
            "columns": list(columns),
            "scope": "all" if rule.get("scope") == "all" else "visible",
        }
    return result


def _clean_filters(filters):
    """Keep only the filter shapes the grid understands (see web/filters.js)."""
    filters = filters if isinstance(filters, dict) else {}
    headers = {}
    for title, expression in (filters.get("headers") or {}).items():
        if _is_text(title) and _is_text(expression) and expression.strip():
            headers[title] = expression
    values = {}
    for title, items in (filters.get("values") or {}).items():
        if _is_text(title) and isinstance(items, list):
            values[title] = [item if _is_text(item) else u"{0}".format(item) for item in items]
    search = filters.get("search")
    return {
        "search": search if _is_text(search) else "",
        "show": filters.get("show") if filters.get("show") in _SHOW_OPTIONS else "all",
        "headers": headers,
        "values": values,
        "advanced": _clean_rule_group(filters.get("advanced"), 0),
    }


def _clean_rule_group(group, depth):
    group = group if isinstance(group, dict) else {}
    rules = []
    for rule in group.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        if isinstance(rule.get("rules"), list):
            if depth < 2:
                rules.append(_clean_rule_group(rule, depth + 1))
        elif _is_text(rule.get("title")) and rule.get("op") in _FILTER_OPERATORS:
            rules.append({
                "title": rule["title"],
                "op": rule["op"],
                "value": u"{0}".format(rule.get("value") if rule.get("value") is not None else ""),
                "value2": u"{0}".format(rule.get("value2") if rule.get("value2") is not None else ""),
            })
    return {"join": "or" if group.get("join") == "or" else "and", "rules": rules}


def match_category(preset_sheet, options):
    """Find the wizard category option for a preset sheet.

    Built-in categories match on their BuiltInCategory name so presets work in
    any project and Revit language; others fall back to the display name.
    """
    key = preset_sheet.get("categoryKey")
    if key:
        for option in options:
            if option.get("builtin") == key:
                return option
    name = (preset_sheet.get("categoryName") or "").lower()
    for option in options:
        if category_display_name(option["label"]).lower() == name:
            return option
    return None
