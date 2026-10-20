# -*- coding: utf-8 -*-
"""Read an edited ExcelLink XLSX and diff it against the open workbook.

No Revit API calls are made here; the result is a list of grid updates that
the web grid turns into pending changes for the user to review and apply.
"""

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

from core.xlsx_export import META_SHEET_NAME, _column_title, _unique_sheet_name

_NONE_LABEL = u"<None>"
_UNIQUE_ID_HEADER = u"unique id"
_ELEMENT_ID_HEADER = u"element id"
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")
_UNIT_SUFFIX = re.compile(r"^(.*?)\s*\[([^\]]*)\]\s*$")
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class _ErrorValue(object):
    def __init__(self, code):
        self.code = code


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _children(node, name):
    return [child for child in node if _local(child.tag) == name]


def _descendants(node, name):
    return [child for child in node.iter() if _local(child.tag) == name]


def _text(value):
    if value is None:
        return u""
    if isinstance(value, bytes) and not isinstance(value, unicode):  # noqa: F821
        return value.decode("utf-8", "replace")
    if not isinstance(value, basestring):  # noqa: F821 - IronPython 2.7
        return unicode(value)  # noqa: F821
    return value


def _norm(value):
    return u" ".join(_text(value).split()).lower()


def _norm_ref_name(value):
    return _norm(value).replace(u" : ", u": ").replace(u" :", u":")


def _column_index(letters):
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _attribute(node, name):
    for key, value in node.attrib.items():
        if _local(key) == name:
            return value
    return None


def _string_item_text(item):
    # Skip phonetic runs (<rPh>), which carry their own <t> elements.
    phonetic = set()
    for ruby in _descendants(item, "rPh"):
        for node in _descendants(ruby, "t"):
            phonetic.add(id(node))
    return u"".join(
        _text(node.text) for node in item.iter()
        if _local(node.tag) == "t" and node.text and id(node) not in phonetic
    )


def _parse_number(text):
    value = float(text)
    if value == int(value) and abs(value) < 2 ** 53:
        return int(value)
    return value


class _XlsxReader(object):
    def __init__(self, file_path):
        self.archive = zipfile.ZipFile(file_path, "r")
        self.names = set(self.archive.namelist())
        self.shared = self._shared_strings()

    def close(self):
        self.archive.close()

    def _xml(self, name):
        return ET.fromstring(self.archive.read(name))

    def _shared_strings(self):
        name = "xl/sharedStrings.xml"
        if name not in self.names:
            return []
        return [_string_item_text(item) for item in _children(self._xml(name), "si")]

    def sheets(self):
        """Return [(sheet_name, part_name)] in workbook order."""
        workbook = self._xml("xl/workbook.xml")
        relationships = {}
        rels_name = "xl/_rels/workbook.xml.rels"
        if rels_name in self.names:
            for rel in _children(self._xml(rels_name), "Relationship"):
                target = rel.get("Target") or ""
                if target.startswith("/"):
                    part = target.lstrip("/")
                else:
                    part = posixpath.normpath(posixpath.join("xl", target))
                relationships[rel.get("Id")] = part
        result = []
        for container in _children(workbook, "sheets"):
            for sheet in _children(container, "sheet"):
                rel_id = sheet.get("{%s}id" % _REL_NS) or _attribute(sheet, "id")
                part = relationships.get(rel_id)
                if part and part in self.names:
                    result.append((_text(sheet.get("name")), part))
        return result

    def rows(self, part):
        """Return a list of rows; each row is a dict {column_index: value}."""
        root = self._xml(part)
        rows = []
        next_row = 1
        for sheet_data in _children(root, "sheetData"):
            for row in _children(sheet_data, "row"):
                row_number = int(row.get("r") or next_row)
                next_row = row_number + 1
                values = {}
                next_col = 0
                for cell in _children(row, "c"):
                    reference = cell.get("r")
                    match = _CELL_REF.match(reference or "")
                    column = _column_index(match.group(1)) if match else next_col
                    next_col = column + 1
                    values[column] = self._cell_value(cell)
                while len(rows) < row_number - 1:
                    rows.append({})
                rows.append(values)
        return rows

    def _cell_value(self, cell):
        cell_type = cell.get("t") or "n"
        value_nodes = _children(cell, "v")
        raw = value_nodes[0].text if value_nodes else None
        if cell_type == "inlineStr":
            inline = _children(cell, "is")
            return _string_item_text(inline[0]) if inline else u""
        if raw is None:
            return None
        if cell_type == "s":
            index = int(raw)
            return self.shared[index] if 0 <= index < len(self.shared) else u""
        if cell_type in ("str", "d"):
            return _text(raw)
        if cell_type == "b":
            return raw.strip() == "1"
        if cell_type == "e":
            return _ErrorValue(_text(raw))
        try:
            return _parse_number(raw)
        except ValueError:
            return _text(raw)


