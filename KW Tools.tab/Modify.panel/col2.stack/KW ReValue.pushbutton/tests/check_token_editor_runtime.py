"""Run with IronPython on an STA WPF host, including Revit's read-only MCP host."""
import ast
import io
import os
import sys

sys.dont_write_bytecode = True
COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import DataObject, DragDropEffects, Point, Size, Rect, Visibility
from System.Windows.Controls import Button, Canvas
from token_editor import TokenEditor, TokenSettings
from token_pattern import expression, parse_pattern, serialize_pattern, token
from range_separator import decode_separator, split_case


def pattern_engine():
    path = os.path.join(COMMAND_DIR, 'script.py')
    with io.open(path, encoding='utf-8') as source:
        tree = ast.parse(source.read())
    names = ('_alpha_to_int', '_int_to_alpha', '_increment_value',
             'build_counter_generator', '_parse_progression_expression',
             '_split_case_modifier', '_parse_val_expression', '_resolve_window',
             '_resolve_progression_source', 'apply_case_conversion', 'apply_pattern',
             'build_tokenizer', 'tokenize')
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    nodes += [node for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id in (
                  'NUMERIC_REGEX', 'ALPHA_REGEX', 'MIXED_SUFFIX_NUM_REGEX',
                  'SIGNED_NUMERIC_REGEX', 'SIGNED_SUFFIX_NUM_REGEX', 'PROGRESSION_SOURCE_REGEX',
                  'CASE_MODIFIERS', 'NAMED_DELIMS', 'VAL_EXPR_REGEX', 'CANONICAL_DELIM',
                  'DEFAULT_DELIMITERS') for target in node.targets)]
    module = ast.Module(nodes)
    ast.fix_missing_locations(module)
    namespace = {'re': __import__('re'), 'decode_separator': decode_separator,
                 'split_case': split_case}
    exec(compile(module, path, 'exec'), namespace)
    return namespace


class Row(object):
    Element = 'Door_Internal_RM09'
    CurrentName = Element


class Host(object):
    def __init__(self):
        from ui_styles import load_window
        self.window = load_window(os.path.join(COMMAND_DIR, 'ReValueUI.xaml'))
        self.available_params = ['Comments', 'Mark', 'Width', 'Height', 'Code', 'Extra']
        self.param_combos = [self.window.FindName('combo_param{}'.format(i)) for i in range(1, 6)]
        for combo in self.param_combos:
            combo.Items.Add('')
            for name in self.available_params:
                combo.Items.Add(name)
            combo.SelectedIndex = 0
        for name in ('txt_pattern', 'txt_counter_start', 'txt_counter_increment', 'btn_use_orig'):
            setattr(self, name, self.window.FindName(name))
        self.txt_pattern.Text = '{val1} - {val2}'
        self.txt_counter_start.Text = '001'
        self.txt_counter_increment.Text = '1'
        self.preview_items = [Row()]
        self._suspend_events = False
        self.calls = 0
        self.can_commit = True
        self.engine = pattern_engine()

    def _selected_combo_text(self, combo):
        return combo.SelectedItem or ''

    def get_original_source_text(self, element):
        return element

    def get_token_sample_item(self):
        return self.preview_items[0] if self.preview_items else None

    def get_tokenizer_func(self):
        return self.engine['build_tokenizer']('_')

    def commit_preview_edits(self):
        return self.can_commit

    def OnSettingsChanged(self, sender, args):
        self.calls += 1
        self.editor.refresh()


