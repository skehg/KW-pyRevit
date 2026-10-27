import ast
import io
import os
import re
import sys
import unittest
import types
from unittest import mock
from decimal import Decimal, InvalidOperation


COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)
from filter_expression import (
    count_rules, evaluate_expression, parse_expression, rule,
    serialize_expression, validate_expression,
)
with io.open(os.path.join(COMMAND_DIR, 'script.py'), encoding='utf-8') as source:
    SCRIPT_TREE = ast.parse(source.read())


def load_preview_classes():
    """Load preview logic without importing the Revit or WPF runtimes."""
    module = ast.parse('')
    dialog_methods = ('matches_preview_filters', 'get_revalue_map',
                      'OnPreviewFilterChanged', 'OnMoreSettingsChanged',
                      'populate_source_parameters', 'get_original_source_text',
                      'get_selected_original_param_name', 'refresh_preview_filters',
                      '_selected_combo_text', '_pattern_uses_counter',
                      'commit_preview_edits', 'OnApply', 'OnClose',
                      'OnUseOriginal', 'OnSettingsChanged', 'update_preview',
                      'OnClearFilters', 'OnEditFilters')
    for node in SCRIPT_TREE.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in (
                    'FILTER_CONDITIONS', 'NUMERIC_FILTER_CONDITIONS')
                for target in node.targets):
            module.body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in (
                'replace_final_value', 'apply_case_conversion',
                '_split_case_modifier', 'get_default_source_label',
                '_resolve_target_param_name', 'parse_filter_number',
                'matches_parameter_filter', 'compare_filter_rule'):
            module.body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == 'PreviewItem':
            module.body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == 'ReValueDialog':
            node = ast.ClassDef(
                name=node.name, bases=node.bases, keywords=[],
                body=[method for method in node.body
                      if isinstance(method, ast.FunctionDef)
                      and method.name in dialog_methods],
                decorator_list=[])
            module.body.append(node)
    ast.fix_missing_locations(module)
    namespace = {
        'DataGridEditingUnit': EditingUnit,
        'GridLength': GridLength,
        'GridUnitType': GridUnitType,
        'ComboBoxItem': LayoutPart,
        'View': View,
        'ViewSheet': ViewSheet,
        'ElementType': ElementType,
        '_safe_element_name': lambda element: getattr(element, 'name', ''),
        '_safe_type_name': lambda element: getattr(element, 'name', ''),
        '_get_element_type': lambda element: getattr(element, 'element_type', None),
        're': re,
        'basestring': str,
        'Decimal': Decimal,
        'InvalidOperation': InvalidOperation,
        'count_rules': count_rules,
        'evaluate_expression': evaluate_expression,
        'serialize_expression': serialize_expression,
        'validate_expression': validate_expression,
        'apply_pattern': lambda value, *args: value,
    }
    exec(compile(module, '<preview logic>', 'exec'), namespace)
    return namespace['PreviewItem'], namespace['ReValueDialog']


