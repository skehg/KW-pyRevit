# -*- coding: utf-8 -*-
"""Core geometry and Revit API logic for Shape Map.

This module intentionally avoids pyrevit.forms / WPF imports so interpolation
and mapping behavior can be tested independently from the UI flow.
"""

import math
import clr
import Autodesk.Revit.DB as DB

from Autodesk.Revit.DB import (
    Arc,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    Face,
    Floor,
    GeometryInstance,
    HostObjectUtils,
    IntersectionResultArray,
    Line,
    Options,
    RoofBase,
    SetComparisonResult,
    Solid,
    UV,
    XYZ,
)

Toposolid = getattr(DB, "Toposolid", None)
SlabShapeVertexType = getattr(DB, "SlabShapeVertexType", None)


DEFAULT_GRID_SPACING_FT = 3.0
BOUNDARY_TESSELLATION_FT = 1.0
DEFAULT_EDGE_SPACING_FT = 1.0
DEFAULT_ARC_MAX_ANGLE_DEG = 5.0
VERTICAL_PROBE_HALF_HEIGHT_FT = 1000.0
VERTICAL_PROBE_MARGIN_FT = 50.0
POINT_KEY_PRECISION = 4
ZERO_OFFSET_TOLERANCE_FT = 0.00328084
BOUNDARY_NUDGE_FT = 0.01
INTERIOR_RING_NUDGE_FT = 0.05
VERTEX_MATCH_TOLERANCE_FT = 0.02
LOOSE_VERTEX_MATCH_TOLERANCE_FT = 0.5


CATEGORY_LABELS = {
    BuiltInCategory.OST_Floors: "Floor",
    BuiltInCategory.OST_Roofs: "Roof",
}
if hasattr(BuiltInCategory, "OST_Toposolid"):
    CATEGORY_LABELS[BuiltInCategory.OST_Toposolid] = "Toposolid"


def _to_bic(element):
    try:
        return element.Category.BuiltInCategory
    except Exception:
        return None


def _cat_label(element):
    bic = _to_bic(element)
    return CATEGORY_LABELS.get(bic, "Element")


def is_supported_host_element(element):
    if element is None or element.Category is None:
        return False

    bic = _to_bic(element)
    if bic == BuiltInCategory.OST_Floors:
        return True
    if bic == BuiltInCategory.OST_Roofs:
        return True
    if Toposolid and hasattr(BuiltInCategory, "OST_Toposolid") and bic == BuiltInCategory.OST_Toposolid:
        return True
    return False


def get_display_label(doc, element):
    elem_id = element.Id.IntegerValue if element else -1
    family_name = _cat_label(element)
    type_name = "<unknown type>"

    try:
        et = doc.GetElement(element.GetTypeId())
        if et:
            family_name = getattr(et, "FamilyName", family_name)
            type_name = getattr(et, "Name", type_name)
    except Exception:
        pass

    return "{0} : {1} ({2})".format(family_name, type_name, elem_id)


def _iter_solid_faces(element):
    opts = Options()
    opts.IncludeNonVisibleObjects = False
    opts.ComputeReferences = True

    geom = element.get_Geometry(opts)
    if geom is None:
        return

    for gobj in geom:
        if isinstance(gobj, Solid) and gobj.Faces and gobj.Faces.Size > 0:
            for face in gobj.Faces:
                yield face
        elif isinstance(gobj, GeometryInstance):
            inst_geom = gobj.GetInstanceGeometry()
            if inst_geom is None:
                continue
            for iobj in inst_geom:
                if isinstance(iobj, Solid) and iobj.Faces and iobj.Faces.Size > 0:
                    for face in iobj.Faces:
                        yield face


def _face_normal_z(face):
    try:
        bb = face.GetBoundingBox()
        u = (bb.Min.U + bb.Max.U) * 0.5
        v = (bb.Min.V + bb.Max.V) * 0.5
        n = face.ComputeNormal(UV(u, v))
        return n.Z
    except Exception:
        return -1e9


def _select_top_face_from_faces(faces):
    candidates = []
    for face in faces:
        if not isinstance(face, Face):
            continue
        nz = _face_normal_z(face)
        if nz > 0.01:
            area = getattr(face, "Area", 0.0)
            candidates.append((area, nz, face))

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]


def _select_top_faces_from_faces(faces):
    selected = []
    for face in faces:
        if not isinstance(face, Face):
            continue
        nz = _face_normal_z(face)
        if nz > 0.01:
            selected.append(face)
    return selected


def get_top_faces(doc, host_element, issues, role_label):
    """Return top faces for supported host, preferring HostObjectUtils then geometry scan."""
    # Preferred API path.
    try:
        refs = HostObjectUtils.GetTopFaces(host_element)
        if refs and refs.Count > 0:
            faces = []
            for r in refs:
                try:
                    f = host_element.GetGeometryObjectFromReference(r)
                    if isinstance(f, Face):
                        faces.append(f)
                except Exception:
                    continue

            top_faces = _select_top_faces_from_faces(faces)
            if top_faces:
                if len(top_faces) > 1:
                    issues.append("{0}: multiple top faces found; all top faces will be sampled.".format(role_label))
                return top_faces
    except Exception:
        pass

    # Fallback for unsupported HostObjectUtils or edge-case geometry.
    fallback_faces = _select_top_faces_from_faces(_iter_solid_faces(host_element))
    if fallback_faces:
        issues.append("{0}: top face resolved using geometry fallback.".format(role_label))
        if len(fallback_faces) > 1:
            issues.append("{0}: fallback returned multiple top faces; all top faces will be sampled.".format(role_label))
        return fallback_faces

    return []


def get_top_face(doc, host_element, issues, role_label):
    """Compatibility wrapper returning largest top face from get_top_faces()."""
    faces = get_top_faces(doc, host_element, issues, role_label)
    if not faces:
        return None
    return _select_top_face_from_faces(faces)


def _extract_boundaries_from_faces(faces, edge_spacing_ft=None):
    boundaries = []
    for face in faces:
        bnd = _extract_outer_boundary_polyline(face, edge_spacing_ft=edge_spacing_ft)
        if len(bnd) >= 4:
            boundaries.append(bnd)

    return boundaries


def _nearest_boundary_across_polylines(x, y, boundary_polylines):
    best_pt = None
    best_d2 = None

    for polyline in boundary_polylines:
        q = nearest_boundary_xy(x, y, polyline)
        if q is None:
            continue

        dx = q.X - x
        dy = q.Y - y
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_pt = q

    return best_pt


def _sample_height_on_faces(faces, x, y):
    best_z = None
    found_any = False

    for face in faces:
        z_lo, z_hi = _get_face_z_probe_bounds(face)
        z = sample_height_on_face(face, x, y, z_lo, z_hi)
        if z is None:
            continue

        found_any = True
        if best_z is None or z > best_z:
            best_z = z

    if not found_any:
        return None

    return best_z


def _xy_key(x, y):
    return (round(float(x), POINT_KEY_PRECISION), round(float(y), POINT_KEY_PRECISION))


def _sample_curve_points(curve, edge_spacing_ft):
    """Sample a curve with arc-aware controls.

    Lines: sampled by length spacing.
    Arcs: sampled by the stricter of chord-length and max-angle step.
    Others: fallback tessellation + optional densification.
    """
    if curve is None:
        return []

    # Fall back to Revit tessellation when spacing is not active.
    if (edge_spacing_ft is None) or (edge_spacing_ft <= 1e-9):
        try:
            return list(curve.Tessellate())
        except Exception:
            return []

    max_len_ft = max(float(edge_spacing_ft), 1e-6)

    # Arc-aware sampling.
    if isinstance(curve, Arc):
        try:
            arc_angle = abs(curve.Angle)
            arc_len = curve.Length
            max_angle_rad = math.radians(DEFAULT_ARC_MAX_ANGLE_DEG)
            n_len = int(math.ceil(arc_len / max_len_ft)) if arc_len > 1e-9 else 1
            n_ang = int(math.ceil(arc_angle / max_angle_rad)) if arc_angle > 1e-9 else 1
            n = max(1, n_len, n_ang)

            p0 = curve.GetEndParameter(0)
            p1 = curve.GetEndParameter(1)
            pts = []
            for i in range(n + 1):
                t = float(i) / float(n)
                param = p0 + ((p1 - p0) * t)
                pts.append(curve.Evaluate(param, False))
            return pts
        except Exception:
            pass

    # Line sampling.
    if isinstance(curve, Line):
        try:
            ln_len = curve.Length
            n = max(1, int(math.ceil(ln_len / max_len_ft)))
            p0 = curve.GetEndParameter(0)
            p1 = curve.GetEndParameter(1)
            pts = []
            for i in range(n + 1):
                t = float(i) / float(n)
                param = p0 + ((p1 - p0) * t)
                pts.append(curve.Evaluate(param, False))
            return pts
        except Exception:
            pass

    # Other curve types: tessellate then densify by segment length.
    try:
        raw = list(curve.Tessellate())
    except Exception:
        raw = []

    if len(raw) < 2:
        try:
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            if p0 is not None and p1 is not None:
                raw = [p0, p1]
        except Exception:
            pass

    if len(raw) >= 2:
        return _densify_polyline(raw, max_len_ft)
    return raw


