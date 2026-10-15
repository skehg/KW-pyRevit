"""Run with an IronPython WPF host, not CPython unittest discovery."""
import os
import sys
import io

sys.dont_write_bytecode = True
COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import RoutedEventArgs, Window
from System.Windows.Controls import Button, CheckBox, ComboBox, TextBox
from filter_editor import FilterEditor
from filter_expression import count_rules, parse_expression, serialize_expression


def descendants(control):
    yield control
    if hasattr(control, 'Children'):
        for child in control.Children:
            for item in descendants(child):
                yield item
    elif hasattr(control, 'Child') and control.Child is not None:
        for item in descendants(control.Child):
            yield item


def click(button):
    button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))


def run_checks():
    main_path = os.path.join(COMMAND_DIR, 'script.py')
    with io.open(main_path, encoding='utf-8') as source:
        compile(source.read(), main_path, 'exec')
    owner = Window()
    owner.ShowActivated = False
    owner.ShowInTaskbar = False
    owner.Width = 1
    owner.Height = 1
    owner.Show()
    owner.Hide()
    parameters = ['Width', 'Comments', 'Mark', 'Name] and [Code']
    active = parse_expression('AND([Width] >= 900, CONTAINS([Comments], "External"))')
    original = serialize_expression(active)
    editor = FilterEditor(owner, parameters, active)
    assert editor.window.Owner == owner
    assert editor.use_button.IsEnabled
    assert '2 rule(s)' in editor.status.Text
    root_controls = list(descendants(editor.rules_panel))
    logical = next(item for item in root_controls
                   if isinstance(item, ComboBox) and item.Width == 190)
    logical.SelectedIndex = 1
    assert editor.tree['operator'] == 'OR'
    assert editor.expression_text.Text.startswith('OR(')
    assert serialize_expression(active) == original

    add_group = next(item for item in root_controls
                     if isinstance(item, Button) and item.Content == '+ Add Group')
    click(add_group)
    assert len(editor.tree['children']) == 3
    assert count_rules(editor.tree) == 3
    controls = list(descendants(editor.rules_panel))
    exclude = next(item for item in controls if isinstance(item, CheckBox))
    exclude.IsChecked = True
    assert editor.expression_text.Text.startswith('NOT(OR(')
    assert editor.use_button.IsEnabled
    exclude = next(item for item in descendants(editor.rules_panel)
                   if isinstance(item, CheckBox))
    exclude.IsChecked = False
    assert editor.expression_text.Text.startswith('OR(')

    editor.expression_text.Text = 'AND([Width] >= 900,'
    assert not editor.use_button.IsEnabled
    assert not editor.rules_panel.IsEnabled
    assert 'character' in editor.status.Text
    editor.expression_text.Text = 'NOT(OR([Width] = 1200.5, ISBLANK([Comments])))'
    assert editor.use_button.IsEnabled
    assert editor.rules_panel.IsEnabled
    assert count_rules(editor.tree) == 2
    conditions = [item for item in descendants(editor.rules_panel)
                  if isinstance(item, ComboBox) and item.Width == 195]
    assert any(item.SelectedItem == 'Equals (numeric)' for item in conditions)
    editor.expression_text.Text = '[Missing] = "x"'
    assert not editor.use_button.IsEnabled
    assert 'unavailable' in editor.status.Text
    click(editor.window.FindName('clear_rules'))
    assert editor.expression_text.Text == ''
    assert editor.use_button.IsEnabled

    editor.expression_text.Text = 'NOT(ISBLANK([Comments]))'
    assert editor.use_button.IsEnabled
    controls = list(descendants(editor.rules_panel))
    value = next(item for item in controls if isinstance(item, TextBox))
    assert not value.IsEnabled
    condition = next(item for item in controls
                     if isinstance(item, ComboBox) and item.Width == 195)
    condition.SelectedItem = 'Greater than'
    assert not editor.use_button.IsEnabled
    value.Text = '1200.5'
    assert editor.use_button.IsEnabled
    assert '[Comments] > 1200.5' in editor.expression_text.Text

    editor.expression_text.Text = 'AND([Width] = 900, [Mark] = "A")'
    remove = next(item for item in descendants(editor.rules_panel)
                  if isinstance(item, Button) and item.Content == 'Remove')
    click(remove)
    assert count_rules(editor.tree) == 1
    assert '[Width]' not in editor.expression_text.Text
    editor.expression_text.Text = 'NOT(NOT([Mark] = "A"))'
    assert editor.use_button.IsEnabled
    assert count_rules(editor.tree) == 1
    editor.expression_text.Text = '[Name]] and [Code] = "a, \\"b\\"\\\\c"'
    assert editor.use_button.IsEnabled
    assert count_rules(editor.tree) == 1

    # Exercise actual modal completion, including Cancel after draft changes.
    editor.window.Loaded += lambda sender, args: editor.cancel(None, None)
    accepted, result = editor.show()
    assert not accepted
    assert result is None
    assert serialize_expression(active) == original

    editor = FilterEditor(owner, parameters, active)
    editor.expression_text.Text = 'OR([Width] >= 900, NOT(ISBLANK([Comments])))'
    editor.window.Loaded += lambda sender, args: editor.accept(None, None)
    accepted, result = editor.show()
    assert accepted
    assert result['operator'] == 'OR'
    assert serialize_expression(active) == original

    editor = FilterEditor(owner, parameters, result)
    editor.clear(None, None)
    editor.window.Loaded += lambda sender, args: editor.accept(None, None)
    accepted, result = editor.show()
    assert accepted and result is None
    editor = FilterEditor(owner, parameters, active)
    controls = list(descendants(editor.rules_panel))
    click(next(item for item in controls
               if isinstance(item, Button) and item.Content == '+ Add Group'))
    remove_group = next(item for item in descendants(editor.rules_panel)
                        if isinstance(item, Button) and item.Content == 'Remove Group')
    click(remove_group)
    assert count_rules(editor.tree) == 2
    editor = FilterEditor(owner, ['Mark'], active)
    assert not editor.use_button.IsEnabled
    assert 'unavailable' in editor.status.Text
    editor.clear(None, None)
    assert editor.use_button.IsEnabled
    capture = os.environ.get('KW_REVALUE_EDITOR_CAPTURE')
    if capture:
        from System.IO import File
        from System.Windows.Media import PixelFormats
        from System.Windows.Media.Imaging import BitmapFrame, PngBitmapEncoder, RenderTargetBitmap
        editor = FilterEditor(owner, parameters, parse_expression(
            'AND([Width] >= 900, OR(CONTAINS([Comments], "External"), '
            'STARTSWITH([Mark], "A")), NOT(ISBLANK([Mark])))'))
        editor.window.FindName('advanced').IsExpanded = True
        editor.window.ShowActivated = False
        editor.window.Show()
        editor.window.UpdateLayout()
        bitmap = RenderTargetBitmap(int(editor.window.ActualWidth),
                                    int(editor.window.ActualHeight),
                                    96, 96, PixelFormats.Pbgra32)
        bitmap.Render(editor.window)
        encoder = PngBitmapEncoder()
        encoder.Frames.Add(BitmapFrame.Create(bitmap))
        stream = File.Create(capture)
        try:
            encoder.Save(stream)
        finally:
            stream.Dispose()
            editor.window.Close()
    owner.Close()
    print('PASS: IronPython WPF editor rules, groups, NOT, numeric input, syntax feedback, '
          'advanced synchronization, Remove, Clear, Cancel isolation and Use Filters.')


if __name__ == '__main__':
    run_checks()
