# -*- coding: utf-8 -*-
__title__ = "Family Clean Manager"
__min_revit_ver__ = 2023
__version__ = "1.0"
__doc__ = """Family Clean Manager (Phase 1)
Analyse and manually clean family content with explicit user actions.
"""

import os
import sys

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from pyrevit import forms, revit

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from fcm.ui import FamilyCleanManagerWindow
from fcm.viewmodels import FamilyCleanManagerViewModel


def _ensure_family_document(doc):
    if doc is None:
        forms.alert("No active document. Open a family file (.rfa) and run the command again.", exitscript=True)
    if not doc.IsFamilyDocument:
        forms.alert(
            "Family Clean Manager only operates on family files (.rfa).\n\n"
            "Open a family document and run the command again.",
            exitscript=True,
        )


def main():
    doc = revit.doc
    _ensure_family_document(doc)

    vm = FamilyCleanManagerViewModel(doc, __revit__)  # noqa: F821
    window = FamilyCleanManagerWindow(vm)
    window.ShowDialog()


if __name__ == "__main__":
    main()
