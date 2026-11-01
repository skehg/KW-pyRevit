import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FilterElement(object):
    def __init__(self, name):
        self.Name = name

    def GetTypeId(self):
        raise AssertionError('Filters must never resolve a type')

    def LookupParameter(self, name):
        raise AssertionError('Filters must never read a parameter')

    @property
    def Parameters(self):
        raise AssertionError('Filters must never collect parameters')


class Event(object):
    def __iadd__(self, handler):
        return self


class Rows(list):
    @property
    def Count(self):
        return len(self)

    def Add(self, item):
        self.append(item)

    def Clear(self):
        del self[:]


class Generic(object):
    def __init__(self, value):
        self.value = value

    def __getitem__(self, item):
        return self.value


class Control(object):
    def __init__(self):
        self.Text = ''
        self.Items = Rows()
        self.SelectedItem = None
        self.IsChecked = False
        self.IsEnabled = True
        self.IsExpanded = False
        self.Parent = types.SimpleNamespace(Visibility='visible')
        for name in ('Click', 'TextChanged', 'SelectionChanged', 'Checked',
                     'Unchecked', 'SelectedCellsChanged', 'Sorting', 'Expanded',
                     'Collapsed'):
            setattr(self, name, Event())

    @property
    def SelectedIndex(self):
        return self.Items.index(self.SelectedItem) if self.SelectedItem in self.Items else -1

    @SelectedIndex.setter
    def SelectedIndex(self, index):
        self.SelectedItem = self.Items[index] if 0 <= index < len(self.Items) else None

    def FindResource(self, name):
        return name


class Grid(Control):
    def __init__(self):
        super(Grid, self).__init__()
        self.SelectedCells = []
        self.view = types.SimpleNamespace(Filter=lambda row: True, Refresh=mock.Mock())
        self.CommitEdit = mock.Mock(return_value=True)

    @property
    def Items(self):
        return Rows(row for row in self.ItemsSource if self.view.Filter(row))

    @Items.setter
    def Items(self, value):
        pass


def module(name, **members):
    result = types.ModuleType(name)
    result.__dict__.update(members)
    return result


