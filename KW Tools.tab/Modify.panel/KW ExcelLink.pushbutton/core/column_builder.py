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
        column["dataType"] = (
            "Integer" if column["field"] in ("ElementId", "TypeElementId")
            else "Yes/No" if column["field"] == "IsTypeRow" else "Text"
        )
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
                    usage,
                ))
            if has_instance:
                columns.append(_parameter_column(
                    index, name, "Instance", TARGET_INSTANCE, False, True, usage
                ))
        elif has_type:
            columns.append(_parameter_column(
                index, name, "Type", TARGET_TYPE, False, True, usage
            ))
        else:
            columns.append(_parameter_column(
                index, name, "Type", TARGET_TYPE, True, False, usage
            ))
    return columns


def _parameter_column(index, name, suffix, target, disabled, formulas_allowed, usage=None):
    usage = usage or {}
    is_type = target == TARGET_TYPE
    return {
        "title": "{0} ({1})".format(usage.get("displayName", name), suffix),
        "field": "p{0}_{1}".format(index, suffix.lower()),
        "columnType": "parameter",
        "parameterKey": name,
        "parameterName": usage.get("name", name),
        "parameterIdentity": usage.get("identity"),
        "dataType": usage.get("dataType"),
        "specTypeId": usage.get("specTypeId"),
        "parameterGuid": usage.get("guid"),
        "parameterBuiltin": usage.get("builtin"),
        "target": target,
        "editable": not disabled,
        "disabled": disabled,
        "formulaAllowed": not disabled and formulas_allowed and usage.get("storageType") != "ElementId",
        "typeHighlight": is_type,
        "storageType": usage.get("storageType"),
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
            name = column.get("parameterKey", column["parameterName"])
            record = parameters.get(name, {})
            target = column["target"]
            target_record = record.get("typeRecord" if target == TARGET_TYPE else "instanceRecord")
            metadata = target_record if target_record is not None else record
            value_key = "typeValue" if target == TARGET_TYPE else "instanceValue"
            result[column["field"]] = record.get(value_key)
            presence_key = "isTypeParam" if target == TARGET_TYPE else "isInstanceParam"
            storage_type = metadata.get("storageType")
            reference_kind = metadata.get("referenceKind") if target_record is not None else column.get("referenceKind")
            options = catalog.options(reference_kind) if catalog is not None and reference_kind else None
            result[column["field"] + "__metadata"] = {
                "parameterIdentity": metadata.get("identity", column.get("parameterIdentity")),
                "parameterGuid": metadata.get("guid"),
                "parameterBuiltin": metadata.get("builtin"),
                "specTypeId": metadata.get("specTypeId", column.get("specTypeId")),
                "storageType": storage_type,
                "referenceKind": reference_kind,
                "options": options,
                "unit": metadata.get("unit", column.get("unit")),
            }
            result[column["field"] + "__disabled"] = (
                column.get("disabled", False)
                or not record.get(presence_key, False)
                or metadata.get("isReadOnly", True)
                or storage_type == "None"
                or (storage_type == "ElementId" and not reference_kind)
            )
            if not record.get(presence_key, False):
                result[column["field"] + "__note"] = "Parameter is not available on this element."
            elif metadata.get("readOnlyReason"):
                result[column["field"] + "__note"] = metadata["readOnlyReason"]
            if column.get("storageType") is None:
                column["storageType"] = metadata.get("storageType")
                if column["storageType"] == "ElementId":
                    column["formulaAllowed"] = False
            if column.get("parameterIdentity") is None and record.get(presence_key):
                column["parameterGuid"] = metadata.get("guid")
                column["parameterBuiltin"] = metadata.get("builtin")
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
            record = row.get("Parameters", {}).get(column.get("parameterKey", column["parameterName"]), {})
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
