# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import ElementId, FilteredElementCollector


def get_all_elements(doc):
    for el in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements():
        yield el
    for el in FilteredElementCollector(doc).WhereElementIsElementType().ToElements():
        yield el


def is_valid_element_id(element_id):
    if element_id is None:
        return False
    if element_id == ElementId.InvalidElementId:
        return False
    try:
        return element_id.IntegerValue > 0
    except Exception:
        return False


def safe_name(element, fallback):
    if element is None:
        return fallback
    try:
        n = element.Name
        if n:
            return n
    except Exception:
        pass
    return fallback
