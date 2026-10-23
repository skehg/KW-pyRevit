# -*- coding: utf-8 -*-
"""Read an edited ExcelLink XLSX and diff it against the open workbook.

No Revit API calls are made here; the result is a list of grid updates that
the web grid turns into pending changes for the user to review and apply.
"""

import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

from core.xlsx_export import (
    ID_FIELDS, META_SHEET_NAME, SCHEMA_VERSION, _META_FIELDS,
    _column_title, _header_type, _unique_sheet_name,
)

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
    """Read and validate the authoritative version-2 hidden schema."""
    meta = {"parameterMode": None, "gridLayout": None, "sheets": {}}
    found = False
    for name, part in sheets:
        if name != META_SHEET_NAME:
            continue
        if found:
            raise ValueError("The workbook contains duplicate ExcelLink metadata sheets.")
        found = True
        rows = reader.rows(part)
        header = rows[0] if rows else {}
        actual_fields = dict((_text(value), index) for index, value in header.items())
        if set(actual_fields) != set(_META_FIELDS):
            raise ValueError("ExcelLink metadata has an unsupported or malformed schema.")
        if len(actual_fields) != len(_META_FIELDS):
            raise ValueError("ExcelLink metadata contains duplicate field names.")
        for values in rows[1:]:
            record = dict(
                (field, values.get(actual_fields[field]))
                for field in _META_FIELDS
            )
            if _text(record.get("schemaVersion")) != SCHEMA_VERSION:
                raise ValueError("Unsupported ExcelLink XLSX schema version.")
            layout = _text(record.get("gridLayout"))
            if layout not in (u"combined", u"separate"):
                raise ValueError("ExcelLink metadata has an invalid gridLayout.")
            if meta["gridLayout"] is not None and meta["gridLayout"] != layout:
                raise ValueError("ExcelLink metadata has conflicting gridLayout values.")
            meta["gridLayout"] = layout
            mode = _text(record.get("parameterMode")) or None
            if meta["parameterMode"] is not None and meta["parameterMode"] != mode:
                raise ValueError("ExcelLink metadata has conflicting parameter modes.")
            meta["parameterMode"] = mode
            sheet_name = _text(record.get("sheet"))
            sheet_key = _text(record.get("sheetKey"))
            if not sheet_name or not sheet_key:
                raise ValueError("ExcelLink worksheet metadata is missing its sheet identity.")
            entry = meta["sheets"].get(sheet_name)
            if entry is None:
                try:
                    categories = json.loads(_text(record.get("categories")))
                    declared_parameter_keys = json.loads(
                        _text(record.get("parameterKeys"))
                    )
                except (TypeError, ValueError):
                    raise ValueError("ExcelLink worksheet metadata is malformed.")
                if not isinstance(categories, list) or not categories:
                    raise ValueError("ExcelLink worksheet category metadata is empty.")
                if (not isinstance(declared_parameter_keys, list)
                        or any(not isinstance(key, basestring) or not key
                               for key in declared_parameter_keys)):
                    raise ValueError("ExcelLink parameter-key metadata is malformed.")
                category_keys = set()
                category_ids = set()
                for category in categories:
                    if (not isinstance(category, dict)
                            or category.get("categoryId") is None
                            or not category.get("categoryKey")
                            or not category.get("name")):
                        raise ValueError("ExcelLink category metadata is incomplete.")
                    category_key = _text(category.get("categoryKey"))
                    category_id = _text(category.get("categoryId"))
                    if category_key in category_keys or category_id in category_ids:
                        raise ValueError("ExcelLink category metadata contains duplicates.")
                    category_keys.add(category_key)
                    category_ids.add(category_id)
                entry = {
                    "xlsxName": sheet_name, "sheetName": sheet_name,
                    "sheetKey": sheet_key,
                    "gridLayout": layout, "categoryId": record.get("categoryId"),
                    "categoryKey": _text(record.get("categoryKey")) or None,
                    "categories": categories, "parameterKeys": [],
                    "declaredParameterKeys": declared_parameter_keys,
                    "parameters": [], "parameterUsage": {}, "columns": [],
                }
                meta["sheets"][sheet_name] = entry
            else:
                try:
                    current_categories = json.loads(_text(record.get("categories")))
                    current_keys = json.loads(_text(record.get("parameterKeys")))
                except (TypeError, ValueError):
                    raise ValueError("ExcelLink worksheet metadata is malformed.")
                if (entry["sheetKey"] != sheet_key or entry["gridLayout"] != layout
                        or entry["categories"] != current_categories
                        or entry["declaredParameterKeys"] != current_keys):
                    raise ValueError("ExcelLink worksheet metadata is inconsistent.")
            record["parameterKey"] = _text(record.get("parameterKey")) or None
            record["parameterName"] = _text(record.get("parameterName")) or None
            record["parameterIdentity"] = _text(record.get("parameterIdentity")) or None
            record["specTypeId"] = _text(record.get("specTypeId")) or None
            for json_key in ("options", "referenceKind"):
                raw_json = record.get(json_key)
                if raw_json in (None, u""):
                    record[json_key] = None
                else:
                    try:
                        record[json_key] = json.loads(_text(raw_json))
                    except (TypeError, ValueError):
                        raise ValueError(
                            "ExcelLink column metadata '{0}' is malformed.".format(json_key)
                        )
            if record.get("columnType") == u"parameter":
                key = record["parameterKey"]
                if not key or not record["parameterName"] or not record["parameterIdentity"] \
                        or not record["specTypeId"]:
                    raise ValueError("ExcelLink parameter metadata is missing its stable identity.")
                try:
                    usage = json.loads(_text(record.get("usage")))
                except (TypeError, ValueError):
                    raise ValueError("ExcelLink parameter usage metadata is malformed.")
                if not isinstance(usage, dict):
                    raise ValueError("ExcelLink parameter usage metadata is malformed.")
                for required in ("name", "displayName", "identity", "specTypeId",
                                 "dataType", "storageType", "isType", "isInstance"):
                    if required not in usage:
                        raise ValueError(
                            "ExcelLink parameter usage is missing '{0}'.".format(required)
                        )
                if (usage.get("name") != record["parameterName"]
                        or usage.get("identity") != record["parameterIdentity"]
                        or usage.get("specTypeId") != record["specTypeId"]
                        or usage.get("storageType") != _text(record.get("storageType"))):
                    raise ValueError("ExcelLink parameter usage identity is inconsistent.")
                if _as_bool(usage.get("isType")) != _as_bool(record.get("isType")) \
                        or _as_bool(usage.get("isInstance")) != _as_bool(record.get("isInstance")):
                    raise ValueError("ExcelLink parameter usage flags are inconsistent.")
                previous = entry["parameterUsage"].get(key)
                if previous is not None and previous != usage:
                    raise ValueError("ExcelLink metadata has conflicting parameter identities.")
                if previous is None:
                    entry["parameterKeys"].append(key)
                    entry["parameters"].append(usage["name"])
                    entry["parameterUsage"][key] = usage
            field = _text(record.get("field"))
            if not field:
                raise ValueError("ExcelLink column metadata is missing its field identity.")
            record["field"] = field
            try:
                record["columnIndex"] = int(record.get("columnIndex"))
            except (TypeError, ValueError):
                raise ValueError("ExcelLink column metadata is missing its column index.")
            record["target"] = _text(record.get("target")) or None
            entry["columns"].append(record)
    if not found or not meta["sheets"]:
        raise ValueError("The workbook has no valid hidden '{0}' schema.".format(META_SHEET_NAME))
    for entry in meta["sheets"].values():
        entry["columns"].sort(key=lambda column: column["columnIndex"])
        if [column["columnIndex"] for column in entry["columns"]] != list(
                range(len(entry["columns"]))):
            raise ValueError("ExcelLink column metadata has duplicate or missing indices.")
        fields = set()
        parameter_targets = set()
        for column in entry["columns"]:
            if column["field"] in fields:
                raise ValueError("ExcelLink column metadata contains duplicate fields.")
            fields.add(column["field"])
            if column.get("columnType") == u"parameter":
                key_target = (column.get("parameterKey"), column.get("target"))
                if not key_target[0] or key_target[1] not in ("type", "instance"):
                    raise ValueError("ExcelLink parameter column identity is invalid.")
                if key_target in parameter_targets:
                    raise ValueError(
                        "ExcelLink metadata contains duplicate parameter key/target columns."
                    )
                parameter_targets.add(key_target)
        if entry["parameterKeys"] != entry["declaredParameterKeys"]:
            raise ValueError("ExcelLink parameter keys do not match the hidden worksheet schema.")
        if entry["gridLayout"] == "combined":
            if entry["categoryId"] not in (None, u"") or not entry["categoryKey"]:
                raise ValueError("Combined worksheet category metadata is invalid.")
        elif entry["gridLayout"] == "separate":
            if len(entry["categories"]) != 1:
                raise ValueError("Separate worksheets must declare exactly one category.")
            category = entry["categories"][0]
            if (str(entry["categoryId"]) != str(category.get("categoryId"))
                    or entry["categoryKey"] != category.get("categoryKey")):
                raise ValueError("Separate worksheet category metadata is inconsistent.")
    return meta


