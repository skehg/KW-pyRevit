"""Run with an IronPython 2.7 WPF host, not CPython unittest discovery."""
import os
import sys

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

sys.dont_write_bytecode = True
COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)

from System.Windows import RoutedEventArgs
from System.Windows.Controls import Button


def install_stubs():
    saved = {}
    for name in ('Autodesk', 'Autodesk.Revit', 'Autodesk.Revit.Exceptions',
                 'pyrevit', 'pyrevit.compat'):
        saved[name] = sys.modules.get(name)
        sys.modules[name] = type(sys)(name)
    sys.modules['Autodesk'].Revit = sys.modules['Autodesk.Revit']
    sys.modules['Autodesk.Revit'].DB = type(sys)('DB')
    sys.modules['Autodesk.Revit.Exceptions'].ArgumentException = ValueError
    alerts = []
    forms = type(sys)('forms')
    forms.alert = lambda message, **kwargs: alerts.append(message)
    sys.modules['pyrevit'].forms = forms
    sys.modules['pyrevit.compat'].get_elementid_value_func = lambda: lambda value: value
    return saved, alerts


saved_modules, alerts = install_stubs()
try:
    from category_selection import CategoryPicker
finally:
    for name, original in saved_modules.items():
        if original is None:
            del sys.modules[name]
        else:
            sys.modules[name] = original


class Row(object):
    def __init__(self, key, name, count):
        self.key = key
        self.name = name
        self.count = count


class Source(object):
    def __init__(self, view_available=True):
        self.view_available = view_available
        self.warnings = {}
        self.family_cache = {}
        self.calls = []
        self.document = self
        self.fail_categories = False
        self.fail_families = False
        self.stale = False
        self.groups = {
            ('view', 1): {'Single': [10]},
            ('view', 2): {None: [14]},
            ('project', 1): {'Single': [10, 11], 'Double': [12]},
            ('project', 2): {None: [14]},
            ('project', 3): {'Basic Wall': [13]},
        }

    def categories(self, scope):
        self.calls.append(('categories', scope))
        if self.fail_categories:
            raise ValueError('Test category failure')
        return ([Row(1, 'Doors', 1), Row(2, 'Sheets', 1)] if scope == 'view'
                else [Row(1, 'Doors', 3), Row(2, 'Sheets', 1), Row(3, 'Walls', 1)])

    def families(self, scope, row):
        if self.fail_families:
            raise ValueError('Test family failure')
        key = (scope, row.key)
        if key not in self.family_cache:
            self.calls.append(('families', scope, row.key))
            self.family_cache[key] = self.groups[key]
        return self.family_cache[key]

    def selected_ids(self, scope, row, state):
        groups = self.groups[(scope, row.key)]
        return [value for name, ids in groups.items()
                if state['all'] or name in state['families'] for value in ids]

    def GetElement(self, element_id):
        return None if self.stale else element_id


def category_checkbox(picker, key):
    return next(item.Content for item in picker.category_list.Items if item.Tag.key == key)


def family_checkbox(picker, name):
    return next(item for item in picker.family_list.Items if item.Tag == name)


def click(button):
    button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))


