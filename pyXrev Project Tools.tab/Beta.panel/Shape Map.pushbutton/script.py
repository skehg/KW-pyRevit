# -*- coding: utf-8 -*-
__title__ = "Shape Map"
__min_revit_ver__ = 2024
__version__ = 1.0
__beta__ = True
__doc__ = """Date    = 06.07.2026
_____________________________________________________________________
Description:
Copy shape-edited top-surface data from a source Floor/Roof/Toposolid
onto a destination host using vertical interpolation on the source face.
_____________________________________________________________________
How-To:
- Run tool
- Select source element (Floor/Roof/Toposolid)
- Select destination element (Floor/Roof/Toposolid)
- Confirm options in dialog and click Run
_____________________________________________________________________
Author: Xrev Team"""

import os
import sys
import traceback

from Autodesk.Revit.DB import LabelUtils, SpecTypeId, UnitUtils
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms, revit, script

SCRIPT_DIR = os.path.dirname(__file__)
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

import shape_map_core
from ui import ShapeMapWindow


logger = script.get_logger()
output = script.get_output()
uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
app = doc.Application


class ShapeHostSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return shape_map_core.is_supported_host_element(element)

    def AllowReference(self, reference, point):
        return False


def _ensure_supported_revit_version():
    try:
        major = int(app.VersionNumber)
    except Exception:
        major = 0

    if major < 2024:
        forms.alert(
            "Shape Map requires Revit 2024 or newer.",
            title=__title__,
            exitscript=True,
        )


def _pick_element(prompt):
    pick_filter = ShapeHostSelectionFilter()
    with forms.WarningBar(title=prompt):
        ref = uidoc.Selection.PickObject(ObjectType.Element, pick_filter, prompt)
    return doc.GetElement(ref)


def _validate_distinct(source, destination):
    if source is None or destination is None:
        forms.alert("Selection failed. Try again.", title=__title__, exitscript=True)

    if source.Id == destination.Id:
        forms.alert("Source and destination must be different elements.", title=__title__, exitscript=True)


def _show_options_dialog(source, destination):
    unit_id, unit_label = _get_length_unit_info(doc)
    src_label = shape_map_core.get_display_label(doc, source)
    dst_label = shape_map_core.get_display_label(doc, destination)

    dlg = ShapeMapWindow(
        source_label=src_label,
        destination_label=dst_label,
        default_grid_spacing_display=UnitUtils.ConvertFromInternalUnits(shape_map_core.DEFAULT_GRID_SPACING_FT, unit_id),
        default_edge_spacing_display=UnitUtils.ConvertFromInternalUnits(shape_map_core.DEFAULT_EDGE_SPACING_FT, unit_id),
        grid_unit_label=unit_label,
    )

    ok = dlg.ShowDialog()
    if not ok or dlg.result is None:
        return None
    return dlg.result


