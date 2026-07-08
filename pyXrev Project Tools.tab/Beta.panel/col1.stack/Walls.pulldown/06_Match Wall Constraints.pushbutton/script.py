# -*- coding: utf-8 -*-

__title__ = "Wall Match: Constraints"
__min_revit_ver__ = 2021
__author__ = "Xrev Team"
__doc__ = """Version = 1.0
Date    = 07.07.2026
_____________________________________________________________________
Description:

Match wall constraints from one source wall to picked destination walls.
Supports preset mappings for top and/or bottom transfers,
destination offset, and optional base/top level overrides.
_____________________________________________________________________
How-to:

-> Run the script
-> Configure mapping/offset/overrides
-> Select source wall
-> Select destination wall(s), ESC to finish
_____________________________________________________________________
"""

from pyrevit import forms, revit, script as _pyscript
from Autodesk.Revit.DB import BuiltInParameter, FilteredElementCollector, Level, UnitUtils
from Autodesk.Revit.Exceptions import OperationCanceledException
from Snippets._selection import pick_wall
from ui import MatchConstraintsWindow


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

_ENV_PREFIX = 'WallMatchConstraints'
_ENV_ENABLE_MAPPING_KEY = '{}_enable_mapping'.format(_ENV_PREFIX)
_ENV_PRESET_KEY = '{}_preset'.format(_ENV_PREFIX)
_ENV_MATCH_OFFSET_KEY = '{}_match_offset'.format(_ENV_PREFIX)
_ENV_OVERRIDE_BASE_KEY = '{}_override_base'.format(_ENV_PREFIX)
_ENV_OVERRIDE_TOP_KEY = '{}_override_top'.format(_ENV_PREFIX)
_ENV_BASE_LEVEL_KEY = '{}_base_level'.format(_ENV_PREFIX)
_ENV_TOP_LEVEL_KEY = '{}_top_level'.format(_ENV_PREFIX)

PRESET_BOTH = 'Both (Top -> Top + Bottom -> Bottom)'
PRESETS = [
    PRESET_BOTH,
    'Top -> Top',
    'Bottom -> Bottom',
    'Bottom -> Top',
    'Top -> Bottom',
]


def _to_bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


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
    preset = str(_get_envvar(_ENV_PRESET_KEY, PRESET_BOTH))
    if preset not in PRESETS:
        preset = PRESET_BOTH

    return {
        'enable_mapping': _to_bool(_get_envvar(_ENV_ENABLE_MAPPING_KEY, 'True')),
        'preset': preset,
        'match_offset': str(_get_envvar(_ENV_MATCH_OFFSET_KEY, '0')),
        'override_base': _to_bool(_get_envvar(_ENV_OVERRIDE_BASE_KEY, 'False')),
        'override_top': _to_bool(_get_envvar(_ENV_OVERRIDE_TOP_KEY, 'False')),
        'base_level': str(_get_envvar(_ENV_BASE_LEVEL_KEY, '')),
        'top_level': str(_get_envvar(_ENV_TOP_LEVEL_KEY, '')),
    }


def _save_dialog_defaults(config):
    _set_envvar(_ENV_ENABLE_MAPPING_KEY, config.get('enable_mapping', True))
    _set_envvar(_ENV_PRESET_KEY, config.get('preset', PRESET_BOTH))
    _set_envvar(_ENV_MATCH_OFFSET_KEY, config.get('match_offset_display', 0))
    _set_envvar(_ENV_OVERRIDE_BASE_KEY, config.get('override_base', False))
    _set_envvar(_ENV_OVERRIDE_TOP_KEY, config.get('override_top', False))
    _set_envvar(_ENV_BASE_LEVEL_KEY, config.get('base_level', ''))
    _set_envvar(_ENV_TOP_LEVEL_KEY, config.get('top_level', ''))


def _get_level_map():
    all_levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    sorted_levels = sorted(all_levels, key=lambda x: (x.Elevation, x.Name))
    level_names = [lvl.Name for lvl in sorted_levels]
    level_map = {lvl.Name: lvl for lvl in sorted_levels}
    return level_map, level_names


def _display_to_internal_length(value_display):
    value = float(value_display)
    units = doc.GetUnits()

    # Revit 2021 and earlier API path
    try:
        from Autodesk.Revit.DB import UnitType
        format_options = units.GetFormatOptions(UnitType.UT_Length)
        return UnitUtils.ConvertToInternalUnits(value, format_options.DisplayUnits)
    except Exception:
        pass

    # Revit 2022+ API path
    try:
        from Autodesk.Revit.DB import SpecTypeId
        format_options = units.GetFormatOptions(SpecTypeId.Length)
        return UnitUtils.ConvertToInternalUnits(value, format_options.GetUnitTypeId())
    except Exception:
        pass

    # Fallback to internal units if no unit metadata is available.
    return value


