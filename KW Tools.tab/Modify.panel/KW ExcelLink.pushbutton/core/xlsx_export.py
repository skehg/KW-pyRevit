# -*- coding: utf-8 -*-
"""Minimal dependency-free XLSX (SpreadsheetML) writer for ExcelLink workbooks."""

import json
import re
import zipfile

try:
    import zlib  # noqa: F401
    _COMPRESSION = zipfile.ZIP_DEFLATED
except ImportError:
    _COMPRESSION = zipfile.ZIP_STORED


META_SHEET_NAME = "_ExcelLink"
# Kept (hidden) so rows can be matched back to Revit elements on import.
ID_FIELDS = ("ElementId", "UniqueId", "TypeElementId")

_STYLE_DEFAULT = 0
_STYLE_HEADER = 1
_STYLE_TYPE = 2
_STYLE_DISABLED = 3

_INVALID_XML = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INVALID_SHEET_CHARS = re.compile(r"[\[\]\:\*\?\/\\]")
_META_FIELDS = (
    "schemaVersion", "gridLayout", "parameterMode", "sheet", "sheetKey",
    "categories", "parameterKeys", "categoryId", "categoryKey", "field", "columnType",
    "columnIndex", "parameterKey", "parameterName", "displayName", "parameterIdentity",
    "dataType", "specTypeId", "usage", "target", "storageType", "unit", "options",
    "referenceKind", "parameterGuid", "parameterBuiltin", "isType",
    "isInstance",
)
SCHEMA_VERSION = u"2"


def _text(value):
    if value is None:
        return u""
    if not isinstance(value, basestring):  # noqa: F821 - IronPython 2.7
        value = str(value)
    if isinstance(value, bytes) and not isinstance(value, unicode):  # noqa: F821
        value = value.decode("utf-8", "replace")
    return value


def _escape(value):
    text = _INVALID_XML.sub(u"", _text(value))
    return (
        text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
        .replace(u">", u"&gt;").replace(u'"', u"&quot;")
    )


def _column_letter(index):
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _cell(reference, value, style):
    style_attr = u' s="{0}"'.format(style) if style else u""
    if value is None or value == "":
        return u'<c r="{0}"{1}/>'.format(reference, style_attr) if style else u""
    if isinstance(value, bool):
        return u'<c r="{0}"{1} t="b"><v>{2}</v></c>'.format(
            reference, style_attr, 1 if value else 0
        )
    if isinstance(value, (int, long, float)):  # noqa: F821
        if value != value or value in (float("inf"), float("-inf")):
            value = _text(value)
        else:
            return u'<c r="{0}"{1}><v>{2}</v></c>'.format(
                reference, style_attr, repr(value) if isinstance(value, float) else value
            )
    return u'<c r="{0}"{1} t="inlineStr"><is><t xml:space="preserve">{2}</t></is></c>'.format(
        reference, style_attr, _escape(value)
    )


def _unique_sheet_name(name, used):
    base = _INVALID_SHEET_CHARS.sub(u"_", _text(name)).strip(u"'") or u"Sheet"
    base = base[:31]
    candidate = base
    counter = 2
    while candidate.lower() in used or candidate.lower() == META_SHEET_NAME.lower():
        suffix = u" ({0})".format(counter)
        candidate = base[:31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate.lower())
    return candidate


def _export_columns(sheet, grid_layout):
    columns = sheet.get("columns") or []
    by_field = dict((column.get("field"), column) for column in columns)
    exported = []
    for field in ID_FIELDS:
        if field in by_field:
            exported.append((by_field[field], True))
    for column in columns:
        is_combined_category = (
            grid_layout == "combined" and column.get("field") == "Category"
        )
        if column.get("field") in ID_FIELDS or (
                column.get("visible") is False and not is_combined_category):
            continue
        exported.append((column, False))
    return exported


def _cell_style(column, row):
    if column.get("disabled") or row.get(u"{0}__disabled".format(column.get("field"))):
        return _STYLE_DISABLED
    if column.get("typeHighlight"):
        return _STYLE_TYPE
    return _STYLE_DEFAULT


