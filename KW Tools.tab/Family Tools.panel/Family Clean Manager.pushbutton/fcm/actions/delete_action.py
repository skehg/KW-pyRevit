# -*- coding: utf-8 -*-

from System.Collections.Generic import List

from Autodesk.Revit.DB import ElementId
from pyrevit import revit

from fcm.interfaces import IDeleteAction


class DeleteElementsAction(IDeleteAction):
    def __init__(self, transaction_name):
        self._transaction_name = transaction_name

    def delete(self, doc, element_ids):
        valid_ids = [eid for eid in (element_ids or []) if eid is not None]
        if not valid_ids:
            return 0

        deleted_count = 0
        with revit.Transaction(self._transaction_name):
            try:
                id_list = List[ElementId]()
                for eid in valid_ids:
                    id_list.Add(eid)
                deleted_ids = doc.Delete(id_list)
                return deleted_ids.Count if deleted_ids is not None else 0
            except Exception:
                # Fallback keeps partial progress if batch delete is rejected.
                pass

            for eid in valid_ids:
                try:
                    deleted = doc.Delete(eid)
                    if deleted:
                        deleted_count += 1
                except Exception:
                    continue

        return deleted_count