def _read_meta(reader, sheets):
    """Return {'parameterMode', 'sheets': {xlsx_name: {'categoryId', 'parameters'}}}."""
    meta = {"parameterMode": None, "sheets": {}}
    for name, part in sheets:
        if name != META_SHEET_NAME:
            continue
        header = None
        for row in reader.rows(part):
            if header is None:
                if _text(row.get(0)) == u"parameterMode":
                    meta["parameterMode"] = _text(row.get(1)) or None
                elif _text(row.get(0)) == u"sheet":
                    header = dict((_text(v), k) for k, v in row.items())
                continue
            sheet_name = _text(row.get(header.get(u"sheet")))
            if not sheet_name:
                continue
            entry = meta["sheets"].setdefault(
                sheet_name, {"categoryId": None, "parameters": []}
            )
            category_id = row.get(header.get(u"categoryId"))
            if entry["categoryId"] is None and category_id is not None:
                entry["categoryId"] = category_id
            parameter_name = _text(row.get(header.get(u"parameterName")))
            column_type = _text(row.get(header.get(u"columnType")))
            if (column_type == u"parameter" and parameter_name
                    and parameter_name not in entry["parameters"]):
                entry["parameters"].append(parameter_name)
    return meta


def _id_columns(header_row):
    ids = {}
    for index, header in header_row.items():
        key = _norm(header)
        if key == _UNIQUE_ID_HEADER:
            ids["UniqueId"] = index
        elif key == _ELEMENT_ID_HEADER:
            ids["ElementId"] = index
    return ids


def _id_text(value):
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return _text(value).strip()


def read_import_plan(file_path):
    """Describe what an ExcelLink XLSX contains so the grid can be rebuilt.

    Returns {'parameterMode', 'sheets': [{'xlsxName', 'categoryId',
    'parameters', 'uniqueIds', 'elementIds'}], 'issues': [...]}.
    """
    reader = _XlsxReader(file_path)
    try:
        xlsx_sheets = reader.sheets()
        meta = _read_meta(reader, xlsx_sheets)
        if not meta["sheets"]:
            raise ValueError(
                "This file has no hidden '{0}' sheet. Only workbooks saved from "
                "KW ExcelLink can be imported.".format(META_SHEET_NAME)
            )
        plan = {"parameterMode": meta["parameterMode"], "sheets": [], "issues": []}
        for name, part in xlsx_sheets:
            if name == META_SHEET_NAME:
                continue
            entry = meta["sheets"].get(name)
            if entry is None or entry["categoryId"] is None:
                plan["issues"].append({
                    "sheet": name, "row": None, "column": None,
                    "message": u"Worksheet is not described in the ExcelLink metadata "
                               u"(was the tab renamed?); skipped.",
                })
                continue
            rows = reader.rows(part)
            ids = _id_columns(rows[0]) if rows else {}
            if not ids:
                plan["issues"].append({
                    "sheet": name, "row": 1, "column": None,
                    "message": u"No 'Unique ID' or 'Element ID' column; worksheet skipped.",
                })
                continue
            unique_ids = []
            element_ids = []
            for values in rows[1:]:
                unique_id = _id_text(values.get(ids.get("UniqueId")))
                element_id = _id_text(values.get(ids.get("ElementId")))
                if unique_id or element_id:
                    unique_ids.append(unique_id)
                    element_ids.append(element_id)
            plan["sheets"].append({
                "xlsxName": name,
                "categoryId": int(entry["categoryId"]),
                "parameters": list(entry["parameters"]),
                "uniqueIds": unique_ids,
                "elementIds": element_ids,
            })
        return plan
    finally:
        reader.close()