def _column_title(column):
    return column.get("title") or column.get("field")


def _header_type(column, sheet):
    if column.get("columnType") == "parameter":
        parameter_key = column.get("parameterKey")
        usage = (sheet.get("parameterUsage") or {}).get(parameter_key)
        if not parameter_key or not usage:
            raise ValueError(
                "Parameter column '{0}' is missing its stable parameter key or usage metadata."
                .format(_text(column.get("field")))
            )
        label = usage.get("dataType") or column.get("dataType")
        if not label:
            raise ValueError(
                "Parameter '{0}' is missing its data type label.".format(
                    _text(parameter_key)
                )
            )
    else:
        label = column.get("dataType")
        if not label:
            label = u"Identifier" if column.get("field") in ID_FIELDS else u"Text"
    if column.get("unit"):
        label = u"{0} [{1}]".format(_text(label), _text(column.get("unit")))
    return label


def _width(column, rows, sheet):
    longest = max(len(_text(_column_title(column))),
                  len(_text(_header_type(column, sheet))))
    field = column.get("field")
    for row in rows[:500]:
        longest = max(longest, len(_text(row.get(field))))
    return min(max(longest + 2, 8), 60)


def _worksheet_xml(columns, rows, sheet):
    parts = [
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        u'<sheetViews><sheetView workbookViewId="0">'
        u'<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
        u'</sheetView></sheetViews>',
        u'<sheetFormatPr defaultRowHeight="15"/>',
    ]
    if columns:
        parts.append(u"<cols>")
        for index, (column, hidden) in enumerate(columns):
            parts.append(u'<col min="{0}" max="{0}" width="{1}" customWidth="1"{2}/>'.format(
                index + 1, _width(column, rows, sheet), u' hidden="1"' if hidden else u""
            ))
        parts.append(u"</cols>")
    parts.append(u"<sheetData>")
    type_header = [
        _cell(u"{0}1".format(_column_letter(index)),
              _header_type(column, sheet), _STYLE_HEADER)
        for index, (column, _) in enumerate(columns)
    ]
    name_header = [
        _cell(u"{0}2".format(_column_letter(index)), _column_title(column),
              _STYLE_HEADER)
        for index, (column, _) in enumerate(columns)
    ]
    parts.append(u'<row r="1">{0}</row>'.format(u"".join(type_header)))
    parts.append(u'<row r="2">{0}</row>'.format(u"".join(name_header)))
    for row_index, row in enumerate(rows):
        number = row_index + 3
        cells = [
            _cell(
                u"{0}{1}".format(_column_letter(index), number),
                row.get(column.get("field")),
                _cell_style(column, row),
            )
            for index, (column, _) in enumerate(columns)
        ]
        parts.append(u'<row r="{0}">{1}</row>'.format(number, u"".join(cells)))
    parts.append(u"</sheetData>")
    if columns:
        parts.append(u'<autoFilter ref="A2:{0}{1}"/>'.format(
            _column_letter(len(columns) - 1), len(rows) + 2
        ))
    parts.append(u"</worksheet>")
    return u"".join(parts)


