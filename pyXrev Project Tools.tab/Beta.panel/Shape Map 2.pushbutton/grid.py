# -*- coding: utf-8 -*-

import utils


def _poly_area(loop_xyz):
    if len(loop_xyz) < 3:
        return 0.0
    a = 0.0
    for i in range(len(loop_xyz) - 1):
        p0 = loop_xyz[i]
        p1 = loop_xyz[i + 1]
        a += (p0.X * p1.Y) - (p1.X * p0.Y)
    return a * 0.5


def _point_on_segment_2d(x, y, x0, y0, x1, y1, tol):
    dx = x1 - x0
    dy = y1 - y0
    seg2 = (dx * dx) + (dy * dy)
    if seg2 <= 1e-14:
        return ((x - x0) * (x - x0) + (y - y0) * (y - y0)) <= (tol * tol)

    t = ((x - x0) * dx + (y - y0) * dy) / seg2
    if t < 0.0 or t > 1.0:
        return False

    px = x0 + (dx * t)
    py = y0 + (dy * t)
    return ((x - px) * (x - px) + (y - py) * (y - py)) <= (tol * tol)


def _point_in_polygon_2d(x, y, loop_xyz, tol):
    inside = False
    n = len(loop_xyz)
    if n < 3:
        return False

    for i in range(n - 1):
        x0 = loop_xyz[i].X
        y0 = loop_xyz[i].Y
        x1 = loop_xyz[i + 1].X
        y1 = loop_xyz[i + 1].Y

        if _point_on_segment_2d(x, y, x0, y0, x1, y1, tol):
            return True

        y_between = ((y0 > y) != (y1 > y))
        if not y_between:
            continue

        xin = x0 + ((y - y0) * (x1 - x0) / (y1 - y0))
        if xin >= x:
            inside = not inside

    return inside


def _split_outer_holes(boundary_loops):
    if not boundary_loops:
        return None, []

    ordered = sorted(boundary_loops, key=lambda pts: abs(_poly_area(pts)), reverse=True)
    return ordered[0], ordered[1:]


def boundary_grid_points(boundary_loops, spacing_ft):
    if spacing_ft is None or spacing_ft <= 0.0:
        return []

    pts = []
    for loop in boundary_loops:
        for p in loop:
            pts.append((p.X, p.Y))
    return utils.dedupe_xy_points(pts)


def internal_grid_points(boundary_loops, spacing_ft):
    if spacing_ft is None or spacing_ft <= 0.0:
        return []

    outer, holes = _split_outer_holes(boundary_loops)
    if outer is None:
        return []

    xs = [p.X for p in outer]
    ys = [p.Y for p in outer]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    tol = utils.XY_TOLERANCE_FT
    x = min_x
    out = []
    while x <= max_x + tol:
        y = min_y
        while y <= max_y + tol:
            if _point_in_polygon_2d(x, y, outer, tol):
                blocked = False
                for hole in holes:
                    if _point_in_polygon_2d(x, y, hole, tol):
                        blocked = True
                        break
                if not blocked:
                    out.append((x, y))
            y += spacing_ft
        x += spacing_ft

    return utils.dedupe_xy_points(out)