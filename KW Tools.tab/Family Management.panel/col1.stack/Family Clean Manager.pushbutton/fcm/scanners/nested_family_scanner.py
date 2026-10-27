# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import Family, FillPatternElement, FilteredElementCollector, ImportInstance, Material

from fcm.interfaces import IScanner
from fcm.models import Issue, Severity


class NestedFamilyScanner(IScanner):
    CATEGORY = "Nested Families"

    def __init__(self, deep_scan=False):
        self._deep_scan = bool(deep_scan)

    def _summarize_nested_doc(self, nested_doc):
        material_count = FilteredElementCollector(nested_doc).OfClass(Material).GetElementCount()
        fill_pattern_count = FilteredElementCollector(nested_doc).OfClass(FillPatternElement).GetElementCount()
        dwg_count = FilteredElementCollector(nested_doc).OfClass(ImportInstance).GetElementCount()

        subcat_count = 0
        try:
            categories = nested_doc.Settings.Categories
            for category in categories:
                try:
                    subcats = category.SubCategories
                    if subcats:
                        subcat_count += subcats.Size
                except Exception:
                    continue
        except Exception:
            pass

        return {
            "materials": material_count,
            "fill_patterns": fill_pattern_count,
            "subcategories": subcat_count,
            "dwg_imports": dwg_count,
        }

    def _build_notes(self, summary):
        return "DWG: {0} | Subcategories: {1} | Materials: {2} | Fill Patterns: {3}".format(
            summary.get("dwg_imports", 0),
            summary.get("subcategories", 0),
            summary.get("materials", 0),
            summary.get("fill_patterns", 0),
        )

    def _find_open_nested_doc(self, host_doc, family_name):
        for open_doc in host_doc.Application.Documents:
            try:
                if not open_doc.IsFamilyDocument:
                    continue
                owner = open_doc.OwnerFamily
                if owner and owner.Name == family_name:
                    return open_doc
            except Exception:
                continue
        return None

    def scan(self, doc):
        issues = []

        for family in FilteredElementCollector(doc).OfClass(Family).ToElements():
            family_name = family.Name if family else "<Unnamed Family>"
            summary = {}
            notes = "Ready to open for manual cleanup."

            if self._deep_scan:
                nested_doc = None
                should_close = False
                try:
                    nested_doc = self._find_open_nested_doc(doc, family_name)
                    if nested_doc is None:
                        nested_doc = doc.EditFamily(family)
                        should_close = True
                    summary = self._summarize_nested_doc(nested_doc)
                    notes = self._build_notes(summary)
                except Exception as ex:
                    notes = "Deep scan failed: {0}".format(str(ex))
                finally:
                    if nested_doc and should_close:
                        try:
                            nested_doc.Close(False)
                        except Exception:
                            pass

            issues.append(
                Issue(
                    category=self.CATEGORY,
                    name=family_name,
                    element_id=family.Id,
                    severity=Severity.INFO,
                    can_delete=False,
                    can_replace=False,
                    notes=notes,
                    metadata={
                        "family_name": family_name,
                        "summary": summary,
                    },
                )
            )

        issues.sort(key=lambda x: x.name.lower())
        return issues
