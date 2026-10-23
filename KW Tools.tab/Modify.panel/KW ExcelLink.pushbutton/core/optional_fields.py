# -*- coding: utf-8 -*-
"""Optional read-only API fields and narrowly scoped parameter filtering."""

DEFAULT_OPTIONS = {"coordinates": False, "usefulFields": False, "filterFalsePositives": True}


def field_options(options=None):
    if options is not None and not isinstance(options, dict):
        raise ValueError("ExcelLink field options must be an object.")
    result = dict(DEFAULT_OPTIONS)
    for key in DEFAULT_OPTIONS:
        if options is not None and key in options:
            if not isinstance(options[key], bool):
                raise ValueError("ExcelLink field option '{0}' must be true or false.".format(key))
            result[key] = options[key]
    return result


def select_usage(usage, options):
    options = field_options(options)
    result = {}
    for key, original in usage.items():
        entry = dict(original)
        group = entry.get("derivedGroup")
        if group and not options[group]:
            continue
        if options["filterFalsePositives"]:
            for target in ("Type", "Instance"):
                if entry.get("is" + target) and entry.get("useful" + target) is False:
                    entry["is" + target] = False
            if not entry.get("isType") and not entry.get("isInstance"):
                continue
            if "usefulTypeCategoryIds" in entry or "usefulInstanceCategoryIds" in entry:
                labels = dict(zip(entry.get("categoryIds", []), entry.get("categoryNames", [])))
                categories = set()
                for target in ("Type", "Instance"):
                    target_ids = entry.get("useful" + target + "CategoryIds", [])
                    entry[target.lower() + "CategoryIds"] = list(target_ids)
                    if entry.get("is" + target):
                        categories.update(target_ids)
                entry["categoryIds"] = sorted(categories)
                entry["categoryCount"] = len(categories)
                entry["categoryNames"] = [labels[category_id] for category_id in sorted(categories)]
        result[key] = entry
    return result


def is_false_positive(parameter):
    from Autodesk.Revit.DB import BuiltInParameter, StorageType
    from core.types import element_id_value

    builtin = element_id_value(parameter.Id)
    if builtin in (int(BuiltInParameter.ELEM_CATEGORY_PARAM),
                   int(BuiltInParameter.ELEM_CATEGORY_PARAM_MT)):
        return True
    return (builtin in (int(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM),
                        int(BuiltInParameter.SYMBOL_NAME_PARAM))
            and parameter.IsReadOnly and parameter.StorageType == StorageType.String
            and not parameter.AsString())


def derived_descriptors():
    fields = [
        ("category", "Category name", "Text"),
        ("family", "Family name (resolved)", "Text"),
        ("host", "Host element ID", "Integer"),
        ("pinned", "Pinned", "Yes/No"),
        ("rotation", "Location rotation", "Angle"),
        ("facing_x", "Facing X", "Number"),
        ("facing_y", "Facing Y", "Number"),
        ("facing_z", "Facing Z", "Number"),
        ("hand_x", "Hand X", "Number"),
        ("hand_y", "Hand Y", "Number"),
        ("hand_z", "Hand Z", "Number"),
    ]
    for frame, label, axes in (
            ("internal", "Internal origin", ("X", "Y", "Z")),
            ("project", "Project base point", ("X", "Y", "Z")),
            ("shared", "Shared", ("Easting", "Northing", "Elevation"))):
        for index, axis in enumerate(axes):
            fields.append(("{0}_{1}".format(frame, index),
                           "{0} {1}".format(label, axis), "Length"))
    result = []
    for name, label, data_type in fields:
        key = "derived:" + name
        result.append({
            "key": key, "identity": key, "name": label,
            "displayName": label + " [read-only API]",
            "dataType": data_type, "specTypeId": "derived:" + data_type.lower(),
            "storageType": "Double" if data_type in ("Length", "Angle", "Number")
                           else "Integer" if data_type in ("Integer", "Yes/No") else "String",
            "builtin": None, "guid": None,
            "derivedGroup": "coordinates" if data_type == "Length" else "usefulFields",
        })
    return result