def _format_summary(summary):
    lines = []
    lines.append("Shape Map completed.")
    lines.append("Source ID: {0}".format(summary["source_id"]))
    lines.append("Destination ID: {0}".format(summary["destination_id"]))
    lines.append("Sampling mode: {0}".format(summary.get("sampling_mode", "hybrid")))
    lines.append("Use interior grid: {0}".format("Yes" if summary.get("use_interior_grid", False) else "No"))
    lines.append("Grid spacing ({0}): {1}".format(summary.get("grid_spacing_label", "display"), _format_optional_number(summary.get("grid_spacing_display"), 3)))
    lines.append("Edge spacing ({0}): {1}".format(summary.get("grid_spacing_label", "display"), _format_optional_number(summary.get("edge_spacing_display"))))
    lines.append("Global point offset ({0}): {1}".format(summary.get("grid_spacing_label", "display"), _format_optional_number(summary.get("point_offset_display"))))
    lines.append("Grid spacing (ft internal): {0}".format(_format_optional_number(summary.get("grid_spacing_ft"))))
    lines.append("Edge spacing (ft internal): {0}".format(_format_optional_number(summary.get("edge_spacing_ft"))))
    lines.append("Global point offset (ft internal): {0}".format(_format_optional_number(summary.get("point_offset_ft"))))
    lines.append("Sample XY points: {0}".format(summary["sample_xy_count"]))
    lines.append("Mapped XYZ points: {0}".format(summary["mapped_xyz_count"]))
    lines.append("Added destination points: {0}".format(summary["points_added"]))
    lines.append("Modified existing vertices: {0}".format(summary.get("points_modified", 0)))
    lines.append("Failed destination points: {0}".format(summary["points_failed"]))
    lines.append("Skipped near-zero offsets: {0}".format(summary.get("points_skipped_zero", 0)))
    lines.append("Boundary nudge retry points: {0}".format(summary.get("boundary_nudged_retry_count", 0)))
    lines.append("Interior ring retry points: {0}".format(summary.get("interior_ring_retry_count", 0)))
    lines.append("Clamped points: {0}".format(summary["clamped_count"]))
    lines.append("Interpolated points: {0}".format(summary.get("interpolated_count", 0)))
    lines.append("Unresolved points: {0}".format(summary["missed_count"]))
    lines.append("Source probe Z range (ft): {0:.3f} to {1:.3f}".format(summary.get("source_probe_z_lo", 0.0), summary.get("source_probe_z_hi", 0.0)))
    lines.append("Z write mode: {0}".format(summary.get("z_mode", "absolute")))
    lines.append("Skip zero offsets: {0}".format("Yes" if summary.get("skip_zero_offsets", False) else "No"))
    lines.append("Source base elevation (ft): {0}".format(_format_optional_number(summary.get("source_base_elevation"))))
    lines.append("Destination base elevation (ft): {0}".format(_format_optional_number(summary.get("destination_base_elevation"))))
    lines.append("Level/Offset aligned: {0}".format("Yes" if summary["level_offset_aligned"] else "No"))
    lines.append("Comments updated: {0}".format("Yes" if summary["comments_written"] else "No"))
    lines.append("Destination shape vertices (total): {0}".format(summary.get("destination_vertex_count", 0)))
    lines.append("Destination boundary vertices: {0}".format(summary.get("destination_boundary_vertex_count", 0)))
    lines.append("Destination internal vertices: {0}".format(summary.get("destination_internal_vertex_count", 0)))
    lines.append("Destination unknown vertices: {0}".format(summary.get("destination_unknown_vertex_count", 0)))
    lines.append("Destination boundary control points: {0}".format(summary.get("destination_boundary_row_count", 0)))

    if summary["issues"]:
        lines.append("")
        lines.append("Warnings:")
        for issue in summary["issues"]:
            lines.append("- {0}".format(issue))

    return "\n".join(lines)


def _get_length_unit_info(active_doc):
    units = active_doc.GetUnits()
    fmt = units.GetFormatOptions(SpecTypeId.Length)
    unit_id = fmt.GetUnitTypeId()

    try:
        unit_label = LabelUtils.GetLabelForUnit(unit_id)
    except Exception:
        try:
            unit_label = unit_id.TypeId
        except Exception:
            unit_label = "project units"

    return unit_id, unit_label


def _format_optional_number(value, precision=6):
    if value is None:
        return "<disabled>"
    return ("{0:." + str(int(precision)) + "f}").format(value)


def _format_exception_details(ex):
    lines = []

    try:
        lines.append("Exception type: {0}".format(type(ex)))
    except Exception:
        pass

    try:
        lines.append("Exception string: {0}".format(str(ex)))
    except Exception:
        pass

    try:
        lines.append("Exception repr: {0}".format(repr(ex)))
    except Exception:
        pass

    try:
        tb_text = traceback.format_exc()
        if tb_text and tb_text.strip() and tb_text.strip() != "NoneType: None":
            lines.append("Traceback:\n{0}".format(tb_text))
    except Exception:
        pass

    if not lines:
        return "No exception details were captured."

    return "\n\n".join(lines)


