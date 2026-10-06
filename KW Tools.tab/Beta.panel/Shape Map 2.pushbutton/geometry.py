# -*- coding: utf-8 -*-

import math

from pyrevit import DB

import utils


def _iter_solids(element):
    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = False

    geom = element.get_Geometry(options)
    if geom is None:
        return

    for gobj in geom:
        if isinstance(gobj, DB.Solid) and gobj.Faces and gobj.Faces.Size > 0:
            yield gobj
            continue

        if isinstance(gobj, DB.GeometryInstance):
            inst = gobj.GetInstanceGeometry()
            if inst is None:
                continue
            for iobj in inst:
                if isinstance(iobj, DB.Solid) and iobj.Faces and iobj.Faces.Size > 0:
                    yield iobj


def _face_normal_z(face):
    try:
        bb = face.GetBoundingBox()
        uv = DB.UV((bb.Min.U + bb.Max.U) * 0.5, (bb.Min.V + bb.Max.V) * 0.5)
        n = face.ComputeNormal(uv)
        return n.Z
    except Exception:
        return -1.0


def _highest_face_from_geometry(element):
    best = None
    best_score = None

    for solid in _iter_solids(element):
        for face in solid.Faces:
            nz = _face_normal_z(face)
            if nz <= 0.01:
                continue

            try:
                area = float(face.Area)
            except Exception:
                area = 0.0

            try:
                bb = face.GetBoundingBox()
                z_guess = face.Evaluate(DB.UV((bb.Min.U + bb.Max.U) * 0.5, (bb.Min.V + bb.Max.V) * 0.5)).Z
            except Exception:
                z_guess = -1e9

            score = (z_guess, area)
            if best is None or score > best_score:
                best = face
                best_score = score

    return best


def _bottom_faces_for_ceiling(element):
    faces = []
    try:
        refs = DB.HostObjectUtils.GetBottomFaces(element)
        for ref in refs:
            try:
                f = element.GetGeometryObjectFromReference(ref)
                if isinstance(f, DB.Face):
                    faces.append(f)
            except Exception:
                continue
    except Exception:
        pass
    return faces


def _top_faces_for_host(element):
    faces = []
    try:
        refs = DB.HostObjectUtils.GetTopFaces(element)
        for ref in refs:
            try:
                f = element.GetGeometryObjectFromReference(ref)
                if isinstance(f, DB.Face):
                    faces.append(f)
            except Exception:
                continue
    except Exception:
        pass
    return faces


def get_source_faces(source, issues):
    bic = None
    try:
        bic = source.Category.BuiltInCategory
    except Exception:
        bic = None

    if bic == DB.BuiltInCategory.OST_Ceilings:
        faces = _bottom_faces_for_ceiling(source)
        if faces:
            return faces

    if bic == DB.BuiltInCategory.OST_Floors:
        faces = _top_faces_for_host(source)
        if faces:
            return faces

    if bic == DB.BuiltInCategory.OST_Roofs:
        faces = _top_faces_for_host(source)
        if faces:
            return faces

    if hasattr(DB.BuiltInCategory, "OST_Toposolid") and bic == DB.BuiltInCategory.OST_Toposolid:
        top_faces = []
        for solid in _iter_solids(source):
            for face in solid.Faces:
                if _face_normal_z(face) > 0.01:
                    top_faces.append(face)
        if top_faces:
            return top_faces

    fallback = _highest_face_from_geometry(source)
    if fallback is not None:
        issues.append("Source top face resolved by geometry fallback.")
        return [fallback]

    return []


def _sample_curve_points(curve, spacing_ft):
    try:
        if spacing_ft is None or spacing_ft <= 0.0:
            return list(curve.Tessellate())
    except Exception:
        pass

    max_len = max(float(spacing_ft), 1e-6)

    if isinstance(curve, DB.Arc):
        try:
            arc_angle = abs(curve.Angle)
            arc_len = curve.Length
            n_len = int(math.ceil(arc_len / max_len)) if arc_len > 1e-9 else 1
            n_ang = int(math.ceil(arc_angle / math.radians(5.0))) if arc_angle > 1e-9 else 1
            n = max(1, n_len, n_ang)

            p0 = curve.GetEndParameter(0)
            p1 = curve.GetEndParameter(1)
            pts = []
            for i in range(n + 1):
                t = float(i) / float(n)
                pts.append(curve.Evaluate(p0 + ((p1 - p0) * t), False))
            return pts
        except Exception:
            pass

    try:
        raw = list(curve.Tessellate())
    except Exception:
        raw = []

    if len(raw) < 2:
        return raw

    dense = []
    for i in range(len(raw) - 1):
        p0 = raw[i]
        p1 = raw[i + 1]
        dense.append(p0)
        seg_len = p0.DistanceTo(p1)
        if seg_len <= max_len:
            continue
        seg_count = int(math.ceil(seg_len / max_len))
        for j in range(1, seg_count):
            t = float(j) / float(seg_count)
            dense.append(DB.XYZ(p0.X + (p1.X - p0.X) * t, p0.Y + (p1.Y - p0.Y) * t, p0.Z + (p1.Z - p0.Z) * t))
    dense.append(raw[-1])
    return dense


def extract_boundary_loops(faces, spacing_ft):
    loops_xyz = []
    for face in faces:
        try:
            cloops = face.GetEdgesAsCurveLoops()
        except Exception:
            cloops = None
        if cloops is None:
            continue

        for cloop in cloops:
            points = []
            for curve in cloop:
                seg = _sample_curve_points(curve, spacing_ft)
                if not seg:
                    continue
                if not points:
                    points.extend(seg)
                else:
                    points.extend(seg[1:])

            if len(points) < 3:
                continue

            if points[0].DistanceTo(points[-1]) > 1e-7:
                points.append(points[0])
            loops_xyz.append(points)

    return loops_xyz


def _vertex_type_text(vertex):
    try:
        return str(vertex.VertexType)
    except Exception:
        return ""


def _split_vertices(vertices):
    boundary_pts = []
    internal_pts = []
    all_pts = []

    for vertex in vertices:
        pt = utils.get_point_from_vertex(vertex)
        if pt is None:
            continue
        all_pts.append(pt)
        vtype = _vertex_type_text(vertex).lower()
        if "bound" in vtype:
            boundary_pts.append(pt)
        elif "inter" in vtype:
            internal_pts.append(pt)

    if not boundary_pts and all_pts:
        boundary_pts = list(all_pts)
    return all_pts, boundary_pts, internal_pts


def source_shape_points(source, include_vertex, include_boundary, include_internal):
    vertices = utils.get_shape_vertices(source)
    all_pts, boundary_pts, internal_pts = _split_vertices(vertices)

    out = []
    if include_vertex:
        for p in all_pts:
            out.append((p.X, p.Y))
    if include_boundary:
        for p in boundary_pts:
            out.append((p.X, p.Y))
    if include_internal:
        for p in internal_pts:
            out.append((p.X, p.Y))
    return utils.dedupe_xy_points(out)


def source_has_shape_edits(source):
    vertices = utils.get_shape_vertices(source)
    return len(vertices) > 0


def destination_vertices(destination):
    vertices = utils.get_shape_vertices(destination)
    out = []
    for v in vertices:
        p = utils.get_point_from_vertex(v)
        if p is None:
            continue
        out.append(v)
    return out