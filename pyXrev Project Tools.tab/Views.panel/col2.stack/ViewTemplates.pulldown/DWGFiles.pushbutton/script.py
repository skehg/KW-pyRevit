import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('System.Xml')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import FilteredElementCollector, ImportInstance, View
from System.IO import File, Path
from System.Windows.Markup import XamlReader
from System.Windows import SystemParameters, WindowStartupLocation
from System.Text.RegularExpressions import Regex

from pyrevit import forms, revit, DB, script


logger = script.get_logger()
doc = revit.doc


class SelectableViewItem(object):
	def __init__(self, element, item_type, view_type_name):
		self.Element = element
		self.Name = element.Name
		self.ItemType = item_type
		self.ViewTypeName = view_type_name

	def ToString(self):
		return "[{0}] {1}".format(self.ItemType, self.Name)


def _cfg_get(name):
	cfg = script.get_config()
	try:
		return getattr(cfg, name)
	except:
		return None


def _cfg_set(name, value):
	cfg = script.get_config()
	setattr(cfg, name, value)


def _is_rect_on_screen(left, top, width, height):
	try:
		v_left = float(SystemParameters.VirtualScreenLeft)
		v_top = float(SystemParameters.VirtualScreenTop)
		v_width = float(SystemParameters.VirtualScreenWidth)
		v_height = float(SystemParameters.VirtualScreenHeight)
	except:
		return True

	v_right = v_left + v_width
	v_bottom = v_top + v_height
	right = left + width
	bottom = top + height

	if right < v_left:
		return False
	if left > v_right:
		return False
	if bottom < v_top:
		return False
	if top > v_bottom:
		return False
	return True


def restore_window_position(window, key):
	left = _cfg_get(key + '_left')
	top = _cfg_get(key + '_top')
	if left is None or top is None:
		return

	try:
		left = float(left)
		top = float(top)
	except:
		return

	width = 800.0
	height = 600.0
	try:
		if window.Width > 0:
			width = float(window.Width)
		if window.Height > 0:
			height = float(window.Height)
	except:
		pass

	if _is_rect_on_screen(left, top, width, height):
		window.WindowStartupLocation = WindowStartupLocation.Manual
		window.Left = left
		window.Top = top


def save_window_position(window, key):
	try:
		_cfg_set(key + '_left', float(window.Left))
		_cfg_set(key + '_top', float(window.Top))
		script.save_config()
	except:
		pass


def load_xaml_window(xaml_name):
	script_dir = Path.GetDirectoryName(__file__)
	xaml_path = Path.Combine(script_dir, xaml_name)
	if not File.Exists(xaml_path):
		forms.alert('XAML not found: {0}'.format(xaml_path), exitscript=True)

	# pyRevit/IronPython does not provide compiled backing classes for x:Class,
	# so remove x:Class from loose XAML before parsing.
	xaml_text = File.ReadAllText(xaml_path)
	xaml_text = Regex.Replace(xaml_text, '\\s+x:Class="[^"]*"', '')
	return XamlReader.Parse(xaml_text)


def get_all_views_and_templates(document):
	views = []
	templates = []
	for v in FilteredElementCollector(document).OfClass(View):
		try:
			if v.IsTemplate:
				templates.append(v)
			elif not v.ViewType.ToString().startswith('Internal'):
				views.append(v)
		except:
			pass
	return views, templates


def get_view_type_name(view):
	try:
		return view.ViewType.ToString()
	except:
		return 'Unknown'


