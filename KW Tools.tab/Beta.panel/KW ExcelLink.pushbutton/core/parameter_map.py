# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import ElementType

from core.types import element_id_value


def _parameter_names(element):
    names = set()
    if element is None:
        return names
    for parameter in element.Parameters:
        if parameter is None or parameter.Definition is None:
            continue
        name = parameter.Definition.Name
        if name:
            names.add(name)
    return names


def build_parameter_usage_map(doc, elements):
    usage = {}
    type_names_by_id = {}

    for element in elements:
        if isinstance(element, ElementType):
            for name in _parameter_names(element):
                usage.setdefault(name, {"isType": False, "isInstance": False})
                usage[name]["isType"] = True
            continue

        type_id = element.GetTypeId()
        for name in _parameter_names(element):
            usage.setdefault(name, {"isType": False, "isInstance": False})
            usage[name]["isInstance"] = True

        if type_id is not None and element_id_value(type_id) >= 0:
            type_key = element_id_value(type_id)
            if type_key not in type_names_by_id:
                type_names_by_id[type_key] = _parameter_names(doc.GetElement(type_id))
            for name in type_names_by_id[type_key]:
                usage.setdefault(name, {"isType": False, "isInstance": False})
                usage[name]["isType"] = True
    return dict((name, usage[name]) for name in sorted(usage, key=lambda value: value.lower()))


def is_mixed_use(usage_entry):
    return bool(usage_entry.get("isType") and usage_entry.get("isInstance"))