def _meta_rows(workbook, sheet_entries):
    if workbook.get("gridLayout") not in ("combined", "separate"):
        raise ValueError("Workbook metadata must declare gridLayout as 'combined' or 'separate'.")
    rows = []
    for sheet_name, sheet, columns in sheet_entries:
        category_id = sheet.get("categoryId")
        category_key = sheet.get("categoryKey")
        if workbook["gridLayout"] == "combined":
            if category_id is not None or not category_key:
                raise ValueError("Combined worksheets require a categoryKey and a null categoryId.")
        elif category_id is None or not category_key:
            raise ValueError("Separate worksheets require a categoryId and categoryKey.")
        categories = sheet.get("categories")
        if not isinstance(categories, list) or not categories:
            raise ValueError("Every worksheet must include its category metadata list.")
        category_keys = set()
        category_ids = set()
        for category in categories:
            if (not isinstance(category, dict)
                    or category.get("categoryId") is None
                    or not category.get("categoryKey")
                    or not category.get("name")):
                raise ValueError("Worksheet category metadata is incomplete.")
            key = _text(category.get("categoryKey"))
            category_id_value = _text(category.get("categoryId"))
            if key in category_keys or category_id_value in category_ids:
                raise ValueError("Worksheet category metadata contains duplicates.")
            category_keys.add(key)
            category_ids.add(category_id_value)
        categories_json = json.dumps(categories, ensure_ascii=False, sort_keys=True)
        usage_map = sheet.get("parameterUsage") or {}
        declared_keys = sheet.get("parameters")
        if not isinstance(declared_keys, list):
            raise ValueError("Worksheet parameters must be the stable parameter key list.")
        column_keys = []
        for column_index, (column, _) in enumerate(columns):
            key = column.get("parameterKey")
            if column.get("columnType") == "parameter" and key not in column_keys:
                column_keys.append(key)
        if declared_keys != column_keys:
            raise ValueError("Worksheet parameters do not match its parameter-key columns.")
        if workbook["gridLayout"] == "separate":
            if len(categories) != 1:
                raise ValueError("Separate worksheets must describe exactly one category.")
            category = categories[0]
            if (str(category.get("categoryId")) != str(category_id)
                    or category.get("categoryKey") != category_key):
                raise ValueError("Separate worksheet category metadata is inconsistent.")
        sheet_key = sheet.get("sheetKey") or category_key
        if not sheet_key:
            raise ValueError("Worksheet metadata requires a stable sheetKey.")
        for column_index, (column, _) in enumerate(columns):
            parameter_key = column.get("parameterKey")
            usage = usage_map.get(parameter_key) if parameter_key else {}
            if column.get("columnType") == "parameter":
                if (not parameter_key or not usage
                        or not usage.get("name") or not usage.get("displayName")
                        or not usage.get("identity") or not usage.get("specTypeId")
                        or not usage.get("dataType") or not usage.get("storageType")
                        or "isType" not in usage or "isInstance" not in usage):
                    raise ValueError("Parameter columns require stable parameter metadata.")
            rows.append({
                "schemaVersion": SCHEMA_VERSION,
                "gridLayout": workbook["gridLayout"],
                "parameterMode": workbook.get("parameterMode"),
                "sheet": sheet_name,
                "sheetKey": sheet_key,
                "categories": categories_json,
                "parameterKeys": json.dumps(declared_keys, ensure_ascii=False),
                "categoryId": category_id,
                "categoryKey": category_key,
                "field": column.get("field"),
                "columnType": column.get("columnType"),
                "columnIndex": column_index,
                "parameterKey": parameter_key,
                "parameterName": usage.get("name", column.get("parameterName")),
                "displayName": usage.get("displayName"),
                "parameterIdentity": usage.get("identity"),
                "dataType": usage.get("dataType") or column.get("dataType"),
                "specTypeId": usage.get("specTypeId"),
                "usage": json.dumps(usage, ensure_ascii=False, sort_keys=True)
                         if usage else None,
                "target": column.get("target"),
                "storageType": column.get("storageType"),
                "unit": column.get("unit"),
                "options": json.dumps(column.get("options"), ensure_ascii=False)
                           if column.get("options") is not None else None,
                "referenceKind": json.dumps(
                    column.get("referenceKind"), ensure_ascii=False, sort_keys=True
                ) if column.get("referenceKind") is not None else None,
                "parameterGuid": column.get("parameterGuid"),
                "parameterBuiltin": column.get("parameterBuiltin"),
                "isType": usage.get("isType"),
                "isInstance": usage.get("isInstance"),
            })
    return rows


def _meta_sheet_xml(meta_rows):
    parts = [
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        u"<sheetData>",
    ]
    parts.append(u'<row r="1">{0}</row>'.format(u"".join(
        _cell(u"{0}1".format(_column_letter(index)), name, 0)
        for index, name in enumerate(_META_FIELDS)
    )))
    for row_index, row in enumerate(meta_rows):
        number = row_index + 2
        cells = [
            _cell(u"{0}{1}".format(_column_letter(index), number), row.get(name), 0)
            for index, name in enumerate(_META_FIELDS)
        ]
        parts.append(u'<row r="{0}">{1}</row>'.format(number, u"".join(cells)))
    parts.append(u"</sheetData></worksheet>")
    return u"".join(parts)