def run_checks():
    source = Source()
    picker = CategoryPicker(source)
    picker.loaded(None, None)
    assert picker.scope == 'view'
    assert len(picker.category_list.Items) == 2
    assert not picker.use_selection.IsEnabled
    assert source.calls == [('categories', 'view')]
    category_checkbox(picker, 1).IsChecked = True
    assert picker.active_category.key == 1
    assert picker.use_selection.IsEnabled
    assert ('view', 1) in source.family_cache
    assert ('view', 2) not in source.family_cache
    assert 'Matching elements: 1.' in picker.selection_status.Text
    picker.selected_families.IsChecked = True
    assert not picker.use_selection.IsEnabled
    family_checkbox(picker, 'Single').IsChecked = True
    assert picker.use_selection.IsEnabled
    calls = list(source.calls)
    picker.search_families.Text = 'not found'
    assert picker.family_list.Items.Count == 0
    assert picker.state(1)['families'] == set(['Single'])
    assert picker.use_selection.IsEnabled
    assert source.calls == calls
    picker.search_categories.Text = 'Sheets'
    assert picker.category_list.Items.Count == 1
    assert picker.use_selection.IsEnabled
    picker.search_categories.Text = ''
    assert category_checkbox(picker, 1).IsChecked
    assert picker.state(1)['all'] is False
    assert source.calls == calls

    picker.scope_project.IsChecked = True
    assert picker.scope == 'project'
    assert picker.state(1)['checked']
    assert picker.state(1)['families'] == set(['Single'])
    assert picker.state(1)['all'] is False
    assert 'Matching elements: 2.' in picker.selection_status.Text
    picker.category_list.SelectedItem = next(
        item for item in picker.category_list.Items if item.Tag.key == 1)
    picker.search_families.Text = ''
    family_checkbox(picker, 'Single').IsChecked = False
    family_checkbox(picker, 'Double').IsChecked = True
    assert 'Matching elements: 1.' in picker.selection_status.Text
    category_checkbox(picker, 3).IsChecked = True
    picker.scope_view.IsChecked = True
    assert picker.state(1)['families'] == set(['Single'])
    assert '1 selected category(s)' in picker.notice
    picker.scope_project.IsChecked = True
    assert picker.state(1)['families'] == set(['Double'])
    assert picker.state(3)['checked']
    calls = list(source.calls)
    picker.scope_view.IsChecked = True
    picker.scope_project.IsChecked = True
    assert not any(call[0] == 'families' for call in source.calls[len(calls):])

    # Starting in Project scope exercises a restricted first visit to View.
    restricted = CategoryPicker(Source())
    restricted._updating = True
    restricted.scope = 'project'
    restricted.scope_project.IsChecked = True
    restricted._updating = False
    restricted.load_scope()
    restricted.states['project'][1] = dict(
        checked=True, all=False, families=set(['Double']))
    restricted.scope_view.IsChecked = True
    assert restricted.state(1)['families'] == set()
    assert not restricted.state(1)['all']
    assert not restricted.use_selection.IsEnabled
    assert '1 family choice(s) unavailable' in restricted.notice
    restricted.category_list.SelectedItem = restricted.category_list.Items[0]
    assert not restricted.state(1)['all']
    assert not restricted.use_selection.IsEnabled
    restricted.all_families.IsChecked = True
    assert restricted.use_selection.IsEnabled

    # A category losing meaningful family grouping must not broaden a restriction.
    ungrouped = CategoryPicker(Source())
    ungrouped.load_scope()
    ungrouped.source.family_cache[('view', 1)] = {None: [10]}
    ungrouped.states['view'][1] = dict(
        checked=True, all=False, families=set(['Missing']))
    ungrouped.category_list.SelectedItem = ungrouped.category_list.Items[0]
    assert not ungrouped.state(1)['all']
    assert not ungrouped.use_selection.IsEnabled
    ungrouped.all_families.IsChecked = True
    assert ungrouped.use_selection.IsEnabled

    no_family = CategoryPicker(Source())
    no_family.load_scope()
    category_checkbox(no_family, 2).IsChecked = True
    assert no_family.state(2)['all']
    assert not no_family.selected_families.IsEnabled
    assert no_family.use_selection.IsEnabled

    unavailable = CategoryPicker(Source(False))
    unavailable.load_scope()
    assert unavailable.scope == 'project'
    assert not unavailable.scope_view.IsEnabled
    assert 'Current View is unavailable' in unavailable.selection_status.Text

    failure = CategoryPicker(Source())
    failure.load_scope()
    category_checkbox(failure, 1).IsChecked = True
    failure.source.fail_categories = True
    failure.scope_project.IsChecked = True
    failure.update_status()
    assert not failure.use_selection.IsEnabled
    assert len(failure.rows) == 0
    assert 'Test category failure' in failure.selection_status.Text
    failure.source.fail_categories = False
    failure.scope_view.IsChecked = True
    assert failure.use_selection.IsEnabled
    failure.source.fail_families = True
    category_checkbox(failure, 2).IsChecked = True
    failure.update_status()
    assert not failure.use_selection.IsEnabled
    assert 'Test family failure' in failure.selection_status.Text
    failure.source.fail_families = False
    failure.category_list.SelectedItem = failure.category_list.Items[0]
    assert failure.use_selection.IsEnabled

    accepted = CategoryPicker(Source())

    def accept_on_load(sender, args):
        category_checkbox(accepted, 1).IsChecked = True
        category_checkbox(accepted, 2).IsChecked = True
        click(accepted.use_selection)

    accepted.window.Loaded += accept_on_load
    assert accepted.show() == [10, 14]
    assert accepted.window.DialogResult

    cancelled = CategoryPicker(Source())
    cancelled.window.Loaded += lambda sender, args: click(cancelled.cancel_selection)
    assert cancelled.show() is None
    assert cancelled.window.DialogResult is False

    stale = CategoryPicker(Source())
    stale.load_scope()
    category_checkbox(stale, 1).IsChecked = True
    stale.source.stale = True
    stale.accept(None, None)
    assert stale.result is None
    assert not stale.use_selection.IsEnabled
    assert 'no longer available' in stale.selection_status.Text
    assert len(alerts) == 3