def _extract_face_uv_domain_ring(top_face):
    """Fallback ring from the face UV domain corners mapped to XYZ."""
    try:
        bb = top_face.GetBoundingBox()
        if bb is None:
            return []

        uv_corners = [
            UV(bb.Min.U, bb.Min.V),
            UV(bb.Max.U, bb.Min.V),
            UV(bb.Max.U, bb.Max.V),
            UV(bb.Min.U, bb.Max.V),
        ]

        pts = []
        for uv in uv_corners:
            try:
                p = top_face.Evaluate(uv)
                if p is not None:
                    pts.append(p)
            except Exception:
                continue

        if len(pts) >= 3 and pts[0].DistanceTo(pts[-1]) > 1e-6:
            pts.append(pts[0])
        return pts if len(pts) >= 4 else []
    except Exception:
        return []


def _extract_outer_boundary_polyline(top_face, edge_spacing_ft=None):
    loops = top_face.GetEdgesAsCurveLoops()
    if loops is None or loops.Count == 0:
        return []

    best_points = []
    best_len = -1.0

    for loop in loops:
        loop_points = []
        total = 0.0
        for curve in loop:
            pts = _sample_curve_points(curve, edge_spacing_ft)
            if not pts:
                continue
            if not loop_points:
                loop_points.extend(pts)
            else:
                loop_points.extend(pts[1:])
            try:
                total += curve.Length
            except Exception:
                pass

        if len(loop_points) < 3:
            continue

        if total > best_len:
            best_len = total
            best_points = loop_points

    if not best_points:
        return []

    if best_points[0].DistanceTo(best_points[-1]) > 1e-6:
        best_points.append(best_points[0])

    return best_points


def _densify_polyline(points, max_len_ft):
    if len(points) < 2:
        return list(points)

    dense = []
    for i in range(len(points) - 1):
        p0 = points[i]
        p1 = points[i + 1]
        dense.append(p0)
        seg_len = p0.DistanceTo(p1)

        if seg_len <= 1e-9:
            continue

        n = int(seg_len / max_len_ft)
        for j in range(1, n + 1):
            t = float(j) / float(n + 1)
            dense.append(XYZ(
                p0.X + (p1.X - p0.X) * t,
                p0.Y + (p1.Y - p0.Y) * t,
                p0.Z + (p1.Z - p0.Z) * t,
            ))

    dense.append(points[-1])
    return dense


def _build_bbox_boundary_polyline(element, edge_spacing_ft=None):
    """Fallback XY boundary from element bounding box."""
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None

    if bbox is None:
        return []

    min_pt = bbox.Min
    max_pt = bbox.Max
    if min_pt is None or max_pt is None:
        return []

    z = max_pt.Z
    ring = [
        XYZ(min_pt.X, min_pt.Y, z),
        XYZ(max_pt.X, min_pt.Y, z),
        XYZ(max_pt.X, max_pt.Y, z),
        XYZ(min_pt.X, max_pt.Y, z),
        XYZ(min_pt.X, min_pt.Y, z),
    ]

    if edge_spacing_ft and edge_spacing_ft > 1e-9:
        return _densify_polyline(ring, float(edge_spacing_ft))
    return ring


def _build_seed_points_for_shape_enable(element):
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None

    if bbox is None or bbox.Min is None or bbox.Max is None:
        return []

    min_pt = bbox.Min
    max_pt = bbox.Max
    cx = (min_pt.X + max_pt.X) * 0.5
    cy = (min_pt.Y + max_pt.Y) * 0.5
    z = max_pt.Z

    dx = max_pt.X - min_pt.X
    dy = max_pt.Y - min_pt.Y
    ox = dx * 0.15
    oy = dy * 0.15

    return [
        XYZ(cx, cy, z),
        XYZ(cx + ox, cy, z),
        XYZ(cx - ox, cy, z),
        XYZ(cx, cy + oy, z),
        XYZ(cx, cy - oy, z),
    ]


def _ensure_destination_shape_editable(destination_element, issues):
    """Ensure destination shape editing is enabled even when never edited before."""
    editor = _get_editor(destination_element)
    if editor is None:
        return False

    try:
        editor.Enable()
    except Exception:
        pass

    if _editor_vertex_count(editor) > 0:
        return True, None

    seed_points = _build_seed_points_for_shape_enable(destination_element)
    if not seed_points:
        issues.append("Destination has no shape vertices and no seed point could be derived from bounding box.")
        return False, None

    for seed in seed_points:
        try:
            editor.AddPoint(seed)
            issues.append("Destination shape editing auto-enabled using seed point.")
            # Keep it during write operations, then remove it at end of run.
            return True, seed
        except Exception:
            continue

    issues.append("Failed to auto-enable destination shape editing via seed point.")
    return False, None


def _delete_seed_vertex_if_present(destination_element, seed_point_xyz, issues):
    if seed_point_xyz is None:
        return False

    editor = _get_editor(destination_element)
    if editor is None:
        return False

    seed_key = _xy_key(seed_point_xyz.X, seed_point_xyz.Y)
    target_vertex = None

    # Prefer deleting an interior vertex that matches the seed XY.
    for vertex, pos in _list_editor_vertices(editor):
        if _xy_key(pos.X, pos.Y) != seed_key:
            continue
        vtype = _get_vertex_type_text(vertex)
        if "Interior" in vtype or "Internal" in vtype:
            target_vertex = vertex
            break
        if target_vertex is None:
            target_vertex = vertex

    if target_vertex is None:
        return False

    # Try known delete signatures across host/API variants.
    try:
        editor.DeletePoint(target_vertex)
        issues.append("Temporary seed point removed after shape mapping.")
        return True
    except Exception:
        pass

    try:
        editor.DeletePoint(seed_point_xyz)
        issues.append("Temporary seed point removed after shape mapping.")
        return True
    except Exception:
        pass

    try:
        pos = target_vertex.Position
        if pos is not None:
            editor.DeletePoint(pos)
            issues.append("Temporary seed point removed after shape mapping.")
            return True
    except Exception:
        pass

    return False


def _point_in_polygon_2d(x, y, polygon_pts):
    # Ray casting in XY.
    inside = False
    count = len(polygon_pts)
    if count < 3:
        return False

    j = count - 1
    for i in range(count):
        xi = polygon_pts[i].X
        yi = polygon_pts[i].Y
        xj = polygon_pts[j].X
        yj = polygon_pts[j].Y

        intersects = ((yi > y) != (yj > y))
        if intersects:
            denom = (yj - yi)
            if abs(denom) < 1e-12:
                j = i
                continue
            x_at_y = (xj - xi) * (y - yi) / denom + xi
            if x < x_at_y:
                inside = not inside

        j = i

    return inside


def _point_on_polygon_boundary_2d(x, y, polygon_pts, tol_ft=1e-4):
    if not polygon_pts or len(polygon_pts) < 2:
        return False

    tol2 = tol_ft * tol_ft
    for i in range(len(polygon_pts) - 1):
        q = _nearest_point_on_segment_2d(x, y, polygon_pts[i], polygon_pts[i + 1])
        dx = q.X - x
        dy = q.Y - y
        if (dx * dx + dy * dy) <= tol2:
            return True

    return False


def _nearest_point_on_segment_2d(x, y, a, b):
    ax = a.X
    ay = a.Y
    bx = b.X
    by = b.Y

    vx = bx - ax
    vy = by - ay
    wx = x - ax
    wy = y - ay

    vv = vx * vx + vy * vy
    if vv <= 1e-12:
        return XYZ(ax, ay, 0.0)

    t = (wx * vx + wy * vy) / vv
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0

    return XYZ(ax + vx * t, ay + vy * t, 0.0)


