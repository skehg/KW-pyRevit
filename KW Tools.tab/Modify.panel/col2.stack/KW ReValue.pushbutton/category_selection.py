"""On-demand, read-only category/family selection for KW ReValue."""
import os

from Autodesk.Revit import DB
from Autodesk.Revit.Exceptions import ArgumentException as RevitArgumentException
from System import Action
from System.Windows import Thickness
from System.Windows.Controls import CheckBox, ListBoxItem
from System.Windows.Input import Cursors
from ui_styles import load_window
from System.Windows.Threading import DispatcherPriority
from pyrevit import forms
from pyrevit.compat import get_elementid_value_func


element_id_value = get_elementid_value_func()


class CategoryData(object):
    def __init__(self, category, count):
        self.id = category.Id
        self.key = element_id_value(category.Id)
        self.name = category.Name
        self.count = count


class CategorySource(object):
    """Cache per scope/category; resolve family names once per distinct type."""
    def __init__(self, document, view):
        self.document = document
        self.view = view
        self.category_cache = {}
        self.family_cache = {}
        self.type_cache = {}
        self.warnings = {}
        self.view_available = DB.FilteredElementCollector.IsViewValidForElementIteration(
            document, view.Id)

    def collector(self, scope, category_id):
        if scope == 'view':
            if not self.view_available:
                raise ValueError('The active view does not support element collection.')
            collector = DB.FilteredElementCollector(self.document, self.view.Id)
        else:
            collector = DB.FilteredElementCollector(self.document)
        return collector.OfCategoryId(category_id).WhereElementIsNotElementType()

    def categories(self, scope):
        if scope == 'view' and not self.view_available:
            raise ValueError('The active view does not support element collection.')
        if scope in self.category_cache:
            return self.category_cache[scope]
        rows = []
        unsupported = []
        for category in self.document.Settings.Categories:
            try:
                with self.collector(scope, category.Id) as collector:
                    count = collector.GetElementCount()
            except RevitArgumentException as ex:
                unsupported.append(category.Name)
                print("KW ReValue: category '{}' cannot be collected: {}".format(
                    category.Name, ex))
                continue
            if count:
                rows.append(CategoryData(category, count))
        rows.sort(key=lambda row: row.name.lower())
        self.category_cache[scope] = rows
        self.warnings[scope] = unsupported
        return rows

    def family_name(self, element):
        if isinstance(element, DB.View):
            return None
        type_id = element.GetTypeId()
        type_key = element_id_value(type_id)
        if type_key == element_id_value(DB.ElementId.InvalidElementId):
            return None
        if type_key not in self.type_cache:
            element_type = self.document.GetElement(type_id)
            name = element_type.FamilyName if isinstance(element_type, DB.ElementType) else None
            self.type_cache[type_key] = name or None
        return self.type_cache[type_key]

    def families(self, scope, category):
        key = (scope, category.key)
        if key not in self.family_cache:
            groups = {}
            with self.collector(scope, category.id) as collector:
                for element in collector:
                    name = self.family_name(element)
                    groups.setdefault(name, []).append(element.Id)
            self.family_cache[key] = groups
        return self.family_cache[key]

    def selected_ids(self, scope, category, state):
        if state['all']:
            cached = self.family_cache.get((scope, category.key))
            if cached is not None:
                return [element_id for ids in cached.values() for element_id in ids]
            with self.collector(scope, category.id) as collector:
                return list(collector.ToElementIds())
        groups = self.families(scope, category)
        return [element_id for name in state['families']
                for element_id in groups.get(name, [])]


