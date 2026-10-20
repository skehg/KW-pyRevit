# -*- coding: utf-8 -*-
"""Human-readable names for ElementId parameters and name -> ElementId lookup.

Grid cells, dropdown options, saved workbooks and imported values all use the
same display names, so any of them can be resolved back to a Revit ElementId.
"""

import System

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    ElementType,
    FamilyInstance,
    FilteredElementCollector,
    Level,
    Phase,
    Wall,
)

from core.types import element_id_value
from core.units import UnitConverter


NONE_LABEL = "<None>"

_TYPE_CHANGE_BUILTINS = (
    int(BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM),
)
# Family/Type halves of "Family and Type" are ambiguous on their own; edit
# them through the "Family and Type" parameter instead.
_DISPLAY_ONLY_BUILTINS = (
    int(BuiltInParameter.ELEM_FAMILY_PARAM),
    int(BuiltInParameter.ELEM_TYPE_PARAM),
)
_PHASE_BUILTINS = (
    int(BuiltInParameter.PHASE_CREATED),
    int(BuiltInParameter.PHASE_DEMOLISHED),
)
# Wall inserts (doors, windows) stay hosted when their level changes and keep
# their sill height, so they may move as long as the wall spans the new level
# (checked in apply_changes). Other hosts (faces, floors, roofs) stay locked.
_FAMILY_LEVEL_BUILTIN = int(BuiltInParameter.FAMILY_LEVEL_PARAM)


def _builtin_ids(*names):
    result = set()
    for name in names:
        try:
            result.add(int(getattr(BuiltInParameter, name)))
        except AttributeError:
            pass
    return result


# Level references that may be unset (e.g. a wall's "Unconnected" Top
# Constraint); they still need level choices so they can be connected.
_LEVEL_REFERENCE_BUILTINS = _builtin_ids(
    "WALL_HEIGHT_TYPE",
    "WALL_BASE_CONSTRAINT",
    "FAMILY_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM",
    "FAMILY_TOP_LEVEL_PARAM",
    "SCHEDULE_BASE_LEVEL_PARAM",
    "SCHEDULE_TOP_LEVEL_PARAM",
    "STAIRS_BASE_LEVEL_PARAM",
    "STAIRS_TOP_LEVEL_PARAM",
)
_UNCONNECTED_BUILTINS = _builtin_ids("WALL_HEIGHT_TYPE", "STAIRS_TOP_LEVEL_PARAM")
UNCONNECTED_LABEL = "Unconnected"
_LEVEL_KIND_KEY = "class|Autodesk.Revit.DB.Level|{0}".format(int(BuiltInCategory.OST_Levels))


def none_labels(kind):
    labels = [NONE_LABEL]
    if kind and kind.get("noneLabel"):
        labels.append(kind["noneLabel"])
    return labels


def _hints(pairs):
    result = {}
    for name, hint in pairs:
        for builtin in _builtin_ids(name):
            result[builtin] = hint
    return result


# Read-only only while a related constraint is set a certain way; the grid
# keeps these editable because the constraint can change in the same apply.
CONDITIONAL_HINTS = _hints([
    ("WALL_TOP_OFFSET", "set Top Constraint to a level to use Top Offset."),
    ("WALL_USER_HEIGHT_PARAM", "set Top Constraint to Unconnected to use Unconnected Height."),
    ("STAIRS_TOP_OFFSET", "set Top Level to a level to use Top Offset."),
])


def make_element_id(value):
    return ElementId(System.Int64(int(value)))


def element_type_name(type_element):
    name_parameter = type_element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if name_parameter is not None:
        type_name = name_parameter.AsString()
        if type_name:
            return type_name
    raise ValueError(
        "Could not read the type name for element {0}.".format(
            element_id_value(type_element.Id)
        )
    )


def element_display_name(element):
    if element is None:
        return NONE_LABEL
    if isinstance(element, ElementType):
        type_name = element_type_name(element)
        family_name = element.FamilyName
        if family_name:
            return "{0}: {1}".format(family_name, type_name)
        return type_name
    try:
        name = element.Name
        if name:
            return name
    except Exception:
        pass
    return str(element_id_value(element.Id))


def _normalize(name):
    text = " ".join(str(name).split()).lower()
    return text.replace(" : ", ": ").replace(" :", ":")


def _parameter_builtin(parameter):
    try:
        value = element_id_value(parameter.Id)
    except Exception:
        return None
    return value if value < 0 else None


def locked_reason(owner, parameter):
    """Why a writable ElementId parameter must not be edited, or None."""
    builtin = _parameter_builtin(parameter)
    if builtin in _DISPLAY_ONLY_BUILTINS:
        return "Edit this through the 'Family and Type' parameter."
    if builtin == _FAMILY_LEVEL_BUILTIN and isinstance(owner, FamilyInstance):
        if owner.SuperComponent is not None:
            return "Nested component; its level follows the parent family."
        host = owner.Host
        if host is not None and not isinstance(host, (Level, Wall)):
            host_label = "{0} {1}".format(
                host.Category.Name if host.Category is not None else "element",
                element_id_value(host.Id),
            )
            return "Hosted element; its level follows the host ({0}). Change the host's level instead.".format(
                host_label
            )
    return None


def is_wall_insert(element):
    return isinstance(element, FamilyInstance) and isinstance(element.Host, Wall)


def is_editable_reference(parameter, owner=None):
    if owner is None:
        return _parameter_builtin(parameter) not in _DISPLAY_ONLY_BUILTINS
    return locked_reason(owner, parameter) is None