def _print_debug_rows(debug_rows, destination_top_plane_elevation=None):
    if not debug_rows:
        output.print_md("No debug fallback rows were captured.")
        return

    output.print_md("### Shape Map Debug Rows")
    output.print_md("Showing first 250 rows.")
    output.print_md("| # | X | Y | Z | Z Rel Top Plane | Method |")
    output.print_md("|---:|---:|---:|---:|---:|---|")

    for idx, row in enumerate(debug_rows[:250], 1):
        x, y, z, method = row
        z_text = "" if z is None else "{0:.6f}".format(z)

        z_rel_text = ""
        if z is not None and destination_top_plane_elevation is not None:
            try:
                z_rel_text = "{0:.6f}".format(float(z) - float(destination_top_plane_elevation))
            except Exception:
                z_rel_text = ""

        output.print_md("| {0} | {1:.6f} | {2:.6f} | {3} | {4} | {5} |".format(idx, x, y, z_text, z_rel_text, method))


def _print_destination_vertex_rows(vertex_rows):
    if not vertex_rows:
        output.print_md("No destination shape vertices were captured.")
        return

    output.print_md("### Destination Vertex Rows")
    output.print_md("Showing all destination slab-shape vertices after write.")
    output.print_md("| # | X | Y | Z Abs | Z Rel Top Plane | Kind | Vertex Offset | Vertex Type |")
    output.print_md("|---:|---:|---:|---:|---:|---|---:|---|")

    for row in vertex_rows:
        idx, x, y, z_abs, z_rel, kind, v_offset, vtype = row

        z_abs_text = "" if z_abs is None else "{0:.6f}".format(z_abs)
        z_rel_text = "" if z_rel is None else "{0:.6f}".format(z_rel)
        v_offset_text = "" if v_offset is None else "{0:.6f}".format(v_offset)

        output.print_md(
            "| {0} | {1:.6f} | {2:.6f} | {3} | {4} | {5} | {6} | {7} |".format(
                idx,
                x,
                y,
                z_abs_text,
                z_rel_text,
                kind,
                v_offset_text,
                vtype,
            )
        )


def _print_destination_boundary_rows(boundary_rows):
    if not boundary_rows:
        output.print_md("No destination boundary control points were captured.")
        return

    output.print_md("### Destination Boundary Control Points")
    output.print_md("Geometric boundary points from destination top face (includes corners).")
    output.print_md("| # | X | Y | Z Abs | Z Rel Top Plane |")
    output.print_md("|---:|---:|---:|---:|---:|")

    for row in boundary_rows:
        idx, x, y, z_abs, z_rel = row

        z_abs_text = "" if z_abs is None else "{0:.6f}".format(z_abs)
        z_rel_text = "" if z_rel is None else "{0:.6f}".format(z_rel)

        output.print_md(
            "| {0} | {1:.6f} | {2:.6f} | {3} | {4} |".format(
                idx,
                x,
                y,
                z_abs_text,
                z_rel_text,
            )
        )


def _confirm_and_reset_destination_if_needed(destination_element):
    if not shape_map_core.destination_has_shape_edits(destination_element):
        return True

    message = (
        "Destination already has shape edits.\n\n"
        "Would you like to reset destination shape edits before running Shape Map?\n"
        "Choose Yes to reset and continue, or No to cancel."
    )

    if not forms.alert(message, title=__title__, yes=True, no=True):
        return False

    with revit.Transaction("Shape Map: reset destination shape"):
        shape_map_core.reset_destination_shape(destination_element)

    return True


def _log_stage(stage_name):
    try:
        logger.info("Shape Map stage: {0}".format(stage_name))
    except Exception:
        pass


