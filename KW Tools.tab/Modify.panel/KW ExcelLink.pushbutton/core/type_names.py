# -*- coding: utf-8 -*-
"""Document type-name inventory and preflight validation for staged renames."""

from functools import cmp_to_key

from Autodesk.Revit.DB import ElementType, FamilySymbol, FilteredElementCollector, NamingUtils

from core.element_refs import element_type_name
from core.types import element_id_value

try:
    _TEXT_TYPE = unicode
except NameError:
    _TEXT_TYPE = str


def type_name_value(value):
    return _TEXT_TYPE(value if value is not None else "").strip()


def collect_type_names(doc):
    records = []
    for element in FilteredElementCollector(doc).OfClass(ElementType):
        if isinstance(element, FamilySymbol):
            scope = "family:{0}".format(element_id_value(element.Family.Id))
        else:
            scope = "{0}|{1}".format(element.GetType().FullName, element.FamilyName)
        records.append({
            "id": element_id_value(element.Id),
            "scope": scope,
            "family": element.FamilyName,
            "name": element_type_name(element),
        })
    return records


def attach_type_names(doc, rows, catalog):
    if not hasattr(catalog, "type_names"):
        catalog.type_names = collect_type_names(doc)
    by_id = dict((item["id"], item) for item in catalog.type_names)
    scopes = set()
    for row in rows:
        record = by_id.get(row.get("TypeElementId"))
        if record is not None:
            scopes.add(record["scope"])
    return [item for item in catalog.type_names if item["scope"] in scopes]


def validate_type_renames(records, names):
    groups = {}
    found = set()
    for item in records:
        type_id = item["id"]
        name = names.get(type_id, item["name"])
        if type_id in names:
            found.add(type_id)
            if not name.strip() or not NamingUtils.IsValidName(name):
                raise ValueError("Invalid type name for element {0}: '{1}'.".format(type_id, name))
        group = groups.setdefault(item["scope"], [])
        group.append((name, type_id))
    missing = set(names) - found
    if missing:
        raise ValueError("Type elements no longer exist: {0}.".format(sorted(missing)))
    for group in groups.values():
        group.sort(key=cmp_to_key(lambda a, b: NamingUtils.CompareNames(a[0], b[0])))
        for previous, current in zip(group, group[1:]):
            if (NamingUtils.CompareNames(previous[0], current[0]) == 0
                    and (previous[1] in names or current[1] in names)):
                raise ValueError(
                    "Type-name conflict: '{0}' is used by type elements {1} and {2}. "
                    "Resolve the names before applying.".format(
                        current[0], previous[1], current[1]
                    )
                )