def nearest_boundary_xy(x, y, boundary_polyline):
    if len(boundary_polyline) < 2:
        return None

    best_pt = None
    best_d2 = None

    for i in range(len(boundary_polyline) - 1):
        q = _nearest_point_on_segment_2d(x, y, boundary_polyline[i], boundary_polyline[i + 1])
        dx = q.X - x
        dy = q.Y - y
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_pt = q

    return best_pt


def sample_height_on_face(face, x, y, z_lo, z_hi):
    """Vertically intersect a line at XY with face and return Z or None."""
    p0 = XYZ(x, y, z_lo)
    p1 = XYZ(x, y, z_hi)
    ln = Line.CreateBound(p0, p1)

    try:
        ira_ref = clr.Reference[IntersectionResultArray]()
        relation = face.Intersect(ln, ira_ref)
        if relation != SetComparisonResult.Overlap:
            return None

        ira = ira_ref.Value
        if ira is None or ira.Size == 0:
            return None

        best_z = None
        for i in range(ira.Size):
            ir = ira.get_Item(i)
            pt = ir.XYZPoint
            if pt is None:
                continue
            if best_z is None or pt.Z > best_z:
                best_z = pt.Z
        return best_z
    except Exception:
        return None


def _get_face_z_probe_bounds(face):
    """Return robust vertical probe bounds around the face elevation range."""
    try:
        mesh = face.Triangulate()
        verts = mesh.Vertices if mesh else None
        if verts and verts.Count > 0:
            min_z = None
            max_z = None
            for i in range(verts.Count):
                p = verts[i]
                z = p.Z
                if min_z is None or z < min_z:
                    min_z = z
                if max_z is None or z > max_z:
                    max_z = z

            if min_z is not None and max_z is not None:
                return min_z - VERTICAL_PROBE_MARGIN_FT, max_z + VERTICAL_PROBE_MARGIN_FT
    except Exception:
        pass

    return -VERTICAL_PROBE_HALF_HEIGHT_FT, VERTICAL_PROBE_HALF_HEIGHT_FT


def _interpolate_z_from_neighbors(x, y, known_xyz, neighbor_count=6):
    """Interpolate Z at XY from nearby known XYZ points with inverse-distance weights."""
    if not known_xyz:
        return None

    nearest = []
    for px, py, pz in known_xyz:
        dx = px - x
        dy = py - y
        d2 = dx * dx + dy * dy
        if d2 <= 1e-12:
            return pz
        nearest.append((d2, pz))

    if not nearest:
        return None

    nearest.sort(key=lambda t: t[0])
    subset = nearest[:max(1, int(neighbor_count))]

    weighted_sum = 0.0
    weight_total = 0.0
    for d2, pz in subset:
        w = 1.0 / d2
        weighted_sum += w * pz
        weight_total += w

    if weight_total <= 1e-12:
        return None

    return weighted_sum / weight_total


def _collect_source_vertex_xys(source_element, destination_boundary):
    result = []
    editor = None

    try:
        editor = source_element.SlabShapeEditor
    except Exception:
        editor = None

    if editor is None:
        return result

    try:
        verts = editor.SlabShapeVertices
    except Exception:
        verts = None

    if not verts:
        return result

    for v in verts:
        try:
            p = v.Position
            if not p:
                continue

            if destination_boundary is None or len(destination_boundary) < 4:
                result.append((p.X, p.Y))
            elif _point_in_polygon_2d(p.X, p.Y, destination_boundary) or _point_on_polygon_boundary_2d(p.X, p.Y, destination_boundary):
                result.append((p.X, p.Y))
        except Exception:
            continue

    return result


def _collect_source_vertex_candidates(source_element, interior_preferred=True):
    """Return source vertex XY candidates, preferring interior vertices when requested."""
    candidates = []
    fallback = []

    editor = _get_editor(source_element)
    if editor is None:
        return candidates

    seen = set()
    for vertex, pos in _list_editor_vertices(editor):
        key = _xy_key(pos.X, pos.Y)
        if key in seen:
            continue
        seen.add(key)

        state = _is_boundary_vertex(vertex)
        if interior_preferred and state is False:
            candidates.append((pos.X, pos.Y))
        else:
            fallback.append((pos.X, pos.Y))

    if candidates:
        return candidates + fallback
    return fallback


def _bootstrap_destination_vertices_from_source(destination_element,
                                                destination_top_face,
                                                source_element,
                                                issues,
                                                max_points=200):
    """Create initial destination shape vertices from source vertex XY positions."""
    editor = _get_editor(destination_element)
    if editor is None:
        return 0

    try:
        editor.Enable()
    except Exception:
        pass

    source_xy = _collect_source_vertex_candidates(source_element, interior_preferred=True)
    if not source_xy:
        return 0

    z_lo, z_hi = _get_face_z_probe_bounds(destination_top_face)
    added = 0
    for x, y in source_xy:
        if added >= max_points:
            break

        z = sample_height_on_face(destination_top_face, x, y, z_lo, z_hi)
        if z is None:
            continue

        try:
            editor.AddPoint(XYZ(x, y, z))
            added += 1
        except Exception:
            continue

    if added > 0:
        issues.append("Destination vertices auto-bootstrapped from source shape vertices: {0} points.".format(added))

    return added


def build_destination_sample_xy(destination_top_face,
                                grid_spacing_ft,
                                edge_spacing_ft,
                                include_source_xy=None,
                                use_interior_grid=True,
                                sampling_mode="hybrid"):
    """Build boundary + optional interior XY sample points on destination footprint."""
    boundary_spacing = edge_spacing_ft if sampling_mode in ("hybrid", "edge_only") else None
    boundary = _extract_outer_boundary_polyline(destination_top_face, edge_spacing_ft=boundary_spacing)

    # Retry extraction without forced spacing; some faces are sparse/fragile with dense sampling.
    if len(boundary) < 4 and boundary_spacing is not None:
        boundary = _extract_outer_boundary_polyline(destination_top_face, edge_spacing_ft=None)

    # Last-resort fallback so sampling can still proceed on valid top faces.
    if len(boundary) < 4:
        boundary = _extract_face_uv_domain_ring(destination_top_face)

    if len(boundary) < 4:
        return [], boundary

    dense_boundary = list(boundary)

    points = []
    seen = set()

    def add_xy(x, y):
        key = _xy_key(x, y)
        if key in seen:
            return
        seen.add(key)
        points.append((x, y))

    if sampling_mode != "source_vertices_only":
        for p in dense_boundary:
            add_xy(p.X, p.Y)

    min_x = min(p.X for p in dense_boundary)
    max_x = max(p.X for p in dense_boundary)
    min_y = min(p.Y for p in dense_boundary)
    max_y = max(p.Y for p in dense_boundary)

    if use_interior_grid and grid_spacing_ft and grid_spacing_ft > 0.0 and sampling_mode != "source_vertices_only":
        x = min_x
        while x <= max_x + 1e-9:
            y = min_y
            while y <= max_y + 1e-9:
                if _point_in_polygon_2d(x, y, boundary):
                    add_xy(x, y)
                y += grid_spacing_ft
            x += grid_spacing_ft

    if include_source_xy and sampling_mode in ("hybrid", "source_vertices_only"):
        for sx, sy in include_source_xy:
            if _point_in_polygon_2d(sx, sy, boundary):
                add_xy(sx, sy)
            elif sampling_mode == "source_vertices_only":
                # In source-vertex mode, project out-of-bound source XY onto destination boundary.
                projected = nearest_boundary_xy(sx, sy, boundary)
                if projected is not None:
                    add_xy(projected.X, projected.Y)

    return points, boundary


