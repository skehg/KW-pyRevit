# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import FilteredElementCollector, FillPatternElement

from fcm.actions.delete_action import DeleteElementsAction
from fcm.actions.fill_pattern_replace_action import FillPatternReplaceAction
from fcm.scanners.dwg_scanner import DWGScanner
from fcm.scanners.fill_pattern_scanner import FillPatternScanner
from fcm.scanners.material_scanner import MaterialScanner
from fcm.scanners.nested_family_scanner import NestedFamilyScanner
from fcm.scanners.subcategory_scanner import SubcategoryScanner


class IssueRow(object):
    def __init__(self, issue):
        self.Issue = issue
        self.Name = issue.name
        self.Severity = issue.severity
        self.Notes = issue.notes
        self.DisplayLabel = "{0} | {1} | {2}".format(issue.name, issue.severity, issue.notes)


class FillPatternOption(object):
    def __init__(self, name, element_id, target_label, display_name):
        self.Name = name
        self.ElementId = element_id
        self.TargetLabel = target_label
        self.DisplayName = display_name

    def __str__(self):
        return self.DisplayName


class FamilyCleanManagerViewModel(object):
    def __init__(self, doc, uiapp):
        self.doc = doc
        self.uiapp = uiapp
        self._scanners = {
            "materials": MaterialScanner(),
            "fill_patterns": FillPatternScanner(),
            "subcategories": SubcategoryScanner(),
            "dwg_imports": DWGScanner(),
            "nested_families": NestedFamilyScanner(deep_scan=False),
        }

    def get_active_family_doc(self):
        try:
            uidoc = self.uiapp.ActiveUIDocument
            if uidoc is None:
                return None
            doc = uidoc.Document
            if doc is None or not doc.IsFamilyDocument:
                return None
            return doc
        except Exception:
            return None

    def _to_rows(self, issues):
        return [IssueRow(issue) for issue in issues]

    def analyze_family(self):
        doc = self.get_active_family_doc()
        if doc is None:
            return {
                "materials": [],
                "fill_patterns": [],
                "subcategories": [],
                "dwg_imports": [],
                "nested_families": [],
            }

        return {
            "materials": self._to_rows(self._scanners["materials"].scan(doc)),
            "fill_patterns": self._to_rows(self._scanners["fill_patterns"].scan(doc)),
            "subcategories": self._to_rows(self._scanners["subcategories"].scan(doc)),
            "dwg_imports": self._to_rows(self._scanners["dwg_imports"].scan(doc)),
            "nested_families": self._to_rows(self._scanners["nested_families"].scan(doc)),
        }

    def deep_scan_nested_families(self):
        doc = self.get_active_family_doc()
        if doc is None:
            return []
        scanner = NestedFamilyScanner(deep_scan=True)
        return self._to_rows(scanner.scan(doc))

    def delete_issues(self, rows, transaction_name):
        doc = self.get_active_family_doc()
        if doc is None:
            return 0

        element_ids = []
        for row in rows or []:
            issue = row.Issue
            if issue.can_delete and issue.element_id is not None:
                element_ids.append(issue.element_id)

        action = DeleteElementsAction(transaction_name)
        return action.delete(doc, element_ids)

    def replace_fill_patterns(self, rows, replacement_id):
        doc = self.get_active_family_doc()
        if doc is None:
            return 0

        action = FillPatternReplaceAction()
        total_changes = 0
        for row in rows or []:
            issue = row.Issue
            if not issue.can_replace:
                continue
            if issue.element_id is None:
                continue
            if issue.element_id == replacement_id:
                continue
            total_changes += action.replace(doc, issue.element_id, replacement_id)
        return total_changes

    def get_fill_pattern_options(self):
        doc = self.get_active_family_doc()
        if doc is None:
            return []

        options = []
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements():
            try:
                name = fp.Name
            except Exception:
                name = "Fill Pattern {0}".format(fp.Id.IntegerValue)

            target_label = "Unknown"
            try:
                fill_pattern = fp.GetFillPattern()
                if fill_pattern is not None:
                    target_label = str(fill_pattern.Target)
            except Exception:
                pass

            display_name = "{0} [{1}] (Id: {2})".format(name, target_label, fp.Id.IntegerValue)
            options.append(FillPatternOption(name, fp.Id, target_label, display_name))

        options.sort(key=lambda x: x.Name.lower())
        return options

    def open_nested_family(self, row):
        doc = self.get_active_family_doc()
        if doc is None:
            return "No active family document."

        if row is None or row.Issue is None:
            return "No nested family selected."

        family = doc.GetElement(row.Issue.element_id)
        if family is None:
            return "Selected nested family no longer exists."

        # If already open and saved, activate by path.
        for open_doc in self.uiapp.Application.Documents:
            try:
                if not open_doc.IsFamilyDocument:
                    continue
                owner = open_doc.OwnerFamily
                if owner and owner.Name == family.Name:
                    path = open_doc.PathName
                    if path:
                        self.uiapp.OpenAndActivateDocument(path)
                        return "Activated open nested family: {0}".format(family.Name)
                    try:
                        doc.EditFamily(family)
                        return "Activated open nested family: {0}".format(family.Name)
                    except Exception:
                        return "Nested family is already open: {0}".format(family.Name)
            except Exception:
                continue

        try:
            nested_doc = doc.EditFamily(family)
            path = nested_doc.PathName
            if path:
                self.uiapp.OpenAndActivateDocument(path)
            return "Opened nested family: {0}".format(family.Name)
        except Exception as ex:
            return "Failed to open nested family: {0}".format(str(ex))
