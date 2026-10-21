# -*- coding: utf-8 -*-

from core.types import MODE_INSTANCES, MODE_TYPES, TARGET_INSTANCE, TARGET_TYPE


BASE_COLUMNS = [
    {"title": "Element ID", "field": "ElementId", "visible": False},
    {"title": "Unique ID", "field": "UniqueId", "visible": False},
    {"title": "Category", "field": "Category", "visible": False},
    {"title": "Is Type Row", "field": "IsTypeRow", "visible": False},
    {"title": "Type Element ID", "field": "TypeElementId", "visible": False},
    {"title": "Type Key", "field": "TypeKey", "visible": False},
    {
        "title": "Type Name",
        "field": "TypeName",
        "columnType": "typeName",
        "target": "typeName",
        "editable": True,
        "formulaAllowed": False,
        "typeHighlight": True,
        "disabled": False,
    },
]


def build_columns(selected_parameters, usage_map, parameter_mode):
    columns = [dict(column) for column in BASE_COLUMNS]
    for column in columns:
        if column.get("target") == "typeName":
            column["formulaAllowed"] = parameter_mode == MODE_TYPES
    for index, name in enumerate(selected_parameters):
        usage = usage_map.get(name, {})
        has_type = bool(usage.get("isType"))
        has_instance = bool(usage.get("isInstance"))

        if parameter_mode == MODE_INSTANCES:
            if has_type:
                columns.append(_parameter_column(
                    index, name, "Type", TARGET_TYPE, False,
                    parameter_mode != MODE_INSTANCES,
                ))
            if has_instance:
                columns.append(_parameter_column(
                    index, name, "Instance", TARGET_INSTANCE, False, True
                ))
        elif has_type:
            columns.append(_parameter_column(
                index, name, "Type", TARGET_TYPE, False, True
            ))
        else:
            columns.append(_parameter_column(
                index, name, "Type", TARGET_TYPE, True, False
            ))
    return columns


def _parameter_column(index, name, suffix, target, disabled, formulas_allowed):
    is_type = target == TARGET_TYPE
    return {
        "title": "{0} ({1})".format(name, suffix),
        "field": "p{0}_{1}".format(index, suffix.lower()),
        "columnType": "parameter",
        "parameterName": name,
        "target": target,
        "editable": not disabled,
        "disabled": disabled,
        "formulaAllowed": not disabled and formulas_allowed,
        "typeHighlight": is_type,
        "storageType": None,
    }


def project_rows(rows, columns, catalog=None):
    _attach_reference_options(rows, columns, catalog)
    projected = []
    for row in rows:
        result = dict(row)
        parameters = row.get("Parameters", {})
        for column in columns:
            if column.get("columnType") != "parameter":
                continue
            name = column["parameterName"]
            record = parameters.get(name, {})
            target = column["target"]
            value_key = "typeValue" if target == TARGET_TYPE else "instanceValue"
            result[column["field"]] = record.get(value_key)
            presence_key = "isTypeParam" if target == TARGET_TYPE else "isInstanceParam"
            storage_type = record.get("storageType")
            result[column["field"] + "__disabled"] = (
                column.get("disabled", False)
                or not record.get(presence_key, False)
                or record.get("isReadOnly", True)
                or storage_type == "None"
                or (storage_type == "ElementId" and not column.get("referenceKind"))
            )
            if record.get(presence_key) and record.get("readOnlyReason"):
                result[column["field"] + "__note"] = record["readOnlyReason"]
            if column.get("storageType") is None:
                column["storageType"] = record.get("storageType")
                if column["storageType"] == "ElementId":
                    column["formulaAllowed"] = False
            if target == TARGET_TYPE:
                column["parameterGuid"] = record.get("guid")
                column["parameterBuiltin"] = record.get("builtin")
            elif not column.get("parameterGuid"):
                column["parameterGuid"] = record.get("guid")
                column["parameterBuiltin"] = record.get("builtin")
        projected.append(result)
    return projected


def _attach_reference_options(rows, columns, catalog):
    for column in columns:
        if column.get("columnType") != "parameter":
            continue
        column["referenceKind"] = None
        column["options"] = None
        column["unit"] = None
        kind_key = "typeKind" if column["target"] == TARGET_TYPE else "instanceKind"
        unit_key = "typeUnit" if column["target"] == TARGET_TYPE else "instanceUnit"
        for row in rows:
            record = row.get("Parameters", {}).get(column["parameterName"], {})
            if record.get(unit_key) and not column["unit"]:
                column["unit"] = record[unit_key]
            if record.get(kind_key) and not column["referenceKind"]:
                column["referenceKind"] = record[kind_key]
            if column["unit"] and column["referenceKind"]:
                break
        if column["referenceKind"]:
            column["formulaAllowed"] = False
            if catalog is not None:
                column["options"] = catalog.options(column["referenceKind"])
