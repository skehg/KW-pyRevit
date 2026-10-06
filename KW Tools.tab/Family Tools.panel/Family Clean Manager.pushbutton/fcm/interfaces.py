# -*- coding: utf-8 -*-


class IScanner(object):
    """Scanner contract: accept a Document and return Issue list."""

    def scan(self, doc):
        raise NotImplementedError("Scanner must implement scan(doc)")


class IDeleteAction(object):
    """Delete contract for explicit user-selected elements."""

    def delete(self, doc, element_ids):
        raise NotImplementedError("Delete action must implement delete(doc, element_ids)")


class IReplaceAction(object):
    """Replace contract for explicit user-selected source/target ids."""

    def replace(self, doc, source_id, target_id):
        raise NotImplementedError("Replace action must implement replace(doc, source_id, target_id)")
