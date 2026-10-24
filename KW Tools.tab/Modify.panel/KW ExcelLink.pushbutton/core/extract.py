# -*- coding: utf-8 -*-

import System

from Autodesk.Revit.DB import ElementType, StorageType

from core.element_refs import (
    CONDITIONAL_HINTS,
    ReferenceCatalog,
    element_type_name,
    locked_reason,
)
from core.types import MODE_INSTANCES, element_id_value
from core.parameter_metadata import parameter_descriptor


_READ_ONLY_REASON = "Read-only in Revit."


def _read_parameter(parameter, owner, catalog):
    storage = parameter.StorageType
    value = None
    value_id = None
    reference_kind = None
    unit = None
    storage_name = str(storage)
    if storage == StorageType.String:
        value = parameter.AsString()
    elif storage == StorageType.Integer:
        value = parameter.AsInteger()
    elif storage == StorageType.Double:
        value = catalog.units.to_display(parameter, parameter.AsDouble())
        unit = catalog.units.symbol(parameter) or None
    elif storage == StorageType.ElementId:
        value, value_id, reference_kind = catalog.describe(owner, parameter)

    read_only_reason = None
    if parameter.IsReadOnly:
        if element_id_value(parameter.Id) not in CONDITIONAL_HINTS:
            read_only_reason = _READ_ONLY_REASON
    elif storage == StorageType.ElementId:
        read_only_reason = locked_reason(owner, parameter)

    guid = None
    try:
        guid_value = parameter.GUID
        if guid_value != System.Guid.Empty:
            guid = str(guid_value)
    except Exception:
        pass

    builtin = None
    try:
        parameter_id = element_id_value(parameter.Id)
        if parameter_id < 0:
            builtin = parameter_id
    except Exception:
        pass

    return {
        "value": value,
        "storageType": storage_name,
        "isReadOnly": read_only_reason is not None,
        "readOnlyReason": read_only_reason,
        "guid": guid,
        "builtin": builtin,
        "valueId": value_id,
        "referenceKind": reference_kind,
        "unit": unit,
    }


def _parameter_values(element, selected_names, catalog, usage_map=None):
    result = {}
    if element is None:
        return result
    wanted_names = (set(usage_map[key].get("name", key) for key in selected_names)
                    if usage_map is not None else selected_names)
    member_keys = {}
    if usage_map is not None:
        for selected in selected_names:
            for member in usage_map[selected].get("members", [selected]):
                member_keys[member] = selected
    for parameter in element.Parameters:
        if parameter is None or parameter.Definition is None:
            continue
        name = parameter.Definition.Name
        if name not in wanted_names:
            continue
        if usage_map is not None:
            descriptor = parameter_descriptor(catalog.doc, element, parameter)
            key = member_keys.get(descriptor["key"], descriptor["key"])
        else:
            descriptor = None
            key = name
        if key not in selected_names:
            continue
        if usage_map is not None:
            scope = "isType" if isinstance(element, ElementType) else "isInstance"
            if not usage_map[key].get(scope):
                continue
        existing = result.get(key)
        if (existing is not None and descriptor is not None
                and usage_map[key].get("members")
                and existing.get("identity") != descriptor["identity"]):
            existing.update(value=None, isReadOnly=True,
                            readOnlyReason="Multiple compatible definitions coexist on this element; select individual definitions.")
            continue
        # Some elements expose two parameters with one name (e.g. a read-only
        # schedule "Level" and the editable placement "Level"); keep the editable one,
        # otherwise the one whose lock reason is more specific than plain read-only.
        if existing is not None and not existing["isReadOnly"]:
            continue
        record = _read_parameter(parameter, element, catalog)
        if descriptor is not None:
            record.update(descriptor)
        if (existing is None or not record["isReadOnly"]
                or (existing["readOnlyReason"] == _READ_ONLY_REASON
                    and record["readOnlyReason"] != _READ_ONLY_REASON)):
            result[key] = record
    if (usage_map is not None and not isinstance(element, ElementType)
            and any(usage_map[key].get("derivedGroup") for key in selected_names)):
        from core.optional_fields import DerivedReader
        if not hasattr(catalog, "derived_reader"):
            catalog.derived_reader = DerivedReader(catalog.doc)
        result.update(catalog.derived_reader.read(element, selected_names, usage_map))
    return result


def _is_element_type(element):
    return isinstance(element, ElementType)


def _element_type_name(type_element):
    return element_type_name(type_element)