def _choose_preset():
    level_map, level_names = _get_level_map()
    defaults = _get_dialog_defaults()

    wnd = MatchConstraintsWindow(
        presets=PRESETS,
        levels=level_names,
        defaults=defaults,
        title=__title__
    )
    if not wnd.ShowDialog():
        return None

    config = wnd.result
    _save_dialog_defaults(config)

    config['match_offset_internal'] = _display_to_internal_length(config['match_offset_display'])
    config['base_level_obj'] = level_map.get(config.get('base_level')) if config.get('override_base') else None
    config['top_level_obj'] = level_map.get(config.get('top_level')) if config.get('override_top') else None

    return config


def _pick_source_wall():
    try:
        source_wall = pick_wall(uidoc)
    except OperationCanceledException:
        return None
    except Exception:
        source_wall = None

    return source_wall


def _source_top_data(source_wall):
    top_constraint_id = source_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
    is_unconnected = str(top_constraint_id) == '-1'

    return {
        'constraint_id': top_constraint_id,
        'is_unconnected': is_unconnected,
        'top_offset': source_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).AsDouble(),
        'user_height': source_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble(),
        'base_offset': source_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble(),
        'origin_z': source_wall.Location.Curve.Origin.Z,
    }


def _source_bottom_data(source_wall):
    return {
        'constraint_id': source_wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId(),
        'offset': source_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble(),
    }


def _wall_base_elevation(wall):
    base_level = doc.GetElement(wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId())
    base_offset = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    base_level_elev = base_level.Elevation if base_level else 0.0
    return base_level_elev + base_offset


def _wall_top_elevation(wall):
    base_elev = _wall_base_elevation(wall)
    top_constraint_id = wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()

    if str(top_constraint_id) == '-1':
        user_height = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
        return base_elev + user_height

    top_level = doc.GetElement(top_constraint_id)
    top_offset = wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
    top_level_elev = top_level.Elevation if top_level else 0.0
    return top_level_elev + top_offset


def _apply_top_from_top(dest_wall, src_top):
    dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(src_top['constraint_id'])

    if src_top['is_unconnected']:
        match_base_offset = dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
        match_unconnected_height = dest_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
        match_top_z = (dest_wall.Location.Curve.Origin.Z + match_base_offset) + match_unconnected_height

        source_top_z = src_top['origin_z'] + src_top['base_offset'] + src_top['user_height']
        new_unconnected_height = match_unconnected_height + source_top_z - match_top_z
        dest_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(new_unconnected_height)
    else:
        dest_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(src_top['top_offset'])


def _apply_top_from_bottom(dest_wall, src_bottom):
    dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(src_bottom['constraint_id'])
    dest_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(src_bottom['offset'])


def _apply_bottom_from_bottom(dest_wall, src_bottom):
    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).Set(src_bottom['constraint_id'])
    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).Set(src_bottom['offset'])


def _apply_bottom_from_top(dest_wall, src_top):
    if src_top['is_unconnected']:
        return False

    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).Set(src_top['constraint_id'])
    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).Set(src_top['top_offset'])
    return True


def _apply_base_override_keep_geometry(dest_wall, new_base_level):
    base_elevation = _wall_base_elevation(dest_wall)
    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).Set(new_base_level.Id)
    new_base_offset = base_elevation - new_base_level.Elevation
    dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).Set(new_base_offset)


def _apply_top_override_keep_geometry(dest_wall, new_top_level):
    top_elevation = _wall_top_elevation(dest_wall)
    dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).Set(new_top_level.Id)
    new_top_offset = top_elevation - new_top_level.Elevation
    dest_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET).Set(new_top_offset)


def _preserve_unconnected_top_elevation(dest_wall, target_top_elevation):
    current_base_elevation = _wall_base_elevation(dest_wall)
    new_user_height = target_top_elevation - current_base_elevation
    dest_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).Set(new_user_height)


def _apply_bottom_offset_delta(dest_wall, delta):
    if abs(delta) < 1e-9:
        return
    p_base_offset = dest_wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
    p_base_offset.Set(p_base_offset.AsDouble() + delta)