def main():
    stage = "init"
    try:
        _ensure_supported_revit_version()
        stage = "pick source"
        _log_stage(stage)

        try:
            source = _pick_element("Select source element")
        except Exception:
            return

        stage = "pick destination"
        _log_stage(stage)
        try:
            destination = _pick_element("Select destination element")
        except Exception:
            return

        _validate_distinct(source, destination)

        stage = "precheck faces"
        _log_stage(stage)
        precheck_issues = []
        src_faces = shape_map_core.get_top_faces(doc, source, precheck_issues, "Source")
        dst_faces = shape_map_core.get_top_faces(doc, destination, precheck_issues, "Destination")

        if (not src_faces) or (not dst_faces):
            forms.alert(
                "Could not resolve top face for source or destination.\n\n"
                "This can happen with unsupported geometry configurations.",
                title=__title__,
                exitscript=True,
            )

        stage = "check/reset destination shape"
        _log_stage(stage)
        if not _confirm_and_reset_destination_if_needed(destination):
            return

        stage = "show options"
        _log_stage(stage)
        options = _show_options_dialog(source, destination)
        if options is None:
            return

        unit_id, unit_label = _get_length_unit_info(doc)
        grid_spacing_ft = None
        if options.get("grid_spacing_display") is not None:
            grid_spacing_ft = UnitUtils.ConvertToInternalUnits(options["grid_spacing_display"], unit_id)

        edge_spacing_ft = None
        if options.get("edge_spacing_display") is not None:
            edge_spacing_ft = UnitUtils.ConvertToInternalUnits(options["edge_spacing_display"], unit_id)

        point_offset_ft = 0.0
        if options.get("point_offset_display") is not None:
            point_offset_ft = UnitUtils.ConvertToInternalUnits(options["point_offset_display"], unit_id)

        tx_name = "Shape Map: copy shape edit"
        summary = None

        stage = "execute transaction"
        _log_stage(stage)
        with revit.Transaction(tx_name):
            summary = shape_map_core.execute_shape_map(
                doc=doc,
                source_element=source,
                destination_element=destination,
                grid_spacing_ft=grid_spacing_ft,
                edge_spacing_ft=edge_spacing_ft,
                point_offset_ft=point_offset_ft,
                align_level_offset=options["align_level_offset"],
                logger=logger,
                collect_debug=options.get("debug_fallback", False),
                z_mode=options.get("z_mode", "relative_level_offset"),
                skip_zero_offsets=options.get("skip_zero_offsets", True),
                use_interior_grid=options.get("use_interior_grid", True),
                sampling_mode=options.get("sampling_mode", "hybrid"),
            )

        if summary is None:
            forms.alert("Shape Map did not return a summary.", title=__title__, exitscript=True)

        summary["grid_spacing_display"] = options.get("grid_spacing_display")
        summary["edge_spacing_display"] = options.get("edge_spacing_display")
        summary["point_offset_display"] = options.get("point_offset_display")
        summary["grid_spacing_label"] = unit_label

        text = _format_summary(summary)
        print(text)
        output.print_md("### Shape Map Result")
        output.print_md(text.replace("\n", "  \n"))
        if options.get("debug_fallback", False):
            _print_debug_rows(
                summary.get("debug_rows", []),
                summary.get("destination_base_elevation"),
            )
        _print_destination_vertex_rows(summary.get("destination_vertex_rows", []))
        _print_destination_boundary_rows(summary.get("destination_boundary_rows", []))
        forms.alert(text, title=__title__)

    except Exception as ex:
        details = _format_exception_details(ex)
        try:
            details = "Stage: {0}\n\n{1}".format(stage, details)
        except Exception:
            pass
        try:
            logger.error("Shape Map failed:\n{0}".format(details))
        except Exception:
            pass
        try:
            output.print_md("### Shape Map Failure")
            output.print_md(details.replace("\n", "  \n"))
        except Exception:
            pass
        forms.alert(
            "Shape Map failed and all changes were rolled back.\n\n{0}".format(details),
            title=__title__,
            exitscript=True,
        )


if __name__ == "__main__":
    main()
