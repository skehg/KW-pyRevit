# -*- coding: utf-8 -*-

import math
import uuid

from Autodesk.Revit.DB import (
    BuiltInParameter,
    FamilyInstance,
    SpecTypeId,
    StorageType,
    Transaction,
    TransactionStatus,
    UnitFormatUtils,
    Wall,
)

from core.element_refs import (
    CONDITIONAL_HINTS,
    ReferenceCatalog,
    is_editable_reference,
    is_wall_insert,
    locked_reason,
    make_element_id,
)
from core.types import TARGET_INSTANCE, TARGET_TYPE, TARGET_TYPE_NAME, element_id_value
from core.type_names import collect_type_names, type_name_value, validate_type_renames
from core.parameter_metadata import parameter_identity

_WALL_BASE_BUILTIN = int(BuiltInParameter.WALL_BASE_CONSTRAINT)
_FAMILY_LEVEL_BUILTIN = int(BuiltInParameter.FAMILY_LEVEL_PARAM)
# About 1 mm, in feet.
_HEIGHT_TOLERANCE = 0.0033


def _group_changes(changes):
    type_changes = {}
    instance_changes = {}

    def add_change(group, key, change):
        previous = group.get(key)
        if previous is not None and previous.get("value") != change.get("value"):
            raise ValueError(
                "Conflicting values were submitted for parameter '{0}'.".format(
                    key[1]
                )
            )
        group[key] = change

    for change in changes:
        target = change.get("target")
        parameter_name = change.get("parameterKey") or change.get("parameterName")
        if target == TARGET_TYPE_NAME:
            type_id = int(change.get("typeElementId") or change.get("elementId"))
            add_change(type_changes, (type_id, "__TYPE_NAME__"), change)
        elif target == TARGET_TYPE:
            type_id = int(change.get("typeElementId"))
            add_change(type_changes, (type_id, parameter_name), change)
        elif target == TARGET_INSTANCE:
            element_id = int(change.get("elementId"))
            add_change(instance_changes, (element_id, parameter_name), change)
        else:
            raise ValueError("Unsupported change target: {0}".format(target))
    return type_changes, instance_changes


def _is_writable(element, parameter):
    if parameter.IsReadOnly:
        return False
    if parameter.StorageType == StorageType.ElementId:
        return is_editable_reference(parameter, element)
    return True


def _find_parameter(element, change):
    """Find the parameter to write, preferring an editable one.

    Elements can expose two parameters with the same name (a read-only
    schedule "Level" and the editable placement "Level"), and a grid column's
    builtin id may come from a different element in the same sheet, so the
    builtin only orders the built-in candidates.
    """
    name = change.get("parameterName")
    guid = change.get("parameterGuid")
    builtin = change.get("parameterBuiltin")
    candidates = []
    for parameter in element.Parameters:
        if parameter is None or parameter.Definition is None:
            continue
        if parameter.Definition.Name != name:
            continue
        if change.get("parameterIdentity"):
            if parameter_identity(element.Document, element, parameter) != change["parameterIdentity"]:
                continue
            if parameter.Definition.GetDataType().TypeId != change.get("specTypeId"):
                continue
            if str(parameter.StorageType) != change.get("storageType"):
                continue
            candidates.append(parameter)
            continue
        if guid:
            try:
                if str(parameter.GUID) != guid:
                    continue
            except Exception:
                continue
        if builtin is not None:
            try:
                parameter_id = element_id_value(parameter.Id)
            except Exception:
                continue
            if parameter_id >= 0:
                continue
            if parameter_id == int(builtin):
                candidates.insert(0, parameter)
                continue
        candidates.append(parameter)
    for parameter in candidates:
        if _is_writable(element, parameter):
            return parameter
    return candidates[0] if candidates else None


def _client_reference_kind(kind):
    if not isinstance(kind, dict):
        return None
    key = str(kind.get("key") or "")
    similar_type = key.split("|")
    is_similar_type = (
        len(similar_type) == 2 and similar_type[0] == "similarTypes"
        and similar_type[1].isdigit()
    )
    if not is_similar_type and (
        not key.startswith("class|") or len(key.split("|", 2)) != 3
    ):
        return None
    result = {"key": key, "allowNone": True, "changesType": False}
    if kind.get("noneLabel"):
        result["noneLabel"] = str(kind.get("noneLabel"))
    return result