def _match_sheets(workbook, xlsx_sheets, meta):
    targets = workbook.get("sheets") or []
    used = set()
    export_names = {}
    for index, sheet in enumerate(targets):
        export_names[_unique_sheet_name(sheet.get("name"), used).lower()] = index
    by_category = {}
    for index, sheet in enumerate(targets):
        by_category.setdefault(str(sheet.get("categoryId")), []).append(index)

    matches = []
    unmatched = []
    data_sheets = [(name, part) for name, part in xlsx_sheets if name != META_SHEET_NAME]
    for name, part in data_sheets:
        index = export_names.get(name.lower())
        if index is None:
            for sheet_index, sheet in enumerate(targets):
                if _norm(sheet.get("name")) == _norm(name):
                    index = sheet_index
                    break
        if index is None and name in meta["sheets"]:
            candidates = by_category.get(str(meta["sheets"][name]["categoryId"]), [])
            if len(candidates) == 1:
                index = candidates[0]
        if index is None and len(data_sheets) == 1 and len(targets) == 1:
            index = 0
        if index is None:
            unmatched.append(name)
        else:
            matches.append((name, part, index))
    return matches, unmatched


def _map_headers(header_row, sheet):
    """Return ({column_index: column}, id_columns, issues)."""
    columns = [column for column in sheet.get("columns") or []]
    by_title = {}
    by_base = {}
    for column in columns:
        by_title[_norm(_column_title(column))] = column
        by_base.setdefault(_norm(column.get("title") or column.get("field")), column)

    mapped = {}
    ids = {}
    issues = []
    for index, header in header_row.items():
        text = _text(header).strip()
        if not text:
            continue
        key = _norm(text)
        if key == _UNIQUE_ID_HEADER:
            ids["UniqueId"] = index
            continue
        if key == _ELEMENT_ID_HEADER:
            ids["ElementId"] = index
            continue
        column = by_title.get(key)
        if column is None:
            match = _UNIT_SUFFIX.match(text)
            base = _norm(match.group(1)) if match else key
            unit = match.group(2).strip() if match else u""
            column = by_base.get(base)
            if column is not None and _text(column.get("unit")) != unit:
                issues.append(
                    u"Column '{0}' was saved in [{1}] but the project now uses [{2}]; "
                    u"column skipped.".format(text, unit, _text(column.get("unit")))
                )
                continue
        if column is None:
            if key not in (u"category", u"is type row", u"type element id", u"type key"):
                issues.append(u"Column '{0}' does not match any grid column; skipped.".format(text))
            continue
        if column.get("columnType") in ("parameter", "typeName"):
            mapped[index] = column
    return mapped, ids, issues


def _is_blank(value):
    return value is None or (isinstance(value, basestring) and not value.strip())  # noqa: F821


def _format_number_as_text(value):
    if isinstance(value, float) and value == int(value) and abs(value) < 2 ** 53:
        return unicode(int(value))  # noqa: F821
    if isinstance(value, float):
        return unicode("%.15g" % value)  # noqa: F821
    return unicode(value)  # noqa: F821


