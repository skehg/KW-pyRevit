# -*- coding: utf-8 -*-

from fcm.interfaces import IScanner
from fcm.models import Issue, Severity


class SubcategoryScanner(IScanner):
    CATEGORY = "Subcategories"

    def _is_user_subcategory(self, subcat):
        # Built-in/hard-coded categories typically use non-positive ids and are
        # not user-created subcategories intended for manual cleanup.
        try:
            return subcat is not None and subcat.Id.IntegerValue > 0
        except Exception:
            return False

    def scan(self, doc):
        issues = []

        try:
            categories = doc.Settings.Categories
        except Exception:
            categories = []

        for category in categories:
            try:
                subcats = category.SubCategories
            except Exception:
                subcats = None
            if not subcats:
                continue

            iterator = subcats.GetEnumerator()
            while iterator.MoveNext():
                subcat = iterator.Current
                if not self._is_user_subcategory(subcat):
                    continue
                parent_name = category.Name if category else "<Unknown Category>"
                sub_name = subcat.Name if subcat else "<Unnamed Subcategory>"
                issues.append(
                    Issue(
                        category=self.CATEGORY,
                        name="{0} :: {1}".format(parent_name, sub_name),
                        element_id=subcat.Id,
                        severity=Severity.INFO,
                        can_delete=True,
                        can_replace=False,
                        notes="Manual deletion only. Usage is not analyzed.",
                        metadata={"parent_category": parent_name, "subcategory_name": sub_name},
                    )
                )

        issues.sort(key=lambda x: x.name.lower())
        return issues
