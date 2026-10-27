# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import BuiltInParameter, FilteredElementCollector, ImportInstance

from fcm.interfaces import IScanner
from fcm.models import Issue, Severity


class DWGScanner(IScanner):
    CATEGORY = "DWG Imports"

    def scan(self, doc):
        issues = []

        for imp in FilteredElementCollector(doc).OfClass(ImportInstance).ToElements():
            name = None
            try:
                p = imp.get_Parameter(BuiltInParameter.IMPORT_SYMBOL_NAME)
                if p:
                    name = p.AsString()
            except Exception:
                name = None

            if not name:
                try:
                    name = imp.Name
                except Exception:
                    name = "ImportInstance {0}".format(imp.Id.IntegerValue)

            issues.append(
                Issue(
                    category=self.CATEGORY,
                    name=name,
                    element_id=imp.Id,
                    severity=Severity.WARNING,
                    can_delete=True,
                    can_replace=False,
                    notes="Imported CAD instance.",
                    metadata={},
                )
            )

        issues.sort(key=lambda x: x.name.lower())
        return issues
