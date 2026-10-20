# -*- coding: utf-8 -*-
"""Read schedule defaults without changing the schedule or its elements."""

import re

from Autodesk.Revit.DB import UnitUtils, ViewSchedule

from core.element_refs import element_display_name
from core.units import _decimals


_OPERATORS = {
    "Equal": "equals", "NotEqual": "notEquals",
    "GreaterThan": "gt", "GreaterThanOrEqual": "gte",
    "LessThan": "lt", "LessThanOrEqual": "lte",
    "Contains": "contains", "NotContains": "notContains",
    "BeginsWith": "startsWith", "EndsWith": "endsWith",
    "HasValue": "notEmpty", "HasNoValue": "empty",
}


def read_schedule_defaults(uidoc, selection_mode):
    if selection_mode != "Current View" or not isinstance(uidoc.ActiveView, ViewSchedule):
        return None
    definition = uidoc.ActiveView.Definition
    fields = [definition.GetField(key) for key in definition.GetFieldOrder()]
    filters = list(definition.GetFilters())
    sorts = list(definition.GetSortGroupFields())
    needed_ids = set(item.FieldId for item in filters + sorts)
    visible = [field for field in fields if not field.IsHidden]
    extra = [field for field in fields if field.IsHidden and field.FieldId in needed_ids]
    issues = []
    for enabled, message in (
        (definition.IsFilteredBySheet, "Schedule filtering by sheet is not a portable grid filter."),
        (definition.IncludeLinkedFiles, "Linked-file schedule rows are not supported by the grid."),
        (definition.HasEmbeddedSchedule, "Embedded schedule fields and filters are not transferred."),
        (definition.IsMaterialTakeoff, "Material takeoff rows are not reproduced by the parameter grid."),
    ):
        if enabled:
            issues.append(message)
    return {
        "fields": visible + extra,
        "filters": [(definition.GetField(item.FieldId), item) for item in filters],
        "sort": [(definition.GetField(item.FieldId), item) for item in sorts],
        "issues": issues,
    }


def schedule_parameters(defaults, usage):
    names = []
    for field in defaults["fields"]:
        name = field.GetName()
        if name in usage and name not in names and _supported_field(field):
            names.append(name)
    return names


def _supported_field(field):
    return field.HasSchedulableField and str(field.FieldType) in ("Instance", "ElementType")


def _column_for(field, sheet):
    if not _supported_field(field):
        return None
    candidates = [column for column in sheet["columns"]
                  if column.get("parameterName") == field.GetName()]
    target = "type" if str(field.FieldType) == "ElementType" else "instance"
    for column in candidates:
        if column.get("target") == target:
            return None if column.get("disabled") else column
    usage = sheet.get("parameterUsage", {}).get(field.GetName(), {})
    if usage.get("isType" if target == "type" else "isInstance"):
        return None
    return candidates[0] if len(candidates) == 1 and not candidates[0].get("disabled") else None


def _filter_value(doc, field, item):
    if item.IsStringValue:
        return item.GetStringValue() or ""
    if item.IsIntegerValue:
        return item.GetIntegerValue()
    if item.IsElementIdValue:
        return element_display_name(doc.GetElement(item.GetElementIdValue()))
    if item.IsDoubleValue:
        value = item.GetDoubleValue()
        spec = field.GetSpecTypeId()
        if UnitUtils.IsMeasurableSpec(spec):
            options = doc.GetUnits().GetFormatOptions(spec)
            value = UnitUtils.ConvertFromInternalUnits(value, options.GetUnitTypeId())
            value = round(value, _decimals(options.Accuracy))
        return value
    return ""


def build_schedule_layout(doc, defaults, sheet):
    """Translate supported rules to the grid's portable, title-based layout."""
    rules = []
    sort = []
    issues = list(defaults.get("issues") or [])
    for field in defaults["fields"]:
        if _column_for(field, sheet) is None:
            issues.append("Schedule field '{0}' is not available as a parameter column.".format(
                field.GetName()
            ))
    for field, item in defaults["filters"]:
        column = _column_for(field, sheet)
        kind = str(item.FilterType)
        op = _OPERATORS.get(kind)
        if kind in ("NotBeginsWith", "NotEndsWith"):
            op = "regex"
        if column is None or op is None:
            issues.append("Schedule filter '{0}: {1}' cannot be transferred to this grid.".format(
                field.GetName(), kind
            ))
            continue
        value = _filter_value(doc, field, item)
        if kind in ("NotBeginsWith", "NotEndsWith"):
            escaped = re.escape(value)
            pattern = "^" + escaped if kind == "NotBeginsWith" else escaped + "$"
            value = r"^(?!{0})[\s\S]*$".format(pattern)
            if kind == "NotEndsWith":
                value = r"^(?![\s\S]*{0})[\s\S]*$".format(pattern)
        rules.append({
            "title": column["title"], "op": op,
            "value": u"{0}".format(value), "value2": "",
        })
    for field, item in defaults["sort"]:
        column = _column_for(field, sheet)
        if column is not None:
            sort.append({
                "title": column["title"],
                "dir": "desc" if str(item.SortOrder) == "Descending" else "asc",
            })
    return {
        "sort": sort,
        "filters": {"advanced": {"join": "and", "rules": rules}},
    }, issues