def get_dwg_categories(document):
	items = []
	seen_cat_ids = set()

	for imp in FilteredElementCollector(document).OfClass(ImportInstance):
		try:
			cat = imp.Category
			if cat is None:
				continue
			cid = cat.Id.IntegerValue
			if cid in seen_cat_ids:
				continue
			seen_cat_ids.add(cid)
			items.append(cat)
		except:
			pass

	if items:
		items.sort(key=lambda x: x.Name.lower())
		return items

	try:
		root = document.Settings.Categories.get_Item(DB.BuiltInCategory.OST_ImportObjectStyles)
	except:
		root = None

	if root is None:
		return []

	for cat in root.SubCategories:
		try:
			has_layers = False
			for _ in cat.SubCategories:
				has_layers = True
				break
			if has_layers:
				items.append(cat)
		except:
			pass

	items.sort(key=lambda x: x.Name.lower())
	return items


def get_target_display_name(view):
	try:
		kind = 'View Template' if view.IsTemplate else 'View'
	except:
		kind = 'View'

	try:
		name = view.Name
	except:
		name = 'Unnamed'

	return '[{0}] {1}'.format(kind, name)


def get_target_name(view):
	try:
		return view.Name
	except:
		return 'Unnamed'


def get_category_visible_in_view(view, category_id):
	try:
		return not view.GetCategoryHidden(category_id)
	except:
		return None


def get_uniform_visibility(target_views, category_id):
	states = []
	for view in target_views:
		visible = get_category_visible_in_view(view, category_id)
		if visible is None:
			continue
		states.append(visible)

	if not states:
		return None

	first_state = states[0]
	for state in states[1:]:
		if state != first_state:
			return None
	return first_state


def build_target_summary(target_views):
	if not target_views:
		return 'No targets selected.'

	lines = []
	for view in target_views:
		lines.append(get_target_display_name(view))
	return '\n'.join(lines)


class DwgVisibilityItem(object):
	def __init__(self, category, current_visible):
		self.Category = category
		self.Name = category.Name
		self.CurrentVisible = current_visible
		self.CurrentStateText = self._format_state(current_visible)
		self.IsVisible = current_visible

	def _format_state(self, value):
		if value is True:
			return 'On'
		if value is False:
			return 'Off'
		return 'Mixed'

	def ToString(self):
		return self.Name


class DwgVisibilityDialog(object):
	def __init__(self, target_views):
		self.window = load_xaml_window('DWGFiles.xaml')
		self.target_views = target_views

		self.target_summary_text = self.window.FindName('TargetSummaryText')
		self.search_box = self.window.FindName('SearchBox')
		self.dwg_grid = self.window.FindName('DwgGrid')
		self.set_selected_on_btn = self.window.FindName('SetSelectedOnBtn')
		self.set_selected_off_btn = self.window.FindName('SetSelectedOffBtn')
		self.set_all_on_btn = self.window.FindName('SetAllOnBtn')
		self.set_all_off_btn = self.window.FindName('SetAllOffBtn')
		self.cancel_btn = self.window.FindName('CancelBtn')
		self.apply_btn = self.window.FindName('ApplyBtn')

		self.all_items = []
		self.filtered_items = []
		self.accepted = False

		self.target_summary_text.Text = build_target_summary(self.target_views)

		self._populate_items()
		self.dwg_grid.ItemsSource = self.filtered_items

		self.search_box.TextChanged += self._on_search_changed
		self.set_selected_on_btn.Click += self._on_set_selected_on
		self.set_selected_off_btn.Click += self._on_set_selected_off
		self.set_all_on_btn.Click += self._on_set_all_on
		self.set_all_off_btn.Click += self._on_set_all_off
		self.cancel_btn.Click += self._on_cancel
		self.apply_btn.Click += self._on_apply

		self.refresh_list()

	def _populate_items(self):
		self.all_items = []
		for category in get_dwg_categories(doc):
			current_visible = get_uniform_visibility(self.target_views, category.Id)
			self.all_items.append(DwgVisibilityItem(category, current_visible))

	def _on_search_changed(self, sender, args):
		self.refresh_list()

	def refresh_list(self):
		search_text = (self.search_box.Text or '').lower().strip()
		self.filtered_items = []

		for item in self.all_items:
			if search_text and search_text not in item.Name.lower():
				continue
			self.filtered_items.append(item)

		self.dwg_grid.ItemsSource = None
		self.dwg_grid.ItemsSource = self.filtered_items

	def _get_selected_rows(self):
		rows = []
		for row in self.dwg_grid.SelectedItems:
			rows.append(row)
		return rows

	def _set_rows_visibility(self, rows, visible):
		if not rows:
			forms.alert('Select one or more DWG rows first.')
			return

		for row in rows:
			row.IsVisible = visible
			row.CurrentStateText = 'On' if visible else 'Off'

		try:
			self.dwg_grid.Items.Refresh()
		except:
			pass

	def _on_set_selected_on(self, sender, args):
		self._set_rows_visibility(self._get_selected_rows(), True)

	def _on_set_selected_off(self, sender, args):
		self._set_rows_visibility(self._get_selected_rows(), False)

	def _on_set_all_on(self, sender, args):
		self._set_rows_visibility(self.all_items, True)

	def _on_set_all_off(self, sender, args):
		self._set_rows_visibility(self.all_items, False)

	def _on_cancel(self, sender, args):
		self.accepted = False
		self.window.DialogResult = False
		self.window.Close()

	def _on_apply(self, sender, args):
		has_changes = False
		for row in self.all_items:
			desired_visible = row.IsVisible
			if desired_visible is None:
				continue

			for view in self.target_views:
				current_visible = get_category_visible_in_view(view, row.Category.Id)
				if current_visible is None:
					continue
				if current_visible != desired_visible:
					has_changes = True
					break

			if has_changes:
				break

		if not has_changes:
			forms.alert('No DWG visibility changes were requested.')
			return

		self.accepted = True
		self.window.DialogResult = True
		self.window.Close()

	def show(self):
		restore_window_position(self.window, 'dwg_visibility_editor')
		result = self.window.ShowDialog()
		save_window_position(self.window, 'dwg_visibility_editor')
		return bool(result)


