# -*- coding: utf-8 -*-
"""Named grid presets in writable User and read-only Enterprise libraries.

A preset records the wizard choices (selection mode, parameter mode,
categories and ordered parameters) plus column layout, primary-first sort
levels, filters and formula templates. It contains no element data, so it can
be reused in any project.
"""

import io
import json
import logging
import os
import re

PRESET_VERSION = 2
SOURCE_USER = "user"
SOURCE_ENTERPRISE = "enterprise"
_EXTENSION = ".json"
_LOGGER = logging.getLogger(__name__)


def _app_data_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(root, "KW", "ExcelLink")


def default_user_folder():
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
    except (IOError, OSError) as exc:
        if exc.errno == 2:
            return {}
        raise
    if not isinstance(settings, dict):
        raise ValueError("ExcelLink settings must contain a JSON object.")
    return settings


def save_settings(settings):
    _write_json(_settings_path(), settings)


def user_folder():
    return load_settings().get("userFolder") or default_user_folder()


def enterprise_folder():
    settings = load_settings()
    return settings.get("enterpriseFolder", settings.get("sharedFolder")) or None


def _normalized(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _inside(path, root):
    path, root = _normalized(path), _normalized(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _set_folder(key, folder):
    if folder:
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            raise ValueError("Choose an existing presets folder: {0}".format(folder))
        other = enterprise_folder() if key == "userFolder" else user_folder()
        if other and (_inside(folder, other) or _inside(other, folder)):
            raise ValueError("Enterprise and User locations must not overlap.")
    settings = load_settings()
    if folder:
        settings[key] = folder
    else:
        settings.pop(key, None)
    if key == "enterpriseFolder":
        settings.pop("sharedFolder", None)
    save_settings(settings)


def set_user_folder(folder):
    _set_folder("userFolder", folder or default_user_folder())


def set_enterprise_folder(folder):
    _set_folder("enterpriseFolder", folder)


def folder_for(source):
    if source == SOURCE_USER:
        return user_folder()
    if source == SOURCE_ENTERPRISE:
        return enterprise_folder()
    raise ValueError("Unknown preset library: {0}".format(source))


def safe_file_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        raise ValueError("Enter a preset name.")
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", cleaned, re.I):
        raise ValueError("This preset name is reserved by Windows.")
    return cleaned + _EXTENSION


def _report_issue(message, issues):
    _LOGGER.warning(message)
    if issues is not None:
        issues.append(message)


def _walk_library(folder, issues=None):
    if not folder:
        return
    if not os.path.isdir(folder):
        if folder != default_user_folder() or os.path.exists(folder):
            _report_issue("Presets location unavailable: {0}".format(folder), issues)
        return

    def on_error(exc):
        _report_issue("Could not read presets: {0}".format(exc), issues)

    for current, directories, files in os.walk(folder, onerror=on_error, followlinks=False):
        directories[:] = sorted(
            [name for name in directories
             if not os.path.islink(os.path.join(current, name))
             and _inside(os.path.join(current, name), folder)],
            key=lambda name: name.lower(),
        )
        yield current, files


def _list_folder(folder, source, issues=None):
    items = []
    for current, files in _walk_library(folder, issues):
        for file_name in sorted(files):
            if not file_name.lower().endswith(_EXTENSION):
                continue
            path = os.path.join(current, file_name)
            if not _inside(path, folder):
                _report_issue("Preset points outside its library: {0}".format(path), issues)
                continue
            try:
                data = load_preset(path)
                if not isinstance(data.get("name", ""), (str, type(u""))):
                    raise ValueError("Preset name must be text.")
            except (IOError, OSError, ValueError, TypeError) as exc:
                _report_issue("Could not load preset {0}: {1}".format(path, exc), issues)
                continue
            items.append({
                "name": data.get("name") or file_name[:-len(_EXTENSION)],
                "path": path,
                "source": source,
                "relativePath": os.path.relpath(path, folder),
            })
    return items


def list_presets(issues=None):
    """Keep both libraries and every subfolder visible, including duplicate names."""
    items = _list_folder(enterprise_folder(), SOURCE_ENTERPRISE, issues)
    items.extend(_list_folder(user_folder(), SOURCE_USER, issues))
    return sorted(items, key=lambda item: (
        item["source"], item["relativePath"].lower()
    ))


def preset_label(item):
    return "{0} [{1}: {2}]".format(
        item["name"], item["source"].title(), item["relativePath"]
    )


def preset_reference(item):
    return {"source": item["source"], "relativePath": item["relativePath"]}


def find_preset(reference):
    if not reference:
        return None
    items = list_presets()
    if isinstance(reference, dict):
        for item in items:
            if (item["source"] == reference.get("source")
                    and os.path.normcase(item["relativePath"])
                    == os.path.normcase(reference.get("relativePath") or "")):
                return item
    else:
        # Legacy defaults used a name, with personal presets taking precedence.
        for source in (SOURCE_USER, SOURCE_ENTERPRISE):
            for item in items:
                if item["source"] == source and item["name"].lower() == reference.lower():
                    return item
    return None


def load_preset(path):
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("sheets"), list):
        raise ValueError("{0} is not an ExcelLink preset.".format(path))
    version = int(data.get("version") or 0)
    if version > PRESET_VERSION:
        raise ValueError(
            "{0} was saved by a newer version of ExcelLink.".format(path)
        )
    if version < 2 and data.get("selectionMode") == "Entire Model":
        # Before v2, Entire Model included every unused type in the project.
        data["selectionMode"] = "Entire Project File"
    if data.get("selectionMode") == "Entire Project":
        data["selectionMode"] = "Entire Project File"
    data["version"] = PRESET_VERSION
    return data


def _relative_path(path):
    path = (path or "").replace("\\", os.sep).replace("/", os.sep)
    if os.path.isabs(path) or os.path.splitdrive(path)[0]:
        raise ValueError("Choose a relative path inside the User presets location.")
    if any(part == ".." for part in path.split(os.sep)):
        raise ValueError("Preset folders must stay inside the User location.")
    for part in path.split(os.sep):
        if part in ("", "."):
            continue
        if (re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((" ", "."))
                or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", part, re.I)):
            raise ValueError("Invalid Windows folder or file name: {0}".format(part))
    result = os.path.normpath(path)
    return "" if result == "." else result


def _user_path(relative):
    root = user_folder()
    path = os.path.join(root, _relative_path(relative))
    enterprise = enterprise_folder()
    if not _inside(path, root) or (enterprise and _inside(path, enterprise)):
        raise ValueError("Enterprise presets are read-only. Choose a User folder.")
    return path


def user_subfolders():
    return sorted([
        os.path.relpath(current, user_folder())
        for current, files in _walk_library(user_folder())
        if _normalized(current) != _normalized(user_folder())
    ], key=lambda path: path.lower())


def ensure_user_folder(subfolder=""):
    path = _user_path(subfolder)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def preset_path(name, source=SOURCE_USER, subfolder=""):
    if source != SOURCE_USER:
        raise ValueError("Enterprise presets are read-only. Save a User copy instead.")
    folder = folder_for(source)
    if not folder:
        raise ValueError("No User presets location is configured.")
    return _user_path(os.path.join(_relative_path(subfolder), safe_file_name(name)))


def save_preset(preset, source=SOURCE_USER, subfolder=""):
    path = preset_path(preset["name"], source, subfolder)
    _write_json(path, preset)
    return path


def delete_preset(item):
    if item["source"] != SOURCE_USER:
        raise ValueError("Enterprise presets are read-only.")
    path = _user_path(item["relativePath"])
    if _normalized(path) != _normalized(item["path"]):
        raise ValueError("Preset no longer belongs to the configured User location.")
    default = default_preset()
    os.remove(path)
    if default and preset_reference(default) == preset_reference(item):
        set_default_preset(None)


def default_preset():
    reference = load_settings().get("defaultPreset")
    item = find_preset(reference)
    if item and not isinstance(reference, dict):
        set_default_preset(item)
    return item


def set_default_preset(item):
    settings = load_settings()
    if item:
        settings["defaultPreset"] = preset_reference(item)
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
        categories = []
        for category in sheet.get("categories") or []:
            categories.append({
                "categoryId": category.get("categoryId"),
                "categoryKey": category.get("categoryKey"),
                "name": category.get("name"),
            })
        if not categories and sheet.get("categoryId") is not None:
            categories.append({
                "categoryId": sheet.get("categoryId"),
                "categoryKey": sheet.get("categoryKey"),
                "name": category_display_name(sheet.get("name")),
            })
        sheets.append({
            "categoryKey": sheet.get("categoryKey"),
            "sheetKey": sheet.get("sheetKey") or sheet.get("categoryKey"),
            "categoryId": sheet.get("categoryId"),
            "categoryName": category_display_name(sheet.get("name")),
            "categories": categories,
            "parameters": list(sheet.get("parameters") or []),
            "layout": _clean_layout(layout),
        })
    return {
        "version": PRESET_VERSION,
        "name": name,
        "selectionMode": selection_mode,
        "parameterMode": workbook.get("parameterMode"),
        "gridLayout": workbook.get("gridLayout") or "separate",
        "fieldOptions": workbook.get("fieldOptions"),
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


_SHOW_OPTIONS = (
    "all", "topLevelInstances", "pending", "notPending", "editable",
    "readOnly", "typeRows", "instanceRows",
)
_FILTER_OPERATORS = (
    "contains", "notContains", "equals", "notEquals", "startsWith", "notStartsWith",
    "endsWith", "notEndsWith", "gt", "gte", "lt", "lte", "between", "empty",
    "notEmpty", "wildcard", "regex",
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
    try:
        category_id = int(preset_sheet.get("categoryId"))
    except (TypeError, ValueError):
        category_id = None
    if category_id is not None:
        for option in options:
            if option.get("category_id") == category_id:
                return option
    name = (preset_sheet.get("categoryName") or preset_sheet.get("name") or "").lower()
    for option in options:
        if category_display_name(option["label"]).lower() == name:
            return option
    return None