def load_pattern_function():
    """Load the pattern parser without importing Revit or WPF runtimes."""
    function_names = {
        '_alpha_to_int', '_int_to_alpha', '_increment_value',
        '_parse_val_expression', '_resolve_window',
        '_parse_progression_expression', '_resolve_progression_source',
        '_split_case_modifier', 'apply_case_conversion', 'apply_pattern',
    }
    module = ast.Module(body=[
        node for node in SCRIPT_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        're': re,
        'basestring': str,
        'VAL_EXPR_REGEX': re.compile(r'\{([^{}]+)\}'),
        'NUMERIC_REGEX': re.compile(r'^\d+$'),
        'ALPHA_REGEX': re.compile(r'^[A-Za-z]+$'),
        'MIXED_SUFFIX_NUM_REGEX': re.compile(r'^(.*?)(\d+)$'),
        'SIGNED_NUMERIC_REGEX': re.compile(r'^-?\d+$'),
        'SIGNED_SUFFIX_NUM_REGEX': re.compile(r'^(.*?)(-?\d+)$'),
        'PROGRESSION_SOURCE_REGEX': re.compile(
            r'^(val[1-9]\d*|param[1-5])$', re.IGNORECASE),
        'NAMED_DELIMS': {
            'space': ' ',
            'hyphen': '-',
            'underscore': '_',
        },
        'CASE_MODIFIERS': ('upper', 'lower', 'title', 'sentence'),
    }
    exec(compile(module, '<pattern logic>', 'exec'), namespace)
    return namespace


class EditingUnit(object):
    Cell = 'cell'
    Row = 'row'


class GridUnitType(object):
    Star = 'star'


class GridLength(object):
    Auto = 'auto'

    def __init__(self, value, unit):
        self.Value = value
        self.GridUnitType = unit


class LayoutPart(object):
    pass


class View(object):
    pass


class ViewSheet(View):
    pass


class ElementType(object):
    pass


class ComboItems(list):
    def Clear(self):
        del self[:]

    def Add(self, item):
        self.append(item)


class SourceCombo(object):
    def __init__(self):
        self.Items = ComboItems()
        self.SelectedItem = None

    @property
    def SelectedIndex(self):
        return self.Items.index(self.SelectedItem)

    @SelectedIndex.setter
    def SelectedIndex(self, index):
        self.SelectedItem = self.Items[index]


class TextBox(object):
    def __init__(self, text=''):
        self.Text = text


class GridItems(object):
    def __init__(self, rows, predicate):
        self.rows = rows
        self.predicate = predicate
        self.Refresh()

    def Refresh(self):
        self.visible = [row for row in self.rows if self.predicate(row)]

    def __iter__(self):
        return iter(self.visible)

    @property
    def Count(self):
        return len(self.visible)


class Grid(object):
    def __init__(self, rows, predicate):
        self.Items = GridItems(rows, predicate)
        self.commits = []

    def CommitEdit(self, unit, exit_editing):
        self.commits.append((unit, exit_editing))
        return True


PreviewItem, ReValueDialog = load_preview_classes()
replace_final_value = PreviewItem.format_value.__globals__['replace_final_value']
get_default_source_label = PreviewItem.format_value.__globals__['get_default_source_label']
resolve_target = PreviewItem.format_value.__globals__['_resolve_target_param_name']
matches_parameter_filter = PreviewItem.format_value.__globals__['matches_parameter_filter']
parse_filter_number = PreviewItem.format_value.__globals__['parse_filter_number']


class DefaultSourceTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ReValueDialog()
        self.dialog.elements = [View()]
        self.dialog.is_instance_mode = True
        self.dialog.available_params = ['View Name', '<Default: View Name>', '[Code]']
        self.dialog.combo_orig_param = SourceCombo()
        self.dialog.get_param_value = lambda element, parameter: 'value:' + parameter
        self.dialog.populate_source_parameters('')

    def test_type_mode_always_identifies_type_name(self):
        self.assertEqual('<Default: Type Name>',
                         get_default_source_label([View(), object()], False))

    def test_instance_defaults_follow_selection(self):
        for elements, expected in [
                ([View(), View()], '<Default: View Name>'),
                ([ViewSheet(), ViewSheet()], '<Default: Sheet Name>'),
                ([ViewSheet(), View()], '<Default: Name (varies by element)>'),
                ([ElementType()], '<Default: Type Name>'),
                ([object()], '<Default: Name>'),
                ([View(), object()], '<Default: Name (varies by element)>'),
                ([], '<Default: Name>')]:
            self.assertEqual(expected, get_default_source_label(elements, True))

    def test_default_is_selected_and_is_not_a_write_parameter(self):
        self.assertEqual('<Default: View Name>',
                         self.dialog.combo_orig_param.SelectedItem.Content)
        self.assertEqual('', self.dialog.get_selected_original_param_name())
        self.assertEqual('', resolve_target(
            self.dialog.get_selected_original_param_name()))

    def test_sheets_display_sheet_name_without_changing_source_or_target(self):
        sheet = ViewSheet()
        sheet.name = 'Ground Floor Plan'
        self.dialog.elements = [sheet]
        self.dialog.populate_source_parameters('')
        self.assertEqual('<Default: Sheet Name>',
                         self.dialog.combo_orig_param.SelectedItem.Content)
        self.assertEqual('Ground Floor Plan',
                         self.dialog.get_original_source_text(sheet))
        self.assertEqual('', self.dialog.get_selected_original_param_name())

    def test_instance_using_type_name_displays_type_name_in_both_modes(self):
        element = LayoutPart()
        element.name = 'Basic Wall'
        element.element_type = ElementType()
        element.element_type.name = 'Basic Wall'
        self.dialog.elements = [element]
        for instance_mode in (False, True):
            self.dialog.is_instance_mode = instance_mode
            self.dialog.populate_source_parameters('')
            self.assertEqual('<Default: Type Name>',
                             self.dialog.combo_orig_param.SelectedItem.Content)
            self.assertEqual('', self.dialog.get_selected_original_param_name())
        self.assertEqual('Basic Wall', self.dialog.get_original_source_text(element))

    def test_distinct_instance_name_is_not_labelled_as_type_name(self):
        element = LayoutPart()
        element.name = 'Instance Name'
        element.element_type = ElementType()
        element.element_type.name = 'Type Name'
        self.assertEqual('<Default: Name>',
                         get_default_source_label([element], True))

    def test_views_keep_view_name_even_if_it_matches_the_type(self):
        element = View()
        element.name = 'Plan'
        element.element_type = ElementType()
        element.element_type.name = 'Plan'
        self.assertEqual('<Default: View Name>',
                         get_default_source_label([element], True))

    def test_mixed_views_and_type_named_instances_keep_mixed_label(self):
        element = LayoutPart()
        element.name = 'Basic Wall'
        element.element_type = ElementType()
        element.element_type.name = 'Basic Wall'
        self.assertEqual('<Default: Name (varies by element)>',
                         get_default_source_label([View(), element], True))

    def test_empty_type_name_does_not_infer_type_source(self):
        element = LayoutPart()
        element.name = ''
        element.element_type = ElementType()
        element.element_type.name = ''
        self.assertEqual('<Default: Name>',
                         get_default_source_label([element], True))

    def test_default_preview_uses_element_name(self):
        element = View()
        element.name = 'Floor Plan'
        self.assertEqual('Floor Plan', self.dialog.get_original_source_text(element))

    def test_default_preview_uses_type_name_in_type_mode(self):
        self.dialog.is_instance_mode = False
        self.dialog.populate_source_parameters('')
        element = ElementType()
        element.name = 'Wall Type'
        self.assertEqual('Wall Type', self.dialog.get_original_source_text(element))

    def test_actual_parameter_can_have_same_text_as_default(self):
        self.dialog.populate_source_parameters('<Default: View Name>')
        self.assertEqual('<Default: View Name>',
                         self.dialog.get_selected_original_param_name())
        self.assertEqual('value:<Default: View Name>',
                         self.dialog.get_original_source_text(View()))

    def test_bracketed_real_parameter_is_preserved(self):
        self.dialog.populate_source_parameters('[Code]')
        self.assertEqual('[Code]', self.dialog.get_selected_original_param_name())
        self.assertEqual('[Code]', resolve_target(
            self.dialog.get_selected_original_param_name()))

    def test_mode_change_rebuilds_label_without_duplicate_options(self):
        self.dialog.is_instance_mode = False
        self.dialog.populate_source_parameters('')
        self.assertEqual('<Default: Type Name>',
                         self.dialog.combo_orig_param.SelectedItem.Content)
        self.assertEqual(4, len(self.dialog.combo_orig_param.Items))

    def test_saved_parameter_is_restored_and_unavailable_one_uses_default(self):
        self.dialog.populate_source_parameters('View Name')
        self.assertEqual('View Name', self.dialog.get_selected_original_param_name())
        self.assertEqual('value:View Name',
                         self.dialog.get_original_source_text(View()))
        self.dialog.populate_source_parameters('Missing parameter')
        self.assertEqual('', self.dialog.get_selected_original_param_name())


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ReValueDialog()
        self.dialog.more_settings = LayoutPart()
        self.dialog.settings_row = LayoutPart()
        self.dialog.preview_row = LayoutPart()

    def test_expanding_allocates_resizable_settings_space(self):
        self.dialog.more_settings.IsExpanded = True
        self.dialog.OnMoreSettingsChanged(None, None)
        self.assertEqual(2, self.dialog.settings_row.Height.Value)
        self.assertEqual('star', self.dialog.settings_row.Height.GridUnitType)
        self.assertEqual(3, self.dialog.preview_row.Height.Value)

    def test_collapsing_reclaims_space_after_splitter_resize(self):
        self.dialog.settings_row.Height = 'dragged settings height'
        self.dialog.preview_row.Height = 'dragged preview height'
        self.dialog.more_settings.IsExpanded = False
        self.dialog.OnMoreSettingsChanged(None, None)
        self.assertEqual('auto', self.dialog.settings_row.Height)
        self.assertEqual(3, self.dialog.preview_row.Height.Value)
        self.assertEqual('star', self.dialog.preview_row.Height.GridUnitType)


class RepeatedApplyTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ReValueDialog()
        self.dialog.window = mock.Mock()
        self.dialog.is_instance_mode = True
        self.dialog._suspend_events = False
        self.dialog._parameter_filter_error = ''
        self.dialog.txt_pattern = TextBox('{orig}')
        self.dialog.btn_use_orig = types.SimpleNamespace(IsChecked=False)
        self.dialog._pattern_before_original = None
        self.dialog.txt_find = TextBox('Door')
        self.dialog.txt_replace = TextBox('Entry')
        self.dialog.chk_match_case = types.SimpleNamespace(IsChecked=True)
        self.dialog.chk_match_whole_word = types.SimpleNamespace(IsChecked=False)
        self.dialog._selected_final_case = lambda: 'None'
        self.dialog.get_selected_original_param_name = lambda: ''
        self.dialog.get_tokenizer_func = lambda: lambda value: value.split('-')
        self.dialog.get_counter_generator = lambda: (None, None)
        self.dialog.get_selected_param_values = lambda element: []
        self.dialog.update_tokenization_display = mock.Mock()
        self.dialog.persist_settings = mock.Mock()
        self.dialog.preview_items = []
        for name in ('Door-A', 'Door-B'):
            element = LayoutPart()
            element.name = name
            self.dialog.preview_items.append(PreviewItem(element, name))
        self.dialog.txt_filter_current = TextBox()
        self.dialog.txt_filter_new = TextBox()
        self.dialog.preview_grid = Grid(
            self.dialog.preview_items, self.dialog.matches_preview_filters)
        self.dialog.refresh_preview_filters = mock.Mock(
            side_effect=self.dialog.preview_grid.Items.Refresh)
        self.globals = ReValueDialog.OnApply.__globals__
        patch = mock.patch.dict(self.globals, {
            'forms': mock.Mock(),
            'revalue_elements': mock.Mock(side_effect=self.apply_to_model),
            '_sequence_source_refs': lambda pattern: [],
            'apply_pattern': load_pattern_function()['apply_pattern'],
        })
        patch.start()
        self.addCleanup(patch.stop)
        self.dialog.update_preview()

    def apply_to_model(self, changes, is_instance_mode, target):
        for element, value in changes.items():
            element.name = value
        return True

    def test_apply_stays_open_reloads_values_and_clears_find_replace(self):
        self.dialog.preview_items[0].final = True
        self.dialog.OnApply(None, None)
        self.dialog.window.Close.assert_not_called()
        self.assertEqual('', self.dialog.txt_find.Text)
        self.assertEqual('', self.dialog.txt_replace.Text)
        self.assertFalse(self.dialog._suspend_events)
        self.assertTrue(all(not row.final for row in self.dialog.preview_items))
        self.assertEqual(['Entry-A', 'Entry-B'],
                         [row.CurrentName for row in self.dialog.preview_items])
        self.assertTrue(all(not row.HasChanges for row in self.dialog.preview_items))
        self.dialog.persist_settings.assert_called_once_with()
        self.dialog.update_tokenization_display.assert_called()
        self.assertEqual('{orig}', self.dialog.txt_pattern.Text)
        self.assertTrue(self.dialog.chk_match_case.IsChecked)

        self.dialog.txt_find.Text = 'Entry'
        self.dialog.txt_replace.Text = 'Opening'
        self.dialog.update_preview()
        self.dialog.OnApply(None, None)
        self.assertEqual(['Opening-A', 'Opening-B'],
                         [row.CurrentName for row in self.dialog.preview_items])
        self.assertEqual(2, self.globals['revalue_elements'].call_count)

    def test_only_visible_rows_are_written_and_filters_are_preserved(self):
        self.dialog.txt_filter_current.Text = 'Door-A'
        self.dialog.preview_grid.Items.Refresh()
        self.dialog.OnApply(None, None)
        self.assertEqual(['Entry-A', 'Door-B'],
                         [row.CurrentName for row in self.dialog.preview_items])
        self.assertEqual('Door-A', self.dialog.txt_filter_current.Text)
        self.assertEqual(0, self.dialog.preview_grid.Items.Count)

    def test_parameter_target_reloads_actual_parameter_values(self):
        self.dialog.get_selected_original_param_name = lambda: '[Code]'
        self.dialog.get_param_value = lambda element, name: element.name
        self.dialog.OnApply(None, None)
        self.assertEqual('[Code]', self.globals['revalue_elements'].call_args[0][2])
        self.assertEqual('Entry-A', self.dialog.preview_items[0].CurrentName)

    def test_partial_failure_reloads_actual_values_not_proposed_values(self):
        def partial_apply(changes, is_instance_mode, target):
            element, value = next(iter(changes.items()))
            element.name = value
            return True
        self.globals['revalue_elements'].side_effect = partial_apply
        self.dialog.OnApply(None, None)
        self.assertEqual(['Entry-A', 'Door-B'],
                         [row.CurrentName for row in self.dialog.preview_items])
        self.assertTrue(all(not row.HasChanges for row in self.dialog.preview_items))
        self.assertEqual('', self.dialog.txt_find.Text)

    def test_transaction_error_preserves_inputs_and_preview(self):
        self.globals['revalue_elements'].side_effect = None
        self.globals['revalue_elements'].return_value = False
        self.dialog.OnApply(None, None)
        self.assertEqual('Door', self.dialog.txt_find.Text)
        self.assertEqual('Entry', self.dialog.txt_replace.Text)
        self.assertEqual('Door-A', self.dialog.preview_items[0].CurrentName)
        self.dialog.persist_settings.assert_not_called()
        self.dialog.window.Close.assert_not_called()

    def test_no_changes_preserves_inputs_without_writing(self):
        for row in self.dialog.preview_items:
            row.NewName = row.CurrentName
        self.dialog.OnApply(None, None)
        self.globals['revalue_elements'].assert_not_called()
        self.globals['forms'].alert.assert_called_once_with("No changes to apply.")
        self.assertEqual('Door', self.dialog.txt_find.Text)

    def test_invalid_filter_prevents_writes(self):
        self.dialog._parameter_filter_error = 'Invalid filter'
        self.dialog.OnApply(None, None)
        self.globals['revalue_elements'].assert_not_called()
        self.globals['forms'].alert.assert_called_once_with('Invalid filter')

    def test_pending_cell_and_row_edits_are_committed_before_writing(self):
        self.dialog.OnApply(None, None)
        self.assertEqual([('cell', True), ('row', True)],
                         self.dialog.preview_grid.commits)

    def test_uncommittable_edit_prevents_writes_and_reset(self):
        self.dialog.preview_grid.CommitEdit = mock.Mock(return_value=False)
        self.dialog.OnApply(None, None)
        self.globals['revalue_elements'].assert_not_called()
        self.assertEqual('Door', self.dialog.txt_find.Text)

    def test_close_does_not_apply_pending_changes(self):
        self.dialog.OnClose(None, None)
        self.dialog.window.Close.assert_called_once_with()
        self.globals['revalue_elements'].assert_not_called()

    def test_original_toggle_restores_pattern_across_repeated_cycles(self):
        self.dialog.txt_pattern.Text = '{val1}-{count}'
        for _ in range(2):
            self.dialog.btn_use_orig.IsChecked = True
            self.dialog.OnUseOriginal(None, None)
            self.assertEqual('{orig}', self.dialog.txt_pattern.Text)
            self.dialog.btn_use_orig.IsChecked = False
            self.dialog.OnUseOriginal(None, None)
            self.assertEqual('{val1}-{count}', self.dialog.txt_pattern.Text)
        self.assertEqual('Door', self.dialog.txt_find.Text)

    def test_original_toggle_restores_empty_pattern(self):
        self.dialog.txt_pattern.Text = ''
        self.dialog.btn_use_orig.IsChecked = True
        self.dialog.OnUseOriginal(None, None)
        self.dialog.btn_use_orig.IsChecked = False
        self.dialog.OnUseOriginal(None, None)
        self.assertEqual('', self.dialog.txt_pattern.Text)

    def test_original_toggle_preserves_saved_pattern_after_apply(self):
        self.dialog.txt_pattern.Text = '{val1}-{count}'
        self.dialog.btn_use_orig.IsChecked = True
        self.dialog.OnUseOriginal(None, None)
        self.dialog.OnApply(None, None)
        self.assertTrue(self.dialog.btn_use_orig.IsChecked)
        self.dialog.btn_use_orig.IsChecked = False
        self.dialog.OnUseOriginal(None, None)
        self.assertEqual('{val1}-{count}', self.dialog.txt_pattern.Text)

    def test_editing_original_pattern_turns_toggle_off_and_keeps_edit(self):
        self.dialog.txt_pattern.Text = '{val1}'
        self.dialog.btn_use_orig.IsChecked = True
        self.dialog.OnUseOriginal(None, None)
        self.dialog.txt_pattern.Text = '{orig}-edited'
        self.dialog.OnSettingsChanged(self.dialog.txt_pattern, None)
        self.assertFalse(self.dialog.btn_use_orig.IsChecked)
        self.assertIsNone(self.dialog._pattern_before_original)
        self.assertEqual('{orig}-edited', self.dialog.txt_pattern.Text)
        self.dialog.btn_use_orig.IsChecked = True
        self.dialog.OnUseOriginal(None, None)
        self.dialog.OnSettingsChanged(self.dialog.txt_pattern, None)
        self.assertTrue(self.dialog.btn_use_orig.IsChecked)
        self.dialog.btn_use_orig.IsChecked = False
        self.dialog.OnUseOriginal(None, None)
        self.assertEqual('{orig}-edited', self.dialog.txt_pattern.Text)


class FindReplaceTests(unittest.TestCase):
    def test_defaults_preserve_case_sensitive_substring_replacement(self):
        self.assertEqual('Entry Doorway door',
                         replace_final_value('Door Doorway door', 'Door ', 'Entry '))
        self.assertEqual('Entry Entryway door',
                         replace_final_value('Door Doorway door', 'Door', 'Entry'))

    def test_all_option_combinations(self):
        value = 'Door door DOOR Doorway doorway'
        for whole_word, match_case, expected in [
                (False, True, 'X door DOOR Xway doorway'),
                (False, False, 'X X X Xway Xway'),
                (True, True, 'X door DOOR Doorway doorway'),
                (True, False, 'X X X Doorway doorway')]:
            with self.subTest(whole_word=whole_word, match_case=match_case):
                self.assertEqual(expected, replace_final_value(
                    value, 'Door', 'X', whole_word, match_case))

    def test_whole_word_boundaries(self):
        self.assertEqual(
            'X-X (X), X. Door_A ADoor Door2 2Door',
            replace_final_value(
                'Door-Door (Door), Door. Door_A ADoor Door2 2Door',
                'Door', 'X', True))

    def test_search_metacharacters_are_literal(self):
        self.assertEqual(
            'X AxB X',
            replace_final_value('A.B AxB a.b', 'A.B', 'X', False, False))

    def test_replacement_backslashes_are_literal(self):
        self.assertEqual(
            r'\1\new \1\new',
            replace_final_value('Door DOOR', 'door', r'\1\new', False, False))

    def test_whole_phrase_and_punctuation_only_searches(self):
        self.assertEqual('X Door Framework', replace_final_value(
            'Door Frame Door Framework', 'Door Frame', 'X', True))
        self.assertEqual('X A++B', replace_final_value(
            '++ A++B', '++', 'X', True))

    def test_empty_find_is_no_op_and_empty_replacement_deletes(self):
        self.assertEqual('Door', replace_final_value('Door', '', 'X', True, False))
        self.assertEqual(' Doorway', replace_final_value(
            'Door Doorway', 'door', '', True, False))
        self.assertEqual('', replace_final_value('', 'Door', 'X', True, False))

    def test_unicode_word_boundaries(self):
        self.assertEqual(u'\u00e9Door Door\u00e9 X', replace_final_value(
            u'\u00e9Door Door\u00e9 Door', 'Door', 'X', True))

    def test_preview_formatting_uses_find_replace_options(self):
        item = PreviewItem('a', 'Door door Doorway')
        item.format_value('{orig}', [], None, find_text='door',
                          replace_text='Entry', match_whole_word=True,
                          match_case=False)
        self.assertEqual('Entry Entry Doorway', item.NewName)
        self.assertEqual('OK', item.tooltip)
        self.assertTrue(item.HasChanges)

    def test_frozen_preview_value_is_not_replaced(self):
        item = PreviewItem('a', 'Door')
        item.final = True
        item.format_value('{orig}', [], None, find_text='door',
                          replace_text='Entry', match_case=False)
        self.assertEqual('Door', item.NewName)

    def test_preview_applies_final_case_after_find_replace(self):
        item = PreviewItem('a', 'Door')
        item.format_value('{orig}', [], None, find_text='Door',
                          replace_text='Entry', final_case='upper')
        self.assertEqual('ENTRY', item.NewName)


class CaseConversionTests(unittest.TestCase):
    def test_case_conversion_modes(self):
        convert_case = load_pattern_function()['apply_case_conversion']
        cases = [
            ('upper', 'mixed Case', 'MIXED CASE'),
            ('lower', 'Mixed CASE', 'mixed case'),
            ('title', 'mixed CASE name', 'Mixed Case Name'),
            ('sentence', 'mIXED CASE. NEXT', 'Mixed case. next'),
            ('None', 'Mixed CASE', 'Mixed CASE'),
        ]
        for mode, value, expected in cases:
            with self.subTest(mode=mode):
                self.assertEqual(expected, convert_case(value, mode))

    def test_split_case_modifier_preserves_unknown_suffix(self):
        split_modifier = load_pattern_function()['_split_case_modifier']
        self.assertEqual(
            ('val1:3|space', 'upper'),
            split_modifier('val1:3|space~UPPER'))
        self.assertEqual(
            ('val1~unknown', None),
            split_modifier('val1~unknown'))

    def test_token_parameter_and_sequence_modifiers(self):
        apply_pattern = load_pattern_function()['apply_pattern']
        tokenizer = lambda value: value.split('-')
        params = {
            'param1': 'mIXED wIDTH',
            'orig': 'sOURCE TEXT',
            'count': 'AbC',
        }
        self.assertEqual(
            'ONE TWO THREE',
            apply_pattern('one-two-THREE-four',
                          '{val1:3|space~upper}', params, tokenizer))
        self.assertEqual(
            'Mixed Width/Source text/abc',
            apply_pattern('one-two', '{param1~title}/{orig~sentence}/{count~lower}',
                          params, tokenizer))
        self.assertEqual(
            'C',
            apply_pattern('a-b', '{seq:val1:1~upper}', params, tokenizer,
                          sequence_seeds={'val1': 'A'}, row_index=2))

    def test_case_modified_counter_placeholder_still_enables_counter(self):
        dialog = ReValueDialog()
        dialog.txt_pattern = TextBox()
        for pattern, expected in [
                ('{count~upper}', True),
                ('{param6~sentence}', True),
                ('{val1~upper}', False),
                ('{count~unknown}', False)]:
            with self.subTest(pattern=pattern):
                dialog.txt_pattern.Text = pattern
                self.assertEqual(expected, dialog._pattern_uses_counter())


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ReValueDialog()
        self.dialog._suspend_events = False
        self.dialog.txt_filter_current = TextBox()
        self.dialog.txt_filter_new = TextBox()
        self.rows = []
        for element, current, new in [
                ('a', 'Door-A', 'Entry-01'),
                ('b', 'Door-B', 'Entry-02'),
                ('c', 'Wall-A', 'Partition-03'),
                ('d', 'Unchanged', 'Unchanged'),
                ('e', 'Invalid', '')]:
            item = PreviewItem(element, current)
            item.NewName = new
            self.rows.append(item)
        self.dialog.preview_items = self.rows
        self.dialog.preview_grid = Grid(
            self.rows, self.dialog.matches_preview_filters)
        self.dialog.preview_view = self.dialog.preview_grid.Items
        self.dialog.parameter_filter = None
        self.dialog.available_params = ['Width', 'Comments']
        self.dialog.txt_filter_summary = TextBox()
        self.dialog.btn_clear_filters = LayoutPart()
        self.dialog.txt_filter_status = TextBox()
        self.dialog.btn_apply = LayoutPart()
        self.dialog._decimal_separator = '.'
        self.dialog._group_separator = ','
        self.dialog._parameter_filter_error = ''
        self.dialog.get_param_value = lambda element, parameter: {
            'a': '900 mm', 'b': '1200 mm', 'c': '1500 mm',
            'd': '', 'e': 'not numeric',
        }[element]

    def filter_rows(self, current='', new=''):
        self.dialog.txt_filter_current.Text = current
        self.dialog.txt_filter_new.Text = new
        self.dialog.OnPreviewFilterChanged(None, None)

    def test_unfiltered_map_skips_unchanged_and_blank_values(self):
        self.assertEqual({'a': 'Entry-01', 'b': 'Entry-02',
                          'c': 'Partition-03'}, self.dialog.get_revalue_map())

    def test_current_filter_is_case_insensitive_contains_match(self):
        self.filter_rows('oOr')
        self.assertEqual({'a': 'Entry-01', 'b': 'Entry-02'},
                         self.dialog.get_revalue_map())

    def test_new_value_filter_is_independent(self):
        self.filter_rows(new='PARTITION')
        self.assertEqual({'c': 'Partition-03'}, self.dialog.get_revalue_map())

    def test_both_filters_must_match(self):
        self.filter_rows('door', '02')
        self.assertEqual({'b': 'Entry-02'}, self.dialog.get_revalue_map())
        self.filter_rows('wall', '02')
        self.assertEqual({}, self.dialog.get_revalue_map())

    def test_clearing_filters_restores_rows_without_renumbering(self):
        self.filter_rows(new='02')
        self.assertEqual('Entry-02', self.rows[1].NewName)
        self.filter_rows()
        self.assertEqual(5, len(list(self.dialog.preview_grid.Items)))
        self.assertEqual('Entry-02', self.dialog.get_revalue_map()['b'])

    def test_final_rows_are_still_eligible_when_visible(self):
        self.rows[0].final = True
        self.filter_rows(new='01')
        self.assertEqual({'a': 'Entry-01'}, self.dialog.get_revalue_map())

    def test_highlight_tracks_differences_including_blank_new_values(self):
        self.assertTrue(self.rows[0].HasChanges)
        self.assertFalse(self.rows[3].HasChanges)
        self.assertTrue(self.rows[4].HasChanges)
        self.rows[0].NewName = self.rows[0].CurrentName
        self.assertFalse(self.rows[0].HasChanges)
        self.rows[0].CurrentName = 'Updated source'
        self.assertTrue(self.rows[0].HasChanges)

    def test_refresh_rechecks_filters_after_preview_value_changes(self):
        self.filter_rows(new='entry')
        self.rows[0].NewName = 'Other'
        self.rows[2].NewName = 'Entry-03'
        self.dialog.preview_view.Refresh()
        self.assertEqual({'b': 'Entry-02', 'c': 'Entry-03'},
                         self.dialog.get_revalue_map())

    def test_filter_commits_pending_edits_before_refresh(self):
        self.filter_rows('door')
        self.assertEqual([('cell', True), ('row', True)],
                         self.dialog.preview_grid.commits)

    def test_initialization_does_not_refresh_filters(self):
        self.dialog._suspend_events = True
        self.filter_rows('door')
        self.assertEqual([], self.dialog.preview_grid.commits)
        self.assertEqual(5, len(list(self.dialog.preview_grid.Items)))

    def test_numeric_parameter_filter_combines_with_header_and_limits_apply(self):
        self.dialog.parameter_filter = parse_expression('[Width] >= 1200')
        self.filter_rows()
        self.assertEqual({'b': 'Entry-02', 'c': 'Partition-03'},
                         self.dialog.get_revalue_map())
        self.assertIn('2 row(s) excluded', self.dialog.txt_filter_status.Text)
        self.filter_rows(new='entry')
        self.assertEqual({'b': 'Entry-02'}, self.dialog.get_revalue_map())
        self.assertIn('1 of 5', self.dialog.txt_filter_status.Text)

    def test_invalid_numeric_input_hides_all_rows_and_disables_apply(self):
        self.dialog.parameter_filter = rule('Width', 'Less than', 'wrong', True)
        self.filter_rows()
        self.assertEqual({}, self.dialog.get_revalue_map())
        self.assertFalse(self.dialog.btn_apply.IsEnabled)
        self.assertTrue(self.dialog._parameter_filter_error)
        self.assertIn('decimal number', self.dialog.txt_filter_status.Text)
        self.dialog.parameter_filter = parse_expression('[Width] < 1000')
        self.filter_rows()
        self.assertTrue(self.dialog.btn_apply.IsEnabled)
        self.assertEqual({'a': 'Entry-01'}, self.dialog.get_revalue_map())

    def test_clear_parameter_restores_rows_despite_invalid_numeric_input(self):
        self.dialog.parameter_filter = rule('Width', 'Less than', 'wrong', True)
        self.filter_rows()
        self.dialog.OnClearFilters(None, None)
        self.assertEqual(5, self.dialog.preview_view.Count)
        self.assertTrue(self.dialog.btn_apply.IsEnabled)

    def test_blank_condition(self):
        self.dialog.parameter_filter = parse_expression('ISBLANK([Comments])')
        self.filter_rows()
        self.assertEqual(['d'], [row.Element for row in self.dialog.preview_view])

    def test_mode_change_blocks_unavailable_parameter_filter_instead_of_broadening(self):
        self.dialog.parameter_filter = parse_expression('[Width] >= 900')
        self.dialog.available_params = ['Type Comments']
        self.filter_rows()
        self.assertFalse(self.dialog.btn_apply.IsEnabled)
        self.assertEqual({}, self.dialog.get_revalue_map())
        self.assertIn('unavailable', self.dialog.txt_filter_status.Text)

    def test_nested_or_and_not_limit_apply(self):
        self.dialog.parameter_filter = parse_expression(
            'AND(OR([Width] = 900, [Width] = 1500), NOT([Width] < 1000))')
        self.filter_rows()
        self.assertEqual({'c': 'Partition-03'}, self.dialog.get_revalue_map())

    def test_not_does_not_include_invalid_numeric_values(self):
        self.dialog.parameter_filter = parse_expression('NOT([Width] < 1200)')
        self.filter_rows()
        self.assertEqual(['b', 'c'], [item.Element for item in self.dialog.preview_view])

    def test_numeric_filter_respects_comma_decimal_display_values(self):
        self.dialog._decimal_separator = ','
        self.dialog._group_separator = '.'
        self.dialog.get_param_value = lambda element, parameter: '1.200,50 mm'
        self.dialog.parameter_filter = parse_expression('[Width] = 1200.5')
        self.filter_rows()
        self.assertEqual(5, self.dialog.preview_view.Count)

    def test_cancel_editor_preserves_active_filter_and_preview(self):
        active = parse_expression('[Width] >= 1200')
        self.dialog.parameter_filter = active
        self.dialog.window = object()
        self.filter_rows()
        module = types.ModuleType('filter_editor')
        editor = mock.Mock()
        editor.show.return_value = (False, None)
        module.FilterEditor = mock.Mock(return_value=editor)
        with mock.patch.dict(sys.modules, {'filter_editor': module}):
            self.dialog.OnEditFilters(None, None)
        self.assertIs(active, self.dialog.parameter_filter)
        self.assertEqual({'b': 'Entry-02', 'c': 'Partition-03'},
                         self.dialog.get_revalue_map())

    def test_confirm_editor_replaces_filter_and_refreshes_preview(self):
        self.dialog.window = object()
        node = parse_expression('AND([Width] >= 900, [Width] < 1200)')
        module = types.ModuleType('filter_editor')
        editor = mock.Mock()
        editor.show.return_value = (True, node)
        module.FilterEditor = mock.Mock(return_value=editor)
        with mock.patch.dict(sys.modules, {'filter_editor': module}):
            self.dialog.OnEditFilters(None, None)
        self.assertIs(node, self.dialog.parameter_filter)
        self.assertEqual({'a': 'Entry-01'}, self.dialog.get_revalue_map())

    def test_clear_parameter_filters_preserves_header_filters(self):
        self.dialog.parameter_filter = parse_expression('[Width] >= 1200')
        self.filter_rows(new='entry')
        self.dialog.OnClearFilters(None, None)
        self.assertEqual({'a': 'Entry-01', 'b': 'Entry-02'},
                         self.dialog.get_revalue_map())


class ParameterComparisonTests(unittest.TestCase):
    def test_text_conditions_ignore_case(self):
        for condition, value, expected, result in [
                ('Equals', 'External', 'EXTERNAL', True),
                ('Does not equal', 'External', 'internal', True),
                ('Contains', 'External Door', 'DOOR', True),
                ('Starts with', 'A101', 'a', True),
                ('Ends with', 'A101', '01', True),
                ('Is blank', '  ', '', True),
                ('Is not blank', '', '', False),
                ('Equals', 'A01', 'A1', False)]:
            self.assertEqual(result, matches_parameter_filter(value, condition, expected))

    def test_numeric_thresholds_include_exact_boundaries(self):
        for condition, equal_result in [
                ('Greater than', False), ('Less than', False),
                ('Greater than or equal to', True),
                ('Less than or equal to', True)]:
            self.assertEqual(equal_result, matches_parameter_filter(
                '900.00 mm', condition, '900'))
        self.assertTrue(matches_parameter_filter('901 mm', 'Greater than', '900'))
        self.assertTrue(matches_parameter_filter('-1', 'Less than', '0'))
        self.assertFalse(matches_parameter_filter('10', 'Less than', '2'))

    def test_display_units_grouping_decimals_and_exponents(self):
        self.assertEqual(Decimal('1234.5'), parse_filter_number('1,234.5 mm', allow_unit=True))
        self.assertEqual(Decimal('1234.5'), parse_filter_number('1.234,5 m', ',', '.', True))
        self.assertEqual(Decimal('1234.5'), parse_filter_number('1 234,5', ',', ' '))
        self.assertEqual(Decimal('1234'), parse_filter_number('1 234 mm', ',', ' ', True))
        self.assertEqual(Decimal('0.25'), parse_filter_number('.25'))
        self.assertEqual(Decimal('1200'), parse_filter_number('1.2e3'))
        self.assertEqual(Decimal('12.5'), parse_filter_number('12.5 m\u00b2', allow_unit=True))

    def test_invalid_and_compound_values_are_rejected(self):
        for text in ('', 'NaN', 'Infinity', 'wrong', '1,5', '1.2.3',
                     '1/2', '900 mm', '1,23,456'):
            with self.assertRaises(ValueError):
                parse_filter_number(text)
        for text in ('5\' 6"', '1/2"', '12 m 3 cm', '1-2', '1.2.3 mm'):
            with self.assertRaises(ValueError):
                parse_filter_number(text, allow_unit=True)

    def test_unknown_condition_is_explicit_error(self):
        with self.assertRaises(ValueError):
            matches_parameter_filter('value', 'unknown', 'value')


if __name__ == '__main__':
    unittest.main()