def map_sample_xy_to_source_z(sample_xy,
                              source_top_faces,
                              source_boundaries,
                              issues,
                              collect_debug=False,
                              allow_clamp=True,
                              allow_interpolation=True):
    mapped = []
    clamped_count = 0
    interpolated_count = 0
    missed_count = 0
    debug_rows = []

    unresolved_xy = []

    for x, y in sample_xy:
        z = _sample_height_on_faces(source_top_faces, x, y)
        if z is not None:
            mapped.append((x, y, z))
            if collect_debug:
                debug_rows.append((x, y, z, "direct"))
            continue

        if allow_clamp:
            # Clamp fallback to nearest source boundary point in XY.
            nb = _nearest_boundary_across_polylines(x, y, source_boundaries)
            if nb is None:
                unresolved_xy.append((x, y, "no_boundary"))
                continue

            z2 = _sample_height_on_faces(source_top_faces, nb.X, nb.Y)
            if z2 is None:
                unresolved_xy.append((x, y, "clamp_no_intersection"))
                continue

            clamped_count += 1
            mapped.append((x, y, z2))
            if collect_debug:
                debug_rows.append((x, y, z2, "clamped"))
        else:
            unresolved_xy.append((x, y, "direct_no_intersection"))

    if allow_interpolation and unresolved_xy and mapped:
        for x, y, reason in unresolved_xy:
            zi = _interpolate_z_from_neighbors(x, y, mapped, neighbor_count=6)
            if zi is None:
                missed_count += 1
                if collect_debug:
                    debug_rows.append((x, y, None, "missed:{0}".format(reason)))
                continue

            interpolated_count += 1
            mapped.append((x, y, zi))
            if collect_debug:
                debug_rows.append((x, y, zi, "interpolated:{0}".format(reason)))
    else:
        missed_count += len(unresolved_xy)
        if collect_debug:
            for x, y, reason in unresolved_xy:
                debug_rows.append((x, y, None, "missed:{0}".format(reason)))

    if clamped_count > 0:
        issues.append("{0} sample points were outside source footprint and were clamped to source boundary.".format(clamped_count))
    if interpolated_count > 0:
        issues.append("{0} sample points were interpolated from nearby mapped points.".format(interpolated_count))
    if missed_count > 0:
        issues.append("{0} sample points could not be resolved and were skipped.".format(missed_count))

    return mapped, clamped_count, interpolated_count, missed_count, debug_rows


def _get_editor(element):
    try:
        return element.SlabShapeEditor
    except Exception:
        return None


def _editor_vertex_count(editor):
    try:
        verts = editor.SlabShapeVertices
        return verts.Size if verts else 0
    except Exception:
        return 0


def _build_editor_vertex_xy_index(editor):
    """Map rounded XY keys to existing slab shape vertices."""
    index = {}
    try:
        verts = editor.SlabShapeVertices
    except Exception:
        verts = None

    if not verts:
        return index

    for vertex in verts:
        try:
            pos = vertex.Position
            if pos is None:
                continue
            key = _xy_key(pos.X, pos.Y)
            if key not in index:
                index[key] = vertex
        except Exception:
            continue

    return index


def _try_modify_existing_vertex(editor, vertex, target_xyz, target_offset=None):
    """Modify an existing slab shape vertex.

    Prefer absolute point writes first, then fall back to offset-based writes.
    Some hosts apply a base-plane shift when offset writes are used eagerly.
    """
    try:
        editor.ModifyPoint(vertex, target_xyz)
        return True
    except Exception:
        pass

    try:
        editor.ModifySubElement(vertex, target_xyz)
        return True
    except Exception:
        pass

    if target_offset is not None:
        try:
            editor.ModifySubElement(vertex, float(target_offset))
            return True
        except Exception:
            pass

    return False


def _list_editor_vertices(editor):
    vertices = []
    try:
        verts = editor.SlabShapeVertices
    except Exception:
        verts = None

    if not verts:
        return vertices

    for vertex in verts:
        try:
            pos = vertex.Position
            if pos is None:
                continue
            vertices.append((vertex, pos))
        except Exception:
            continue

    return vertices


def _is_boundary_vertex(vertex):
    if hasattr(vertex, "IsBoundary"):
        try:
            return bool(vertex.IsBoundary)
        except Exception:
            pass

    if hasattr(vertex, "VertexType"):
        try:
            vt = str(vertex.VertexType)
            if "Corner" in vt or "Edge" in vt or "Boundary" in vt:
                return True
            if "Interior" in vt or "Internal" in vt:
                return False
        except Exception:
            pass

    return None


def _list_editor_creases(editor):
    creases = []
    try:
        raw = editor.SlabShapeCreases
    except Exception:
        raw = None

    if not raw:
        return creases

    for crease in raw:
        creases.append(crease)
    return creases


def _is_boundary_crease(crease):
    if hasattr(crease, "IsBoundary"):
        try:
            return bool(crease.IsBoundary)
        except Exception:
            pass

    if hasattr(crease, "CreaseType"):
        try:
            text = str(crease.CreaseType)
            if "Boundary" in text:
                return True
        except Exception:
            pass

    return None


def _get_crease_endpoints(crease):
    # Try direct curve first.
    if hasattr(crease, "Curve"):
        try:
            c = crease.Curve
            if c is not None:
                return c.GetEndPoint(0), c.GetEndPoint(1)
        except Exception:
            pass

    # Fallback via vertices collection.
    if hasattr(crease, "Vertices"):
        try:
            verts = [v for v in crease.Vertices]
            if len(verts) >= 2:
                p0 = verts[0].Position if hasattr(verts[0], "Position") else None
                p1 = verts[1].Position if hasattr(verts[1], "Position") else None
                if p0 is not None and p1 is not None:
                    return p0, p1
        except Exception:
            pass

    return None, None


def _collect_destination_boundary_vertex_xys(destination_element):
    xys = []
    editor = _get_editor(destination_element)
    if editor is None:
        return xys

    seen = set()
    fallback_unknown = []
    for vertex, pos in _list_editor_vertices(editor):
        state = _is_boundary_vertex(vertex)
        if state is True:
            key = _xy_key(pos.X, pos.Y)
            if key in seen:
                continue
            seen.add(key)
            xys.append((pos.X, pos.Y))
        elif state is None:
            fallback_unknown.append((pos.X, pos.Y))

    # Some hosts do not classify boundary state reliably. Keep unknown-state
    # vertices as boundary candidates so corners are not lost.
    for x, y in fallback_unknown:
        key = _xy_key(x, y)
        if key in seen:
            continue
        seen.add(key)
        xys.append((x, y))

    return xys


def _collect_destination_vertex_xys(destination_element):
    xys = []
    editor = _get_editor(destination_element)
    if editor is None:
        return xys

    seen = set()
    for vertex, pos in _list_editor_vertices(editor):
        key = _xy_key(pos.X, pos.Y)
        if key in seen:
            continue
        seen.add(key)
        xys.append((pos.X, pos.Y))

    return xys


def _get_vertex_offset(vertex):
    if hasattr(vertex, "Offset"):
        try:
            return float(vertex.Offset)
        except Exception:
            pass
    return None


def _get_vertex_type_text(vertex):
    if hasattr(vertex, "VertexType"):
        try:
            return str(vertex.VertexType)
        except Exception:
            pass
    return "<unknown>"


def _is_corner_vertex(vertex):
    if not hasattr(vertex, "VertexType"):
        return False

    try:
        vt = vertex.VertexType
    except Exception:
        return False

    if SlabShapeVertexType is not None:
        try:
            if vt == SlabShapeVertexType.Corner:
                return True
        except Exception:
            pass

    try:
        return "Corner" in str(vt)
    except Exception:
        return False


def _collect_destination_vertex_rows(destination_element, destination_base_elev=None):
    """Return all destination slab-shape vertices after write.

    Each row: (index, x, y, z_abs, z_rel_top_plane, vertex_kind, offset, vertex_type)
    """
    rows = []
    editor = _get_editor(destination_element)
    if editor is None:
        return rows

    index = 1
    for vertex, pos in _list_editor_vertices(editor):
        state = _is_boundary_vertex(vertex)
        if state is True:
            kind = "boundary"
        elif state is False:
            kind = "internal"
        else:
            kind = "unknown"

        z_rel = None
        if destination_base_elev is not None:
            try:
                z_rel = float(pos.Z) - float(destination_base_elev)
            except Exception:
                z_rel = None

        rows.append((
            index,
            pos.X,
            pos.Y,
            pos.Z,
            z_rel,
            kind,
            _get_vertex_offset(vertex),
            _get_vertex_type_text(vertex),
        ))
        index += 1

    return rows