def apply_dwg_visibility(target_views, dwg_items):
	updated_views = []
	updated_templates = []

	with revit.Transaction('Toggle DWG Visibility'):
		for view in target_views:
			view_changed = False

			for item in dwg_items:
				desired_visible = item.IsVisible
				if desired_visible is None:
					continue

				current_visible = get_category_visible_in_view(view, item.Category.Id)
				if current_visible is None:
					continue
				if current_visible == desired_visible:
					continue

				try:
					if not view.CanCategoryBeHidden(item.Category.Id):
						continue
					view.SetCategoryHidden(item.Category.Id, not desired_visible)
					view_changed = True
				except Exception as ex:
					logger.debug('Failed to toggle DWG {0} in {1}: {2}'.format(item.Name, get_target_display_name(view), ex))

			if view_changed:
				if getattr(view, 'IsTemplate', False):
					updated_templates.append(get_target_name(view))
				else:
					updated_views.append(get_target_name(view))

	return updated_views, updated_templates


def print_visibility_summary(updated_views, updated_templates):
	if not updated_views and not updated_templates:
		print('No DWG visibility changes were applied.')
		return

	if updated_views:
		print('Updated Views ({0}):'.format(len(updated_views)))
		for name in updated_views:
			print(' - {0}'.format(name))

	if updated_templates:
		print('Updated View Templates ({0}):'.format(len(updated_templates)))
		for name in updated_templates:
			print(' - {0}'.format(name))


def main():
	select_dialog = SelectViewTemplateDialog()
	if not select_dialog.show() or not select_dialog.selected_elements:
		return

	dwg_categories = get_dwg_categories(doc)
	if not dwg_categories:
		forms.alert('No imported DWG files were found in this document.', title='DWG Visibility')
		return

	visibility_dialog = DwgVisibilityDialog(select_dialog.selected_elements)
	if not visibility_dialog.show() or not visibility_dialog.accepted:
		return

	try:
		updated_views, updated_templates = apply_dwg_visibility(
			select_dialog.selected_elements,
			visibility_dialog.all_items,
		)
		print_visibility_summary(updated_views, updated_templates)
		forms.alert('DWG visibility changes were applied.', title='DWG Visibility')
	except Exception as ex:
		forms.alert('Error applying DWG visibility changes:\n{0}'.format(ex), title='DWG Visibility')


