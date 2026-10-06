# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import FillPatternElement, FilteredElementCollector

from fcm.interfaces import IScanner
from fcm.models import Issue, Severity
from fcm.revit_utils import get_all_elements, is_valid_element_id, safe_name


class FillPatternScanner(IScanner):
    CATEGORY = "Fill Patterns"

    def _is_protected(self, fill_pattern_element):
        try:
            fill_pattern = fill_pattern_element.GetFillPattern()
            if fill_pattern and fill_pattern.IsSolidFill:
                return True
        except Exception:
            pass

        name = safe_name(fill_pattern_element, "").strip().lower()
        return name in ("solid fill", "solid")

    def _collect_used_fill_pattern_ids(self, doc):
        used = set()

        # Revit 2023+ fill-pattern typed parameters are represented as ElementId
        # references to FillPatternElement. This generic pass covers materials,
        # filled regions, and newer parameter data types.
        for element in get_all_elements(doc):
            try:
                params = element.Parameters
            except Exception:
                params = None
            if not params:
                continue

            for param in params:
                try:
                    if str(param.StorageType) != "ElementId":
                        continue
                    fp_id = param.AsElementId()
                    if not is_valid_element_id(fp_id):
                        continue
                    if isinstance(doc.GetElement(fp_id), FillPatternElement):
                        used.add(fp_id.IntegerValue)
                except Exception:
                    continue

        return used

    def scan(self, doc):
        used_ids = self._collect_used_fill_pattern_ids(doc)
        issues = []

        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements():
            name = safe_name(fp, "<Unnamed Fill Pattern>")
            is_protected = self._is_protected(fp)
            is_used = fp.Id.IntegerValue in used_ids

            notes = []
            if is_protected:
                notes.append("Protected built-in pattern")
            if is_used:
                notes.append("Used by parameters/elements")
            if not notes:
                notes.append("No direct references detected")

            issues.append(
                Issue(
                    category=self.CATEGORY,
                    name=name,
                    element_id=fp.Id,
                    severity=Severity.WARNING if is_used or is_protected else Severity.INFO,
                    can_delete=(not is_protected),
                    can_replace=(not is_protected),
                    notes="; ".join(notes),
                    metadata={"is_used": is_used, "is_protected": is_protected},
                )
            )

        issues.sort(key=lambda x: x.name.lower())
        return issues