def _as_bool(value):
    if value in (True, 1, u"1", u"true", u"True"):
        return True
    if value in (False, 0, u"0", u"false", u"False", None, u""):
        return False
    raise ValueError("ExcelLink metadata contains an invalid boolean value.")


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


def _validate_worksheet_headers(rows, metadata_columns, sheet_name):
    if len(rows) < 2:
        raise ValueError(
            "Worksheet '{0}' does not contain both header rows.".format(sheet_name)
        )
    expected_columns = len(metadata_columns)
    for header in rows[:2]:
        if set(header) != set(range(expected_columns)):
            raise ValueError(
                "Worksheet '{0}' has malformed or incomplete two-row headers."
                .format(sheet_name)
            )
    for index, column in enumerate(metadata_columns):
        label = _text(column.get("dataType")).strip()
        if not label:
            label = u"Identifier" if column.get("field") in ID_FIELDS else u"Text"
        unit = _text(column.get("unit")).strip()
        expected = u"{0} [{1}]".format(label, unit) if unit else label
        actual = _text(rows[0].get(index)).strip()
        if actual != expected:
            raise ValueError(
                "Worksheet '{0}' has an invalid data type/unit header in column {1}."
                .format(sheet_name, index + 1)
            )


def read_import_plan(file_path):
    """Describe what an ExcelLink XLSX contains so the grid can be rebuilt.

    Returns the declared grid layout, stable category/parameter identities,
    and element IDs. Visible headers are never used to infer parameter identity.
    """
    reader = _XlsxReader(file_path)
    try:
        xlsx_sheets = reader.sheets()
        meta = _read_meta(reader, xlsx_sheets)
        plan = {
            "parameterMode": meta["parameterMode"],
            "gridLayout": meta["gridLayout"], "sheets": [], "issues": [],
        }
        for name, part in xlsx_sheets:
            if name == META_SHEET_NAME:
                continue
            entry = meta["sheets"].get(name)
            if entry is None:
                raise ValueError(
                    "Worksheet '{0}' is not described by the authoritative ExcelLink metadata."
                    .format(name)
                )
            rows = reader.rows(part)
            _validate_worksheet_headers(rows, entry["columns"], name)
            ids = {}
            for index, column in enumerate(entry["columns"]):
                if column["field"] == "UniqueId":
                    ids["UniqueId"] = index
                elif column["field"] == "ElementId":
                    ids["ElementId"] = index
            if not ids:
                raise ValueError("Worksheet '{0}' has no stable element ID column.".format(name))
            unique_ids = []
            element_ids = []
            for values in rows[2:]:
                unique_id = _id_text(values.get(ids.get("UniqueId")))
                element_id = _id_text(values.get(ids.get("ElementId")))
                if unique_id or element_id:
                    unique_ids.append(unique_id)
                    element_ids.append(element_id)
            if entry["gridLayout"] == "combined":
                if entry["categoryId"] not in (None, u""):
                    raise ValueError("Combined worksheet metadata must have a null categoryId.")
            else:
                if entry["categoryId"] in (None, u""):
                    raise ValueError("Separate worksheet metadata requires a categoryId.")
                entry["categoryId"] = int(entry["categoryId"])
            plan_entry = dict(
                (key, entry[key]) for key in (
                    "xlsxName", "sheetName", "sheetKey", "gridLayout", "categoryId",
                    "categoryKey", "categories", "parameterKeys", "parameters",
                    "parameterUsage",
                )
            )
            plan_entry.update({"uniqueIds": unique_ids, "elementIds": element_ids})
            plan["sheets"].append(plan_entry)
        return plan
    finally:
        reader.close()