class CategoryPicker(object):
    def __init__(self, source):
        self.source = source
        path = os.path.join(os.path.dirname(__file__), 'CategorySelection.xaml')
        self.window = load_window(path)
        for name in (
                'scope_toggle', 'category_list', 'family_list',
                'search_categories', 'search_families', 'family_toggle',
                'family_heading', 'family_modes',
                'selection_summary', 'selection_status', 'use_selection',
                'cancel_selection'):
            setattr(self, name, self.window.FindName(name))
        self.scope = 'view' if source.view_available else 'project'
        self.states = {'view': {}, 'project': {}}
        self.rows = []
        self.active_category = None
        self.result = None
        self._updating = False
        self._collection_error = None
        self.notice = ''
        if not source.view_available:
            self.scope_toggle.IsChecked = True
            self.scope_toggle.IsEnabled = False
            self.scope_toggle.ToolTip = (
                'The active view does not support element collection. Using Entire Project.')
            self.notice = 'Current View is unavailable for this view; Entire Project is selected.'
        self.scope_toggle.Checked += self.scope_changed
        self.scope_toggle.Unchecked += self.scope_changed
        self.category_list.SelectionChanged += self.category_changed
        self.search_categories.TextChanged += self.render_categories
        self.search_families.TextChanged += self.render_families
        self.family_toggle.Checked += self.family_mode_changed
        self.family_toggle.Unchecked += self.family_mode_changed
        self.use_selection.Click += self.accept
        self.cancel_selection.Click += self.cancel
        self.window.Loaded += self.loaded

    def busy(self, callback):
        self.window.Cursor = Cursors.Wait
        self.window.IsEnabled = False
        self.selection_status.Text = 'Collecting elements - please wait...'
        self.window.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Render)
        try:
            return callback()
        finally:
            self.window.Cursor = None
            self.window.IsEnabled = True

    def state(self, key):
        return self.states[self.scope].setdefault(
            key, dict(checked=False, all=True, families=set()))

    def loaded(self, sender, args):
        self.load_scope()

    def load_scope(self):
        self.rows = []
        self.active_category = None
        self._collection_error = None
        self.category_list.Items.Clear()
        self.render_families()
        try:
            self.rows = self.busy(lambda: self.source.categories(self.scope))
        except Exception as ex:
            self.report_error('Could not collect categories', ex)
            return False
        self.active_category = None
        self.render_categories()
        self.render_families()
        self.update_status()
        return True

    def report_error(self, message, error):
        self._collection_error = '{}: {}'.format(message, error)
        self.use_selection.IsEnabled = False
        self.selection_status.Text = self._collection_error
        forms.alert(self.selection_status.Text, title='KW ReValue Selection')

    def scope_changed(self, sender, args):
        if self._updating:
            return
        new_scope = 'project' if self.scope_toggle.IsChecked else 'view'
        if new_scope == self.scope:
            return
        old_states = self.states[self.scope]
        self.scope = new_scope
        existing_keys = set(self.states[self.scope])
        if not self.load_scope():
            return
        available = set(row.key for row in self.rows)
        dropped = sum(1 for key, state in old_states.items()
                      if state['checked'] and key not in available)
        retained = self.states[self.scope]
        transfers = {}
        removed_families = 0
        for row in self.rows:
            if row.key not in old_states or row.key in existing_keys:
                continue
            old = old_states[row.key]
            selected = set(old['families'])
            if not old['all']:
                try:
                    groups = self.busy(lambda: self.source.families(self.scope, row))
                except Exception as ex:
                    self.rows = []
                    self.render_categories()
                    self.report_error('Could not check families in the new scope', ex)
                    return
                selected.intersection_update(groups)
                removed_families += len(old['families']) - len(selected)
            transfers[row.key] = dict(checked=old['checked'], all=old['all'], families=selected)
        retained.update(transfers)
        self.notice = (
            '{} selected category(s) and {} family choice(s) unavailable in this scope. '
            'Each scope retains its previous choices.').format(dropped, removed_families)
        self.render_categories()
        self.render_families()
        self.update_status()

    def render_categories(self, sender=None, args=None):
        active_key = self.active_category.key if self.active_category else None
        self._updating = True
        try:
            self.category_list.Items.Clear()
            search = self.search_categories.Text.lower()
            for row in self.rows:
                if search not in row.name.lower():
                    continue
                item = ListBoxItem()
                item.Tag = row
                checkbox = CheckBox()
                checkbox.Content = '{} ({})'.format(row.name, row.count)
                checkbox.Margin = Thickness(3)
                checkbox.IsChecked = self.state(row.key)['checked']
                checkbox.Tag = row
                checkbox.Checked += self.category_checked
                checkbox.Unchecked += self.category_checked
                item.Content = checkbox
                self.category_list.Items.Add(item)
                if row.key == active_key:
                    self.category_list.SelectedItem = item
        finally:
            self._updating = False

    def category_checked(self, sender, args):
        if self._updating:
            return
        self.state(sender.Tag.key)['checked'] = bool(sender.IsChecked)
        for item in self.category_list.Items:
            if item.Tag.key == sender.Tag.key:
                self.category_list.SelectedItem = item
                break
        self.update_status()

    def category_changed(self, sender, args):
        if self._updating:
            return
        selected = self.category_list.SelectedItem
        self.active_category = selected.Tag if selected is not None else None
        self.search_families.Text = ''
        if self.active_category is not None:
            try:
                self.busy(lambda: self.source.families(self.scope, self.active_category))
                self._collection_error = None
            except Exception as ex:
                self.report_error('Could not collect families', ex)
                return
        self.render_families()
        self.update_status()

    def render_families(self, sender=None, args=None):
        self._updating = True
        try:
            self.family_list.Items.Clear()
            row = self.active_category
            groups = self.source.family_cache.get((self.scope, row.key)) if row else None
            meaningful = groups is not None and any(name is not None for name in groups)
            self.family_modes.IsEnabled = groups is not None
            self.search_families.IsEnabled = meaningful
            self.family_heading.Text = (
                'Families in {}'.format(row.name) if meaningful else
                'No family grouping - use All families to include this category.'
                if row else 'Families - highlight a category first')
            if not row:
                self.family_toggle.IsChecked = False
                return
            state = self.state(row.key)
            self.family_toggle.IsEnabled = meaningful or not state['all']
            self.family_toggle.IsChecked = not state['all']
            self.family_list.IsEnabled = not state['all'] and meaningful
            search = self.search_families.Text.lower()
            for name in sorted(groups or {}, key=lambda value: (value or '').lower()):
                label = name if name is not None else '<No family>'
                if search not in label.lower() or not meaningful:
                    continue
                checkbox = CheckBox()
                checkbox.Content = '{} ({})'.format(label, len(groups[name]))
                checkbox.Tag = name
                checkbox.Margin = Thickness(3)
                checkbox.IsChecked = name in state['families']
                checkbox.Checked += self.family_checked
                checkbox.Unchecked += self.family_checked
                self.family_list.Items.Add(checkbox)
        finally:
            self._updating = False

    def family_mode_changed(self, sender, args):
        if self._updating or self.active_category is None:
            return
        self.state(self.active_category.key)['all'] = not bool(self.family_toggle.IsChecked)
        self.render_families()
        self.update_status()

    def family_checked(self, sender, args):
        if self._updating or self.active_category is None:
            return
        families = self.state(self.active_category.key)['families']
        if sender.IsChecked:
            families.add(sender.Tag)
        else:
            families.discard(sender.Tag)
        self.update_status()

    def update_status(self):
        if self._collection_error:
            self.use_selection.IsEnabled = False
            self.selection_status.Text = self._collection_error
            return
        total = 0
        invalid = False
        summary = []
        for row in self.rows:
            state = self.state(row.key)
            if not state['checked']:
                continue
            if state['all']:
                total += row.count
                summary.append('{}: All families'.format(row.name))
            else:
                groups = self.source.family_cache.get((self.scope, row.key), {})
                count = sum(len(groups.get(name, [])) for name in state['families'])
                invalid = invalid or not count
                total += count
                summary.append('{}: {} selected family group(s)'.format(
                    row.name, len(state['families'])))
        self.selection_summary.Text = '; '.join(summary)
        self.selection_summary.ToolTip = self.selection_summary.Text
        self.use_selection.IsEnabled = total > 0 and not invalid
        message = 'Matching elements: {}.'.format(total)
        if invalid:
            message += ' Choose at least one family for every restricted category.'
        unsupported = self.source.warnings.get(self.scope, [])
        if unsupported:
            message += ' {} unsupported category(s) omitted; see output.'.format(len(unsupported))
        self.selection_status.Text = '{} {}'.format(message, self.notice).strip()

    def accept(self, sender, args):
        if not self.use_selection.IsEnabled:
            return

        def collect():
            ids = {}
            for row in self.rows:
                state = self.state(row.key)
                if state['checked']:
                    for element_id in self.source.selected_ids(self.scope, row, state):
                        ids[element_id_value(element_id)] = element_id
            elements = [self.source.document.GetElement(ids[key]) for key in sorted(ids)]
            if any(element is None for element in elements):
                raise ValueError('Selected elements are no longer available. Reopen the selector.')
            return elements

        try:
            elements = self.busy(collect)
        except Exception as ex:
            self.report_error('Could not collect the selection', ex)
            return
        if not elements:
            self.report_error('No matching elements', 'Change the scope or category/family choices.')
            return
        self.result = elements
        self.window.DialogResult = True

    def cancel(self, sender, args):
        self.window.DialogResult = False

    def show(self):
        self.window.ShowDialog()
        return self.result


def select_by_categories(document, active_view):
    return CategoryPicker(CategorySource(document, active_view)).show()