def _category_id(element):
    try:
        if element.Category is not None:
            return element_id_value(element.Category.Id)
    except Exception:
        pass
    return None


class ReferenceCatalog(object):
    """Caches candidate elements per reference kind for one document."""

    def __init__(self, doc):
        self.doc = doc
        self.units = UnitConverter(doc)
        self._candidates = {}
        self._class_types = {}

    def describe(self, owner, parameter):
        """Return (display_value, id_value, kind) for an ElementId parameter."""
        element_id = parameter.AsElementId()
        id_value = element_id_value(element_id)
        referenced = None
        if id_value is not None and id_value >= 0:
            referenced = self.doc.GetElement(element_id)
        builtin = _parameter_builtin(parameter)

        if referenced is not None:
            if builtin == int(BuiltInParameter.ELEM_FAMILY_PARAM):
                display = referenced.FamilyName or element_display_name(referenced)
            elif builtin == int(BuiltInParameter.ELEM_TYPE_PARAM):
                display = element_type_name(referenced)
            else:
                display = element_display_name(referenced)
        elif id_value is not None and id_value >= 0:
            display = parameter.AsValueString() or str(id_value)
        elif builtin in _UNCONNECTED_BUILTINS:
            display = UNCONNECTED_LABEL
        else:
            display = NONE_LABEL

        return display, id_value, self._kind(owner, parameter, builtin, referenced)

    def _kind(self, owner, parameter, builtin, referenced):
        if parameter.IsReadOnly or locked_reason(owner, parameter) is not None:
            return None
        if builtin in _TYPE_CHANGE_BUILTINS:
            category_id = _category_id(owner)
            key = "validTypes|{0}".format(category_id)
            if key not in self._candidates:
                self._candidates[key] = [
                    self.doc.GetElement(type_id) for type_id in owner.GetValidTypes()
                ]
            return {"key": key, "allowNone": False, "changesType": True}
        if referenced is not None:
            class_name = referenced.GetType().FullName
            self._class_types[class_name] = referenced.GetType()
            category_id = _category_id(referenced)
            kind = {
                "key": "class|{0}|{1}".format(class_name, category_id),
                "allowNone": builtin != int(BuiltInParameter.PHASE_CREATED),
                "changesType": False,
            }
            if builtin in _UNCONNECTED_BUILTINS:
                kind["noneLabel"] = UNCONNECTED_LABEL
            return kind
        if builtin in _LEVEL_REFERENCE_BUILTINS:
            self._class_types["Autodesk.Revit.DB.Level"] = Level
            kind = {"key": _LEVEL_KIND_KEY, "allowNone": True, "changesType": False}
            if builtin in _UNCONNECTED_BUILTINS:
                kind["noneLabel"] = UNCONNECTED_LABEL
            return kind
        if builtin in _PHASE_BUILTINS:
            class_name = "Autodesk.Revit.DB.Phase"
            self._class_types[class_name] = Phase
            return {
                "key": "class|{0}|None".format(class_name),
                "allowNone": builtin != int(BuiltInParameter.PHASE_CREATED),
                "changesType": False,
            }
        return None

    def candidates(self, kind):
        if not kind:
            return []
        key = kind["key"]
        if key in self._candidates:
            return self._candidates[key]
        _, class_name, category_id = key.split("|", 2)
        collector = FilteredElementCollector(self.doc)
        if category_id != "None":
            collector = collector.OfCategoryId(make_element_id(category_id))
        elif class_name in self._class_types:
            collector = collector.OfClass(self._class_types[class_name])
        else:
            self._candidates[key] = []
            return []
        elements = [
            element for element in collector
            if element.GetType().FullName == class_name
        ]
        self._candidates[key] = elements
        return elements

    def options(self, kind):
        if not kind:
            return []
        names = set()
        for element in self.candidates(kind):
            if element is not None:
                names.add(element_display_name(element))
        result = sorted(names, key=lambda item: item.lower())
        if kind.get("allowNone"):
            result.insert(0, kind.get("noneLabel") or NONE_LABEL)
        return result

    def resolve(self, kind, value, owner=None):
        """Resolve a display name (or numeric id) to an ElementId."""
        text = "" if value is None else str(value).strip()
        if not text or _normalize(text) in [_normalize(label) for label in none_labels(kind)]:
            if kind and not kind.get("allowNone"):
                raise ValueError("A value is required for this parameter.")
            return ElementId.InvalidElementId
        if not kind:
            raise ValueError(
                "Cannot determine valid choices for '{0}'.".format(text)
            )

        candidates = self.candidates(kind)
        if kind.get("changesType") and owner is not None:
            candidates = [
                self.doc.GetElement(type_id) for type_id in owner.GetValidTypes()
            ]

        wanted = _normalize(text)
        matches = [
            element for element in candidates
            if element is not None and _normalize(element_display_name(element)) == wanted
        ]
        if not matches:
            # Fallbacks for imported data: bare type names and raw element ids.
            matches = [
                element for element in candidates
                if element is not None and isinstance(element, ElementType)
                and _normalize(element_type_name(element)) == wanted
            ]
        if not matches and text.lstrip("-").isdigit():
            matches = [
                element for element in candidates
                if element is not None and element_id_value(element.Id) == int(text)
            ]
        if not matches:
            raise ValueError("'{0}' is not a valid choice.".format(text))
        if len(matches) > 1:
            raise ValueError(
                "'{0}' matches {1} elements; use the full 'Family: Type' name.".format(
                    text, len(matches)
                )
            )
        return matches[0].Id
