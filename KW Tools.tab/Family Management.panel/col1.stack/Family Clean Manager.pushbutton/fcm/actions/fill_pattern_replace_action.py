# -*- coding: utf-8 -*-

from pyrevit import revit

from fcm.interfaces import IReplaceAction
from fcm.revit_utils import get_all_elements


class FillPatternReplaceAction(IReplaceAction):
    def __init__(self, transaction_name="Replace Fill Pattern References"):
        self._transaction_name = transaction_name

    def replace(self, doc, source_id, target_id):
        if source_id is None or target_id is None:
            return 0
        if source_id == target_id:
            return 0

        changed = 0
        with revit.Transaction(self._transaction_name):
            for element in get_all_elements(doc):
                try:
                    params = element.Parameters
                except Exception:
                    params = None
                if not params:
                    continue

                for param in params:
                    try:
                        if param.IsReadOnly:
                            continue
                        if str(param.StorageType) != "ElementId":
                            continue
                        current = param.AsElementId()
                        if current != source_id:
                            continue
                        if param.Set(target_id):
                            changed += 1
                    except Exception:
                        continue

        return changed