def _apply_top_offset_delta(dest_wall, delta):
    if abs(delta) < 1e-9:
        return

    top_constraint_id = dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
    if str(top_constraint_id) == '-1':
        p_user_height = dest_wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        p_user_height.Set(p_user_height.AsDouble() + delta)
        return

    p_top_offset = dest_wall.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
    p_top_offset.Set(p_top_offset.AsDouble() + delta)


def _preset_affects_top(preset_name):
    return preset_name in (PRESET_BOTH, 'Top -> Top', 'Bottom -> Top')


def _preset_affects_bottom(preset_name):
    return preset_name in (PRESET_BOTH, 'Bottom -> Bottom', 'Top -> Bottom')


def _apply_mapping(dest_wall, src_top, src_bottom, preset_name):
    if preset_name == PRESET_BOTH:
        _apply_bottom_from_bottom(dest_wall, src_bottom)
        _apply_top_from_top(dest_wall, src_top)
        return True

    if preset_name == 'Top -> Top':
        _apply_top_from_top(dest_wall, src_top)
        return True

    if preset_name == 'Bottom -> Bottom':
        _apply_bottom_from_bottom(dest_wall, src_bottom)
        return True

    if preset_name == 'Bottom -> Top':
        _apply_top_from_bottom(dest_wall, src_bottom)
        return True

    if preset_name == 'Top -> Bottom':
        return _apply_bottom_from_top(dest_wall, src_top)

    return False


def run_match_constraints():
    while True:
        config = _choose_preset()
        if not config:
            return

        mapping_enabled = bool(config.get('enable_mapping', True))
        preset_name = config['preset']

        source_wall = None
        src_top = None
        src_bottom = None

        if mapping_enabled:
            source_wall = _pick_source_wall()
            if not source_wall:
                # ESC on source pick returns to settings.
                continue

            src_top = _source_top_data(source_wall)
            src_bottom = _source_bottom_data(source_wall)

        if mapping_enabled and preset_name == 'Top -> Bottom' and src_top['is_unconnected']:
            forms.alert(
                'Top -> Bottom requires source top to be constrained to a level.\n'
                'The selected source wall top is Unconnected.',
                title='Unsupported Mapping'
            )
            continue

        if config.get('override_base') and not config.get('base_level_obj'):
            forms.alert('Selected base level is no longer available.', title='Invalid Base Override')
            continue

        if config.get('override_top') and not config.get('top_level_obj'):
            forms.alert('Selected top level is no longer available.', title='Invalid Top Override')
            continue

        match_offset_delta = config.get('match_offset_internal', 0.0) if mapping_enabled else 0.0
        reopen_settings = False

        with forms.WarningBar(title='Pick destination wall. ESC returns to settings.', handle_esc=True):
            while True:
                try:
                    dest_wall = pick_wall(uidoc)
                    if not dest_wall:
                        reopen_settings = True
                        break

                    if mapping_enabled and dest_wall.Id == source_wall.Id:
                        continue

                    with revit.Transaction(__title__):
                        top_constraint_id_before = dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
                        top_was_unconnected_before = str(top_constraint_id_before) == '-1'
                        top_elevation_before_changes = _wall_top_elevation(dest_wall)

                        if mapping_enabled:
                            _apply_mapping(dest_wall, src_top, src_bottom, preset_name)

                        top_constraint_id_after_core = dest_wall.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
                        top_is_unconnected_after_core = str(top_constraint_id_after_core) == '-1'

                        # Apply top first, then base, to keep unconnected-top behavior stable.
                        if config.get('override_top'):
                            _apply_top_override_keep_geometry(dest_wall, config.get('top_level_obj'))

                        if config.get('override_base'):
                            _apply_base_override_keep_geometry(dest_wall, config.get('base_level_obj'))

                        if mapping_enabled and _preset_affects_bottom(preset_name):
                            _apply_bottom_offset_delta(dest_wall, match_offset_delta)

                        if mapping_enabled and _preset_affects_top(preset_name):
                            _apply_top_offset_delta(dest_wall, match_offset_delta)

                        # Final guard: for bottom-only operations, keep an unconnected top fixed.
                        if (top_was_unconnected_before
                                and top_is_unconnected_after_core
                                and not config.get('override_top')
                                and (not mapping_enabled or not _preset_affects_top(preset_name))):
                            _preserve_unconnected_top_elevation(dest_wall, top_elevation_before_changes)

                except OperationCanceledException:
                    reopen_settings = True
                    break
                except Exception as ex:
                    forms.alert(
                        'Failed to apply constraints on one wall:\n{}'.format(ex),
                        title='Wall Match Warning'
                    )
                    reopen_settings = True
                    break

        if reopen_settings:
            continue

        return


if __name__ == '__main__':
    run_match_constraints()
