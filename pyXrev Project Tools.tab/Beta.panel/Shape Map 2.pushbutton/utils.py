# -*- coding: utf-8 -*-

from pyrevit import DB


XY_TOLERANCE_FT = 0.0001
MM_UNIT_ID = DB.UnitTypeId.Millimeters


def _to_bic(element):
    try:
        return element.Category.BuiltInCategory
    except Exception:
        return None


def is_supported_host(element):
    bic = _to_bic(element)
    if bic is None:
        return False

    if bic == DB.BuiltInCategory.OST_Floors:
        return True
    if bic == DB.BuiltInCategory.OST_Roofs:
        return True
    if hasattr(DB.BuiltInCategory, "OST_Ceilings") and bic == DB.BuiltInCategory.OST_Ceilings:
        return True
    if hasattr(DB.BuiltInCategory, "OST_Toposolid") and bic == DB.BuiltInCategory.OST_Toposolid:
        return True
    return False


def mm_to_internal(mm_value):
    return DB.UnitUtils.ConvertToInternalUnits(float(mm_value), MM_UNIT_ID)


def _round_key_xy(x, y):
    # 0.0001 ft tolerance-based keying.
    return (int(round(float(x) / XY_TOLERANCE_FT)), int(round(float(y) / XY_TOLERANCE_FT)))


def dedupe_xy_points(xy_points):
    seen = set()
    out = []
    for x, y in xy_points:
        key = _round_key_xy(x, y)
        if key in seen:
            continue
        seen.add(key)
        out.append((x, y))
    return out


def xy_matches(p1, p2, tol_ft=None):
    tol = XY_TOLERANCE_FT if tol_ft is None else float(tol_ft)
    return abs(p1.X - p2.X) <= tol and abs(p1.Y - p2.Y) <= tol


def get_shape_editor(host_element):
    editor = None

    try:
        editor = host_element.GetSlabShapeEditor()
        if editor:
            return editor
    except Exception:
        pass

    try:
        editor = host_element.SlabShapeEditor
        if editor:
            return editor
    except Exception:
        pass

    return None


def get_shape_vertices(host_element):
    editor = get_shape_editor(host_element)
    if editor is None:
        return []

    try:
        return [v for v in editor.SlabShapeVertices]
    except Exception:
        return []


def get_point_from_vertex(vertex):
    try:
        return vertex.Position
    except Exception:
        return None


def get_element_type(host_doc, element):
    try:
        return host_doc.GetElement(element.GetTypeId())
    except Exception:
        return None


def get_source_identity_label(host_doc, element):
    et = get_element_type(host_doc, element)
    fam = "<unknown family>"
    typ = "<unknown type>"

    if et is not None:
        try:
            fam = et.FamilyName
        except Exception:
            pass
        try:
            typ = et.Name
        except Exception:
            pass

    return "{0} : {1} : {2}".format(element.Id.IntegerValue, fam, typ)


def append_destination_comment(host_doc, destination, source):
    text = "ShapeEditMappedFrom: {0}".format(get_source_identity_label(host_doc, source))

    param = None
    try:
        param = destination.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    except Exception:
        param = None

    if param is None or param.IsReadOnly:
        return False

    try:
        existing = param.AsString() or ""
    except Exception:
        existing = ""

    if text in existing:
        return True

    new_text = text if not existing else "{0}\n{text}".format(existing, text=text)
    try:
        param.Set(new_text)
        return True
    except Exception:
        return False


