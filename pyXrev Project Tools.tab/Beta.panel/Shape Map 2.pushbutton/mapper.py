# -*- coding: utf-8 -*-

import clr

from pyrevit import revit, DB

import geometry
import grid
import rays
import utils


MAX_DEBUG_ROWS = 200
MAX_FAIL_REASONS = 20
NEAREST_FALLBACK_TOLERANCE_FT = 0.5
BOUNDARY_RAY_LENGTH_FT = 10000.0


def _safe_len_vertices(editor):
    try:
        return len([v for v in editor.SlabShapeVertices])
    except Exception:
        return 0


def _find_matching_vertex(vertices, x, y):
    candidate = DB.XYZ(x, y, 0.0)
    for v in vertices:
        p = utils.get_point_from_vertex(v)
        if p is None:
            continue
        if utils.xy_matches(p, candidate, utils.XY_TOLERANCE_FT):
            return v
    return None


def _find_nearest_vertex(vertices, x, y, max_dist_ft):
    max_d2 = float(max_dist_ft) * float(max_dist_ft)
    best_v = None
    best_d2 = None

    for v in vertices:
        p = utils.get_point_from_vertex(v)
        if p is None:
            continue
        dx = p.X - x
        dy = p.Y - y
        d2 = (dx * dx) + (dy * dy)
        if d2 > max_d2:
            continue
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_v = v

    return best_v


def _try_modify_vertex(editor, vertex, target_xyz, target_offset):
    # Prefer absolute XYZ updates first. Some API variants only accept offset.
    errors = []

    try:
        editor.ModifyPoint(vertex, target_xyz)
        return True, "ModifyPoint", errors
    except Exception as ex:
        errors.append("ModifyPoint: {0}".format(str(ex)))

    try:
        editor.ModifySubElement(vertex, target_xyz)
        return True, "ModifySubElement(XYZ)", errors
    except Exception as ex:
        errors.append("ModifySubElement(XYZ): {0}".format(str(ex)))

    try:
        editor.ModifySubElement(vertex, float(target_offset))
        return True, "ModifySubElement(offset)", errors
    except Exception as ex:
        errors.append("ModifySubElement(offset): {0}".format(str(ex)))

    return False, None, errors


def _add_debug_row(debug_rows, row):
    if len(debug_rows) >= MAX_DEBUG_ROWS:
        return
    debug_rows.append(row)


def _append_reason(reason_counts, reason):
    if reason is None:
        return
    text = str(reason).strip()
    if not text:
        return
    if text in reason_counts:
        reason_counts[text] += 1
    elif len(reason_counts) < MAX_FAIL_REASONS:
        reason_counts[text] = 1


def _enable_shape_edit_if_needed(editor, seed_xyz, issues):
    temp_vertex = None
    temp_created = False

    try:
        if hasattr(editor, "IsEnabled") and not editor.IsEnabled:
            editor.Enable()
    except Exception:
        pass

    try:
        if _safe_len_vertices(editor) == 0:
            try:
                temp_vertex = editor.AddPoint(seed_xyz)
            except Exception:
                temp_vertex = editor.DrawPoint(seed_xyz)
            temp_created = temp_vertex is not None
    except Exception as ex:
        issues.append("Could not create temporary point: {0}".format(str(ex)))

    return temp_vertex, temp_created


def _remove_temp_vertex_if_possible(editor, temp_vertex, issues):
    if temp_vertex is None:
        return

    for method_name in ("DeletePoint", "DeleteSubElement"):
        try:
            method = getattr(editor, method_name)
        except Exception:
            method = None
        if method is None:
            continue
        try:
            method(temp_vertex)
            return
        except Exception:
            continue

    issues.append("Temporary shape-edit point could not be deleted automatically.")


def _xy_cross_z(ax, ay, bx, by):
    return (ax * by) - (ay * bx)