def _set_element_id_value(catalog, element, parameter, change):
    if parameter.IsReadOnly:
        raise ValueError(
            "Parameter '{0}' is read-only.".format(parameter.Definition.Name)
        )
    reason = locked_reason(element, parameter)
    if reason:
        raise ValueError(
            "Parameter '{0}' on element {1} cannot be changed: {2}".format(
                parameter.Definition.Name, element_id_value(element.Id), reason
            )
        )
    _, _, kind = catalog.describe(element, parameter)
    if kind is None:
        # Unset references carry no kind; reuse the column kind from the grid.
        kind = _client_reference_kind(change.get("referenceKind"))
    new_id = catalog.resolve(kind, change.get("value"), owner=element)
    old_id = parameter.AsElementId()
    if kind and kind.get("changesType"):
        if element_id_value(element.GetTypeId()) != element_id_value(new_id):
            element.ChangeTypeId(new_id)
        return
    if not parameter.Set(new_id):
        raise ValueError(
            "Revit rejected '{0}' for parameter '{1}'.".format(
                change.get("value"), parameter.Definition.Name
            )
        )
    builtin = element_id_value(parameter.Id)
    if isinstance(element, Wall) and builtin == _WALL_BASE_BUILTIN:
        _carry_wall_inserts(element.Document, element, old_id, new_id)
    elif builtin == _FAMILY_LEVEL_BUILTIN and is_wall_insert(element):
        catalog.moved_inserts.append((element.Id, new_id))


def _carry_wall_inserts(doc, wall, old_level_id, new_level_id):
    """Move doors/windows with their wall when its base level changes.

    Revit leaves hosted inserts on the old level, which makes them stop
    cutting the moved wall; inserts on the wall's old base level are moved
    to the new level so they keep their sill height relative to the wall.
    """
    old_value = element_id_value(old_level_id)
    if old_value == element_id_value(new_level_id):
        return
    for insert_id in wall.FindInserts(False, False, False, False):
        insert = doc.GetElement(insert_id)
        if not isinstance(insert, FamilyInstance):
            continue
        level_parameter = insert.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
        if level_parameter is None or level_parameter.IsReadOnly:
            continue
        if element_id_value(level_parameter.AsElementId()) != old_value:
            continue
        level_parameter.Set(new_level_id)


def _format_length(doc, value):
    try:
        return UnitFormatUtils.Format(doc.GetUnits(), SpecTypeId.Length, value, False)
    except Exception:
        return "{0:.3f} ft".format(value)


def _check_moved_inserts(doc, moved_inserts):
    """Reject level moves that would lift a door/window out of its wall.

    A wall insert keeps its sill height when its level changes, so it moves
    by the level difference while the wall stays put.
    """
    if not moved_inserts:
        return
    doc.Regenerate()
    problems = []
    for insert_id, level_id in moved_inserts:
        insert = doc.GetElement(insert_id)
        host = insert.Host if insert is not None else None
        if host is None:
            continue
        insert_box = insert.get_BoundingBox(None)
        wall_box = host.get_BoundingBox(None)
        if insert_box is None or wall_box is None:
            continue
        bottom = insert.Location.Point.Z if hasattr(insert.Location, "Point") else insert_box.Min.Z
        top = insert_box.Max.Z
        if bottom >= wall_box.Min.Z - _HEIGHT_TOLERANCE and top <= wall_box.Max.Z + _HEIGHT_TOLERANCE:
            continue
        level = doc.GetElement(level_id)
        problems.append(
            "{0} {1} on '{2}' would sit at {3} to {4}, outside its host wall {5} "
            "({6} to {7}).".format(
                insert.Category.Name if insert.Category is not None else "Element",
                element_id_value(insert.Id),
                level.Name if level is not None else "the new level",
                _format_length(doc, bottom),
                _format_length(doc, top),
                element_id_value(host.Id),
                _format_length(doc, wall_box.Min.Z),
                _format_length(doc, wall_box.Max.Z),
            )
        )
    if problems:
        raise ValueError(
            "Doors and windows keep their sill height when their level changes, "
            "so the wall must span the new level. Move the wall (Base Constraint) "
            "or change its height first, or adjust the Sill Height in the same "
            "apply.\n" + "\n".join(problems)
        )


def _set_parameter_value(parameter, value, units=None):
    if parameter.IsReadOnly:
        raise ValueError("Parameter '{0}' is read-only.".format(parameter.Definition.Name))

    storage = parameter.StorageType
    if storage == StorageType.String:
        result = parameter.Set("" if value is None else str(value))
    elif storage == StorageType.Integer:
        if isinstance(value, bool):
            integer_value = 1 if value else 0
        else:
            integer_value = int(value)
            if float(value) != integer_value:
                raise ValueError("Integer parameter received a non-integer value.")
        result = parameter.Set(integer_value)
    elif storage == StorageType.Double:
        double_value = float(value)
        if math.isnan(double_value) or math.isinf(double_value):
            raise ValueError("Double parameter requires a finite number.")
        if units is not None:
            # Grid values are in project display units.
            double_value = units.to_internal(parameter, double_value)
        result = parameter.Set(double_value)
    else:
        raise ValueError("Editing parameters without a storage type is not supported.")
    if not result:
        raise ValueError(
            "Revit rejected the value for parameter '{0}'.".format(
                parameter.Definition.Name
            )
        )