def _param_specs_for_element(element):
    bic = _to_bic(element)

    if bic == DB.BuiltInCategory.OST_Floors:
        return {
            "level_bips": [DB.BuiltInParameter.LEVEL_PARAM],
            "offset_bips": [
                getattr(DB.BuiltInParameter, "FLOOR_PARAM_HEIGHTABOVELEVEL_PARAM", None),
                getattr(DB.BuiltInParameter, "FLOOR_HEIGHTABOVELEVEL_PARAM", None),
            ],
            "level_names": ["Level"],
            "offset_names": ["Height Offset From Level"],
        }

    if bic == DB.BuiltInCategory.OST_Roofs:
        return {
            "level_bips": [getattr(DB.BuiltInParameter, "ROOF_BASE_LEVEL_PARAM", None)],
            "offset_bips": [getattr(DB.BuiltInParameter, "ROOF_LEVEL_OFFSET_PARAM", None)],
            "level_names": ["Base Level", "Level"],
            "offset_names": ["Base Offset From Level", "Height Offset From Level"],
        }

    if hasattr(DB.BuiltInCategory, "OST_Ceilings") and bic == DB.BuiltInCategory.OST_Ceilings:
        return {
            "level_bips": [DB.BuiltInParameter.LEVEL_PARAM],
            "offset_bips": [getattr(DB.BuiltInParameter, "CEILING_HEIGHTABOVELEVEL_PARAM", None)],
            "level_names": ["Level"],
            "offset_names": ["Height Offset From Level"],
        }

    if hasattr(DB.BuiltInCategory, "OST_Toposolid") and bic == DB.BuiltInCategory.OST_Toposolid:
        return {
            "level_bips": [DB.BuiltInParameter.LEVEL_PARAM],
            "offset_bips": [
                getattr(DB.BuiltInParameter, "TOPOSOLID_HEIGHTABOVELEVEL_PARAM", None),
                getattr(DB.BuiltInParameter, "TOPOSOLID_HEIGHT_OFFSET_PARAM", None),
            ],
            "level_names": ["Level", "Base Level"],
            "offset_names": ["Height Offset From Level", "Base Offset From Level"],
        }

    return None


def _lookup_first_param(element, builtins, name_fallbacks):
    for bip in builtins:
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


def get_level_and_offset_params(element):
    spec = _param_specs_for_element(element)
    if not spec:
        return None, None, None

    level_param, level_mode = _lookup_first_param(element, spec["level_bips"], spec["level_names"])
    offset_param, offset_mode = _lookup_first_param(element, spec["offset_bips"], spec["offset_names"])
    mode = "builtin"
    if level_mode == "name" or offset_mode == "name":
        mode = "name"
    return level_param, offset_param, mode


def get_level_plus_offset(host_doc, element):
    level_param, offset_param, _mode = get_level_and_offset_params(element)
    if level_param is None or offset_param is None:
        return 0.0

    level_elevation = 0.0
    try:
        level_id = level_param.AsElementId()
        if level_id and level_id != DB.ElementId.InvalidElementId:
            level = host_doc.GetElement(level_id)
            if level is not None:
                level_elevation = float(level.Elevation)
    except Exception:
        level_elevation = 0.0

    offset_value = 0.0
    try:
        offset_value = float(offset_param.AsDouble())
    except Exception:
        offset_value = 0.0

    return level_elevation + offset_value


def align_level_and_offset(host_doc, source, destination, issues):
    src_level_param, src_offset_param, src_mode = get_level_and_offset_params(source)
    dst_level_param, dst_offset_param, dst_mode = get_level_and_offset_params(destination)

    if src_level_param is None or src_offset_param is None:
        issues.append("Source level/offset parameters not found; alignment skipped.")
        return False

    if dst_level_param is None or dst_offset_param is None:
        issues.append("Destination level/offset parameters not found; alignment skipped.")
        return False

    if src_mode == "name" or dst_mode == "name":
        issues.append("Level/offset alignment used locale-sensitive parameter name fallback.")

    if dst_level_param.IsReadOnly or dst_offset_param.IsReadOnly:
        issues.append("Destination level/offset parameters are read-only; alignment skipped.")
        return False

    try:
        dst_level_param.Set(src_level_param.AsElementId())
        dst_offset_param.Set(src_offset_param.AsDouble())
        return True
    except Exception as ex:
        issues.append("Destination level/offset alignment failed: {0}".format(str(ex)))
        return False


def compute_level_delta(host_doc, source, destination, enabled):
    if not enabled:
        return 0.0

    src = get_level_plus_offset(host_doc, source)
    dst = get_level_plus_offset(host_doc, destination)
    return src - dst