def _build_type_row(type_element, category_name, selected_names, catalog, usage_map=None):
    type_id = element_id_value(type_element.Id)
    type_parameters = _parameter_values(type_element, selected_names, catalog, usage_map)
    parameters = {}
    for name in selected_names:
        record = type_parameters.get(name)
        parameters[name] = {
            "typeRecord": record,
            "instanceRecord": None,
            "value": record.get("value") if record else None,
            "typeValue": record.get("value") if record else None,
            "instanceValue": None,
            "isTypeParam": record is not None,
            "isInstanceParam": False,
            "isReadOnly": record.get("isReadOnly", True) if record else True,
            "readOnlyReason": record.get("readOnlyReason") if record else None,
            "storageType": record.get("storageType") if record else None,
            "guid": record.get("guid") if record else None,
            "builtin": record.get("builtin") if record else None,
            "typeKind": record.get("referenceKind") if record else None,
            "instanceKind": None,
            "typeUnit": record.get("unit") if record else None,
            "instanceUnit": None,
        }
    return {
        "ElementId": type_id,
        "UniqueId": type_element.UniqueId,
        "Category": category_name,
        "IsTypeRow": True,
        "TypeElementId": type_id,
        "TypeName": _element_type_name(type_element),
        "TypeKey": str(type_id),
        "TypeNameEditable": type_element.CanBeRenamed,
        "Parameters": parameters,
    }


def extract_rows(doc, elements, parameter_mode, selected_parameters, catalog=None, usage_map=None):
    if catalog is None:
        catalog = ReferenceCatalog(doc)
    selected_names = set(selected_parameters)
    category_name = ""
    rows = []
    seen_type_ids = set()
    type_parameters_by_id = {}

    for element in elements:
        category_name = element.Category.Name if element.Category is not None else ""
        if _is_element_type(element):
            if parameter_mode == MODE_INSTANCES:
                continue
            type_element = element
            type_id = element_id_value(type_element.Id)
        else:
            type_id_value = element.GetTypeId()
            type_element = None
            if type_id_value is not None and element_id_value(type_id_value) >= 0:
                type_element = doc.GetElement(type_id_value)
            if type_id_value is not None and element_id_value(type_id_value) >= 0:
                if type_element is None:
                    continue
                type_id = element_id_value(type_element.Id)
                type_name = _element_type_name(type_element)
            else:
                type_id = None
                type_name = None
            if parameter_mode != MODE_INSTANCES and type_element is None:
                continue
            instance_id = element_id_value(element.Id)
            instance_name = type_name
            if instance_name is None:
                try:
                    instance_name = element.Name
                except Exception:
                    instance_name = ""
            instance_unique_id = element.UniqueId
            instance_parameters = _parameter_values(element, selected_names, catalog, usage_map)

        if parameter_mode != MODE_INSTANCES:
            if type_id in seen_type_ids:
                continue
            seen_type_ids.add(type_id)
            rows.append(
                _build_type_row(type_element, category_name, selected_names, catalog, usage_map)
            )
            continue

        if type_element is None:
            type_parameters = {}
        else:
            if type_id not in type_parameters_by_id:
                type_parameters_by_id[type_id] = _parameter_values(
                    type_element, selected_names, catalog, usage_map
                )
            type_parameters = type_parameters_by_id[type_id]
        parameters = {}
        for name in selected_names:
            type_record = type_parameters.get(name)
            instance_record = instance_parameters.get(name)
            chosen = instance_record or type_record
            parameters[name] = {
                "typeRecord": type_record,
                "instanceRecord": instance_record,
                "value": chosen.get("value") if chosen else None,
                "typeValue": type_record.get("value") if type_record else None,
                "instanceValue": instance_record.get("value") if instance_record else None,
                "isTypeParam": type_record is not None,
                "isInstanceParam": instance_record is not None,
                "isReadOnly": chosen.get("isReadOnly", True) if chosen else True,
                "readOnlyReason": chosen.get("readOnlyReason") if chosen else None,
                "storageType": chosen.get("storageType") if chosen else None,
                "guid": chosen.get("guid") if chosen else None,
                "builtin": chosen.get("builtin") if chosen else None,
                "typeKind": type_record.get("referenceKind") if type_record else None,
                "instanceKind": (
                    instance_record.get("referenceKind") if instance_record else None
                ),
                "typeUnit": type_record.get("unit") if type_record else None,
                "instanceUnit": instance_record.get("unit") if instance_record else None,
            }

        rows.append({
            "ElementId": instance_id,
            "UniqueId": instance_unique_id,
            "Category": category_name,
            "IsTypeRow": False,
            "TypeElementId": type_id,
            "TypeName": instance_name,
            "TypeKey": str(type_id if type_id is not None else instance_id),
            "TypeNameEditable": type_element is not None and type_element.CanBeRenamed,
            "Parameters": parameters,
        })

    return rows
