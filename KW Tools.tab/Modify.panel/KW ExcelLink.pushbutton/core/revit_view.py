# -*- coding: utf-8 -*-
"""Select or temporarily isolate the elements behind the grid's visible rows."""

from Autodesk.Revit.DB import (
    ElementId,
    FilteredElementCollector,
    TemporaryViewMode,
    Transaction,
)
from System.Collections.Generic import List

from core.element_refs import make_element_id
from core.types import element_id_value


def _int_set(values):
    result = set()
    for value in values or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def target_element_ids(doc, element_ids, type_ids, source_elements):
    """Instance rows map to themselves; type rows map to their source instances."""
    ordered = []
    seen = set()

    def add(value):
        if value not in seen:
            seen.add(value)
            ordered.append(value)

    for value in sorted(_int_set(element_ids)):
        if doc.GetElement(make_element_id(value)) is not None:
            add(value)
    wanted_types = _int_set(type_ids)
    if wanted_types:
        for element in source_elements or []:
            try:
                if not element.IsValidObject:
                    continue
                if element_id_value(element.GetTypeId()) in wanted_types:
                    add(element_id_value(element.Id))
            except Exception:
                continue
    return [make_element_id(value) for value in ordered]


def _run_in_transaction(doc, name, action):
    transaction = Transaction(doc, name)
    transaction.Start()
    try:
        action()
        transaction.Commit()
    except Exception:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        raise


def run_view_action(uidoc, mode, element_ids, type_ids, source_elements):
    """Returns a user-facing summary. Isolation changes view state, so it runs in a
    transaction (Revit rejects it otherwise); selection does not need one."""
    doc = uidoc.Document
    view = uidoc.ActiveView
    if mode == "reset":
        if not view.IsTemporaryHideIsolateActive():
            return "No temporary hide/isolate is active in '{0}'.".format(view.Name)
        _run_in_transaction(
            doc,
            "KW ExcelLink - Reset Temporary Isolate",
            lambda: view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate),
        )
        return "Reset temporary hide/isolate in '{0}'.".format(view.Name)

    ids = target_element_ids(doc, element_ids, type_ids, source_elements)
    if not ids:
        raise ValueError(
            "None of the visible rows map to placed elements in this model "
            "(type rows need instances from the original selection)."
        )
    collection = List[ElementId](ids)
    if mode == "select":
        uidoc.Selection.SetElementIds(collection)
        return "Selected {0} element(s) in Revit.".format(len(ids))
    if mode == "isolate":
        if not view.CanUseTemporaryVisibilityModes():
            raise ValueError(
                "The active view '{0}' does not support temporary isolate. "
                "Switch to a plan, section, elevation or 3D view.".format(view.Name)
            )
        in_view = set(
            element_id_value(element_id)
            for element_id in FilteredElementCollector(doc, view.Id)
            .WhereElementIsNotElementType()
            .ToElementIds()
        )
        shown = len([1 for element_id in ids if element_id_value(element_id) in in_view])
        if not shown:
            raise ValueError(
                "None of the {0} element(s) are visible in '{1}'.".format(len(ids), view.Name)
            )
        _run_in_transaction(
            doc,
            "KW ExcelLink - Isolate Visible Rows",
            lambda: view.IsolateElementsTemporary(collection),
        )
        missing = len(ids) - shown
        return "Isolated {0} element(s) in '{1}'{2}. Use Reset view to undo.".format(
            shown,
            view.Name,
            " ({0} not in this view)".format(missing) if missing else "",
        )
    raise ValueError("Unsupported view action: {0}".format(mode))
