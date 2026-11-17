# -*- coding: utf-8 -*-
"""Refresh placed schedules on the active sheet, including Filter by Sheet legends.

Designed for pyRevit / Revit 2025+ (IronPython compatible).
Recreates only ScheduleSheetInstance objects on the current active sheet.
"""

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

__title__ = "Refresh\nSchedules"
__doc__ = (
    "Rebuild one selected schedule or all schedules on the active sheet "
    "from their source schedule views. Original positions, rotations, "
    "pins and split segment indexes are retained."
)


class SheetScheduleSelectionFilter(ISelectionFilter):
    """Only allow schedule instances belonging to the active sheet."""

    def __init__(self, sheet_id):
        self.sheet_id = sheet_id

    def AllowElement(self, elem):
        return (
            isinstance(elem, DB.ScheduleSheetInstance)
            and elem.OwnerViewId == self.sheet_id
            and not elem.IsTitleblockRevisionSchedule
        )

    def AllowReference(self, reference, point):
        return False


def get_sheet_schedules(doc, sheet):
    """Collect sheet-owned schedule instances; omit titleblock revision tables."""
    return [
        inst
        for inst in DB.FilteredElementCollector(doc, sheet.Id)
        .OfClass(DB.ScheduleSheetInstance)
        .ToElements()
        if not inst.IsTitleblockRevisionSchedule
        and inst.OwnerViewId == sheet.Id
    ]


def choose_one_schedule(uidoc, doc, sheet, schedules):
    """Use preselection when unique; otherwise ask user to pick one on sheet."""
    current_ids = [inst.Id for inst in schedules]
    preselected = [
        doc.GetElement(elem_id)
        for elem_id in uidoc.Selection.GetElementIds()
        if elem_id in current_ids
    ]
    if len(preselected) == 1:
        return preselected[0]

    try:
        reference = uidoc.Selection.PickObject(
            ObjectType.Element,
            SheetScheduleSelectionFilter(sheet.Id),
            "Pick a schedule on the active sheet (Esc to cancel)"
        )
        return doc.GetElement(reference.ElementId)
    except OperationCanceledException:
        return None


def snapshot_instance(doc, instance):
    """Store enough data to recreate a placed schedule at its same anchor."""
    schedule = doc.GetElement(instance.ScheduleId)
    if not isinstance(schedule, DB.ViewSchedule):
        raise Exception(
            "Schedule source could not be resolved for instance {}.".format(
                instance.Id
            )
        )

    position = instance.Point
    count = schedule.GetSegmentCount()
    index = instance.SegmentIndex

    # Segment index comes from the placed instance. The primary schedule can
    # be shared among many sheets, including those using Filter by Sheet.
    if count > 1 and not (0 <= index < count):
        raise Exception(
            "Split schedule '{}' has an unsupported segment index {}.".format(
                schedule.Name, index
            )
        )

    return {
        "old_id": instance.Id,
        "source_id": instance.ScheduleId,  # primary view, NOT internal filtered view
        "name": schedule.Name,
        "point": DB.XYZ(position.X, position.Y, position.Z),
        "rotation": instance.Rotation,
        "pinned": instance.Pinned,
        "segment_index": index,
        "is_split": count > 1,
    }


def refresh_placements(doc, sheet, records):
    """Two committed steps under one undo item, like manual remove/reinsert.

    TransactionGroup rollback restores deleted instances if creation fails.
    Commit the removal separately to force Revit's internal per-sheet schedule
    to be discarded before creating a fresh instance.
    """
    group = DB.TransactionGroup(doc, "Refresh Schedules on Active Sheet")
    group.Start()
    recreated = []
    try:
        remove_tx = DB.Transaction(doc, "Remove old schedule instances")
        remove_tx.Start()
        try:
            for item in records:
                doc.Delete(item["old_id"])
            if remove_tx.Commit() != DB.TransactionStatus.Committed:
                raise Exception("Revit could not complete schedule removal.")
        except Exception:
            if remove_tx.GetStatus() == DB.TransactionStatus.Started:
                remove_tx.RollBack()
            raise

        # Separate transaction more closely mimics manual removal and placement.
        add_tx = DB.Transaction(doc, "Reinsert schedules from source views")
        add_tx.Start()
        try:
            for item in records:
                if item["is_split"]:
                    new_inst = DB.ScheduleSheetInstance.Create(
                        doc, sheet.Id, item["source_id"],
                        item["point"], item["segment_index"]
                    )
                else:
                    new_inst = DB.ScheduleSheetInstance.Create(
                        doc, sheet.Id, item["source_id"], item["point"]
                    )

                # Retain rotation, placement anchor and pinned status.
                if new_inst.Rotation != item["rotation"]:
                    new_inst.Rotation = item["rotation"]
                if new_inst.Point.DistanceTo(item["point"]) > 1.0e-8:
                    new_inst.Point = item["point"]
                if item["pinned"]:
                    new_inst.Pinned = True
                recreated.append(new_inst.Id)

            if add_tx.Commit() != DB.TransactionStatus.Committed:
                raise Exception("Revit could not complete schedule recreation.")
        except Exception:
            if add_tx.GetStatus() == DB.TransactionStatus.Started:
                add_tx.RollBack()
            raise

        if group.Assimilate() != DB.TransactionStatus.Committed:
            raise Exception("Revit did not finalise the refresh operation.")
        return recreated
    except Exception:
        if group.GetStatus() == DB.TransactionStatus.Started:
            group.RollBack()
        raise


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    sheet = doc.ActiveView

    if not isinstance(sheet, DB.ViewSheet):
        forms.alert(
            "Open a sheet before using this command. It never changes "
            "schedules on other sheets.",
            title="Refresh Schedules"
        )
        return

    schedules = get_sheet_schedules(doc, sheet)
    if not schedules:
        forms.alert(
            "There are no refreshable schedules on the active sheet. "
            "Titleblock revision schedules are excluded.",
            title="Refresh Schedules"
        )
        return

    one_choice = "Refresh one schedule"
    all_choice = "Refresh all schedules on this sheet"
    mode = forms.CommandSwitchWindow.show(
        [one_choice, all_choice],
        message="Sheet {} - {}".format(sheet.SheetNumber, sheet.Name)
    )
    if not mode:
        return

    if mode == one_choice:
        chosen = choose_one_schedule(uidoc, doc, sheet, schedules)
        if chosen is None:
            return
        targets = [chosen]
    elif mode == all_choice:
        targets = schedules
    else:
        return

    try:
        # Resolve every source and check segment indexes before deleting any.
        records = [snapshot_instance(doc, inst) for inst in targets]
        new_ids = refresh_placements(doc, sheet, records)
    except Exception as err:
        forms.alert(
            "The refresh could not be completed. Revit has been instructed "
            "to restore the original schedule instances.\n\n{}".format(err),
            title="Refresh Schedules - Not Completed"
        )
        return

    # Keep the refreshed schedule selected if it was a one-schedule operation.
    if mode == one_choice and new_ids:
        selection_ids = List[DB.ElementId]()
        selection_ids.Add(new_ids[0])
        uidoc.Selection.SetElementIds(selection_ids)

    forms.alert(
        "Refreshed {} schedule{} on sheet {}.\n\n"
        "Use Undo once to restore the previous placements if necessary.".format(
            len(new_ids), "" if len(new_ids) == 1 else "s", sheet.SheetNumber
        ),
        title="Refresh Schedules"
    )


if __name__ == "__main__":
    main()