class FilterNameTests(unittest.TestCase):
    def setUp(self):
        self.controls = {}

        def find_control(name):
            if name not in self.controls:
                control = Grid() if name == 'preview_grid' else Control()
                if name == 'combo_final_case':
                    control.Items.extend(['None', 'upper', 'lower', 'title', 'sentence'])
                self.controls[name] = control
            return self.controls[name]

        self.window = mock.Mock(IsVisible=True)
        self.window.FindName.side_effect = find_control
        enum_property = types.SimpleNamespace(
            PropertyType=types.SimpleNamespace(GetGenericArguments=lambda: ['sort']))
        self.forms = mock.Mock()
        self.settings = mock.Mock()
        self.settings.get_envvar.side_effect = lambda key: {
            'KWReValue_mode': 'type',
            'KWReValue_orig_param': 'Comments',
            'KWReValue_param1': 'Type Mark',
            'KWReValue_pattern': 'UNSAFE_{param1}',
            'KWReValue_sort_mode': 'param',
            'KWReValue_sort_param': 'Comments',
        }.get(key)
        self.selection = mock.Mock()
        self.document = mock.Mock()
        self.revit = mock.Mock()
        self.token_editor = mock.Mock()

        def get_view(rows):
            return self.controls['preview_grid'].view

        stubs = {
            'clr': module('clr', AddReference=mock.Mock(), GetClrType=lambda cls:
                          types.SimpleNamespace(GetProperty=lambda name: enum_property)),
            'System': module('System', Enum=types.SimpleNamespace(Parse=lambda cls, value: value),
                             Predicate=Generic(lambda value: value)),
            'System.Windows': module(
                'System.Windows', Window=mock.Mock(), GridLength=mock.Mock(),
                GridUnitType=mock.Mock(),
                Visibility=types.SimpleNamespace(Collapsed='collapsed', Visible='visible')),
            'System.Windows.Controls': module(
                'System.Windows.Controls', ComboBoxItem=Control, DataGridColumn=Control,
                DataGridEditingUnit=types.SimpleNamespace(Cell='cell', Row='row'),
                TextBox=Control),
            'System.Windows.Data': module(
                'System.Windows.Data',
                CollectionViewSource=types.SimpleNamespace(GetDefaultView=get_view)),
            'System.Windows.Input': module('System.Windows.Input', Mouse=mock.Mock()),
            'System.Windows.Media': module('System.Windows.Media', VisualTreeHelper=mock.Mock()),
            'System.Collections.ObjectModel': module(
                'System.Collections.ObjectModel', ObservableCollection=Generic(Rows)),
            'System.Globalization': module(
                'System.Globalization', CultureInfo=types.SimpleNamespace(
                    CurrentCulture=types.SimpleNamespace(NumberFormat=types.SimpleNamespace(
                        NumberDecimalSeparator='.', NumberGroupSeparator=',')))),
            'Autodesk.Revit.DB': module('Autodesk.Revit.DB', FilterElement=FilterElement),
            'Autodesk.Revit.UI.Selection': module(
                'Autodesk.Revit.UI.Selection', ObjectType=mock.Mock()),
            'Autodesk.Revit.Exceptions': module(
                'Autodesk.Revit.Exceptions', OperationCanceledException=RuntimeError),
            'pyrevit': module('pyrevit', revit=self.revit, forms=self.forms,
                              script=self.settings),
            'pyrevit.compat': module(
                'pyrevit.compat', get_elementid_value_func=lambda: lambda value: value),
            'ui_styles': module('ui_styles', load_window=mock.Mock(return_value=self.window)),
            'token_editor': module('token_editor', TokenEditor=self.token_editor),
        }
        patch = mock.patch.dict(sys.modules, stubs)
        patch.start()
        self.addCleanup(patch.stop)
        path = os.path.join(COMMAND_DIR, 'script.py')
        spec = importlib.util.spec_from_file_location('revalue_filter_name_test', path)
        self.script = importlib.util.module_from_spec(spec)
        self.script.basestring = str
        self.script.__revit__ = types.SimpleNamespace(
            ActiveUIDocument=types.SimpleNamespace(
                Document=self.document, Selection=self.selection))
        spec.loader.exec_module(self.script)
        self.elements = [FilterElement('Wall-A'), FilterElement('Wall-B')]
        self.writer = mock.Mock(side_effect=self.write_names)

    def write_names(self, approved):
        for element, name in approved.items():
            element.Name = name

    def dialog(self):
        return self.script.ReValueDialog(
            self.elements, launch_context='filter_names', rename_writer=self.writer)

    def proposed_dialog(self):
        dialog = self.dialog()
        dialog.txt_find.Text = 'Wall'
        dialog.txt_replace.Text = 'Facade'
        dialog.OnSettingsChanged(None, None)
        return dialog

    def test_import_does_not_launch_ribbon_select_or_write(self):
        self.selection.assert_not_called()
        self.assertEqual([], self.selection.mock_calls)
        self.forms.assert_not_called()
        self.assertEqual([], self.forms.mock_calls)
        self.window.ShowDialog.assert_not_called()
        self.window.FindName.assert_not_called()
        self.document.GetElement.assert_not_called()
        self.settings.get_envvar.assert_not_called()
        self.revit.update.set_name.assert_not_called()

    def test_explicit_context_ignores_saved_modes_sources_parameters_and_patterns(self):
        dialog = self.dialog()
        self.assertEqual(self.elements, [row.Element for row in dialog.preview_items])
        self.assertEqual(['Wall-A', 'Wall-B'], [row.CurrentName for row in dialog.preview_items])
        self.assertEqual(['Wall-A', 'Wall-B'], [row.NewName for row in dialog.preview_items])
        self.assertEqual('{orig}', dialog.txt_pattern.Text)
        self.assertEqual([], dialog.available_params)
        self.assertEqual('<Filter Name>', dialog.default_source_item.Content)
        self.assertEqual('none', dialog.sort_mode)
        self.assertFalse(dialog.btn_mode.IsEnabled)
        self.assertEqual('collapsed', dialog.btn_mode.Parent.Visibility)
        self.assertFalse(dialog.combo_orig_param.IsEnabled)
        self.assertTrue(all(not combo.IsEnabled for combo in dialog.param_combos))
        self.assertFalse(dialog.btn_edit_filters.IsEnabled)
        self.settings.get_envvar.assert_not_called()
        self.settings.set_envvar.assert_not_called()
        self.document.GetElement.assert_not_called()

    def test_mode_parameter_source_and_python_filters_cannot_redirect_names(self):
        dialog = self.dialog()
        dialog.btn_mode.IsChecked = False
        dialog.OnModeChanged(None, None)
        dialog.combo_orig_param.SelectedItem = 'Comments'
        dialog.param_combos[0].SelectedItem = 'Type Mark'
        dialog.parameter_filter = {'invalid': 'saved expression'}
        dialog.OnEditFilters(None, None)
        dialog.update_preview()
        self.assertEqual('', dialog.get_selected_original_param_name())
        self.assertEqual([''] * 5, dialog.get_selected_param_values(self.elements[0]))
        self.assertIsNone(dialog._lookup_parameter(self.elements[0], 'Comments'))
        self.assertEqual('Wall-A', dialog.get_original_source_text(self.elements[0]))
        self.assertIsNone(dialog.parameter_filter)
        self.assertEqual(2, dialog.preview_grid.Items.Count)
        self.settings.set_envvar.assert_not_called()

    def test_token_find_replace_case_preview_and_apply_require_explicit_approval(self):
        dialog = self.dialog()
        dialog.txt_pattern.Text = '{val1}_{end}'
        dialog.txt_find.Text = 'Wall'
        dialog.txt_replace.Text = 'Facade'
        dialog.combo_final_case.SelectedIndex = 1
        dialog.OnSettingsChanged(None, None)
        self.assertEqual(['FACADE_A', 'FACADE_B'], [row.NewName for row in dialog.preview_items])
        self.writer.assert_not_called()
        dialog.OnApply(None, None)
        self.writer.assert_called_once_with(dict(zip(self.elements, ['FACADE_A', 'FACADE_B'])))
        self.assertTrue(dialog.applied)
        self.assertEqual(['FACADE_A', 'FACADE_B'], [row.CurrentName for row in dialog.preview_items])
        self.assertEqual('', dialog.txt_find.Text)
        self.window.Close.assert_not_called()
        self.document.GetElement.assert_not_called()
        self.assertEqual([], self.revit.mock_calls)
        self.settings.set_envvar.assert_not_called()

    def test_only_visible_changed_rows_are_passed_as_native_keys(self):
        dialog = self.proposed_dialog()
        dialog.txt_filter_current.Text = 'Wall-A'
        dialog.OnPreviewFilterChanged(dialog.txt_filter_current, None)
        dialog.preview_items[0].final = True
        dialog.OnApply(None, None)
        self.writer.assert_called_once_with({self.elements[0]: 'Facade-A'})
        self.assertEqual('Wall-B', self.elements[1].Name)
        self.assertEqual('Wall-A', dialog.txt_filter_current.Text)

    def test_new_value_filter_or_uncommitted_edits_prevent_callback(self):
        dialog = self.proposed_dialog()
        dialog.txt_filter_new.Text = 'Facade'
        dialog.OnApply(None, None)
        self.writer.assert_not_called()
        dialog.txt_filter_new.Text = ''
        dialog.preview_grid.CommitEdit.return_value = False
        dialog.OnApply(None, None)
        self.writer.assert_not_called()
        self.assertFalse(dialog.applied)

    def test_name_errors_duplicates_stale_ids_and_ownership_fail_without_success(self):
        for error in ('Invalid name', 'Duplicate filter name', 'Stale ID', 'Not owned'):
            with self.subTest(error=error):
                dialog = self.proposed_dialog()
                self.writer.reset_mock()
                self.forms.reset_mock()
                self.writer.side_effect = ValueError(error)
                dialog.preview_items[0].final = True
                dialog.OnApply(None, None)
                self.writer.assert_called_once()
                self.assertFalse(dialog.applied)
                self.assertEqual('Wall', dialog.txt_find.Text)
                self.assertEqual('Facade', dialog.txt_replace.Text)
                self.assertEqual('Wall-A', dialog.preview_items[0].CurrentName)
                self.assertEqual('Facade-A', dialog.preview_items[0].NewName)
                self.assertTrue(dialog.preview_items[0].final)
                self.forms.alert.assert_called_once_with('Could not rename filters: ' + error)
                self.window.Activate.assert_called()
                self.window.Focus.assert_called()
                self.settings.set_envvar.assert_not_called()

    def test_blank_and_duplicate_proposals_reach_atomic_validator(self):
        dialog = self.dialog()
        dialog.preview_items[0].NewName = ''
        dialog.preview_items[1].NewName = ''
        self.writer.side_effect = ValueError('Empty names')
        dialog.OnApply(None, None)
        self.writer.assert_called_once_with(dict.fromkeys(self.elements, ''))
        self.assertFalse(dialog.applied)
        self.writer.reset_mock()
        for row in dialog.preview_items:
            row.NewName = 'Same name'
        self.writer.side_effect = ValueError('Duplicate names')
        dialog.OnApply(None, None)
        self.writer.assert_called_once_with(dict.fromkeys(self.elements, 'Same name'))
        self.assertFalse(dialog.applied)

    def test_false_callback_return_is_not_success(self):
        dialog = self.proposed_dialog()
        self.writer.side_effect = None
        self.writer.return_value = False
        dialog.OnApply(None, None)
        self.assertFalse(dialog.applied)
        self.assertEqual('Wall', dialog.txt_find.Text)
        self.forms.alert.assert_called_once_with('Filter rename was not completed.')

    def test_close_does_not_apply_and_entry_returns_any_successful_apply(self):
        dialog = self.proposed_dialog()
        dialog.OnClose(None, None)
        self.writer.assert_not_called()
        with mock.patch.object(self.script, 'ReValueDialog', return_value=dialog) as constructor:
            self.assertFalse(self.script.show_filter_names(iter(self.elements), self.writer))
            constructor.assert_called_once_with(
                self.elements, launch_context='filter_names', rename_writer=self.writer)
            dialog.applied = True
            self.assertTrue(self.script.show_filter_names(self.elements, self.writer))

    def test_entry_rejects_non_native_rows_missing_writer_and_empty_input(self):
        with self.assertRaises(TypeError):
            self.script.show_filter_names([types.SimpleNamespace(Name='Wall')], self.writer)
        with self.assertRaises(TypeError):
            self.script.show_filter_names(self.elements, None)
        self.assertFalse(self.script.show_filter_names([], self.writer))
        self.window.ShowDialog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