def _collect_destination_boundary_rows(doc, destination_element, destination_base_elev=None):
    """Return destination outer-boundary control points from top-face geometry.

    These are geometric boundary points (corners/segments), not slab-shape vertices.
    """
    issues = []
    rows = []
    top_face = get_top_face(doc, destination_element, issues, "Destination")
    if top_face is None:
        return rows

    boundary = _extract_outer_boundary_polyline(top_face, edge_spacing_ft=None)
    if len(boundary) >= 2:
        try:
            if boundary[0].DistanceTo(boundary[-1]) <= 1e-6:
                boundary = boundary[:-1]
        except Exception:
            pass

    seen = set()
    idx = 1
    for p in boundary:
        key = _xy_key(p.X, p.Y)
        if key in seen:
            continue
        seen.add(key)

        z_abs = None
        try:
            z_abs = _sample_height_on_faces([top_face], p.X, p.Y)
        except Exception:
            z_abs = None
        if z_abs is None:
            z_abs = p.Z

        z_rel = None
        if destination_base_elev is not None:
            try:
                z_rel = float(z_abs) - float(destination_base_elev)
            except Exception:
                z_rel = None

        rows.append((idx, p.X, p.Y, z_abs, z_rel))
        idx += 1

    return rows


def _find_nearest_vertex(vertices, x, y, tolerance_ft):
    best_vertex = None
    best_d2 = None
    tol2 = tolerance_ft * tolerance_ft

    for vertex, pos in vertices:
        dx = pos.X - x
        dy = pos.Y - y
        d2 = dx * dx + dy * dy
        if d2 > tol2:
            continue
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_vertex = vertex

    return best_vertex


def _try_modify_nearest_vertex(editor, x, y, target_xyz, target_offset, tolerance_ft):
    nearest_vertex = _find_nearest_vertex(_list_editor_vertices(editor), x, y, tolerance_ft)
    if nearest_vertex is None:
        return False
    return _try_modify_existing_vertex(editor, nearest_vertex, target_xyz, target_offset=target_offset)


def destination_has_shape_edits(element):
    """Return True when destination has existing slab shape vertices."""
    editor = _get_editor(element)
    if editor is None:
        return False
    return _editor_vertex_count(editor) > 0


def reset_destination_shape(element):
    """Enable and reset destination slab shape editor."""
    editor = _get_editor(element)
    if editor is None:
        raise Exception("Destination does not expose SlabShapeEditor.")

    try:
        editor.Enable()
    except Exception:
        pass

    editor.ResetSlabShape()
    return True


def _get_level_plus_offset_elevation(element):
    spec = _param_specs_for_element(element)
    if not spec:
        return None

    p_level, _ = _lookup_first_param(element, spec["level_bips"], spec["level_names"])
    p_offset, _ = _lookup_first_param(element, spec["offset_bips"], spec["offset_names"])
    if p_level is None or p_offset is None:
        return None

    try:
        level = element.Document.GetElement(p_level.AsElementId())
        if level is None:
            return None
        return level.Elevation + p_offset.AsDouble()
    except Exception:
        return None


def _nudge_xy_toward_centroid(points_xyz, nudge_ft):
    """Return XYZ points nudged slightly toward XY centroid.

    Revit can reject AddPoint when XY lies exactly on/near host boundary.
    """
    if not points_xyz:
        return []

    cx = sum(p[0] for p in points_xyz) / float(len(points_xyz))
    cy = sum(p[1] for p in points_xyz) / float(len(points_xyz))

    nudged = []
    for x, y, z in points_xyz:
        dx = cx - x
        dy = cy - y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist <= 1e-12:
            nudged.append((x, y, z))
            continue

        nx = x + (dx / dist) * nudge_ft
        ny = y + (dy / dist) * nudge_ft
        nudged.append((nx, ny, z))

    return nudged