def _raise_conditional_read_only(element, parameter):
    hint = CONDITIONAL_HINTS.get(element_id_value(parameter.Id))
    message = "Parameter '{0}' on element {1} is read-only".format(
        parameter.Definition.Name, element_id_value(element.Id)
    )
    raise ValueError(message + (": " + hint if hint else "."))


def _apply_parameter_change(catalog, element, parameter, change):
    if parameter.StorageType == StorageType.ElementId:
        _set_element_id_value(catalog, element, parameter, change)
    else:
        _set_parameter_value(parameter, change.get("value"), catalog.units)


def _apply_type_changes(doc, grouped_changes, catalog):
    for (element_id, parameter_name), change in grouped_changes.items():
        element = doc.GetElement(make_element_id(element_id))
        if element is None:
            raise ValueError("Type element {0} no longer exists.".format(element_id))
        if parameter_name == "__TYPE_NAME__":
            if not element.CanBeRenamed:
                raise ValueError(
                    "Type element {0} cannot be renamed.".format(element_id)
                )
            new_name = type_name_value(change.get("value"))
            if not new_name:
                raise ValueError("Type names cannot be empty.")
            element.Name = new_name
            continue

        parameter = _find_parameter(element, change)
        if parameter is None:
            raise ValueError("Type parameter '{0}' no longer exists.".format(parameter_name))
        _apply_parameter_change(catalog, element, parameter, change)


def _apply_instance_changes(doc, grouped_changes, catalog):
    deferred = []
    for (element_id, parameter_name), change in grouped_changes.items():
        element = doc.GetElement(make_element_id(element_id))
        if element is None:
            raise ValueError("Instance element {0} no longer exists.".format(element_id))
        parameter = _find_parameter(element, change)
        if parameter is None:
            raise ValueError("Instance parameter '{0}' no longer exists.".format(parameter_name))
        if parameter.StorageType == StorageType.ElementId:
            _apply_parameter_change(catalog, element, parameter, change)
        else:
            deferred.append((element, change))
    # Constraints first: Top Offset only becomes writable once Top Constraint
    # is a level, and Unconnected Height once it is Unconnected.
    for element, change in deferred:
        parameter = _find_parameter(element, change)
        if parameter.IsReadOnly:
            _raise_conditional_read_only(element, parameter)
        _apply_parameter_change(catalog, element, parameter, change)


def apply_changes(doc, changes):
    if not changes:
        return {"applied": 0, "typeChanges": 0, "instanceChanges": 0}

    type_changes, instance_changes = _group_changes(changes)
    renames = dict(
        (type_id, type_name_value(change.get("value")))
        for (type_id, name), change in type_changes.items()
        if name == "__TYPE_NAME__"
    )
    if renames:
        validate_type_renames(collect_type_names(doc), renames)
    catalog = ReferenceCatalog(doc)
    catalog.moved_inserts = []
    transaction = Transaction(doc, "KW ExcelLink - Apply Changes")
    try:
        start_status = transaction.Start()
        if start_status != TransactionStatus.Started:
            raise RuntimeError("Revit could not start the ExcelLink transaction.")
        # Free old names first so valid swaps/chains do not depend on row order.
        for type_id in renames:
            element = doc.GetElement(make_element_id(type_id))
            if not element.CanBeRenamed:
                raise ValueError("Type element {0} cannot be renamed.".format(type_id))
            element.Name = "__ExcelLink_{0}".format(uuid.uuid4().hex)
        _apply_type_changes(doc, type_changes, catalog)
        _apply_instance_changes(doc, instance_changes, catalog)
        _check_moved_inserts(doc, catalog.moved_inserts)
        commit_status = transaction.Commit()
        if commit_status != TransactionStatus.Committed:
            raise RuntimeError(
                "Revit did not commit the ExcelLink transaction ({0}).".format(
                    commit_status
                )
            )
    except Exception:
        if transaction.HasStarted():
            # Discard failures Revit posted during regeneration (e.g. "not
            # cutting anything") so only our message is shown.
            options = transaction.GetFailureHandlingOptions()
            transaction.SetFailureHandlingOptions(options.SetClearAfterRollback(True))
            transaction.RollBack()
        raise
    finally:
        transaction.Dispose()

    return {
        "applied": len(type_changes) + len(instance_changes),
        "typeChanges": len(type_changes),
        "instanceChanges": len(instance_changes),
    }
