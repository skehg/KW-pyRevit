# -*- coding: utf-8 -*-
__title__         = "Text Count"
__min_revit_ver__ = 2021
__version__       = 1.0
__doc__ = """Date    = 28.07.2026
_____________________________________________________________________
Description:
places text with an auto incrementing number
_____________________________________________________________________
How-To:
- Run the command
- fill out the dialog with the desired parameters
- click OK and place the text in the model.
_____________________________________________________________________
Author: KoalaBIM Team"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
import clr

clr.AddReference('System')
from System.Collections.Generic import List

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms



# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
uidoc     = __revit__.ActiveUIDocument
doc       = uidoc.Document
app       = doc.Application
selection = uidoc.Selection
rvt_year  = int(app.VersionNumber)



# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
# ==================================================