def run_checks(capture=None):
    host = Host()
    editor = TokenEditor(host, host.engine['build_counter_generator'])
    host.editor = editor
    try:
        assert editor.mode.SelectedIndex == 0
        assert host.txt_pattern.IsReadOnly
        assert editor.panel.Visibility == Visibility.Visible
        assert len(editor.items) == 3
        first_button = editor.bar.Children[0]
        for chip in (first_button, editor.palette.Children[0]):
            chip.ApplyTemplate()
            border = chip.Template.FindName('pill', chip)
            assert border.CornerRadius.TopLeft == 11
            assert chip.Height == border.CornerRadius.TopLeft * 2
            assert chip.Background.GradientStops[1].Color.ToString() == '#FF38BDF8'
            assert border.Effect.ShadowDepth == 1
            assert chip.Padding.Top == 1 and chip.Padding.Bottom == 1
            chip.Measure(Size(1000, 100))
            assert chip.DesiredSize.Height <= 28
        editor.select(0)
        assert editor.bar.Children[0] is first_button  # Preserve double-click target.
        case_menu = next(item for item in editor.context_menu(0).Items
                         if item.Header == 'Text Case')
        assert [item.Header for item in case_menu.Items] == [
            'Unchanged', 'UPPER', 'lower', 'Title Case', 'Sentence case']
        editor.set_case(0, 'upper')
        assert host.txt_pattern.Text == '{val1~upper} - {val2}'
        editor.duplicate(0)
        assert host.txt_pattern.Text.startswith('{val1~upper}{val1~upper}')
        editor.move(0, len(editor.items))
        assert host.txt_pattern.Text.endswith('{val1~upper}')
        editor.remove(len(editor.items) - 1)
        editor.add(token('text', text=' (Existing)'))
        assert ' (Existing)' in host.txt_pattern.Text
        editor.commit([token('text', text='A'), token('text', text='B')], 1)
        assert len(editor.items) == 2  # Adjacent literal chips stay independently editable.
        editor.move(1, 0)
        assert host.txt_pattern.Text == 'BA'

        calls = host.calls
        previous = host.txt_pattern.Text
        host.can_commit = False
        editor.remove(0)
        assert host.txt_pattern.Text == previous and host.calls == calls
        host.can_commit = True

        host.txt_pattern.Text = '{inc:val1:2}'
        editor.refresh()
        assert editor.items[0]['operation'] == 'inc'
        assert 'Progression' in [item.Header for item in editor.context_menu(0).Items]
        host.txt_pattern.Text = '{unknown}'
        editor.refresh()
        assert editor.mode.SelectedIndex == 1
        assert not host.txt_pattern.IsReadOnly
        assert 'Cannot represent' in editor.status.Text
        assert host.txt_pattern.Text == '{unknown}'
        host.txt_pattern.Text = '{val1}{val2}{val3}'
        editor.refresh()
        editor.mode.SelectedIndex = 0
        assert host.txt_pattern.IsReadOnly

        root = host.window.Content
        root.Measure(Size(720, 600))
        root.Arrange(Rect(0, 0, 720, 600))
        root.UpdateLayout()
        assert editor.bar.Children[0].ActualWidth > 0
        first = editor.bar.Children[0]
        origin = first.TranslatePoint(Point(0, 0), editor.bar)
        assert editor.drop_position(Point(origin.X, origin.Y + 5)) == 0
        assert editor.drop_position(Point(origin.X + first.ActualWidth - 1, origin.Y + 5)) == 1

        class DragArgs(object):
            Handled = False
            Effects = getattr(DragDropEffects, 'None')
            Data = DataObject()

            def GetPosition(self, target):
                return Point(0, 0)

        args = DragArgs()
        editor.drag_over(None, args)
        assert args.Effects == getattr(DragDropEffects, 'None')
        assert editor.insertion_caret.Visibility == Visibility.Collapsed
        args.Data.SetData(editor.DRAG_FORMAT, editor.DRAG_FORMAT)
        editor._drag = (editor.bar.Children[2], Point(0, 0), ('bar', 2, False))
        editor.drag_over(None, args)
        assert args.Effects == DragDropEffects.Move
        assert editor.insertion_caret.Visibility == Visibility.Visible
        dimensions = [(child.ActualWidth, child.ActualHeight) for child in editor.bar.Children]
        editor.show_insertion(1, Point(10, 5))
        root.UpdateLayout()
        assert dimensions == [(child.ActualWidth, child.ActualHeight) for child in editor.bar.Children]
        editor.drag_leave(None, args)
        assert editor.insertion_caret.Visibility == Visibility.Collapsed
        editor.drop(None, args)
        assert editor.insertion_caret.Visibility == Visibility.Collapsed
        assert host.txt_pattern.Text == '{val3}{val1}{val2}'
        editor._drag = None

        editor.commit([token('source', start='val{}'.format(i % 3 + 1))
                       for i in range(18)], 0)
        root.Measure(Size(720, 600))
        root.Arrange(Rect(0, 0, 720, 600))
        root.UpdateLayout()
        positions = [child.TranslatePoint(Point(0, 0), editor.bar)
                     for child in editor.bar.Children]
        wrapped = next(i for i, point in enumerate(positions) if point.Y > positions[0].Y)
        assert editor.drop_position(Point(positions[wrapped].X, positions[wrapped].Y + 2)) == wrapped
        editor.show_insertion(wrapped, Point(positions[wrapped].X, positions[wrapped].Y + 2))
        assert Canvas.GetTop(editor.insertion_caret) == positions[wrapped].Y
        editor.show_insertion(wrapped, Point(700, positions[wrapped - 1].Y + 2))
        assert Canvas.GetTop(editor.insertion_caret) == positions[wrapped - 1].Y
        editor.clear_insertion()
        assert editor.bar_scroll.ScrollableHeight > 0
        footer = host.window.FindName('btn_close')
        footer_point = footer.TranslatePoint(Point(0, 0), root)
        assert footer_point.Y + footer.ActualHeight <= 600
        assert host.window.FindName('preview_grid').ActualHeight >= 150
        editor.commit([], -1)
        editor.show_insertion(0, Point(0, 0))
        assert editor.insertion_caret.Visibility == Visibility.Visible
        editor.clear_insertion()
        assert editor.insertion_caret.Visibility == Visibility.Collapsed
        editor.commit(parse_pattern('{val2} - {val1} - {count}'), -1)
        if capture:
            from System.IO import File
            from System.Windows.Media import PixelFormats
            from System.Windows.Media.Imaging import BitmapFrame, PngBitmapEncoder, RenderTargetBitmap
            root.Measure(Size(1010, 880))
            root.Arrange(Rect(0, 0, 1010, 880))
            root.UpdateLayout()
            bitmap = RenderTargetBitmap(1010, 880, 96, 96, PixelFormats.Pbgra32)
            bitmap.Render(root)
            encoder = PngBitmapEncoder()
            encoder.Frames.Add(BitmapFrame.Create(bitmap))
            stream = File.Create(capture)
            try:
                encoder.Save(stream)
            finally:
                stream.Dispose()

        # Show once to establish a valid owner for automatic modal dialog checks.
        host.window.ShowActivated = False
        host.window.ShowInTaskbar = False
        host.window.Show()
        host.window.Hide()
        for case_label, case_value in [
                ('Unchanged', 'Unchanged'), ('UPPER', 'upper'), ('lower', 'lower'),
                ('Title Case', 'title'), ('Sentence case', 'sentence')]:
            case_settings = TokenSettings(editor, token('source', start='val1', case=case_value))
            assert case_settings.fields['case'].SelectedItem == case_label
            case_settings.fields['case'].SelectedItem = case_label
            case_settings.window.Loaded += (
                lambda sender, args: case_settings.accept(None, None))
            case_item, unused, unused_counter = case_settings.show()
            assert case_item['case'] == case_value
            assert expression(case_item) == (
                '{val1}' if case_value == 'Unchanged' else '{val1~' + case_value + '}')
        settings = TokenSettings(editor, token('source', start='val1'))
        action = Button()
        settings.panel.Children.Add(action)
        action.ApplyTemplate()
        face = action.Template.FindName('button_face', action)
        assert face is not None and face.CornerRadius.TopLeft == 6
        assert face.Effect.ShadowDepth == 1
        action.IsEnabled = False
        assert face.Effect is None
        settings.panel.Children.Remove(action)
        settings.fields['operation'].SelectedItem = 'Increment'
        settings.fields['step'].Text = '2'
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, mappings, counter = settings.show()
        assert expression(item) == '{inc:val1:2}'
        assert host.engine['apply_pattern'](
            'RM09', expression(item), {}, tokenizer_func=lambda value: [value]) == 'RM11'

        settings = TokenSettings(editor, token('source', start='end'))
        assert settings.fields['start'].Text == '1'
        assert settings.fields['start_directions'][1].IsChecked
        assert not settings.fields['end_row'].IsEnabled
        settings.fields['operation'].SelectedItem = 'Increment'
        settings.accept(None, None)
        assert 'single valN' in settings.error.Text
        assert settings.result is None

        settings = TokenSettings(editor, token('source', start='val3', end='+2'))
        assert settings.fields['start'].Text == '3'
        assert settings.fields['end'].Text == '2'
        assert settings.fields['end_directions'][2].IsChecked
        assert settings.fields['end_row'].IsEnabled
        settings.fields['start_directions'][1].IsChecked = True
        settings.fields['start'].Text = '2'
        settings.fields['end_directions'][1].IsChecked = True
        settings.fields['end'].Text = '1'
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, unused, unused_counter = settings.show()
        assert expression(item) == '{end-1:end}'

        settings = TokenSettings(editor, token('source', start='val3', end='+2'))
        settings.fields['range'].IsChecked = False
        assert not settings.fields['join'].IsEnabled
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, unused, unused_counter = settings.show()
        assert expression(item) == '{val3}'

        before = editor.mappings()
        settings = TokenSettings(editor, token('parameter'))
        settings.fields['parameter'].SelectedItem = 'Comments'
        assert settings.fields['slot'].SelectedIndex == 0
        settings.window.Loaded += lambda sender, args: settings.window.Close()
        assert settings.show() is None
        assert editor.mappings() == before

        settings = TokenSettings(editor, token('parameter'))
        settings.fields['parameter'].SelectedItem = 'Comments'
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, mappings, counter = settings.show()
        assert mappings[0] == 'Comments' and editor.mappings() == before
        editor.commit([item], 0, mappings, counter)
        assert host.param_combos[0].SelectedItem == 'Comments'
        assert host.txt_pattern.Text == '{param1}'
        for combo, name in zip(host.param_combos, host.available_params):
            combo.SelectedItem = name
        settings = TokenSettings(editor, token('parameter'))
        settings.fields['parameter'].SelectedItem = 'Extra'
        assert settings.fields['slot'].SelectedIndex == -1
        settings.accept(None, None)
        assert settings.result is None and 'shared slot' in settings.error.Text

        settings = TokenSettings(editor, token('counter'))
        settings.fields['counter_increment'].Text = '-1'
        settings.accept(None, None)
        assert settings.result is None and settings.error.Text
        assert host.txt_counter_increment.Text == '1'

        settings = TokenSettings(editor, token('text', text=' - '))
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, unused, unused_counter = settings.show()
        assert item['text'] == ' - '
        assert host.txt_counter_increment.Text == '1'
        settings = TokenSettings(editor, token('source', start='val1', end='3'))
        settings.fields['join'].Text = ' - '
        settings.window.Loaded += lambda sender, args: settings.accept(None, None)
        item, unused, unused_counter = settings.show()
        assert expression(item) == '{val1:3|" - "}'
        assert host.engine['apply_pattern'](
            'Door_Internal_009', expression(item), {},
            tokenizer_func=host.get_tokenizer_func()) == 'Door - Internal - 009'
        print('PASS: IronPython WPF token editing, menus, lossless advanced fallback, '
              'insertion/drop, progression, settings validation, shared slots and Cancel isolation.')
    finally:
        host.window.Close()


