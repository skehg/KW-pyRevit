# -*- coding: utf-8 -*-
"""Convert Double parameter values between Revit internal units and project display units."""

import math

from Autodesk.Revit.DB import FormatOptions, LabelUtils, UnitUtils
from pyrevit import script

_LOGGER = script.get_logger()
_MAX_DECIMALS = 9


def _decimals(accuracy):
    if accuracy <= 0 or math.isnan(accuracy) or math.isinf(accuracy):
        raise ValueError("Project unit accuracy must be a positive finite number.")
    digits = int(math.ceil(-math.log10(accuracy) - 1e-9))
    return min(max(digits, 0), _MAX_DECIMALS)


def _symbol_label(format_options, unit_type_id):
    symbol = format_options.GetSymbolTypeId()
    if symbol is None or symbol.Empty():
        # Project hides the symbol (common for mm); use the unit's shortest symbol.
        labels = []
        for candidate in FormatOptions.GetValidSymbols(unit_type_id):
            if candidate is not None and not candidate.Empty():
                labels.append(LabelUtils.GetLabelForSymbol(candidate))
        labels = [label for label in labels if label]
        return min(labels, key=len) if labels else u""
    return LabelUtils.GetLabelForSymbol(symbol) or u""


class UnitConverter(object):
    """Caches project format options per spec for one document."""

    def __init__(self, doc):
        self.units = doc.GetUnits()
        self._cache = {}

    def describe(self, parameter):
        """Return {'unitTypeId', 'decimals', 'symbol'} or None if not measurable."""
        try:
            spec = parameter.Definition.GetDataType()
            if spec is None or spec.Empty():
                raise ValueError("Revit returned an empty parameter data type.")
            key = spec.TypeId
            if key in self._cache:
                return self._cache[key]
            if not UnitUtils.IsMeasurableSpec(spec):
                self._cache[key] = None
                return None
            options = self.units.GetFormatOptions(spec)
            unit_type_id = options.GetUnitTypeId()
            if (unit_type_id is None or unit_type_id.Empty()
                    or not UnitUtils.IsValidUnit(spec, unit_type_id)):
                raise ValueError("Revit returned an invalid project display unit.")
            info = {
                "unitTypeId": unit_type_id,
                "decimals": _decimals(options.Accuracy),
            }
        except Exception as exc:
            raise ValueError(
                "Cannot resolve project units for parameter '{0}': {1}. "
                "ExcelLink will not use raw internal units.".format(
                    parameter.Definition.Name, exc
                )
            )
        try:
            info["symbol"] = _symbol_label(options, unit_type_id)
        except Exception as exc:
            # Labels are cosmetic; retain conversion and identify the actual unit.
            info["symbol"] = unit_type_id.TypeId
            _LOGGER.warning(
                "ExcelLink could not resolve the unit symbol for parameter "
                "'{0}'; using unit ID '{1}' in headers. Numeric conversion "
                "is unchanged. Details: {2}".format(
                    parameter.Definition.Name, info["symbol"], exc
                )
            )
        self._cache[key] = info
        return info

    def to_display(self, parameter, internal_value):
        info = self.describe(parameter)
        if info is None or internal_value is None:
            return internal_value
        value = UnitUtils.ConvertFromInternalUnits(internal_value, info["unitTypeId"])
        value = round(value, info["decimals"])
        if value == 0:
            value = 0.0
        return value

    def to_internal(self, parameter, display_value):
        info = self.describe(parameter)
        if info is None:
            return display_value
        return UnitUtils.ConvertToInternalUnits(display_value, info["unitTypeId"])

    def symbol(self, parameter):
        info = self.describe(parameter)
        return info["symbol"] if info else u""