def apply_shape_points(destination_element,
                       xyz_points,
                       issues,
                       z_mode="relative_level_offset",
                       skip_zero_offsets=True,
                       enable_boundary_nudge_retry=True,
                       enable_interior_ring_retry=True,
                       reset_existing=False,
                       source_top_faces=None,
                       source_boundaries=None,
                       vertex_resample_offset_ft=0.0,
                       modify_only_existing=False,
                       sampling_mode="hybrid"):
    editor = _get_editor(destination_element)
    if editor is None:
        raise Exception("Destination does not expose SlabShapeEditor.")

    destination_base_elev = None
    if z_mode == "relative_level_offset":
        destination_base_elev = _get_level_plus_offset_elevation(destination_element)
        if destination_base_elev is None:
            issues.append("Relative Level+Offset write mode requested but destination base elevation could not be resolved; absolute mode used.")
            z_mode = "absolute"

    try:
        editor.Enable()
    except Exception:
        # already enabled in many versions
        pass

    if reset_existing:
        try:
            if _editor_vertex_count(editor) > 0:
                editor.ResetSlabShape()
        except Exception as ex:
            issues.append("Could not reset existing destination slab shape: {0}".format(ex))

    # Capture original vertices once; these are the true host vertices/corners we
    # should prefer to modify instead of newly created retry points.
    initial_editor_vertices = _list_editor_vertices(editor)

    # Use the already-mapped targets as the single source of truth for writes.
    mapped_by_xy = {}
    for mx, my, mz in xyz_points:
        mapped_by_xy[_xy_key(mx, my)] = mz

    def _nearest_mapped_world_z(x, y, tolerance_ft):
        best_z = None
        best_d2 = None
        tol2 = tolerance_ft * tolerance_ft
        for px, py, pz in xyz_points:
            dx = px - x
            dy = py - y
            d2 = (dx * dx) + (dy * dy)
            if d2 <= tol2 and (best_d2 is None or d2 < best_d2):
                best_d2 = d2
                best_z = pz
        return best_z

    issues.append("Existing destination vertices will use mapped XY target matching for Z mapping.")

    def _build_targets(tx, ty, world_z):
        z_to_add_local = world_z
        if z_mode == "relative_level_offset" and destination_base_elev is not None:
            z_to_add_local = world_z - destination_base_elev

        target_z_abs_local = world_z
        target_xyz_local = XYZ(tx, ty, target_z_abs_local)
        return z_to_add_local, target_xyz_local

    def _build_add_xyz(tx, ty, world_z):
        # On some hosts, AddPoint/DrawPoint interpret Z as a shape offset
        # relative to the host base plane, not absolute world elevation.
        add_z = world_z
        if z_mode == "relative_level_offset" and destination_base_elev is not None:
            add_z = world_z - destination_base_elev
        return XYZ(tx, ty, add_z)

    def _try_snap_retry_points_to_original_xy(original_points, nudged_points):
        if not original_points or not nudged_points:
            return 0

        snapped = 0
        snap_tolerance = max(VERTEX_MATCH_TOLERANCE_FT, BOUNDARY_NUDGE_FT * 2.5)
        corner_tolerance = max(LOOSE_VERTEX_MATCH_TOLERANCE_FT, 1.0)

        for (ox, oy, oz), (nx, ny, _nz) in zip(original_points, nudged_points):
            z_to_add, target_xyz = _build_targets(ox, oy, oz)

            # First try to write the true pre-existing corner/edge vertex.
            nearest_initial = _find_nearest_vertex(initial_editor_vertices, ox, oy, corner_tolerance)
            if nearest_initial is not None and _try_modify_existing_vertex(editor, nearest_initial, target_xyz, target_offset=z_to_add):
                snapped += 1
                continue

            # Fallback to the nudged retry point if original vertex write fails.
            nearest_nudged = _find_nearest_vertex(_list_editor_vertices(editor), nx, ny, snap_tolerance)
            if nearest_nudged is None:
                continue
            if _try_modify_existing_vertex(editor, nearest_nudged, target_xyz, target_offset=z_to_add):
                snapped += 1

        return snapped

    def _repair_zero_relative_vertices_from_source():
        if z_mode != "relative_level_offset":
            return 0
        if destination_base_elev is None:
            return 0

        repaired = 0
        for vertex, pos in _list_editor_vertices(editor):
            try:
                rel = float(pos.Z) - float(destination_base_elev)
            except Exception:
                continue

            if abs(rel) > ZERO_OFFSET_TOLERANCE_FT:
                continue

            src_z = mapped_by_xy.get(_xy_key(pos.X, pos.Y))
            if src_z is None:
                src_z = _nearest_mapped_world_z(pos.X, pos.Y, max(VERTEX_MATCH_TOLERANCE_FT, LOOSE_VERTEX_MATCH_TOLERANCE_FT))
            if src_z is None:
                continue

            z_to_add, target_xyz = _build_targets(
                pos.X,
                pos.Y,
                src_z + (vertex_resample_offset_ft or 0.0),
            )
            if abs(z_to_add) <= ZERO_OFFSET_TOLERANCE_FT:
                continue

            if _try_modify_existing_vertex(editor, vertex, target_xyz, target_offset=z_to_add):
                repaired += 1

        return repaired

    def _apply_boundary_crease_offsets_from_source():
        # Disabled: direct crease resampling proved unstable on some hosts and
        # produced mixed elevations. Keep corner/vertex writes mapped-only.
        return 0, 0, 0

    def _apply_corner_vertices_from_source():
        # Some hosts expose corner vertices only after geometry regeneration.
        try:
            destination_element.Document.Regenerate()
        except Exception:
            pass

        updated = 0
        corner_candidates = 0
        corner_targets_resolved = 0
        for vertex, pos in _list_editor_vertices(editor):
            if not _is_corner_vertex(vertex):
                continue

            corner_candidates += 1

            src_z = mapped_by_xy.get(_xy_key(pos.X, pos.Y))
            if src_z is None:
                src_z = _nearest_mapped_world_z(pos.X, pos.Y, max(VERTEX_MATCH_TOLERANCE_FT, LOOSE_VERTEX_MATCH_TOLERANCE_FT))

            if src_z is None:
                continue

            corner_targets_resolved += 1
            z_to_add, target_xyz = _build_targets(
                pos.X,
                pos.Y,
                src_z + (vertex_resample_offset_ft or 0.0),
            )

            if _try_modify_existing_vertex(editor, vertex, target_xyz, target_offset=z_to_add):
                updated += 1

        return updated, corner_candidates, corner_targets_resolved

    def _add_points_once(enable_skip_zero, source_points):
        added_local = 0
        modified_local = 0
        failed_local = 0
        skipped_zero_local = 0
        failed_points_local = []
        modified_by_nearest_local = 0
        add_fail_reasons_local = []

        vertex_by_xy = _build_editor_vertex_xy_index(editor)
        editor_vertices = _list_editor_vertices(editor)

        seen = set()
        for x, y, z in source_points:
            key = _xy_key(x, y)
            if key in seen:
                continue
            seen.add(key)

            z_to_add, target_xyz = _build_targets(x, y, z)

            if enable_skip_zero and z_mode == "relative_level_offset" and abs(z_to_add) <= ZERO_OFFSET_TOLERANCE_FT:
                skipped_zero_local += 1
                continue

            existing_vertex = vertex_by_xy.get(key)
            if existing_vertex is not None:
                try:
                    vpos = existing_vertex.Position
                    if vpos is not None:
                        vz = mapped_by_xy.get(_xy_key(vpos.X, vpos.Y))
                        if vz is None:
                            vz = _nearest_mapped_world_z(vpos.X, vpos.Y, max(VERTEX_MATCH_TOLERANCE_FT, LOOSE_VERTEX_MATCH_TOLERANCE_FT))
                        if vz is not None:
                            z_to_add, target_xyz = _build_targets(vpos.X, vpos.Y, vz)
                except Exception:
                    pass

                if enable_skip_zero and z_mode == "relative_level_offset" and abs(z_to_add) <= ZERO_OFFSET_TOLERANCE_FT:
                    skipped_zero_local += 1
                    continue

                if _try_modify_existing_vertex(editor, existing_vertex, target_xyz, target_offset=z_to_add):
                    modified_local += 1
                    continue

            nearest_vertex = _find_nearest_vertex(editor_vertices, x, y, VERTEX_MATCH_TOLERANCE_FT)
            if nearest_vertex is not None:
                try:
                    npos = nearest_vertex.Position
                    if npos is not None:
                        nz = mapped_by_xy.get(_xy_key(npos.X, npos.Y))
                        if nz is None:
                            nz = _nearest_mapped_world_z(npos.X, npos.Y, max(VERTEX_MATCH_TOLERANCE_FT, LOOSE_VERTEX_MATCH_TOLERANCE_FT))
                        if nz is not None:
                            z_to_add, target_xyz = _build_targets(npos.X, npos.Y, nz)
                except Exception:
                    pass

                if enable_skip_zero and z_mode == "relative_level_offset" and abs(z_to_add) <= ZERO_OFFSET_TOLERANCE_FT:
                    skipped_zero_local += 1
                    continue

                if _try_modify_existing_vertex(editor, nearest_vertex, target_xyz, target_offset=z_to_add):
                    modified_local += 1
                    modified_by_nearest_local += 1
                    continue

            nearest_initial = _find_nearest_vertex(initial_editor_vertices, x, y, LOOSE_VERTEX_MATCH_TOLERANCE_FT)
            if nearest_initial is not None:
                if _try_modify_existing_vertex(editor, nearest_initial, target_xyz, target_offset=z_to_add):
                    modified_local += 1
                    modified_by_nearest_local += 1
                    continue

            if modify_only_existing:
                failed_local += 1
                failed_points_local.append((x, y, z))
                continue

            try:
                editor.AddPoint(_build_add_xyz(x, y, z))
                added_local += 1
            except Exception as ex_add:
                try:
                    editor.DrawPoint(_build_add_xyz(x, y, z))
                    added_local += 1
                    continue
                except Exception:
                    pass

                nearest_vertex = _find_nearest_vertex(editor_vertices, x, y, VERTEX_MATCH_TOLERANCE_FT)
                if nearest_vertex is not None and _try_modify_existing_vertex(editor, nearest_vertex, target_xyz, target_offset=z_to_add):
                    modified_local += 1
                    modified_by_nearest_local += 1
                elif nearest_initial is not None and _try_modify_existing_vertex(editor, nearest_initial, target_xyz, target_offset=z_to_add):
                    modified_local += 1
                    modified_by_nearest_local += 1
                elif _try_modify_nearest_vertex(
                    editor,
                    x,
                    y,
                    target_xyz,
                    z_to_add,
                    LOOSE_VERTEX_MATCH_TOLERANCE_FT,
                ):
                    modified_local += 1
                    modified_by_nearest_local += 1
                else:
                    failed_local += 1
                    failed_points_local.append((x, y, z))
                    if len(add_fail_reasons_local) < 8:
                        try:
                            add_fail_reasons_local.append(str(ex_add))
                        except Exception:
                            add_fail_reasons_local.append("<unreadable AddPoint exception>")

        return added_local, modified_local, failed_local, skipped_zero_local, failed_points_local, modified_by_nearest_local, add_fail_reasons_local

    added, modified, failed, skipped_zero, failed_points, modified_by_nearest, add_fail_reasons = _add_points_once(skip_zero_offsets, xyz_points)

    # Safety retry: if zero points were added and skip-zero was enabled, retry without skip.
    if added == 0 and skip_zero_offsets and z_mode == "relative_level_offset":
        issues.append("No points were added with skip-zero enabled; retrying once without zero-offset skip.")
        added, modified, failed, skipped_zero, failed_points, modified_by_nearest, add_fail_reasons = _add_points_once(False, xyz_points)

    nudged_retry_count = 0
    if enable_boundary_nudge_retry and failed_points:
        failed_before_nudge = list(failed_points)
        if added == 0:
            issues.append("No points were added; retrying with a small inward boundary nudge.")
        else:
            issues.append("Retrying failed destination points with a small inward boundary nudge.")
        nudged_points = _nudge_xy_toward_centroid(failed_before_nudge, BOUNDARY_NUDGE_FT)
        nudged_retry_count = len(nudged_points)
        add2, mod2, failed2, skipped2, failed_points2, nearest2, reasons2 = _add_points_once(False, nudged_points)
        added += add2
        modified += mod2
        skipped_zero += skipped2
        modified_by_nearest += nearest2
        failed_points = failed_points2
        failed = failed2
        if reasons2:
            remaining = max(0, 8 - len(add_fail_reasons))
            if remaining > 0:
                add_fail_reasons.extend(reasons2[:remaining])

        snapped_back = _try_snap_retry_points_to_original_xy(failed_before_nudge, nudged_points)
        if snapped_back > 0:
            modified += snapped_back
            issues.append("Boundary retry snap-back moved {0} points to original XY targets.".format(snapped_back))

    interior_ring_retry_count = 0
    if enable_interior_ring_retry and failed_points:
        if added == 0:
            issues.append("No points were added; retrying with an interior ring offset.")
        else:
            issues.append("Retrying remaining failed destination points with an interior ring offset.")
        seed_points = failed_points if failed_points else xyz_points
        ring_points = _nudge_xy_toward_centroid(seed_points, INTERIOR_RING_NUDGE_FT)
        interior_ring_retry_count = len(ring_points)
        add3, mod3, failed3, skipped3, failed_points3, nearest3, reasons3 = _add_points_once(False, ring_points)
        added += add3
        modified += mod3
        skipped_zero += skipped3
        modified_by_nearest += nearest3
        failed_points = failed_points3
        failed = failed3
        if reasons3:
            remaining = max(0, 8 - len(add_fail_reasons))
            if remaining > 0:
                add_fail_reasons.extend(reasons3[:remaining])

    repaired_zero_vertices = _repair_zero_relative_vertices_from_source()
    if repaired_zero_vertices > 0:
        modified += repaired_zero_vertices
        issues.append("Zero-relative destination vertices repaired from source sampling: {0}.".format(repaired_zero_vertices))

    # Ensure latest geometry state before crease/corner passes.
    try:
        destination_element.Document.Regenerate()
    except Exception:
        pass

    # Crease resampling is intentionally disabled because it can destabilize
    # edge elevations on certain host geometries.
    if sampling_mode in ("edge_only", "hybrid"):
        issues.append("Boundary crease resample pass is disabled for stability; using mapped vertex/corner writes only.")

    corner_updates, corner_candidates, corner_targets_resolved = _apply_corner_vertices_from_source()
    if corner_updates > 0:
        modified += corner_updates
        issues.append("Corner vertices updated from mapped targets: {0}.".format(corner_updates))
    elif corner_candidates > 0:
        issues.append(
            "Corner vertices detected but no corner write succeeded (candidates={0}, resolved_targets={1}).".format(
                corner_candidates,
                corner_targets_resolved,
            )
        )
    elif corner_candidates == 0:
        issues.append("No editable Corner-type slab-shape vertices were exposed by the destination host.")

    if failed > 0:
        issues.append("{0} destination shape points failed to add (likely invalid or duplicate placements).".format(failed))
    if modified > 0:
        issues.append("{0} existing destination vertices were updated.".format(modified))
    if modified_by_nearest > 0:
        issues.append("{0} destination points were matched to nearest existing vertices (tolerance {1:.3f} ft).".format(modified_by_nearest, VERTEX_MATCH_TOLERANCE_FT))
    if add_fail_reasons:
        issues.append("Sample AddPoint failures: {0}".format(" | ".join(add_fail_reasons)))
    if skipped_zero > 0:
        issues.append("{0} near-zero destination offsets were skipped.".format(skipped_zero))
    if nudged_retry_count > 0 and added > 0:
        issues.append("Boundary nudge retry used for {0} points.".format(nudged_retry_count))
    if interior_ring_retry_count > 0 and added > 0:
        issues.append("Interior ring retry used for {0} points.".format(interior_ring_retry_count))

    return added, modified, failed, skipped_zero, destination_base_elev, nudged_retry_count, interior_ring_retry_count


