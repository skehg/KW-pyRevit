# -*- coding: utf-8 -*-
__title__ = "Shape Map 2"
__min_revit_ver__ = 2024
__version__ = 1.0
__beta__ = True
__doc__ = """Date    = 08.07.2026
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

from pyrevit import revit, DB, forms, script

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
	sys.path.append(SCRIPT_DIR)

import mapper
import ui
import utils


logger = script.get_logger()
output = script.get_output()
doc = revit.doc


def _ensure_revit_version():
	try:
		major = int(doc.Application.VersionNumber)
	except Exception:
		major = 0
	if major < 2024:
		forms.alert("Shape Map 2 requires Revit 2024 or newer.", title=__title__, exitscript=True)


def _validate_elements(source, destination):
	if source is None or destination is None:
		forms.alert("Source and destination must be selected.", title=__title__, exitscript=True)

	if source.Id == destination.Id:
		forms.alert("Source and destination must be different elements.", title=__title__, exitscript=True)

	if not utils.is_supported_host(source):
		forms.alert("Source category is not supported. Use Floor, Roof, Ceiling, or Toposolid.", title=__title__, exitscript=True)

	if not utils.is_supported_host(destination):
		forms.alert("Destination category is not supported. Use Floor, Roof, Ceiling, or Toposolid.", title=__title__, exitscript=True)


def _print_summary(summary):
	lines = []
	lines.append("Shape Map 2 completed.")
	lines.append("Source: {0}".format(summary.get("source_label", "<unknown>")))
	lines.append("Destination: {0}".format(summary.get("destination_label", "<unknown>")))
	lines.append("Processed XY points: {0}".format(summary.get("xy_total", 0)))
	lines.append("Source faces sampled: {0}".format(summary.get("source_face_count", 0)))
	lines.append("Destination faces sampled: {0}".format(summary.get("destination_face_count", 0)))
	lines.append("XY from destination vertices: {0}".format(summary.get("xy_dest_count", 0)))
	lines.append("XY from source points: {0}".format(summary.get("xy_source_count", 0)))
	lines.append("XY from boundary grid (destination footprint): {0}".format(summary.get("xy_boundary_grid_count", 0)))
	lines.append("XY from internal grid (destination footprint): {0}".format(summary.get("xy_internal_grid_count", 0)))
	lines.append("Mapped points: {0}".format(summary.get("mapped_count", 0)))
	lines.append("Modified existing vertices: {0}".format(summary.get("modified_count", 0)))
	lines.append("Added vertices: {0}".format(summary.get("added_count", 0)))
	lines.append("Boundary-normal fallback hits: {0}".format(summary.get("boundary_normal_fallback_count", 0)))
	lines.append("Skipped (outside destination footprint): {0}".format(summary.get("skipped_outside_destination_count", 0)))
	lines.append("Misses (no source hit): {0}".format(summary.get("miss_no_hit_count", 0)))
	lines.append("Misses (shape edit write failed): {0}".format(summary.get("miss_shape_edit_count", 0)))
	lines.append("Misses (total): {0}".format(summary.get("miss_count", 0)))
	lines.append("Point Z mode: {0}".format(summary.get("point_z_mode", "<unknown>")))
	lines.append("Offset transfer max error (ft): {0:.9f}".format(summary.get("max_transfer_error_ft", 0.0)))
	lines.append("Level delta (ft): {0:.6f}".format(summary.get("level_delta_ft", 0.0)))
	lines.append("Source base (Level+Offset, ft): {0:.6f}".format(summary.get("source_base_ft", 0.0)))
	lines.append("Destination base before align (ft): {0:.6f}".format(summary.get("destination_base_before_ft", 0.0)))
	lines.append("Destination base after align (ft): {0:.6f}".format(summary.get("destination_base_ft", 0.0)))
	lines.append("Match level+offset requested: {0}".format("Yes" if summary.get("requested_align_level_offset") else "No"))
	lines.append("Match level+offset enforced: {0}".format("Yes" if summary.get("enforced_align_level_offset") else "No"))
	lines.append("Match level+offset applied: {0}".format("Yes" if summary.get("aligned_level_offset") else "No"))
	lines.append("Additional offset (ft): {0:.6f}".format(summary.get("additional_offset_ft", 0.0)))
	lines.append("Temporary point used: {0}".format("Yes" if summary.get("temporary_point_used") else "No"))
	lines.append("Comment updated: {0}".format("Yes" if summary.get("comments_updated") else "No"))

	issues = summary.get("issues", [])
	if issues:
		lines.append("")
		lines.append("Warnings:")
		for issue in issues:
			lines.append("- {0}".format(issue))

	output.print_md("\n".join(lines))

	_modify_counts = summary.get("modify_method_counts", {}) or {}
	if _modify_counts:
		output.print_md("### Vertex Write Methods")
		output.print_md("| Method | Count |")
		output.print_md("|---|---:|")
		for method_name in sorted(_modify_counts.keys()):
			output.print_md("| {0} | {1} |".format(method_name, _modify_counts.get(method_name, 0)))

	_fail_reasons = summary.get("write_fail_reasons", {}) or {}
	if _fail_reasons:
		output.print_md("### Shape Edit Failure Reasons")
		output.print_md("| Reason | Count |")
		output.print_md("|---|---:|")
		for reason, count in sorted(_fail_reasons.items(), key=lambda kv: kv[1], reverse=True):
			output.print_md("| {0} | {1} |".format(str(reason).replace("|", "/"), count))

	_debug_rows = summary.get("debug_rows", []) or []
	if _debug_rows:
		cap = summary.get("debug_row_cap", len(_debug_rows))
		output.print_md("### Point Debug Samples ({0} rows, cap {1})".format(len(_debug_rows), cap))
		output.print_md("| # | X | Y | Hit Z | Source Rel Offset Z | Target Abs Z | Target Offset Z | Transfer Error | Hit Mode | Mode | Result | Detail |")
		output.print_md("|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|")
		for idx, row in enumerate(_debug_rows, 1):
			hit_text = "" if row.get("hit_z") is None else "{0:.6f}".format(row.get("hit_z"))
			src_off_text = "" if row.get("source_relative_offset_z") is None else "{0:.6f}".format(row.get("source_relative_offset_z"))
			abs_text = "" if row.get("target_abs_z") is None else "{0:.6f}".format(row.get("target_abs_z"))
			off_text = "" if row.get("target_offset_z") is None else "{0:.6f}".format(row.get("target_offset_z"))
			err_text = "" if row.get("transfer_error") is None else "{0:.9f}".format(row.get("transfer_error"))
			detail = str(row.get("detail", "")).replace("|", "/")
			output.print_md(
				"| {0} | {1:.6f} | {2:.6f} | {3} | {4} | {5} | {6} | {7} | {8} | {9} | {10} | {11} |".format(
					idx,
					float(row.get("x", 0.0)),
					float(row.get("y", 0.0)),
					hit_text,
					src_off_text,
					abs_text,
					off_text,
					err_text,
					row.get("hit_mode", ""),
					row.get("mode", ""),
					row.get("result", ""),
					detail,
				)
			)


def main():
	try:
		_ensure_revit_version()
		dialog_result = ui.show_shape_map_dialog(__title__)
		if dialog_result is None:
			return

		source = dialog_result.get("source")
		destination = dialog_result.get("destination")
		options = dialog_result.get("options", {})

		_validate_elements(source, destination)

		summary = mapper.map_shape_edits(doc, source, destination, options)
		_print_summary(summary)
	except Exception as ex:
		logger.error("Shape Map 2 failed: %s", ex)
		logger.error(traceback.format_exc())
		forms.alert("Shape Map 2 failed.\n\n{0}".format(str(ex)), title=__title__)


if __name__ == "__main__":
	main()