def _extract_outer_boundary_segments(faces):
    best_segments = []
    best_area = 0.0
    best_abs_area = 0.0

    for face in faces:
        try:
            curve_loops = face.GetEdgesAsCurveLoops()
        except Exception:
            curve_loops = None
        if curve_loops is None:
            continue

        for curve_loop in curve_loops:
            segments = [curve for curve in curve_loop]
            if len(segments) < 1:
                continue

            area = 0.0
            for seg in segments:
                try:
                    p0 = seg.GetEndPoint(0)
                    p1 = seg.GetEndPoint(1)
                except Exception:
                    continue
                area += _xy_cross_z(p0.X, p0.Y, p1.X, p1.Y)
            area *= 0.5

            if abs(area) > best_abs_area:
                best_abs_area = abs(area)
                best_area = area
                best_segments = segments

    return best_segments, best_area


def _nearest_boundary_segment_by_endpoints(dest_xyz, boundary_segments):
    best_seg = None
    best_score = None

    for seg in boundary_segments:
        try:
            p0 = seg.GetEndPoint(0)
            p1 = seg.GetEndPoint(1)
        except Exception:
            continue

        dx0 = p0.X - dest_xyz.X
        dy0 = p0.Y - dest_xyz.Y
        dx1 = p1.X - dest_xyz.X
        dy1 = p1.Y - dest_xyz.Y
        score = (dx0 * dx0) + (dy0 * dy0) + (dx1 * dx1) + (dy1 * dy1)

        if best_score is None or score < best_score:
            best_score = score
            best_seg = seg

    return best_seg


def _resolve_source_top_face_plane(source, source_faces, issues):
    top_face = None

    try:
        refs = DB.HostObjectUtils.GetTopFaces(source)
        if refs and len(list(refs)) > 0:
            top_ref = list(refs)[0]
            top_obj = source.GetGeometryObjectFromReference(top_ref)
            if isinstance(top_obj, DB.Face):
                top_face = top_obj
    except Exception:
        top_face = None

    if top_face is None and source_faces:
        top_face = source_faces[0]

    if top_face is None:
        issues.append("Source top face plane unavailable; boundary-normal fallback disabled.")
        return None

    try:
        surface = top_face.GetSurface()
        if isinstance(surface, DB.Plane):
            return surface
    except Exception:
        pass

    if isinstance(top_face, DB.PlanarFace):
        try:
            return DB.Plane.CreateByNormalAndOrigin(top_face.FaceNormal, top_face.Origin)
        except Exception:
            pass

    issues.append("Source top face is not planar; boundary-normal fallback disabled.")
    return None


def _intersect_line_with_plane(ray, plane):
    results_ref = clr.Reference[DB.IntersectionResultArray]()

    try:
        result = ray.Intersect(plane, results_ref)
        if result == DB.SetComparisonResult.Overlap:
            ira = results_ref.Value
            if ira is not None and ira.Size > 0:
                return ira.get_Item(0).XYZPoint
    except Exception:
        pass

    try:
        result = plane.Intersect(ray, results_ref)
        if result == DB.SetComparisonResult.Overlap:
            ira = results_ref.Value
            if ira is not None and ira.Size > 0:
                return ira.get_Item(0).XYZPoint
    except Exception:
        pass

    return None


def project_boundary_normal_to_source_top_face(dest_vertex_xyz, boundary_seg, boundary_area, source_top_plane):
    if boundary_seg is None or source_top_plane is None:
        return None

    try:
        p0 = boundary_seg.GetEndPoint(0)
        p1 = boundary_seg.GetEndPoint(1)
    except Exception:
        return None

    tangent_raw = DB.XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0)
    if tangent_raw.GetLength() <= 1e-9:
        return None
    tangent = tangent_raw.Normalize()

    # Left-hand perpendicular to segment tangent.
    left_normal = DB.XYZ(-tangent.Y, tangent.X, 0.0)

    # Outer-loop orientation gives a stable outward baseline.
    if boundary_area > 0.0:
        normal = DB.XYZ(-left_normal.X, -left_normal.Y, 0.0)
    else:
        normal = left_normal

    # If the destination point is clearly on the opposite side, flip.
    side = _xy_cross_z(tangent.X, tangent.Y, dest_vertex_xyz.X - p0.X, dest_vertex_xyz.Y - p0.Y)
    if abs(side) > utils.XY_TOLERANCE_FT:
        normal_is_left = (normal.X * left_normal.X + normal.Y * left_normal.Y) >= 0.0
        point_is_left = side > 0.0
        if normal_is_left != point_is_left:
            normal = DB.XYZ(-normal.X, -normal.Y, 0.0)

    origin = DB.XYZ(dest_vertex_xyz.X, dest_vertex_xyz.Y, dest_vertex_xyz.Z)
    ray_end = origin.Add(normal.Multiply(BOUNDARY_RAY_LENGTH_FT))
    ray = DB.Line.CreateBound(origin, ray_end)

    return _intersect_line_with_plane(ray, source_top_plane)