def _lookup_first_param(element, bip_list, name_fallbacks):
    for bip in bip_list:
        if bip is None:
            continue
        try:
            p = element.get_Parameter(bip)
            if p is not None:
                return p, "builtin"
        except Exception:
            continue

    for pname in name_fallbacks:
        try:
            p = element.LookupParameter(pname)
            if p is not None:
                return p, "name"
        except Exception:
            continue

    return None, None


def _param_specs_for_element(element):
    bic = _to_bic(element)

    if bic == BuiltInCategory.OST_Floors:
        return {
            "level_bips": [BuiltInParameter.LEVEL_PARAM],
            "offset_bips": [
                getattr(BuiltInParameter, "FLOOR_PARAM_HEIGHTABOVELEVEL_PARAM", None),
                getattr(BuiltInParameter, "FLOOR_HEIGHTABOVELEVEL_PARAM", None),
            ],
            "level_names": ["Level"],
            "offset_names": ["Height Offset From Level"],
        }

    if bic == BuiltInCategory.OST_Roofs:
        return {
            "level_bips": [getattr(BuiltInParameter, "ROOF_BASE_LEVEL_PARAM", None)],
            "offset_bips": [getattr(BuiltInParameter, "ROOF_LEVEL_OFFSET_PARAM", None)],
            "level_names": ["Base Level", "Level"],
            "offset_names": ["Base Offset From Level", "Height Offset From Level"],
        }

    if hasattr(BuiltInCategory, "OST_Toposolid") and bic == BuiltInCategory.OST_Toposolid:
        return {
            "level_bips": [BuiltInParameter.LEVEL_PARAM],
            "offset_bips": [getattr(BuiltInParameter, "TOPOSOLID_HEIGHTABOVELEVEL_PARAM", None)],
            "level_names": ["Level", "Base Level"],
            "offset_names": ["Height Offset From Level", "Base Offset From Level"],
        }

    return None


def align_level_and_offset(source_element, destination_element, issues):
    src_spec = _param_specs_for_element(source_element)
    dst_spec = _param_specs_for_element(destination_element)
    if not src_spec or not dst_spec:
        return False

    src_level_param, src_level_mode = _lookup_first_param(source_element, src_spec["level_bips"], src_spec["level_names"])
    src_offset_param, src_offset_mode = _lookup_first_param(source_element, src_spec["offset_bips"], src_spec["offset_names"])
    dst_level_param, dst_level_mode = _lookup_first_param(destination_element, dst_spec["level_bips"], dst_spec["level_names"])
    dst_offset_param, dst_offset_mode = _lookup_first_param(destination_element, dst_spec["offset_bips"], dst_spec["offset_names"])

    if src_level_param is None or src_offset_param is None:
        issues.append("Source level/offset parameters not found; alignment skipped.")
        return False
    if dst_level_param is None or dst_offset_param is None:
        issues.append("Destination level/offset parameters not found; alignment skipped.")
        return False

    if src_level_mode == "name" or src_offset_mode == "name" or dst_level_mode == "name" or dst_offset_mode == "name":
        issues.append("Level/offset alignment used locale-sensitive name fallback for one or more parameters.")

    if dst_level_param.IsReadOnly or dst_offset_param.IsReadOnly:
        issues.append("Destination level/offset parameters are read-only; alignment skipped.")
        return False

    try:
        dst_level_param.Set(src_level_param.AsElementId())
        dst_offset_param.Set(src_offset_param.AsDouble())
        return True
    except Exception as ex:
        issues.append("Destination level/offset alignment failed: {0}".format(ex))
        return False


def update_comments_from_source(doc, source_element, destination_element):
    src_type = doc.GetElement(source_element.GetTypeId())
    family_name = _cat_label(source_element)
    type_name = "<unknown type>"

    if src_type is not None:
        family_name = getattr(src_type, "FamilyName", family_name)
        type_name = getattr(src_type, "Name", type_name)

    text = "Source ID: {0}; {1} : {2}".format(
        source_element.Id.IntegerValue,
        family_name,
        type_name,
    )

    p = destination_element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and (not p.IsReadOnly):
        p.Set(text)
        return True

    p2 = destination_element.LookupParameter("Comments")
    if p2 is not None and (not p2.IsReadOnly):
        p2.Set(text)
        return True

    return False


