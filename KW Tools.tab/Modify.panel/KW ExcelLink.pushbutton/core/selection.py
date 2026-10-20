# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import ElementType, FilteredElementCollector

from core.element_refs import make_element_id
from core.types import element_id_value


def resolve_elements_by_id(doc, element_ids):
    """Resolve saved source ids against the current document, skipping deleted elements."""
    elements = []
    missing = 0
    seen = set()
    for value in element_ids or []:
        try:
            key = int(value)
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        element = doc.GetElement(make_element_id(key))
        if element is None:
            missing += 1
            continue
        elements.append(element)
    return elements, missing


def resolve_source_elements(uidoc, selection_mode):
    doc = uidoc.Document
    if selection_mode == "Selected Elements":
        selected_ids = uidoc.Selection.GetElementIds()
        elements = [doc.GetElement(element_id) for element_id in selected_ids]
    elif selection_mode == "Current View":
        elements = list(
            FilteredElementCollector(doc, uidoc.ActiveView.Id)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    elif selection_mode in ("Entire Project File", "Entire Project", "Entire Model"):
        instances = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        if selection_mode in ("Entire Project File", "Entire Project"):
            elements = instances + list(
                FilteredElementCollector(doc)
                .WhereElementIsElementType()
                .ToElements()
            )
        else:
            elements = list(instances)
            used_type_ids = set()
            for element in instances:
                type_id = element.GetTypeId()
                type_id_value = element_id_value(type_id)
                if type_id_value is not None and type_id_value >= 0:
                    used_type_ids.add(type_id_value)
            for type_id in sorted(used_type_ids):
                element_type = doc.GetElement(make_element_id(type_id))
                if element_type is not None and isinstance(element_type, ElementType):
                    elements.append(element_type)
    else:
        raise ValueError("Unknown selection mode: {0}".format(selection_mode))

    return [element for element in elements if element is not None]


def category_options(elements):
    categories = {}
    for element in elements:
        category = element.Category
        if category is None:
            continue
        category_id = element_id_value(category.Id)
        if category_id not in categories:
            categories[category_id] = {
                "category_id": category_id,
                "label": "{0} [{1}]".format(category.Name, category_id),
                "builtin": category_key(category),
            }
    return sorted(categories.values(), key=lambda item: item["label"].lower())


def category_key(category):
    """BuiltInCategory name (e.g. 'OST_Doors'), stable across projects and languages."""
    try:
        name = str(category.BuiltInCategory)
    except Exception:
        return None
    return None if name == "INVALID" else name


def elements_for_category(elements, category_id):
    expected_id = int(category_id)
    return [
        element for element in elements
        if element.Category is not None
        and element_id_value(element.Category.Id) == expected_id
    ]