class DerivedReader(object):
    def __init__(self, doc):
        self.doc = doc
        self._base = None
        self._formats = {}

    def _convert(self, value, data_type):
        from Autodesk.Revit.DB import SpecTypeId, UnitUtils
        from core.units import _decimals, _symbol_label

        if data_type not in self._formats:
            spec = SpecTypeId.Length if data_type == "Length" else SpecTypeId.Angle
            options = self.doc.GetUnits().GetFormatOptions(spec)
            unit_id = options.GetUnitTypeId()
            self._formats[data_type] = (
                unit_id, _decimals(options.Accuracy), _symbol_label(options, unit_id))
        unit_id, decimals, symbol = self._formats[data_type]
        return round(UnitUtils.ConvertFromInternalUnits(value, unit_id), decimals), symbol

    def read(self, element, selected, usage):
        keys = [key for key in selected if usage[key].get("derivedGroup")]
        if not keys:
            return {}
        from Autodesk.Revit.DB import BasePoint, ElementType, FamilyInstance, LocationPoint
        from core.types import element_id_value

        location = element.Location if not isinstance(element, ElementType) else None
        point = location.Point if isinstance(location, LocationPoint) else None
        coordinate_keys = [key for key in keys if usage[key]["derivedGroup"] == "coordinates"]
        coordinates = {}
        if point is not None and coordinate_keys:
            coordinates["internal"] = (point.X, point.Y, point.Z)
            if any(key.startswith("derived:project_") for key in coordinate_keys):
                if self._base is None:
                    base = BasePoint.GetProjectBasePoint(self.doc)
                    if base is None:
                        raise ValueError("ExcelLink cannot resolve the project base point.")
                    self._base = base.Position
                relative = point.Subtract(self._base)
                coordinates["project"] = (relative.X, relative.Y, relative.Z)
            if any(key.startswith("derived:shared_") for key in coordinate_keys):
                position = self.doc.ActiveProjectLocation.GetProjectPosition(point)
                coordinates["shared"] = (position.EastWest, position.NorthSouth, position.Elevation)
        result = {}
        for key in keys:
            name = key[len("derived:"):]
            value, unit, note = None, None, "Read-only API field."
            descriptor = usage[key]
            if descriptor["dataType"] in ("Length", "Angle"):
                _, unit = self._convert(0, descriptor["dataType"])
            if descriptor["derivedGroup"] == "coordinates":
                frame, axis = name.rsplit("_", 1)
                if frame in coordinates:
                    value, unit = self._convert(coordinates[frame][int(axis)], "Length")
                else:
                    note = "No point location; curve-based and location-less elements have no insertion XYZ."
            elif name == "category":
                value = element.Category.Name if element.Category is not None else None
            elif name == "family":
                element_type = element if isinstance(element, ElementType) else self.doc.GetElement(element.GetTypeId())
                value = element_type.FamilyName if element_type is not None else None
            elif name == "pinned":
                value = int(element.Pinned)
            elif name == "host" and isinstance(element, FamilyInstance):
                value = element_id_value(element.Host.Id) if element.Host is not None else None
            elif name == "rotation" and isinstance(location, LocationPoint):
                value, unit = self._convert(location.Rotation, "Angle")
            elif (name.startswith("facing_") or name.startswith("hand_")) and isinstance(element, FamilyInstance):
                vector = element.FacingOrientation if name.startswith("facing_") else element.HandOrientation
                value = getattr(vector, name[-1].upper())
            if value is None and note == "Read-only API field.":
                note = "API field is not applicable or has no value on this element."
            result[key] = dict(descriptor, value=value, unit=unit, referenceKind=None,
                               isReadOnly=True, readOnlyReason=note)
        return result