def _coerce(value, column):
    """Convert a cell value to the grid value; returns (value, error, skip_blank)."""
    if isinstance(value, _ErrorValue):
        return None, u"Excel error value {0}".format(value.code), False
    storage = column.get("storageType")
    if column.get("columnType") == "typeName":
        storage = "String"

    if storage == "String":
        if value is None:
            return u"", None, False
        if isinstance(value, bool):
            return (u"TRUE" if value else u"FALSE"), None, False
        if isinstance(value, (int, long, float)):  # noqa: F821
            return _format_number_as_text(value), None, False
        return _text(value), None, False

    if _is_blank(value):
        return None, None, True

    if storage in ("Double", "Integer"):
        number = value
        if isinstance(value, bool):
            number = 1 if value else 0
        elif isinstance(value, basestring):  # noqa: F821
            text = value.strip()
            unit = _text(column.get("unit"))
            if unit and text.endswith(unit):
                text = text[:-len(unit)].strip()
            lowered = text.lower()
            if storage == "Integer" and lowered in ("yes", "true", "y"):
                number = 1
            elif storage == "Integer" and lowered in ("no", "false", "n"):
                number = 0
            else:
                try:
                    number = float(text.replace(",", ""))
                except ValueError:
                    return None, u"'{0}' is not a number".format(value), False
        if storage == "Integer":
            if float(number) != int(float(number)):
                return None, u"'{0}' is not a whole number".format(value), False
            return int(float(number)), None, False
        number = float(number)
        if number != number or number in (float("inf"), float("-inf")):
            return None, u"'{0}' is not a finite number".format(value), False
        return number, None, False

    if storage == "ElementId":
        text = _text(value if not isinstance(value, (int, long, float)) else  # noqa: F821
                     _format_number_as_text(value)).strip()
        options = column.get("options") or []
        wanted = _norm_ref_name(text)
        for option in options:
            if _norm_ref_name(option) == wanted:
                return option, None, False
        bare = [
            option for option in options
            if u": " in option and _norm_ref_name(option.split(u": ", 1)[1]) == wanted
        ]
        if len(bare) == 1:
            return bare[0], None, False
        if len(bare) > 1:
            return None, u"'{0}' matches {1} types; use 'Family: Type'".format(
                text, len(bare)), False
        return None, u"'{0}' is not a valid choice".format(text), False

    return None, u"column cannot be edited", False


def _same(left, right, storage):
    if storage == "Double":
        if left is None or right is None:
            return left is None and right is None
        try:
            left_value, right_value = float(left), float(right)
        except (TypeError, ValueError):
            return False
        scale = max(1.0, abs(left_value), abs(right_value))
        return abs(left_value - right_value) <= 1e-9 * scale
    if storage == "Integer":
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return left == right
    if storage == "ElementId":
        return _norm_ref_name(left or _NONE_LABEL) == _norm_ref_name(right or _NONE_LABEL)
    return _text(left) == _text(right)


def _cell_editable(column, row):
    if column.get("disabled") or column.get("editable") is False:
        return False
    if column.get("columnType") == "typeName":
        return row.get("TypeNameEditable") is not False and row.get("TypeElementId") is not None
    return not row.get(u"{0}__disabled".format(column.get("field")))


