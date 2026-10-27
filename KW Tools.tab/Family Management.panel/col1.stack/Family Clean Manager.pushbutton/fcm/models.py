# -*- coding: utf-8 -*-


class Severity(object):
    INFO = "Info"
    WARNING = "Warning"
    ERROR = "Error"


class Issue(object):
    """Domain model returned by all scanners."""

    def __init__(
        self,
        category,
        name,
        element_id=None,
        severity=Severity.INFO,
        can_delete=False,
        can_replace=False,
        notes="",
        metadata=None,
    ):
        self.category = category
        self.name = name
        self.element_id = element_id
        self.severity = severity
        self.can_delete = bool(can_delete)
        self.can_replace = bool(can_replace)
        self.notes = notes or ""
        self.metadata = metadata or {}

    @property
    def element_id_int(self):
        if self.element_id is None:
            return None
        try:
            return self.element_id.IntegerValue
        except Exception:
            return None
