# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import ElementType

from core.types import element_id_value
from core.parameter_metadata import parameter_descriptor


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
    type_parameters_by_id = {}
    category_ids = set(element_id_value(element.Category.Id) for element in elements
                       if element.Category is not None)

    def descriptors(element):
        return [parameter_descriptor(doc, element, parameter)
                for parameter in element.Parameters
                if parameter is not None and parameter.Definition is not None
                and parameter.Definition.Name]

    def add(records, target, category_id):
        for descriptor in records:
            key = descriptor["key"]
            if key not in usage:
                usage[key] = dict(descriptor, isType=False, isInstance=False,
                                  categoryIds=[], categoryNames=[],
                                  typeCategoryIds=[], instanceCategoryIds=[])
            entry = usage[key]
            entry[target] = True
            if category_id is not None and category_id not in entry["categoryIds"]:
                entry["categoryIds"].append(category_id)
            target_categories = entry["typeCategoryIds" if target == "isType" else "instanceCategoryIds"]
            if category_id is not None and category_id not in target_categories:
                target_categories.append(category_id)

    for element in elements:
        category_id = element_id_value(element.Category.Id) if element.Category is not None else None
        if isinstance(element, ElementType):
            add(descriptors(element), "isType", category_id)
            continue

        type_id = element.GetTypeId()
        add(descriptors(element), "isInstance", category_id)

        if type_id is not None and element_id_value(type_id) >= 0:
            type_key = element_id_value(type_id)
            if type_key not in type_parameters_by_id:
                type_element = doc.GetElement(type_id)
                type_parameters_by_id[type_key] = descriptors(type_element) if type_element is not None else []
            add(type_parameters_by_id[type_key], "isType", category_id)
    names = {}
    categories = dict((element_id_value(element.Category.Id), element.Category.Name)
                      for element in elements if element.Category is not None)
    for key, entry in usage.items():
        names.setdefault(entry["name"], []).append(key)
        entry["categoryIds"].sort()
        entry["categoryNames"] = [categories[key] for key in entry["categoryIds"]]
        entry["categoryCount"] = len(entry["categoryIds"])
        entry["totalCategories"] = len(category_ids)
        entry["displayName"] = entry["name"]
    for name, keys in names.items():
        if len(keys) > 1:
            for key in keys:
                entry = usage[key]
                entry["displayName"] = "{0} [{1}; {2}]".format(
                    name, entry["dataType"], entry["identity"])
    return usage


def is_mixed_use(usage_entry):
    return bool(usage_entry.get("isType") and usage_entry.get("isInstance"))
