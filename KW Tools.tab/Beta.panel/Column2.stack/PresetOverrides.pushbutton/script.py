# -*- coding: utf-8 -*-
__title__         = "Preset Overrides"
__min_revit_ver__ = 2021
__version__       = 1.0
__doc__ = """Date    = 05.08.2026
_____________________________________________________________________
Description:
Apply preset overrides to elements
_____________________________________________________________________
How-To:
- Run the command
- Choose the style
- Select objects to apply the style to
_____________________________________________________________________
Author: KoalaBIM Team"""

import os
import traceback
import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from pyrevit import revit, forms, script as _pyscript
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInParameter

STUB