def _match_sheets(workbook, xlsx_sheets, meta):
    targets = workbook.get("sheets") or []
    by_key = {}
    for index, sheet in enumerate(targets):
        key = sheet.get("sheetKey") or sheet.get("categoryKey")
        if key:
            if key in by_key:
                raise ValueError("The current workbook has duplicate stable sheet identities.")
            by_key[key] = index
    if workbook.get("gridLayout") != meta.get("gridLayout"):
        raise ValueError("The XLSX grid layout does not match the current workbook.")

    matches = []
    unmatched = []
    data_sheets = [(name, part) for name, part in xlsx_sheets if name != META_SHEET_NAME]
    for name, part in data_sheets:
        entry = meta["sheets"].get(name)
        if entry is None:
            raise ValueError("Worksheet '{0}' has no authoritative metadata.".format(name))
        index = by_key.get(entry["sheetKey"])
        if index is None:
            unmatched.append(name)
        else:
            if targets[index].get("gridLayout", meta["gridLayout"]) != meta["gridLayout"]:
                raise ValueError("Worksheet '{0}' has an incompatible grid layout.".format(name))
            matches.append((name, part, index))
    return matches, unmatched


def _map_headers(header_row, sheet, metadata_columns):
    """Map XLSX columns only through hidden stable IDs, never visible labels."""
    mapped = {}
    ids = {}
    issues = []
    current_columns = sheet.get("columns") or []
    by_parameter = {}
    for column in current_columns:
        if column.get("columnType") == "parameter":
            key = (column.get("parameterKey"), column.get("target"))
            if key in by_parameter:
                raise ValueError("The current grid has duplicate parameter key/target columns.")
            by_parameter[key] = column
    current_usage = sheet.get("parameterUsage") or {}

    for index, metadata in enumerate(metadata_columns):
        field = metadata.get("field")
        if field in ("UniqueId", "ElementId"):
            ids[field] = index
            continue
        if metadata.get("columnType") == "parameter":
            parameter_key = metadata.get("parameterKey")
            target = metadata.get("target")
            column = by_parameter.get((parameter_key, target))
            if column is None:
                issues.append(
                    u"Parameter key '{0}' ({1}) is not present in the current grid; column skipped."
                    .format(_text(parameter_key), _text(target))
                )
                continue
            usage = current_usage.get(parameter_key) or {}
            current_identity = (column.get("parameterIdentity")
                                or usage.get("identity"))
            current_spec = column.get("specTypeId") or usage.get("specTypeId")
            if (current_identity != metadata.get("parameterIdentity")
                    or current_spec != metadata.get("specTypeId")):
                issues.append(
                    u"Parameter key '{0}' no longer has the exported identity/specification; "
                    u"column skipped.".format(_text(parameter_key))
                )
                continue
            if column.get("storageType") != metadata.get("storageType"):
                issues.append(
                    u"Parameter key '{0}' has a different storage type; column skipped."
                    .format(_text(parameter_key))
                )
                continue
            if column.get("unit") != metadata.get("unit"):
                issues.append(
                    u"Parameter key '{0}' has a different display unit; column skipped."
                    .format(_text(parameter_key))
                )
                continue
            mapped[index] = column
        elif metadata.get("columnType") == "typeName":
            column = next((item for item in current_columns
                           if item.get("columnType") == "typeName"), None)
            if column is not None:
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