def run_integration(uiapp):
    """Exercise the real dialog/preview and Source switch, never Apply."""
    path = os.path.join(COMMAND_DIR, 'script.py')
    namespace = {'__file__': path, '__name__': 'revalue_integration', '__revit__': uiapp}
    with io.open(path, encoding='utf-8') as source:
        exec(compile(source.read(), path, 'exec'), namespace)
    settings = dict(namespace['_SESSION_SETTING_DEFAULTS'])
    settings['mode'] = 'instance'
    settings['pattern'] = '{orig}'
    namespace['load_session_settings'] = lambda: dict(settings)
    namespace['save_session_setting'] = lambda name, value: None
    dialog = namespace['ReValueDialog']([uiapp.ActiveUIDocument.Document.ActiveView])
    try:
        editor = dialog.token_editor
        original = dialog.preview_items[0].CurrentName
        editor.set_case(0, 'upper')
        assert dialog.preview_items[0].NewName == original.upper()
        dialog.preview_items[0].final = True
        editor.set_case(0, 'lower')
        assert dialog.preview_items[0].NewName == original.upper()
        dialog.preview_items[0].final = False
        pattern = dialog.txt_pattern.Text
        dialog.btn_use_orig.IsChecked = True
        dialog.OnUseOriginal(None, None)
        assert dialog.txt_pattern.Text == '{orig}'
        assert editor.items[0]['kind'] == 'original'
        dialog.btn_use_orig.IsChecked = False
        dialog.OnUseOriginal(None, None)
        assert dialog.txt_pattern.Text == pattern
        assert dialog.preview_items[0].NewName == original.lower()
        dialog.btn_use_orig.IsChecked = True
        dialog.OnUseOriginal(None, None)
        editor.set_case(0, 'upper')
        assert not dialog.btn_use_orig.IsChecked
        assert dialog.txt_pattern.Text == '{orig~upper}'
        # Selection uses cached display values, without calling the Revit source reader.
        dialog.txt_pattern.Text = '{val1}-{seq:val1:2}-{count}'
        first = dialog.preview_items[0]
        dialog._suspend_events = True
        dialog.txt_delimiters.Text = '_'
        dialog._suspend_events = False
        first.CurrentName = 'Door_Internal_01'
        second = namespace['PreviewItem'](None, 'Wall_External_02')
        third = namespace['PreviewItem'](None, 'Floor_03')
        dialog.preview_items.Add(second)
        dialog.preview_items.Add(third)
        grid = dialog.preview_grid
        pattern = dialog.txt_pattern.Text
        values = [item.NewName for item in dialog.preview_items]

        def unexpected(*args):
            raise AssertionError('Selection must not recalculate previews or reread Revit.')

        dialog.get_original_source_text = unexpected
        dialog.update_preview = unexpected
        grid.UnselectAll()
        grid.SelectedItems.Add(second)
        assert editor.source_text == second.CurrentName
        assert editor.samples == ['Wall', 'External', '02']
        assert 'External' in dialog.txt_tokenization.Text
        button = editor.bar.Children[0]
        menu = button.ContextMenu
        palette = editor.palette.Children[1]
        grid.UnselectAll()
        grid.SelectedItems.Add(first)
        assert editor.source_text == first.CurrentName
        assert editor.bar.Children[0] is button
        assert button.ContextMenu is menu
        assert editor.palette.Children[1] is palette

        grid.UnselectAll()
        grid.SelectedItems.Add(third)
        grid.SelectedItems.Add(second)
        assert dialog.get_token_sample_item() is second
        assert editor.source_text == second.CurrentName
        grid.SelectedItems.Add(first)
        assert editor.source_text == first.CurrentName
        assert dialog.txt_pattern.Text == pattern
        assert [item.NewName for item in dialog.preview_items] == values
        grid.UnselectAll()
        dialog.txt_filter_current.Text = 'External'
        assert editor.source_text == second.CurrentName
        dialog.txt_filter_current.Text = 'No matching row'
        assert editor.source_text == '' and editor.samples == []
        assert dialog.txt_tokenization.Text == 'Tokens: (none)'
        assert 'no visible rows' in editor.sample_label.Text
        assert dialog.txt_pattern.Text == pattern
        print('PASS: selected-row samples, reverse ranges, cached source/no preview recalculation, '
              'control/menu reuse, filtered fallback and empty grid.')
        print('PASS: real ReValue dialog, live read-only preview, frozen Final rows and Source switching.')
    finally:
        dialog.window.Close()


if __name__ == '__main__':
    run_checks()