def _build_xy_sets(source, destination, grid_faces, options, issues):
    source_has_edits = geometry.source_has_shape_edits(source)

    destination_vertices = geometry.destination_vertices(destination)
    xy_dest = []
    for v in destination_vertices:
        p = utils.get_point_from_vertex(v)
        if p is None:
            continue
        xy_dest.append((p.X, p.Y))

    xy_source = []
    if source_has_edits:
        xy_source = geometry.source_shape_points(
            source,
            bool(options.get("include_source_vertices", True)),
            bool(options.get("include_source_boundary", True)),
            bool(options.get("include_source_internal", True)),
        )

    boundary_loops = geometry.extract_boundary_loops(grid_faces, options.get("boundary_grid_ft"))
    xy_boundary_grid = grid.boundary_grid_points(boundary_loops, options.get("boundary_grid_ft"))
    xy_internal_grid = grid.internal_grid_points(boundary_loops, options.get("internal_grid_ft"))

    if not source_has_edits:
        # Explicit behavior: ignore source point sets when source has no shape edits.
        xy_source = []

    all_xy = []
    all_xy.extend(xy_dest)
    all_xy.extend(xy_source)
    all_xy.extend(xy_boundary_grid)
    all_xy.extend(xy_internal_grid)

    all_xy = utils.dedupe_xy_points(all_xy)

    if not all_xy:
        issues.append("No sample points were generated from destination vertices, source points, or grids.")

    return {
        "source_has_edits": source_has_edits,
        "destination_vertices": destination_vertices,
        "xy_dest": xy_dest,
        "xy_source": xy_source,
        "xy_boundary_grid": xy_boundary_grid,
        "xy_internal_grid": xy_internal_grid,
        "xy_all": all_xy,
    }


