# -*- coding: utf-8 -*-
__title__         = "Change Level FCR"
__min_revit_ver__ = 2021
__version__       = 1.0
__doc__ = """Date    = 02.07.2026
_____________________________________________________________________
Description:
Change Level / Base Level for Floors, Ceilings, Toposolids and Roofs
while preserving their world elevation by recalculating the offset.
_____________________________________________________________________
How-To:
- *Pre-select eligible elements (optional)
- Run the tool
- Select/confirm elements
- Pick the new target Level
_____________________________________________________________________
Author: Xrev Team"""

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

try:
	from Autodesk.Revit.DB import Toposolid
	HAS_TOPOSOLID_CLASS = True
except:
	Toposolid = None
	HAS_TOPOSOLID_CLASS = False


# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
uidoc     = __revit__.ActiveUIDocument
doc       = uidoc.Document
app       = doc.Application
selection = uidoc.Selection
rvt_year  = int(app.VersionNumber)

HAS_TOPOSOLID = HAS_TOPOSOLID_CLASS and rvt_year >= 2024 and hasattr(BuiltInParameter, 'TOPOSOLID_HEIGHTABOVELEVEL_PARAM')


class SelectionFilter_MultiHost(ISelectionFilter):
	"""Allow only target host elements for this tool."""
	def __init__(self, allow_toposolid=False):
		self.allow_toposolid = allow_toposolid

	def AllowElement(self, element):
		if element is None:
			return False
		if isinstance(element, Floor):
			return True
		if isinstance(element, Ceiling):
			return True
		if isinstance(element, RoofBase):
			return True
		if self.allow_toposolid and Toposolid and isinstance(element, Toposolid):
			return True
		return False

	def AllowReference(self, reference, point):
		return False


def get_param_spec(element):
	"""Get level and offset parameter ids for the given element type."""
	if isinstance(element, RoofBase):
		return (BuiltInParameter.ROOF_BASE_LEVEL_PARAM,
				BuiltInParameter.ROOF_LEVEL_OFFSET_PARAM,
				'Roof')

	if isinstance(element, Floor):
		return (BuiltInParameter.LEVEL_PARAM,
				BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM,
				'Floor')

	if isinstance(element, Ceiling):
		return (BuiltInParameter.LEVEL_PARAM,
				BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM,
				'Ceiling')

	if HAS_TOPOSOLID and Toposolid and isinstance(element, Toposolid):
		return (BuiltInParameter.LEVEL_PARAM,
				BuiltInParameter.TOPOSOLID_HEIGHTABOVELEVEL_PARAM,
				'Toposolid')

	return None


def is_group_member(element):
	"""Check whether element belongs to a model group."""
	try:
		return element.GroupId != ElementId.InvalidElementId
	except:
		return False


def get_selected_target_elements(exitscript=True):
	"""Pick target elements with optional preselection support."""
	selected_elements = [doc.GetElement(eid) for eid in selection.GetElementIds()]

	preselected = []
	for elem in selected_elements:
		if elem and get_param_spec(elem) and not is_group_member(elem):
			preselected.append(elem)

	ref_preselection = List[Reference]([Reference(e) for e in preselected])
	filter_multi = SelectionFilter_MultiHost(allow_toposolid=HAS_TOPOSOLID)

	picked = []
	try:
		with forms.WarningBar(title='Select Floors/Ceilings/Roofs/Toposolids and click "Finish"'):
			refs = selection.PickObjects(ObjectType.Element,
										 filter_multi,
										 'Select elements',
										 ref_preselection)
		picked = [doc.GetElement(r) for r in refs]
	except:
		pass

	result = []
	for elem in picked:
		if not elem:
			continue
		if is_group_member(elem):
			continue
		if get_param_spec(elem):
			result.append(elem)

	if not result and exitscript:
		forms.alert('No eligible elements were selected. Please try again.',
					title=__title__,
					exitscript=True)

	return result


def select_target_level():
	"""Prompt user for target level."""
	all_levels = list(FilteredElementCollector(doc).OfClass(Level).ToElements())
	if not all_levels:
		forms.alert('No Levels found in this document.', title=__title__, exitscript=True)

	all_levels = sorted(all_levels, key=lambda x: (x.Elevation, x.Name))
	dict_levels = {'{} ({:.3f})'.format(lvl.Name, lvl.Elevation): lvl for lvl in all_levels}

	try:
		from rpw.ui.forms import FlexForm, ComboBox, Separator, Button
		components = [
			ComboBox('new_level', dict_levels),
			Separator(),
			Button('Change Level')
		]
		form = FlexForm(__title__, components)
		form.show()
		values = form.values
		if not values or 'new_level' not in values or not values['new_level']:
			forms.alert('Target level was not selected.', title=__title__, exitscript=True)
		return values['new_level']
	except:
		forms.alert('Could not get user input. Please try again.', title=__title__, exitscript=True)


def preserve_elevation_change_level(element, new_level):
	"""Set new level and recompute offset to keep world elevation unchanged."""
	spec = get_param_spec(element)
	if not spec:
		return False, 'Unsupported element type.'

	level_bip, offset_bip, label = spec
	p_level = element.get_Parameter(level_bip)
	p_offset = element.get_Parameter(offset_bip)

	if not p_level or not p_offset:
		return False, '{} is missing required parameters.'.format(label)
	if p_level.IsReadOnly or p_offset.IsReadOnly:
		return False, '{} parameters are read-only.'.format(label)

	try:
		current_level = doc.GetElement(p_level.AsElementId())
		if not current_level:
			return False, '{} has invalid current level.'.format(label)

		current_offset = p_offset.AsDouble()
		current_world_elev = current_level.Elevation + current_offset

		p_level.Set(new_level.Id)
		new_offset = current_world_elev - new_level.Elevation
		p_offset.Set(new_offset)
		return True, ''
	except Exception as ex:
		return False, str(ex)


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝
# ==================================================

# 1) Select Elements
elements = get_selected_target_elements(exitscript=True)

# 2) Ask for target level
new_level = select_target_level()

# 3) Modify elements
modified = 0
skipped = 0
failed = 0
messages = []

if not HAS_TOPOSOLID:
	messages.append('Toposolid is only supported in Revit 2024+ and was excluded.')

t = Transaction(doc, 'Change Level FCR')
t.Start()
for elem in elements:
	try:
		status = WorksharingUtils.GetCheckoutStatus(doc, elem.Id)
		if status == CheckoutStatus.OwnedByOtherUser:
			skipped += 1
			messages.append('[{}] Skipped: owned by another user.'.format(elem.Id))
			continue

		ok, msg = preserve_elevation_change_level(elem, new_level)
		if ok:
			modified += 1
		else:
			failed += 1
			messages.append('[{}] Failed: {}'.format(elem.Id, msg))
	except Exception as ex:
		failed += 1
		messages.append('[{}] Failed: {}'.format(elem.Id, ex))

t.Commit()

summary = 'Selected: {} | Modified: {} | Skipped: {} | Failed: {}'.format(len(elements), modified, skipped, failed)
print(summary)
for line in messages:
	print(line)

forms.alert(summary, title=__title__)
