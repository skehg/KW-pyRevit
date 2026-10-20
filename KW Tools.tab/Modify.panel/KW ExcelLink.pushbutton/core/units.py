# -*- coding: utf-8 -*-
"""Convert Double parameter values between Revit internal units and project display units."""

import math

from Autodesk.Revit.DB import FormatOptions, LabelUtils, UnitUtils

_DEFAULT_DECIMALS = 6
_MAX_DECIMALS = 9


def _decimals(accuracy):
    try:
        if accuracy > 0:
            digits = int(math.ceil(-math.log10(accuracy) - 1e-9))
            return min(max(digits, 0), _MAX_DECIMALS)
    except Exception:
        pass
    return _DEFAULT_DECIMALS


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
        except Exception:
            return None
        if spec is None or spec.Empty():
            return None
        key = spec.TypeId
        if key in self._cache:
            return self._cache[key]
        info = None
        try:
            if UnitUtils.IsMeasurableSpec(spec):
                options = self.units.GetFormatOptions(spec)
                unit_type_id = options.GetUnitTypeId()
                info = {
                    "unitTypeId": unit_type_id,
                    "decimals": _decimals(options.Accuracy),
                    "symbol": _symbol_label(options, unit_type_id),
                }
        except Exception:
            info = None
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