def map_shape_edits(host_doc, source, destination, options):
    issues = []
    source_faces = geometry.get_source_faces(source, issues)
    if not source_faces:
        raise Exception("Could not resolve source top geometry faces.")

    destination_faces = geometry.get_source_faces(destination, issues)
    if not destination_faces:
        issues.append("Destination top geometry could not be resolved; add-point footprint filtering disabled.")

    editor = utils.get_shape_editor(destination)
    if editor is None:
        raise Exception("Destination does not expose a SlabShapeEditor.")

    # Grid points must be generated from destination footprint so candidate XYs
    # are actually writable on destination hosts.
    grid_faces = destination_faces if destination_faces else source_faces
    if not destination_faces:
        issues.append("Grid faces fallback: using source faces because destination faces were unavailable.")

    xy_data = _build_xy_sets(source, destination, grid_faces, options, issues)
    xy_all = xy_data["xy_all"]
    destination_vertices = xy_data["destination_vertices"]

    # Relative-offset transfer expects both hosts to share the same
    # level+offset reference so the copied offsets are interpreted
    # against an equivalent base on destination.
    requested_align_level_offset = bool(options.get("match_level_offset", False))
    enforced_align_level_offset = True

    if not requested_align_level_offset:
        issues.append("Relative offset mode enforces destination level+offset alignment to source.")

    # Diagnostic only: this is NOT applied directly to mapped point Z.
    # Point Z mapping transfers source-relative shape offset.
    level_delta_ft = utils.compute_level_delta(
        host_doc,
        source,
        destination,
        enforced_align_level_offset,
    )
    destination_base_before_ft = utils.get_level_plus_offset(host_doc, destination)
    destination_base_ft = destination_base_before_ft
    source_base_ft = utils.get_level_plus_offset(host_doc, source)
    source_top_plane = _resolve_source_top_face_plane(source, source_faces, issues)
    aligned_level_offset = False

    additional_offset_ft = float(options.get("additional_z_offset_ft", 0.0))

    modified = 0
    added = 0
    miss_no_hit = 0
    miss_shape_edit = 0
    skipped_outside_destination = 0
    boundary_fallback_count = 0
    mapped = 0
    temp_used = False
    modify_method_counts = {}
    write_fail_reasons = {}

    debug_rows = []
    max_transfer_error_ft = 0.0

    seed_x = 0.0
    seed_y = 0.0
    if xy_all:
        seed_x, seed_y = xy_all[0]
    seed_z = rays.vertical_intersection_z(seed_x, seed_y, source_faces)
    if seed_z is None:
        seed_z = 0.0
    seed_xyz = DB.XYZ(seed_x, seed_y, seed_z)

    with revit.Transaction("Map Shape Edits"):
        if enforced_align_level_offset:
            aligned_level_offset = utils.align_level_and_offset(host_doc, source, destination, issues)
            try:
                host_doc.Regenerate()
            except Exception:
                pass

        # Destination geometry objects captured before level/offset edits can
        # become stale after regenerate. Refresh footprint faces for precheck.
        destination_faces_live = geometry.get_source_faces(destination, issues)
        if not destination_faces_live:
            destination_faces_live = []
            issues.append("Destination top geometry unavailable after alignment/regenerate; footprint precheck disabled.")

        destination_boundary_segments, destination_boundary_area = _extract_outer_boundary_segments(destination_faces_live)
        if not destination_boundary_segments:
            issues.append("Destination boundary segments unavailable; boundary-normal fallback disabled.")

        destination_base_ft = utils.get_level_plus_offset(host_doc, destination)
        temp_vertex, temp_used = _enable_shape_edit_if_needed(editor, seed_xyz, issues)

        for x, y in xy_all:
            existing = _find_matching_vertex(destination_vertices, x, y)
            hit_z = rays.vertical_intersection_z(x, y, source_faces)
            hit_mode = "vertical"

            if hit_z is None:
                fallback_hit = None
                if existing is not None and source_top_plane is not None and destination_boundary_segments:
                    fallback_origin_z = destination_base_ft
                    existing_pt = utils.get_point_from_vertex(existing)
                    if existing_pt is not None:
                        fallback_origin_z = existing_pt.Z

                    fallback_origin = DB.XYZ(x, y, fallback_origin_z)
                    boundary_seg = _nearest_boundary_segment_by_endpoints(fallback_origin, destination_boundary_segments)
                    fallback_pt = project_boundary_normal_to_source_top_face(
                        fallback_origin,
                        boundary_seg,
                        destination_boundary_area,
                        source_top_plane,
                    )
                    if fallback_pt is not None:
                        fallback_hit = fallback_pt.Z

                if fallback_hit is None:
                    miss_no_hit += 1
                    _add_debug_row(debug_rows, {
                        "x": x,
                        "y": y,
                        "hit_z": None,
                        "target_abs_z": None,
                        "target_offset_z": None,
                        "mode": "ray",
                        "result": "no_hit",
                        "detail": "No source face intersection and boundary-normal fallback failed",
                    })
                    continue

                hit_z = fallback_hit
                hit_mode = "boundary_normal"
                boundary_fallback_count += 1

            # Transfer shape offset relative to source host base, then apply
            # on destination host base. This avoids world-Z drift when source
            # and destination level/offset differ.
            source_relative_offset_z = hit_z - source_base_ft
            target_offset_z = source_relative_offset_z + additional_offset_ft
            target_abs_z = destination_base_ft + target_offset_z
            transfer_error = target_offset_z - (source_relative_offset_z + additional_offset_ft)
            if abs(transfer_error) > max_transfer_error_ft:
                max_transfer_error_ft = abs(transfer_error)
            target_xyz = DB.XYZ(x, y, target_abs_z)

            if existing is None and destination_faces_live:
                dst_probe_z = rays.vertical_intersection_z(x, y, destination_faces_live)
                if dst_probe_z is None:
                    skipped_outside_destination += 1
                    _add_debug_row(debug_rows, {
                        "x": x,
                        "y": y,
                        "hit_z": hit_z,
                        "source_relative_offset_z": source_relative_offset_z,
                        "target_abs_z": target_abs_z,
                        "target_offset_z": target_offset_z,
                        "transfer_error": transfer_error,
                        "mode": "precheck_destination",
                        "result": "skipped",
                        "detail": "Outside destination top face footprint",
                    })
                    continue

            if existing is not None:
                try:
                    ok, method_name, method_errors = _try_modify_vertex(editor, existing, target_xyz, target_offset_z)
                    if ok:
                        modified += 1
                        mapped += 1
                        if method_name:
                            modify_method_counts[method_name] = modify_method_counts.get(method_name, 0) + 1
                        _add_debug_row(debug_rows, {
                            "x": x,
                            "y": y,
                            "hit_z": hit_z,
                            "source_relative_offset_z": source_relative_offset_z,
                            "target_abs_z": target_abs_z,
                            "target_offset_z": target_offset_z,
                            "transfer_error": transfer_error,
                            "mode": "modify_existing",
                            "hit_mode": hit_mode,
                            "result": "ok",
                            "detail": method_name or "modified",
                        })
                    else:
                        miss_shape_edit += 1
                        for err in method_errors:
                            _append_reason(write_fail_reasons, err)
                        _add_debug_row(debug_rows, {
                            "x": x,
                            "y": y,
                            "hit_z": hit_z,
                            "source_relative_offset_z": source_relative_offset_z,
                            "target_abs_z": target_abs_z,
                            "target_offset_z": target_offset_z,
                            "transfer_error": transfer_error,
                            "mode": "modify_existing",
                            "hit_mode": hit_mode,
                            "result": "failed",
                            "detail": "; ".join(method_errors[:2]) if method_errors else "Modify failed",
                        })
                except Exception as ex:
                    miss_shape_edit += 1
                    _append_reason(write_fail_reasons, "Modify existing exception: {0}".format(str(ex)))
                continue

            add_errors = []
            try:
                new_vertex = editor.AddPoint(target_xyz)
            except Exception as ex_add:
                add_errors.append("AddPoint: {0}".format(str(ex_add)))
                try:
                    new_vertex = editor.DrawPoint(target_xyz)
                except Exception as ex_draw:
                    add_errors.append("DrawPoint: {0}".format(str(ex_draw)))
                    new_vertex = None

            if new_vertex is not None:
                destination_vertices.append(new_vertex)
                added += 1
                mapped += 1
                _add_debug_row(debug_rows, {
                    "x": x,
                    "y": y,
                    "hit_z": hit_z,
                    "source_relative_offset_z": source_relative_offset_z,
                    "target_abs_z": target_abs_z,
                    "target_offset_z": target_offset_z,
                    "transfer_error": transfer_error,
                    "mode": "add",
                    "hit_mode": hit_mode,
                    "result": "ok",
                    "detail": "AddPoint/DrawPoint",
                })
            else:
                # Final fallback for APIs that reject AddPoint but allow nearest-vertex modification.
                nearest = _find_nearest_vertex(destination_vertices, x, y, NEAREST_FALLBACK_TOLERANCE_FT)
                if nearest is not None:
                    ok, method_name, method_errors = _try_modify_vertex(editor, nearest, target_xyz, target_offset_z)
                else:
                    ok, method_name, method_errors = False, None, []

                if nearest is not None and ok:
                    modified += 1
                    mapped += 1
                    if method_name:
                        modify_method_counts[method_name] = modify_method_counts.get(method_name, 0) + 1
                    _add_debug_row(debug_rows, {
                        "x": x,
                        "y": y,
                        "hit_z": hit_z,
                        "source_relative_offset_z": source_relative_offset_z,
                        "target_abs_z": target_abs_z,
                        "target_offset_z": target_offset_z,
                        "transfer_error": transfer_error,
                        "mode": "add_fallback_modify",
                        "hit_mode": hit_mode,
                        "result": "ok",
                        "detail": method_name or "fallback modify",
                    })
                else:
                    miss_shape_edit += 1
                    for err in add_errors:
                        _append_reason(write_fail_reasons, err)
                    for err in method_errors:
                        _append_reason(write_fail_reasons, err)
                    if nearest is None:
                        _append_reason(write_fail_reasons, "No nearby vertex for fallback modify (within {0:.3f} ft).".format(NEAREST_FALLBACK_TOLERANCE_FT))
                    _add_debug_row(debug_rows, {
                        "x": x,
                        "y": y,
                        "hit_z": hit_z,
                        "source_relative_offset_z": source_relative_offset_z,
                        "target_abs_z": target_abs_z,
                        "target_offset_z": target_offset_z,
                        "transfer_error": transfer_error,
                        "mode": "add",
                        "hit_mode": hit_mode,
                        "result": "failed",
                        "detail": "; ".join((add_errors + method_errors)[:2]) if (add_errors or method_errors) else "Shape edit write failed",
                    })

        # Remove temp point only if it was created and remains unmatched in the final set.
        if temp_vertex is not None:
            tp = utils.get_point_from_vertex(temp_vertex)
            keep_temp = False
            if tp is not None:
                for x, y in xy_all:
                    if abs(tp.X - x) <= utils.XY_TOLERANCE_FT and abs(tp.Y - y) <= utils.XY_TOLERANCE_FT:
                        keep_temp = True
                        break
            if not keep_temp:
                _remove_temp_vertex_if_possible(editor, temp_vertex, issues)

        comments_updated = utils.append_destination_comment(host_doc, destination, source)

    return {
        "source_label": utils.get_source_identity_label(host_doc, source),
        "destination_label": utils.get_source_identity_label(host_doc, destination),
        "xy_total": len(xy_all),
        "mapped_count": mapped,
        "modified_count": modified,
        "added_count": added,
        "miss_count": (miss_no_hit + miss_shape_edit),
        "miss_no_hit_count": miss_no_hit,
        "miss_shape_edit_count": miss_shape_edit,
        "skipped_outside_destination_count": skipped_outside_destination,
        "boundary_normal_fallback_count": boundary_fallback_count,
        "source_has_shape_edits": xy_data["source_has_edits"],
        "source_face_count": len(source_faces),
        "destination_face_count": len(destination_faces_live),
        "xy_dest_count": len(xy_data["xy_dest"]),
        "xy_source_count": len(xy_data["xy_source"]),
        "xy_boundary_grid_count": len(xy_data["xy_boundary_grid"]),
        "xy_internal_grid_count": len(xy_data["xy_internal_grid"]),
        "point_z_mode": "relative_offset_transfer",
        "max_transfer_error_ft": max_transfer_error_ft,
        "source_base_ft": source_base_ft,
        "level_delta_ft": level_delta_ft,
        "additional_offset_ft": additional_offset_ft,
        "destination_base_before_ft": destination_base_before_ft,
        "destination_base_ft": destination_base_ft,
        "aligned_level_offset": aligned_level_offset,
        "requested_align_level_offset": requested_align_level_offset,
        "enforced_align_level_offset": enforced_align_level_offset,
        "temporary_point_used": temp_used,
        "modify_method_counts": modify_method_counts,
        "write_fail_reasons": write_fail_reasons,
        "debug_rows": debug_rows,
        "debug_row_cap": MAX_DEBUG_ROWS,
        "comments_updated": comments_updated,
        "issues": issues,
    }