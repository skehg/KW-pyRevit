# -*- coding: utf-8 -*-
__title__ = "Flip Wall (Centreline)"
__min_revit_ver__ = 2020
__version__ = 1.0
__beta__ = False
__doc__ = """Date    = 07.07.2026
_____________________________________________________________________
Description:
Flip selected walls about their true centreline.
_____________________________________________________________________
How-To:
- Run tool
- Select walls to flip (multiple selection allowed)
_____________________________________________________________________
Author: Xrev Team"""
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms

uidoc = revit.uidoc
doc = revit.doc


# -----------------------------
# Selection Filter: Walls Only
# -----------------------------
class WallSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Wall)
    def AllowReference(self, ref, point):
        return True


# -----------------------------
# Flip Wall About True Centreline
# -----------------------------
def flip_about_centreline(wall):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return

    loc_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    if not loc_param:
        return

    # Store original location line
    original_loc_line = loc_param.AsInteger()

    centreline = int(WallLocationLine.WallCenterline)

    # Fast path: wall is already on centreline, so only flip is required.
    if original_loc_line == centreline:
        with revit.Transaction("Flip Wall"):
            wall.Flip()
        return

    # Step 1: Commit location line change so Revit uses this axis for flip
    with revit.Transaction("Set Wall Centreline"):
        loc_param.Set(centreline)

    # Step 2: Flip using the committed centreline axis
    with revit.Transaction("Flip Wall"):
        wall.Flip()

    # Step 3: Restore original location line
    with revit.Transaction("Restore Location Line"):
        loc_param.Set(original_loc_line)


# -----------------------------
# Main Continuous Flip Loop
# -----------------------------
def flip_walls_continuous():
    sel_filter = WallSelectionFilter()

    with forms.WarningBar(title="Click walls to flip — press ESC to finish", handle_esc=True):
        while True:
            try:
                ref = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    sel_filter,
                    "Click a wall to flip — press ESC to finish."
                )
                wall = doc.GetElement(ref.ElementId)

                flip_about_centreline(wall)

            except OperationCanceledException:
                # ESC ends the loop
                break


# -----------------------------
# Run
# -----------------------------
flip_walls_continuous()