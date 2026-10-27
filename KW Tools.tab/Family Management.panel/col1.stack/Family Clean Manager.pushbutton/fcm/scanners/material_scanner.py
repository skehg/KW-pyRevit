# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import FilteredElementCollector, Material

from fcm.interfaces import IScanner
from fcm.models import Issue, Severity
from fcm.revit_utils import get_all_elements, is_valid_element_id, safe_name


class MaterialScanner(IScanner):
    CATEGORY = "Materials"

    def _collect_used_material_ids(self, doc):
        used = set()
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
                    mat_id = param.AsElementId()
                    if not is_valid_element_id(mat_id):
                        continue
                    if isinstance(doc.GetElement(mat_id), Material):
                        used.add(mat_id.IntegerValue)
                except Exception:
                    continue
        return used

    def scan(self, doc):
        used_ids = self._collect_used_material_ids(doc)
        issues = []

        for material in FilteredElementCollector(doc).OfClass(Material).ToElements():
            name = safe_name(material, "<Unnamed Material>")
            is_used = material.Id.IntegerValue in used_ids
            notes = "Used by at least one element parameter." if is_used else "No direct references detected."
            issues.append(
                Issue(
                    category=self.CATEGORY,
                    name=name,
                    element_id=material.Id,
                    severity=Severity.INFO if not is_used else Severity.WARNING,
                    can_delete=not is_used,
                    can_replace=False,
                    notes=notes,
                    metadata={"is_used": is_used},
                )
            )

        issues.sort(key=lambda x: x.name.lower())
        return issues