def _change_metadata(column, row):
    if column.get("columnType") == "typeName":
        return {
            "target": "typeName",
            "parameterName": column.get("parameterName") or "Type Name",
        }
    field = column.get("field")
    metadata = row.get(u"{0}__metadata".format(field))
    if not isinstance(metadata, dict):
        raise ValueError("The row is missing authoritative parameter metadata.")
    for key in ("parameterIdentity", "specTypeId", "storageType"):
        if not metadata.get(key):
            raise ValueError("The row parameter metadata is missing '{0}'.".format(key))
    target = column.get("target")
    if target not in ("type", "instance"):
        raise ValueError("The row parameter metadata has an unsupported target.")
    return {
        "target": target,
        "parameterName": column.get("parameterName"),
        "parameterKey": column.get("parameterKey"),
        "parameterIdentity": metadata.get("parameterIdentity"),
        "specTypeId": metadata.get("specTypeId"),
        "storageType": metadata.get("storageType"),
        "parameterGuid": metadata.get("parameterGuid"),
        "parameterBuiltin": metadata.get("parameterBuiltin"),
        "referenceKind": metadata.get("referenceKind"),
        "options": metadata.get("options"),
        "unit": metadata.get("unit"),
    }


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
            metadata_columns = meta["sheets"][xlsx_name]["columns"]
            _validate_worksheet_headers(rows, metadata_columns, xlsx_name)
            mapped, ids, header_issues = _map_headers(
                rows[1], sheet, metadata_columns
            )
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

            # (field, typeElementId) -> {"column", "row", "values": [...]}
            type_groups = {}
            for row_offset, values in enumerate(rows[2:]):
                xlsx_row = row_offset + 3
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
                    try:
                        change_metadata = _change_metadata(column, grid_row)
                    except ValueError as exc:
                        summary["skipped"] += 1
                        issues.append({"sheet": xlsx_name, "row": xlsx_row,
                                       "column": title, "message": _text(exc)})
                        continue
                    if column.get("target") in ("type", "typeName"):
                        key = (field, _text(grid_row.get("TypeElementId")))
                        group = type_groups.setdefault(key, {
                            "column": column, "row": grid_row, "storage": storage,
                            "values": [], "metadata": change_metadata,
                        })
                        if group["metadata"] != change_metadata:
                            summary["skipped"] += 1
                            issues.append({
                                "sheet": xlsx_name, "row": xlsx_row, "column": title,
                                "message": u"Rows sharing a type have inconsistent parameter identity metadata.",
                            })
                            continue
                        group["values"].append((value, xlsx_row))
                        continue
                    update = {
                        "sheetIndex": sheet_index,
                        "field": field,
                        "uniqueId": grid_row.get("UniqueId"),
                        "typeElementId": grid_row.get("TypeElementId"),
                        "value": value,
                        "oldValue": current,
                    }
                    update.update(change_metadata)
                    updates.append(update)

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
                update = {
                    "sheetIndex": sheet_index,
                    "field": field,
                    "uniqueId": group["row"].get("UniqueId"),
                    "typeElementId": group["row"].get("TypeElementId"),
                    "value": distinct[0],
                    "oldValue": group["row"].get(field),
                }
                update.update(group["metadata"])
                updates.append(update)

        summary["changed"] = len(updates)
        return {"updates": updates, "summary": summary, "issues": issues}
    finally:
        reader.close()