def diff_xlsx(workbook, file_path):
    """Compare an XLSX against the workbook; return {'updates', 'summary', 'issues'}."""
    reader = _XlsxReader(file_path)
    try:
        xlsx_sheets = reader.sheets()
        meta = _read_meta(reader, xlsx_sheets)
        matches, unmatched_sheets = _match_sheets(workbook, xlsx_sheets, meta)
        updates = []
        issues = []
        summary = {
            "sheets": 0, "rowsRead": 0, "rowsUnmatched": 0,
            "changed": 0, "unchanged": 0, "skipped": 0,
        }
        for name in unmatched_sheets:
            issues.append({"sheet": name, "row": None, "column": None,
                           "message": u"Worksheet does not match any grid sheet; skipped."})

        for xlsx_name, part, sheet_index in matches:
            sheet = workbook["sheets"][sheet_index]
            rows = reader.rows(part)
            if not rows:
                continue
            summary["sheets"] += 1
            mapped, ids, header_issues = _map_headers(rows[0], sheet)
            for message in header_issues:
                issues.append({"sheet": xlsx_name, "row": 1, "column": None, "message": message})
            if "UniqueId" not in ids and "ElementId" not in ids:
                issues.append({"sheet": xlsx_name, "row": 1, "column": None,
                               "message": u"No 'Unique ID' or 'Element ID' column; worksheet skipped."})
                continue

            by_unique = {}
            by_element = {}
            for row in sheet.get("rows") or []:
                by_unique[_text(row.get("UniqueId"))] = row
                by_element[_text(row.get("ElementId"))] = row

            # (field, typeElementId) -> {"column", "row", "current", "values": [(value, xlsx_row)]}
            type_groups = {}
            for row_offset, values in enumerate(rows[1:]):
                xlsx_row = row_offset + 2
                if not any(not _is_blank(v) for v in values.values()):
                    continue
                summary["rowsRead"] += 1
                grid_row = None
                if "UniqueId" in ids:
                    grid_row = by_unique.get(_text(values.get(ids["UniqueId"])).strip())
                if grid_row is None and "ElementId" in ids:
                    element_id = values.get(ids["ElementId"])
                    if isinstance(element_id, float) and element_id == int(element_id):
                        element_id = int(element_id)
                    grid_row = by_element.get(_text(element_id).strip())
                if grid_row is None:
                    summary["rowsUnmatched"] += 1
                    continue

                for column_index, column in mapped.items():
                    field = column["field"]
                    title = _column_title(column)
                    value, error, skip_blank = _coerce(values.get(column_index), column)
                    if skip_blank:
                        continue
                    storage = "String" if column.get("columnType") == "typeName" \
                        else column.get("storageType")
                    current = grid_row.get(field)
                    if error is None and _same(value, current, storage):
                        summary["unchanged"] += 1
                        continue
                    if not _cell_editable(column, grid_row):
                        raw = values.get(column_index)
                        if _norm_ref_name(_text(raw)) == _norm_ref_name(_text(current)) or \
                                (current is None and _is_blank(raw)):
                            summary["unchanged"] += 1
                            continue
                        summary["skipped"] += 1
                        note = grid_row.get(u"{0}__note".format(field))
                        issues.append({"sheet": xlsx_name, "row": xlsx_row, "column": title,
                                       "message": u"Cell is read-only in Revit; '{0}' ignored (Revit value '{1}').{2}".format(
                                           _text(raw), _text(current), u" " + _text(note) if note else u"")})
                        continue
                    if error is not None:
                        summary["skipped"] += 1
                        issues.append({"sheet": xlsx_name, "row": xlsx_row, "column": title,
                                       "message": error})
                        continue
                    if column.get("target") in ("type", "typeName"):
                        key = (field, _text(grid_row.get("TypeElementId")))
                        group = type_groups.setdefault(key, {
                            "column": column, "row": grid_row, "storage": storage,
                            "values": [],
                        })
                        group["values"].append((value, xlsx_row))
                        continue
                    updates.append({
                        "sheetIndex": sheet_index,
                        "field": field,
                        "uniqueId": grid_row.get("UniqueId"),
                        "typeElementId": grid_row.get("TypeElementId"),
                        "value": value,
                        "oldValue": current,
                    })

            for (field, _), group in type_groups.items():
                distinct = []
                for value, _row in group["values"]:
                    if not any(_same(value, seen, group["storage"]) for seen in distinct):
                        distinct.append(value)
                if len(distinct) > 1:
                    summary["skipped"] += 1
                    issues.append({
                        "sheet": xlsx_name,
                        "row": u", ".join(_text(r) for _, r in group["values"]),
                        "column": _column_title(group["column"]),
                        "message": u"Rows sharing type '{0}' have different new values; "
                                   u"type change ignored.".format(_text(group["row"].get("TypeName"))),
                    })
                    continue
                updates.append({
                    "sheetIndex": sheet_index,
                    "field": field,
                    "uniqueId": group["row"].get("UniqueId"),
                    "typeElementId": group["row"].get("TypeElementId"),
                    "value": distinct[0],
                    "oldValue": group["row"].get(field),
                })

        summary["changed"] = len(updates)
        return {"updates": updates, "summary": summary, "issues": issues}
    finally:
        reader.close()
