# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import FilteredElementCollector

from core.types import element_id_value


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
    elif selection_mode == "Entire Model":
        elements = list(
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        elements.extend(
            list(
                FilteredElementCollector(doc)
                .WhereElementIsElementType()
                .ToElements()
            )
        )
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