class SelectViewTemplateDialog(object):
	def __init__(self):
		self.window = load_xaml_window('SelectViewTemplate.xaml')
		self.filter_combo = self.window.FindName('FilterCombo')
		self.view_type_filter_combo = self.window.FindName('ViewTypeFilterCombo')
		self.search_box = self.window.FindName('SearchBox')
		self.selection_list = self.window.FindName('SelectionList')
		self.cancel_btn = self.window.FindName('CancelBtn')
		self.next_btn = self.window.FindName('NextBtn')

		self.views, self.templates = get_all_views_and_templates(doc)
		self.filtered_items = []
		self.selected_elements = []

		self.selection_list.ItemsSource = self.filtered_items

		self._populate_view_type_filter()

		self.filter_combo.SelectionChanged += self._on_filter_or_search_changed
		self.view_type_filter_combo.SelectionChanged += self._on_filter_or_search_changed
		self.search_box.TextChanged += self._on_filter_or_search_changed
		self.cancel_btn.Click += self._on_cancel
		self.next_btn.Click += self._on_next

		self.refresh_list()

	def _populate_view_type_filter(self):
		self.view_type_filter_combo.Items.Clear()
		self.view_type_filter_combo.Items.Add('All Types')

		type_names = set()
		for v in self.views:
			type_names.add(get_view_type_name(v))
		for t in self.templates:
			type_names.add(get_view_type_name(t))

		for type_name in sorted(type_names, key=lambda x: x.lower()):
			self.view_type_filter_combo.Items.Add(type_name)

		self.view_type_filter_combo.SelectedIndex = 0

	def _on_filter_or_search_changed(self, sender, args):
		self.refresh_list()

	def refresh_list(self):
		self.filtered_items = []

		mode = self.filter_combo.SelectedIndex
		search_text = (self.search_box.Text or '').lower().strip()
		selected_view_type = self.view_type_filter_combo.SelectedItem
		if selected_view_type is None:
			selected_view_type = 'All Types'

		if mode in [0, 1]:
			for v in self.views:
				view_type_name = get_view_type_name(v)
				if search_text and search_text not in v.Name.lower():
					continue
				if selected_view_type != 'All Types' and view_type_name != selected_view_type:
					continue
				item = SelectableViewItem(v, 'View', view_type_name)
				self.filtered_items.append(item)

		if mode in [0, 2]:
			for t in self.templates:
				view_type_name = get_view_type_name(t)
				if search_text and search_text not in t.Name.lower():
					continue
				if selected_view_type != 'All Types' and view_type_name != selected_view_type:
					continue
				item = SelectableViewItem(t, 'Template', view_type_name)
				self.filtered_items.append(item)

		self.selection_list.ItemsSource = None
		self.selection_list.ItemsSource = self.filtered_items

	def _on_cancel(self, sender, args):
		self.selected_elements = []
		self.window.DialogResult = False
		self.window.Close()

	def _on_next(self, sender, args):
		selected = []
		for item in self.selection_list.SelectedItems:
			try:
				selected.append(item.Element)
			except:
				pass
		if not selected:
			forms.alert('Please select at least one View or View Template.')
			return
		self.selected_elements = selected
		self.window.DialogResult = True
		self.window.Close()

	def show(self):
		restore_window_position(self.window, 'dwg_layers_select_views')
		result = self.window.ShowDialog()
		save_window_position(self.window, 'dwg_layers_select_views')
		return bool(result)


if __name__ == '__main__':
	main()

