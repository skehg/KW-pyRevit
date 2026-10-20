# -*- coding: utf-8 -*-
__title__ = "KW ExcelLink"
__min_revit_ver__ = 2025
__version__ = 1.0
__beta__ = False
__persistentengine__ = True
__doc__ = "Extract, review, and batch-apply Revit parameters in a workbook-style grid."

import os
import sys
import traceback

from pyrevit import forms, script

COMMAND_DIR = os.path.dirname(__file__)
if COMMAND_DIR not in sys.path:
    sys.path.insert(0, COMMAND_DIR)

from ui.workflow import run_wizard


def main():
    uidoc = __revit__.ActiveUIDocument
    if uidoc is None or uidoc.Document is None:
        forms.alert("Open a Revit project before running ExcelLink.", title=__title__)
        return
    try:
        result = run_wizard(uidoc, uidoc.Document)
        if result is None:
            return
        from ui.host import show_workbook
        workbook, source_elements = result
        show_workbook(uidoc, workbook, source_elements)
    except Exception:
        details = traceback.format_exc()
        script.get_logger().error("KW ExcelLink failed:\n{0}".format(details))
        output = script.get_output()
        output.print_md("## KW ExcelLink could not start")
        output.print_md("The full traceback is shown below and can be copied.")
        output.print_code(details)


main()
