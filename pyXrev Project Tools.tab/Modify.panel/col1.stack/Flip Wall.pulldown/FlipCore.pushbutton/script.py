# -*- coding: utf-8 -*-
__title__ = "Flip Wall (Core Centreline)"
__min_revit_ver__ = 2020
__version__ = 1.0
__beta__ = False
__doc__ = """Date    = 07.07.2026
_____________________________________________________________________
Description:
Flip selected walls about their core centreline.
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


class WallSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Wall)
    def AllowReference(self, ref, point):
        return True


def flip_about_core_centreline(wall):
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return

    loc_param = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
    if not loc_param:
        return

    # Store original location line
    original_loc_line = loc_param.AsInteger()

    core_centreline = int(WallLocationLine.CoreCenterline)

    # Fast path: wall is already on core centreline, so only flip is required.
    if original_loc_line == core_centreline:
        with revit.Transaction("Flip Wall"):
            wall.Flip()
        return

    # --- STEP 1: Set location line to Core Centerline ---
    with revit.Transaction("Set Core Centreline"):
        loc_param.Set(core_centreline)

    # --- STEP 2: Flip (Revit now uses the new axis) ---
    with revit.Transaction("Flip Wall"):
        wall.Flip()

    # --- STEP 3: Restore original location line ---
    with revit.Transaction("Restore Location Line"):
        loc_param.Set(original_loc_line)


def flip_walls_continuous():
    sel_filter = WallSelectionFilter()

    with forms.WarningBar(title="Click walls to flip about CORE centreline — ESC to finish", handle_esc=True):
        while True:
            try:
                ref = uidoc.Selection.PickObject(
                    ObjectType.Element,
                    sel_filter,
                    "Click a wall to flip about CORE centreline — ESC to finish."
                )
                wall = doc.GetElement(ref.ElementId)

                flip_about_core_centreline(wall)

            except OperationCanceledException:
                break


flip_walls_continuous()