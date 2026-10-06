# -*- coding: utf-8 -*-
__title__ = "Shape Offset"
__min_revit_ver__ = 2024
__version__ = 1.0
__beta__ = True
__doc__ = """Date    = 07.07.2026
_____________________________________________________________________
Description:
Offset existing shape-edited points on a Floor/Roof/Toposolid.
_____________________________________________________________________
How-To:
- Run tool
- Select destination element (Floor/Roof/Toposolid)
- Choose region (Boundary/Internal/Both)
- Choose mode (Add offset or Reset/Equalize)
- Enter offset in current document units
_____________________________________________________________________
Author: Xrev Team"""

from Autodesk.Revit.DB import (
    BuiltInParameter,
    BuiltInCategory,
    LabelUtils,
    SpecTypeId,
    UnitUtils,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms, revit, script as _pyscript

import traceback
from ui import ShapeOffsetWindow


uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
app = doc.Application
output = _pyscript.get_output()

REGION_BOUNDARY = 'Boundary'
REGION_INTERNAL = 'Internal'
REGION_BOTH = 'Both'

MODE_ADD = 'Add To Existing Values'
MODE_EQUALIZE = 'Reset And Equalize To Value'

_ENV_PREFIX = 'ShapeOffsetSession'
_ENV_REGION_KEY = '{}_region'.format(_ENV_PREFIX)
_ENV_MODE_KEY = '{}_mode'.format(_ENV_PREFIX)
_ENV_OFFSET_KEY = '{}_offset'.format(_ENV_PREFIX)


class ShapeHostSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        if element is None or element.Category is None:
            return False

        try:
            bic = element.Category.BuiltInCategory
        except Exception:
            return False

        if bic == BuiltInCategory.OST_Floors:
            return True
        if bic == BuiltInCategory.OST_Roofs:
            return True
        if hasattr(BuiltInCategory, 'OST_Toposolid') and bic == BuiltInCategory.OST_Toposolid:
            return True
        return False

    def AllowReference(self, reference, point):
        return False


def _ensure_supported_revit_version():
    try:
        major = int(app.VersionNumber)
    except Exception:
        major = 0

    if major < 2024:
        forms.alert('Shape Offset requires Revit 2024 or newer.', title=__title__, exitscript=True)


def _pick_element(prompt):
    pick_filter = ShapeHostSelectionFilter()
    with forms.WarningBar(title=prompt):
        ref = uidoc.Selection.PickObject(ObjectType.Element, pick_filter, prompt)
    return doc.GetElement(ref)


def _get_editor(element):
    try:
        return element.SlabShapeEditor
    except Exception:
        return None


def _is_editor_enabled(editor):
    if hasattr(editor, 'IsEnabled'):
        try:
            return bool(editor.IsEnabled)
        except Exception:
            return None
    return None


def _editor_vertex_count(editor):
    try:
        verts = editor.SlabShapeVertices
        return verts.Size if verts else 0
    except Exception:
        return 0


def _build_seed_points(element):
    bbox = None
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None

    if bbox is None:
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


def _try_add_seed_point(editor, element):
    seed_points = _build_seed_points(element)
    for idx, pt in enumerate(seed_points, 1):
        try:
            editor.AddPoint(pt)
            return True, 'seed_point_added #{} at ({:.6f}, {:.6f}, {:.6f})'.format(idx, pt.X, pt.Y, pt.Z)
        except Exception as ex:
            output.print_md(
                'Seed point #{} failed: {}  \n{}'.format(
                    idx,
                    str(ex),
                    traceback.format_exc().replace('\n', '  \n'),
                )
            )
    return False, 'no valid seed point could be added'


def _ensure_shape_points_enabled(editor, element):
    enabled_state = _is_editor_enabled(editor)
    if enabled_state is False:
        prompt = (
            'Shape points are not enabled on the selected element.\n\n'
            'Would you like to enable shape points and continue?'
        )
        if not forms.alert(prompt, title=__title__, yes=True, no=True):
            return False

    try:
        with revit.Transaction('Shape Offset: enable shape points'):
            try:
                editor.Enable()
            except Exception:
                pass

            enabled_after_enable = _is_editor_enabled(editor)
            if enabled_after_enable is True:
                return True

            if _editor_vertex_count(editor) > 0:
                return True

            # Some hosts only become shape-editable after first interior point is created.
            seeded, seed_note = _try_add_seed_point(editor, element)
            output.print_md('### Shape Offset Enable Path')
            output.print_md(seed_note)
            if seeded:
                return True
    except Exception as ex:
        details = 'Could not enable shape points:\n{}\n\n{}'.format(str(ex), traceback.format_exc())
        output.print_md('### Shape Offset Enable Failure')
        output.print_md(details.replace('\n', '  \n'))
        forms.alert(
            'Could not enable shape points on the selected element.\n'
            'See pyRevit output for traceback details.',
            title=__title__,
            exitscript=True,
        )
        return False

    enabled_final = _is_editor_enabled(editor)
    if enabled_final is True or _editor_vertex_count(editor) > 0:
        return True

    forms.alert(
        'Could not enable shape points on the selected element.\n'
        'See pyRevit output for seed-point diagnostics.',
        title=__title__,
        exitscript=True,
    )
    return False


def _to_py_list(net_collection):
    if net_collection is None:
        return []
    try:
        return [x for x in net_collection]
    except Exception:
        items = []
        try:
            count = net_collection.Size
            for i in range(count):
                items.append(net_collection[i])
        except Exception:
            pass
        return items


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
            unit_label = 'project units'

    return unit_id, unit_label


def _get_envvar(key, default_value):
    try:
        value = _pyscript.get_envvar(key)
        if value is None:
            return default_value
        return value
    except Exception:
        return default_value


def _set_envvar(key, value):
    try:
        _pyscript.set_envvar(key, '' if value is None else str(value))
    except Exception:
        pass


def _get_dialog_defaults():
    region = str(_get_envvar(_ENV_REGION_KEY, REGION_BOTH))
    mode = str(_get_envvar(_ENV_MODE_KEY, MODE_ADD))
    offset_text = str(_get_envvar(_ENV_OFFSET_KEY, '0'))

    if region not in (REGION_BOUNDARY, REGION_INTERNAL, REGION_BOTH):
        region = REGION_BOTH
    if mode not in (MODE_ADD, MODE_EQUALIZE):
        mode = MODE_ADD

    return {
        'region': region,
        'mode': mode,
        'offset_text': offset_text,
    }


def _save_dialog_defaults(options):
    _set_envvar(_ENV_REGION_KEY, options.get('region', REGION_BOTH))
    _set_envvar(_ENV_MODE_KEY, options.get('mode', MODE_ADD))
    _set_envvar(_ENV_OFFSET_KEY, options.get('offset_text', '0'))


def _ask_region_mode_and_offset(unit_label):
    defaults = _get_dialog_defaults()
    window = ShapeOffsetWindow(
        title=__title__,
        unit_label=unit_label,
        defaults=defaults,
    )

    if not window.ShowDialog() or window.result is None:
        return None

    options = window.result
    _save_dialog_defaults(options)

    try:
        offset_display = float(str(options['offset_text']).strip())
    except Exception:
        forms.alert('Offset value must be numeric.', title=__title__, exitscript=True)
        return None

    return {
        'region': options['region'],
        'mode': options['mode'],
        'offset_display': offset_display,
        'offset_text': str(options['offset_text']),
    }


def _is_boundary_vertex(vertex):
    # Primary API shape-vertex boundary check in modern Revit.
    if hasattr(vertex, 'IsBoundary'):
        try:
            return bool(vertex.IsBoundary)
        except Exception:
            pass

    # Fallback: infer from VertexType string when available.
    if hasattr(vertex, 'VertexType'):
        try:
            vt = str(vertex.VertexType)
            if 'Boundary' in vt:
                return True
            if 'Interior' in vt or 'Internal' in vt:
                return False
        except Exception:
            pass

    return None


def _get_vertex_offset(vertex):
    if hasattr(vertex, 'Offset'):
        try:
            return float(vertex.Offset)
        except Exception:
            pass
    return None


def _lookup_first_param(element, bip_list, name_fallbacks):
    for bip in bip_list:
        if bip is None:
            continue
        try:
            p = element.get_Parameter(bip)
            if p is not None:
                return p
        except Exception:
            continue

    for pname in name_fallbacks:
        try:
            p = element.LookupParameter(pname)
            if p is not None:
                return p
        except Exception:
            continue

    return None


def _param_specs_for_element(element):
    bic = None
    try:
        bic = element.Category.BuiltInCategory
    except Exception:
        return None

    if bic == BuiltInCategory.OST_Floors:
        return {
            'level_bips': [BuiltInParameter.LEVEL_PARAM],
            'offset_bips': [
                getattr(BuiltInParameter, 'FLOOR_PARAM_HEIGHTABOVELEVEL_PARAM', None),
                getattr(BuiltInParameter, 'FLOOR_HEIGHTABOVELEVEL_PARAM', None),
            ],
            'level_names': ['Level'],
            'offset_names': ['Height Offset From Level'],
        }

    if bic == BuiltInCategory.OST_Roofs:
        return {
            'level_bips': [getattr(BuiltInParameter, 'ROOF_BASE_LEVEL_PARAM', None)],
            'offset_bips': [getattr(BuiltInParameter, 'ROOF_LEVEL_OFFSET_PARAM', None)],
            'level_names': ['Base Level', 'Level'],
            'offset_names': ['Base Offset From Level', 'Height Offset From Level'],
        }

    if hasattr(BuiltInCategory, 'OST_Toposolid') and bic == BuiltInCategory.OST_Toposolid:
        return {
            'level_bips': [BuiltInParameter.LEVEL_PARAM],
            'offset_bips': [getattr(BuiltInParameter, 'TOPOSOLID_HEIGHTABOVELEVEL_PARAM', None)],
            'level_names': ['Level', 'Base Level'],
            'offset_names': ['Height Offset From Level', 'Base Offset From Level'],
        }

    return None


def _get_host_base_elevation(element):
    spec = _param_specs_for_element(element)
    if not spec:
        return None

    p_level = _lookup_first_param(element, spec['level_bips'], spec['level_names'])
    p_offset = _lookup_first_param(element, spec['offset_bips'], spec['offset_names'])
    if p_level is None or p_offset is None:
        return None

    try:
        level = element.Document.GetElement(p_level.AsElementId())
        if level is None:
            return None
        return level.Elevation + p_offset.AsDouble()
    except Exception:
        return None


def _format_exception_details(ex):
    lines = []

    try:
        lines.append('Exception type: {}'.format(type(ex)))
    except Exception:
        pass

    try:
        lines.append('Exception string: {}'.format(str(ex)))
    except Exception:
        pass

    try:
        lines.append('Exception repr: {}'.format(repr(ex)))
    except Exception:
        pass

    try:
        tb_text = traceback.format_exc()
        if tb_text and tb_text.strip() and tb_text.strip() != 'NoneType: None':
            lines.append('Traceback:\n{}'.format(tb_text))
    except Exception:
        pass

    if not lines:
        return 'No exception details were captured.'

    return '\n\n'.join(lines)


def _describe_vertex(vertex, index):
    parts = ['index={}'.format(index)]

    boundary_state = _is_boundary_vertex(vertex)
    if boundary_state is True:
        parts.append('boundary=True')
    elif boundary_state is False:
        parts.append('boundary=False')
    else:
        parts.append('boundary=Unknown')

    current_offset = _get_vertex_offset(vertex)
    if current_offset is None:
        parts.append('current_offset=<unreadable>')
    else:
        parts.append('current_offset={:.6f}'.format(current_offset))

    if hasattr(vertex, 'Position'):
        try:
            p = vertex.Position
            parts.append('xyz=({:.6f}, {:.6f}, {:.6f})'.format(p.X, p.Y, p.Z))
        except Exception:
            pass

    return ', '.join(parts)


def _print_debug_rows(debug_rows):
    if not debug_rows:
        return

    output.print_md('### Shape Offset Debug Details')
    output.print_md('Showing first 200 rows.')
    for idx, row in enumerate(debug_rows[:200], 1):
        output.print_md('{}. {}'.format(idx, row.replace('\n', '  \n')))


def _filter_vertices(vertices, region):
    selected = []
    unknown_class_count = 0
    unknown_vertices = []
    fallback_used = False

    for vertex in vertices:
        boundary_state = _is_boundary_vertex(vertex)
        if boundary_state is None:
            unknown_class_count += 1
            unknown_vertices.append(vertex)

        if region == REGION_BOTH:
            selected.append(vertex)
        elif region == REGION_BOUNDARY:
            if boundary_state is True:
                selected.append(vertex)
        elif region == REGION_INTERNAL:
            if boundary_state is False or boundary_state is None:
                selected.append(vertex)

    if region == REGION_BOUNDARY and not selected and unknown_vertices:
        # Revit API on some hosts does not expose boundary classification; fallback to all unknowns.
        selected = list(unknown_vertices)
        fallback_used = True

    return selected, unknown_class_count, fallback_used


def _apply_offset(editor, vertices, mode, offset_internal, host_base_elevation):
    changed = 0
    skipped = 0
    debug_rows = []

    for index, vertex in enumerate(vertices, 1):
        vertex_label = _describe_vertex(vertex, index)
        target_offset = None

        try:
            if mode == MODE_EQUALIZE:
                target_offset = offset_internal
            else:
                current_source = 'vertex.Offset'
                current_offset = _get_vertex_offset(vertex)

                if current_offset is None and host_base_elevation is not None and hasattr(vertex, 'Position'):
                    try:
                        current_offset = float(vertex.Position.Z) - float(host_base_elevation)
                        current_source = 'derived_from_vertex_z'
                    except Exception:
                        current_offset = None

                if current_offset is None:
                    skipped += 1
                    debug_rows.append(
                        'SKIP | mode=Add | reason=current offset unreadable | {}'.format(vertex_label)
                    )
                    continue
                target_offset = current_offset + offset_internal
                debug_rows.append(
                    'INFO | mode=Add | current_source={} | current_offset={:.6f} | target_offset={:.6f} | {}'.format(
                        current_source,
                        current_offset,
                        target_offset,
                        vertex_label,
                    )
                )

            editor.ModifySubElement(vertex, target_offset)
            changed += 1
        except Exception as ex:
            skipped += 1
            debug_rows.append(
                'FAIL | mode={} | target_offset={} | {}\n{}'.format(
                    mode,
                    '<unset>' if target_offset is None else '{:.6f}'.format(target_offset),
                    vertex_label,
                    _format_exception_details(ex),
                )
            )

    return changed, skipped, debug_rows


def main():
    _ensure_supported_revit_version()

    try:
        destination = _pick_element('Select element to offset shape points')
    except OperationCanceledException:
        return
    except Exception:
        return

    editor = _get_editor(destination)
    if editor is None:
        forms.alert('Selected element does not expose SlabShapeEditor.', title=__title__, exitscript=True)

    if not _ensure_shape_points_enabled(editor, destination):
        return

    vertices = _to_py_list(editor.SlabShapeVertices)
    if not vertices:
        forms.alert('Selected element has no existing shape-edited points.', title=__title__, exitscript=True)

    unit_id, unit_label = _get_length_unit_info(doc)
    options = _ask_region_mode_and_offset(unit_label)
    if options is None:
        return

    offset_internal = UnitUtils.ConvertToInternalUnits(options['offset_display'], unit_id)
    host_base_elevation = _get_host_base_elevation(destination)
    target_vertices, unknown_count, boundary_fallback_used = _filter_vertices(vertices, options['region'])

    if not target_vertices:
        forms.alert('No shape points matched the selected region filter.', title=__title__, exitscript=True)

    with revit.Transaction('Shape Offset: apply'):
        changed, skipped, debug_rows = _apply_offset(
            editor=editor,
            vertices=target_vertices,
            mode=options['mode'],
            offset_internal=offset_internal,
            host_base_elevation=host_base_elevation,
        )

    _print_debug_rows(debug_rows)

    summary = []
    summary.append('Shape Offset completed.')
    summary.append('Element ID: {}'.format(destination.Id.IntegerValue))
    summary.append('Region: {}'.format(options['region']))
    summary.append('Mode: {}'.format(options['mode']))
    summary.append('Offset ({0}): {1:.6f}'.format(unit_label, options['offset_display']))
    summary.append('Candidate points: {}'.format(len(target_vertices)))
    summary.append('Points changed: {}'.format(changed))
    summary.append('Points skipped: {}'.format(skipped))
    summary.append('Debug rows: {}'.format(len(debug_rows)))
    if host_base_elevation is not None:
        summary.append('Host base elevation (ft): {:.6f}'.format(host_base_elevation))
    else:
        summary.append('Host base elevation (ft): <unavailable>')

    if unknown_count > 0:
        summary.append('Unclassified vertices encountered: {}'.format(unknown_count))

    if boundary_fallback_used:
        summary.append('Boundary filter fallback used: API did not classify boundary vertices; unknown vertices were treated as boundary.')

    if debug_rows:
        summary.append('See pyRevit output for traceback diagnostics.')

    forms.alert('\n'.join(summary), title=__title__)


if __name__ == '__main__':
    main()