def execute_shape_map(doc,
                      source_element,
                      destination_element,
                      grid_spacing_ft,
                      edge_spacing_ft,
                      point_offset_ft,
                      align_level_offset,
                      logger=None,
                      collect_debug=False,
                      z_mode="relative_level_offset",
                      skip_zero_offsets=True,
                      use_interior_grid=True,
                      sampling_mode="hybrid"):
    issues = []

    source_base_elev = _get_level_plus_offset_elevation(source_element)

    source_top_faces = get_top_faces(doc, source_element, issues, "Source")
    if not source_top_faces:
        raise Exception("Could not resolve source top face.")

    # Keep destination level/offset unchanged unless user explicitly requested
    # alignment. Corner handling is now performed via explicit vertex updates.

    destination_top = get_top_face(doc, destination_element, issues, "Destination")
    if destination_top is None:
        raise Exception("Could not resolve destination top face.")

    destination_editor = _get_editor(destination_element)
    destination_vertex_count_before = _editor_vertex_count(destination_editor) if destination_editor else 0

    _, seed_point_used = _ensure_destination_shape_editable(destination_element, issues)

    if sampling_mode == "edge_only":
        destination_vertex_xy = _collect_destination_boundary_vertex_xys(destination_element)
        if destination_vertex_xy:
            sample_xy = destination_vertex_xy
            destination_boundary = _extract_outer_boundary_polyline(destination_top, edge_spacing_ft=edge_spacing_ft)
            issues.append("Edge-only sampling used destination slab-shape boundary vertices.")
        else:
            sample_xy = None
            destination_boundary = None
    elif sampling_mode == "destination_vertices_only":
        destination_vertex_xy = _collect_destination_vertex_xys(destination_element)
        if destination_vertex_count_before <= 0 and len(destination_vertex_xy) <= 1:
            _bootstrap_destination_vertices_from_source(
                destination_element,
                destination_top,
                source_element,
                issues,
            )
            destination_vertex_xy = _collect_destination_vertex_xys(destination_element)

        if len(destination_vertex_xy) <= 1:
            raise Exception(
                "Destination Vertices Only mode could not establish destination shape vertices. "
                "Try running with Edge-only once on this destination, then rerun Destination Vertices Only."
            )
        if destination_vertex_xy:
            sample_xy = destination_vertex_xy
            destination_boundary = _extract_outer_boundary_polyline(destination_top, edge_spacing_ft=edge_spacing_ft)
            issues.append("Destination-vertex sampling used destination slab-shape vertices only.")
        else:
            sample_xy = None
            destination_boundary = None
    else:
        sample_xy = None
        destination_boundary = None

    source_boundaries = _extract_boundaries_from_faces(
        source_top_faces,
        edge_spacing_ft=edge_spacing_ft if edge_spacing_ft else DEFAULT_EDGE_SPACING_FT,
    )
    if not source_boundaries:
        raise Exception("Source top boundary could not be resolved.")

    injected_xy = _collect_source_vertex_xys(source_element, _extract_outer_boundary_polyline(destination_top))

    if sample_xy is None:
        sample_xy, destination_boundary = build_destination_sample_xy(
            destination_top,
            grid_spacing_ft,
            edge_spacing_ft,
            include_source_xy=injected_xy,
            use_interior_grid=use_interior_grid,
            sampling_mode=sampling_mode,
        )

    if (not sample_xy) and sampling_mode == "source_vertices_only":
        destination_vertex_xy = _collect_destination_boundary_vertex_xys(destination_element)
        if destination_vertex_xy:
            sample_xy = destination_vertex_xy
            issues.append("Source-vertex sampling fallback used: destination slab-shape vertices.")

    if not sample_xy and sampling_mode != "source_vertices_only":
        # Last-resort fallback for hosts where face-loop extraction is unreliable.
        bbox_boundary = _build_bbox_boundary_polyline(
            destination_element,
            edge_spacing_ft=edge_spacing_ft if edge_spacing_ft else DEFAULT_EDGE_SPACING_FT,
        )
        if bbox_boundary:
            issues.append("Destination sampling fallback used: element bounding box boundary.")
            sample_xy = []
            seen = set()
            for p in bbox_boundary:
                key = _xy_key(p.X, p.Y)
                if key in seen:
                    continue
                seen.add(key)
                sample_xy.append((p.X, p.Y))

    if not sample_xy:
        raise Exception("Destination sample point generation returned zero points.")

    min_probe = None
    max_probe = None
    for face in source_top_faces:
        lo, hi = _get_face_z_probe_bounds(face)
        if min_probe is None or lo < min_probe:
            min_probe = lo
        if max_probe is None or hi > max_probe:
            max_probe = hi
    if min_probe is None or max_probe is None:
        min_probe, max_probe = -VERTICAL_PROBE_HALF_HEIGHT_FT, VERTICAL_PROBE_HALF_HEIGHT_FT

    mapped_xyz, clamped_count, interpolated_count, missed_count, debug_rows = map_sample_xy_to_source_z(
        sample_xy,
        source_top_faces,
        source_boundaries,
        issues,
        collect_debug=collect_debug,
        allow_clamp=(sampling_mode not in ("source_vertices_only", "destination_vertices_only")),
        allow_interpolation=(sampling_mode not in ("source_vertices_only", "destination_vertices_only")),
    )

    if not mapped_xyz:
        raise Exception("No destination points could be mapped from source surface.")

    if point_offset_ft and abs(point_offset_ft) > 1e-12:
        mapped_xyz = [(x, y, z + point_offset_ft) for (x, y, z) in mapped_xyz]
        issues.append("Applied global point offset of {0:.6f} ft to all mapped points.".format(point_offset_ft))

    aligned = False
    if align_level_offset:
        aligned = align_level_and_offset(source_element, destination_element, issues)

    added, modified, failed, skipped_zero, destination_base_elev, nudged_retry_count, interior_ring_retry_count = apply_shape_points(
        destination_element,
        mapped_xyz,
        issues,
        z_mode=z_mode,
        skip_zero_offsets=skip_zero_offsets,
        enable_boundary_nudge_retry=(sampling_mode not in ("source_vertices_only", "destination_vertices_only")),
        enable_interior_ring_retry=(sampling_mode not in ("source_vertices_only", "destination_vertices_only")),
        reset_existing=False,
        source_top_faces=source_top_faces,
        source_boundaries=source_boundaries,
        vertex_resample_offset_ft=point_offset_ft,
        modify_only_existing=(sampling_mode == "destination_vertices_only"),
        sampling_mode=sampling_mode,
    )

    if (added + modified) <= 0:
        raise Exception(
            "No destination shape points were added. "
            "Operation canceled to avoid leaving a reset shape. "
            "Write stats: added={0}, modified={1}, failed={2}, skipped_zero={3}.".format(
                added,
                modified,
                failed,
                skipped_zero,
            )
        )

    comments_written = update_comments_from_source(doc, source_element, destination_element)

    if not comments_written:
        issues.append("Destination Comments parameter could not be set.")

    _delete_seed_vertex_if_present(destination_element, seed_point_used, issues)

    try:
        doc.Regenerate()
    except Exception:
        pass

    destination_vertex_rows = _collect_destination_vertex_rows(destination_element, destination_base_elev)
    destination_boundary_rows = _collect_destination_boundary_rows(doc, destination_element, destination_base_elev)
    destination_boundary_vertex_count = 0
    destination_internal_vertex_count = 0
    destination_unknown_vertex_count = 0
    for row in destination_vertex_rows:
        kind = row[5]
        if kind == "boundary":
            destination_boundary_vertex_count += 1
        elif kind == "internal":
            destination_internal_vertex_count += 1
        else:
            destination_unknown_vertex_count += 1

    summary = {
        "source_id": source_element.Id.IntegerValue,
        "destination_id": destination_element.Id.IntegerValue,
        "grid_spacing_ft": grid_spacing_ft,
        "sample_xy_count": len(sample_xy),
        "mapped_xyz_count": len(mapped_xyz),
        "points_added": added,
        "points_modified": modified,
        "points_failed": failed,
        "points_skipped_zero": skipped_zero,
        "boundary_nudged_retry_count": nudged_retry_count,
        "interior_ring_retry_count": interior_ring_retry_count,
        "clamped_count": clamped_count,
        "interpolated_count": interpolated_count,
        "missed_count": missed_count,
        "level_offset_aligned": aligned,
        "comments_written": comments_written,
        "issues": issues,
        "source_probe_z_lo": min_probe,
        "source_probe_z_hi": max_probe,
        "debug_rows": debug_rows,
        "destination_vertex_rows": destination_vertex_rows,
        "destination_vertex_count": len(destination_vertex_rows),
        "destination_boundary_vertex_count": destination_boundary_vertex_count,
        "destination_internal_vertex_count": destination_internal_vertex_count,
        "destination_unknown_vertex_count": destination_unknown_vertex_count,
        "destination_boundary_rows": destination_boundary_rows,
        "destination_boundary_row_count": len(destination_boundary_rows),
        "z_mode": z_mode,
        "source_base_elevation": source_base_elev,
        "destination_base_elevation": destination_base_elev,
        "skip_zero_offsets": skip_zero_offsets,
        "use_interior_grid": use_interior_grid,
        "sampling_mode": sampling_mode,
        "edge_spacing_ft": edge_spacing_ft,
        "point_offset_ft": point_offset_ft,
    }

    if logger is not None:
        try:
            logger.info(
                "Shape Map summary | src=%s dst=%s grid=%s sample=%s mapped=%s added=%s clamped=%s missed=%s aligned=%s",
                summary["source_id"],
                summary["destination_id"],
                summary["grid_spacing_ft"],
                summary["sample_xy_count"],
                summary["mapped_xyz_count"],
                summary["points_added"],
                summary["clamped_count"],
                summary["missed_count"],
                summary["level_offset_aligned"],
            )
        except Exception:
            pass

    return summary