_STYLES_XML = (
    u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    u'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    u'<fonts count="3">'
    u'<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    u'<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    u'<font><sz val="11"/><color rgb="FF808080"/><name val="Calibri"/><family val="2"/></font>'
    u'</fonts>'
    u'<fills count="5">'
    u'<fill><patternFill patternType="none"/></fill>'
    u'<fill><patternFill patternType="gray125"/></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>'
    u'<fill><patternFill patternType="solid"><fgColor rgb="FFEDEDED"/><bgColor indexed="64"/></patternFill></fill>'
    u'</fills>'
    u'<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    u'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    u'<cellXfs count="4">'
    u'<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    u'<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    u'<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>'
    u'<xf numFmtId="0" fontId="2" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    u'</cellXfs>'
    u'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    u'</styleSheet>'
)


def _workbook_xml(sheet_names):
    sheets = []
    for index, name in enumerate(sheet_names):
        state = u' state="veryHidden"' if name == META_SHEET_NAME else u""
        sheets.append(u'<sheet name="{0}" sheetId="{1}"{2} r:id="rId{1}"/>'.format(
            _escape(name), index + 1, state
        ))
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        u'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        u'<bookViews><workbookView activeTab="0"/></bookViews>'
        u"<sheets>{0}</sheets></workbook>"
    ).format(u"".join(sheets))


def _workbook_rels(count):
    relationships = [
        u'<Relationship Id="rId{0}" '
        u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        u'Target="worksheets/sheet{0}.xml"/>'.format(index + 1)
        for index in range(count)
    ]
    relationships.append(
        u'<Relationship Id="rId{0}" '
        u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        u'Target="styles.xml"/>'.format(count + 1)
    )
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        u"{0}</Relationships>"
    ).format(u"".join(relationships))


def _content_types(count):
    overrides = [
        u'<Override PartName="/xl/worksheets/sheet{0}.xml" '
        u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        .format(index + 1)
        for index in range(count)
    ]
    return (
        u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        u'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        u'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        u'<Default Extension="xml" ContentType="application/xml"/>'
        u'<Override PartName="/xl/workbook.xml" '
        u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        u'<Override PartName="/xl/styles.xml" '
        u'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        u"{0}</Types>"
    ).format(u"".join(overrides))


_ROOT_RELS = (
    u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    u'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    u'<Relationship Id="rId1" '
    u'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    u'Target="xl/workbook.xml"/></Relationships>'
)


def write_xlsx(workbook, file_path):
    if workbook.get("gridLayout") not in ("combined", "separate"):
        raise ValueError("Workbook metadata must declare gridLayout as 'combined' or 'separate'.")
    used = set()
    entries = []
    for sheet in workbook.get("sheets") or []:
        name = _unique_sheet_name(sheet.get("name"), used)
        entries.append((name, sheet, _export_columns(sheet, workbook["gridLayout"])))
    if not entries:
        raise ValueError("The workbook has no sheets to export.")

    sheet_names = [name for name, _, _ in entries] + [META_SHEET_NAME]
    parts = [
        ("[Content_Types].xml", _content_types(len(sheet_names))),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", _workbook_xml(sheet_names)),
        ("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheet_names))),
        ("xl/styles.xml", _STYLES_XML),
    ]
    for index, (_, sheet, columns) in enumerate(entries):
        parts.append((
            "xl/worksheets/sheet{0}.xml".format(index + 1),
            _worksheet_xml(columns, sheet.get("rows") or [], sheet),
        ))
    parts.append((
        "xl/worksheets/sheet{0}.xml".format(len(sheet_names)),
        _meta_sheet_xml(_meta_rows(workbook, entries)),
    ))

    archive = zipfile.ZipFile(file_path, "w", _COMPRESSION)
    try:
        for name, xml in parts:
            archive.writestr(name, xml.encode("utf-8"))
    finally:
        archive.close()
    return file_path
