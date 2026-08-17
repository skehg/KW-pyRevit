# -*- coding: utf-8 -*-

import clr

from pyrevit import DB


def _face_z_bounds(face):
    try:
        bb = face.GetBoundingBox()
    except Exception:
        return -500.0, 500.0

    try:
        corners = [
            DB.UV(bb.Min.U, bb.Min.V),
            DB.UV(bb.Max.U, bb.Min.V),
            DB.UV(bb.Max.U, bb.Max.V),
            DB.UV(bb.Min.U, bb.Max.V),
        ]
        zs = [face.Evaluate(uv).Z for uv in corners]
    except Exception:
        zs = [0.0]

    z_min = min(zs)
    z_max = max(zs)
    if z_max - z_min < 1.0:
        z_min -= 100.0
        z_max += 100.0
    return z_min, z_max


def _intersect_face_with_line(face, line):
    results_ref = clr.Reference[DB.IntersectionResultArray]()
    try:
        outcome = face.Intersect(line, results_ref)
    except Exception:
        return []

    if outcome != DB.SetComparisonResult.Overlap:
        return []

    ira = results_ref.Value
    if ira is None or ira.Size == 0:
        return []

    hits = []
    for i in range(ira.Size):
        try:
            hits.append(ira.get_Item(i).XYZPoint)
        except Exception:
            continue
    return hits


def _intersections_for_faces(x, y, faces, z0, z1):
    p0 = DB.XYZ(x, y, z0)
    p1 = DB.XYZ(x, y, z1)
    line = DB.Line.CreateBound(p0, p1)

    hits = []
    for face in faces:
        pts = _intersect_face_with_line(face, line)
        for pt in pts:
            hits.append(pt.Z)
    return hits


def vertical_intersection_z(x, y, faces):
    if not faces:
        return None

    zmins = []
    zmaxs = []
    for face in faces:
        z_min, z_max = _face_z_bounds(face)
        zmins.append(z_min)
        zmaxs.append(z_max)

    global_min = min(zmins) - 500.0
    global_max = max(zmaxs) + 500.0

    # Downward ray first.
    down_hits = _intersections_for_faces(x, y, faces, global_max, global_min)
    if down_hits:
        return max(down_hits)

    # Upward fallback.
    up_hits = _intersections_for_faces(x, y, faces, global_min, global_max)
    if up_hits:
        return min(up_hits)

    return None