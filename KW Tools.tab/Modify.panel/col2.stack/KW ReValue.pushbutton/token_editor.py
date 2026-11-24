"""WPF token editing; model writes remain in the existing ReValue Apply path."""
import copy
from clr import GetClrType

from System.Windows import (
    DataObject, DragDrop, DragDropEffects, HorizontalAlignment, Point, VerticalAlignment,
    SystemParameters, Thickness, Visibility, Window, WindowStartupLocation,
    SizeToContent,
)
from System.Windows.Controls import (
    Button, Canvas, CheckBox, ComboBox, ColumnDefinition, ContextMenu, Grid, MenuItem, Orientation,
    RadioButton, RowDefinition, ScrollViewer,
    ScrollBarVisibility, StackPanel, TextBlock, TextBox,
)
from System.Windows.Automation import AutomationProperties
from System.Windows.Input import Key, MouseButtonState
from System.Windows.Media import Brushes
from System.Windows.Shapes import Ellipse
from rule_model import (
    CASES, CASE_LABELS, deep_copy_composition, edit_operation,
    insert_operation, operation, position_controls,
    position_value, describe_operation, serialize_composition,
    validate_composition,
)


class TokenSettings(object):
    """Draft-only settings; parameter names are stored on the operation itself."""
    def __init__(self, editor, item):
        self.editor = editor
        self.item = copy.deepcopy(item)
        self.result = None
        self.fields = {}
        self.window = Window()
        button_type = GetClrType(Button)
        self.window.Resources[button_type] = editor.host.window.FindResource(button_type)
        self.window.Title = 'ReValue - Token Settings'
        self.window.Owner = editor.host.window
        self.window.WindowStartupLocation = WindowStartupLocation.CenterOwner
        self.window.SizeToContent = SizeToContent.Height
        self.window.Width = 490
        self.window.MaxHeight = 700
        self.window.MinWidth = 390
        panel = StackPanel()
        panel.Margin = Thickness(12)
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.Content = panel
        self.window.Content = scroll
        self.panel = panel
        kind = item['kind']
        if kind == 'text':
            self.text('Literal text (spaces are preserved)', 'text', item.get('text', ''))
        elif kind == 'source':
            self.note('Count from Start or End. Position 1 from End is the last token.')
            self.position_row('Start position', 'start',
                              item.get('start', {'direction': 'start', 'index': 1}))
            include_range = CheckBox()
            include_range.Content = 'Include a range'
            include_range.Margin = Thickness(0, 5, 0, 5)
            include_range.IsChecked = bool(item.get('end'))
            self.fields['range'] = include_range
            panel.Children.Add(include_range)
            self.position_row('End position', 'end',
                              item.get('end') or {'direction': 'end', 'index': 1}, True)
            self.combo('Join separator (ranges; enter custom text exactly, without wrapping quotes)', 'join',
                       ['', 'hyphen', 'space', 'underscore', '/', '.'],
                       item.get('separator', ''), editable=True)
            self.position_hint = self.note('')
            include_range.Checked += self.positions_changed
            include_range.Unchecked += self.positions_changed
            for name in ('start', 'end'):
                self.fields[name].TextChanged += self.positions_changed
                for direction in self.fields[name + '_directions']:
                    direction.Checked += self.positions_changed
            self.positions_changed(None, None)
        elif kind == 'parameter':
            self.note('Choose the Revit parameter read directly by this chip.')
            self.combo('Parameter', 'parameter', [''] + list(editor.host.available_params),
                       item.get('parameter', ''))
        elif kind == 'counter':
            self.note('Repeated Counter chips use the same row value.\n'
                      'Configure Start and Increment directly on this chip.')
            self.text('Start', 'counter_start', item.get('start', 'A'))
            self.text('Increment (nonnegative integer)', 'counter_increment',
                      str(item.get('increment', 1)))
        if kind != 'text':
            self.combo('Text case (this chip)', 'case', [CASE_LABELS[case] for case in CASES],
                       CASE_LABELS[item.get('case', 'Unchanged')])
        if kind in ('source', 'parameter'):
            self.note('Progression supports a single position counted from Start or a parameter name, not ranges.\n'
                      'Increment: each row independently. Sequence: first unfiltered row plus row position.')
            progression = item.get('progression')
            self.combo('Progression', 'operation', ['None', 'Increment', 'Sequence'],
                       {'inc': 'Increment', 'seq': 'Sequence'}.get(
                           progression['kind'] if progression else '', 'None'))
            self.text('Step (signed integer, e.g. 2 or -1)', 'step',
                      str(progression['step'] if progression else 1))
        self.error = self.note('')
        self.error.Foreground = Brushes.Firebrick
        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.HorizontalAlignment = HorizontalAlignment.Right
        ok = editor.button('OK', self.accept)
        ok.IsDefault = True
        cancel = editor.button('Cancel', lambda sender, args: self.window.Close())
        cancel.IsCancel = True
        actions.Children.Add(ok)
        actions.Children.Add(cancel)
        panel.Children.Add(actions)

    def note(self, text):
        block = TextBlock()
        block.Text = text
        from System.Windows import TextWrapping
        block.TextWrapping = TextWrapping.Wrap
        block.Margin = Thickness(0, 3, 0, 6)
        self.panel.Children.Add(block)
        return block

    def text(self, title, name, value):
        self.note(title)
        field = TextBox()
        field.Text = value
        field.Margin = Thickness(0, 0, 0, 6)
        self.panel.Children.Add(field)
        self.fields[name] = field

    def combo(self, title, name, options, value, editable=False):
        self.note(title)
        field = ComboBox()
        field.IsEditable = editable
        for option in options:
            field.Items.Add(option)
        if value is not None and value not in options:
            field.Items.Add(value)
        field.SelectedItem = value
        field.Margin = Thickness(0, 0, 0, 6)
        self.panel.Children.Add(field)
        self.fields[name] = field

    def accept(self, sender, args):
        candidate = copy.deepcopy(self.item)
        candidate.pop('raw', None)
        counter = None
        try:
            for name in ('text', 'step'):
                if name in self.fields:
                    value = self.fields[name].Text
                    candidate[name] = value if name == 'text' else value.strip()
            if candidate['kind'] == 'source':
                candidate['start'] = self.read_position('start')
                candidate['end'] = (self.read_position('end')
                                    if self.fields['range'].IsChecked else None)
            if 'case' in self.fields:
                case_index = self.fields['case'].SelectedIndex
                if case_index < 0:
                    raise ValueError('Choose a text case.')
                candidate['case'] = CASES[case_index]
            if 'join' in self.fields:
                candidate['separator'] = self.fields['join'].Text
            if candidate['kind'] == 'source' and not self.fields['range'].IsChecked:
                candidate['separator'] = ''
            if 'operation' in self.fields:
                operation_name = {
                    'None': '', 'Increment': 'inc', 'Sequence': 'seq',
                }[self.fields['operation'].SelectedItem]
                candidate['progression'] = (
                    {'kind': operation_name, 'step': int(candidate['step'])}
                    if operation_name else None)
            if candidate['kind'] == 'parameter':
                name = self.fields['parameter'].SelectedItem
                if not name:
                    raise ValueError('Choose an available parameter.')
                if name not in self.editor.host.available_params:
                    raise ValueError('This parameter is unavailable in the current mode.')
                candidate['parameter'] = str(name).strip()
            if candidate['kind'] == 'text' and not candidate['text']:
                raise ValueError('Enter literal text, including at least one character or space.')
            if candidate['kind'] == 'counter':
                start = self.fields['counter_start'].Text
                increment = self.fields['counter_increment'].Text
                unused, error = self.editor.counter_builder(start, increment)
                if error:
                    raise ValueError(error)
                candidate['start'] = start.strip()
                candidate['increment'] = int(increment.strip())
            validate_composition({'version': 1, 'operations': [candidate]})
        except ValueError as ex:
            self.error.Text = str(ex)
            return
        self.result = candidate, None, counter
        self.window.DialogResult = True

    def position_row(self, title, name, spec, is_end=False):
        self.note(title)
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        direction, number = position_controls(spec)
        buttons = []
        for value in (('Start', 'End', 'Following') if is_end else ('Start', 'End')):
            button = RadioButton()
            button.Content = value
            button.GroupName = name + '_direction'
            button.Style = self.editor.host.window.FindResource('TokenDirectionStyle')
            button.IsChecked = value == direction
            button.ToolTip = ('Additional tokens after the start (0 allowed).' if value == 'Following'
                              else 'Count from the {}: 1 is the {} token.'.format(
                                  value.lower(), 'first' if value == 'Start' else 'last'))
            AutomationProperties.SetName(button, title + ': ' + value)
            row.Children.Add(button)
            buttons.append(button)
        field = TextBox()
        field.Text = number
        field.Width = 62
        field.Margin = Thickness(8, 0, 0, 0)
        AutomationProperties.SetName(field, title + ' number')
        row.Children.Add(field)
        self.fields[name] = field
        self.fields[name + '_directions'] = buttons
        self.fields[name + '_row'] = row
        self.panel.Children.Add(row)

    def read_position(self, name):
        direction = next(button.Content for button in self.fields[name + '_directions']
                         if button.IsChecked)
        return position_value(direction, self.fields[name].Text, name == 'end')

    def positions_changed(self, sender, args):
        ranged = bool(self.fields['range'].IsChecked)
        self.fields['end_row'].IsEnabled = ranged
        self.fields['join'].IsEnabled = ranged
        try:
            start = self.read_position('start')
            end = self.read_position('end') if ranged else ''
            start_direction = start['direction']
            start_number = start.get('index')
            if end:
                end_direction = end['direction']
                if end_direction == 'following':
                    self.position_hint.Text = 'Selection: {} {} plus {} following'.format(
                        start_direction.title(), start_number, end['count'])
                else:
                    self.position_hint.Text = 'Selection: {} {} to {} {}'.format(
                        start_direction.title(), start_number,
                        end_direction.title(), end.get('index', 1))
            else:
                self.position_hint.Text = 'Selection: {} {}'.format(
                    start_direction.title(), start_number)
        except ValueError as ex:
            self.position_hint.Text = str(ex)

    def show(self):
        self.window.ShowDialog()
        return self.result


class TokenEditor(object):
    DRAG_FORMAT = 'KW.ReValue.Token'

    def __init__(self, host, counter_builder):
        self.host = host
        self.counter_builder = counter_builder
        self.items = deep_copy_composition(host.composition)['operations']
        self.selected = -1
        self.samples = []
        self.source_text = ''
        self._signature = None
        self._syncing = False
        self._drag = None
        window = host.window
        self.panel = window.FindName('token_editor_panel')
        self.palette = window.FindName('token_palette')
        self.bar = window.FindName('token_bar')
        self.bar_scroll = window.FindName('token_bar_scroll')
        self.insertion_caret = window.FindName('token_insertion_caret')
        self.status = window.FindName('token_status')
        self.sample_label = window.FindName('token_sample')
        self.clear_button = window.FindName('btn_clear_tokens')
        window.FindName('btn_add_token').Click += self.add_menu
        if self.clear_button:
            self.clear_button.Click += self.clear
        window.AllowDrop = True
        window.DragOver += self.outside_drag_over
        window.Drop += self.outside_drop
        self.bar.AllowDrop = True
        self.bar.DragOver += self.drag_over
        self.bar.DragLeave += self.drag_leave
        self.bar.Drop += self.drop
        self.refresh()

    def button(self, text, callback):
        button = Button()
        button.Content = text
        button.Padding = Thickness(6, 3, 6, 3)
        button.Margin = Thickness(2)
        button.Click += callback
        return button

    def icon_content(self, button, kind):
        button.Style = self.host.window.FindResource('TokenPillStyle')
        button.Padding = Thickness(5, 1, 9, 1)
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        grip = Grid()
        grip.Width = 10
        grip.Height = 18
        grip.Margin = Thickness(0, 0, 6, 0)
        grip.VerticalAlignment = VerticalAlignment.Center
        for column in range(2):
            grip.ColumnDefinitions.Add(ColumnDefinition())
        for row in range(3):
            grip.RowDefinitions.Add(RowDefinition())
        for row in range(3):
            for column in range(2):
                dot = Ellipse()
                dot.Width = 3
                dot.Height = 3
                dot.Fill = Brushes.DimGray
                dot.HorizontalAlignment = HorizontalAlignment.Center
                dot.VerticalAlignment = VerticalAlignment.Center
                Grid.SetRow(dot, row)
                Grid.SetColumn(dot, column)
                grip.Children.Add(dot)
        text = TextBlock()
        text.Margin = Thickness(0)
        text.Text = button.Content
        AutomationProperties.SetName(button, text.Text)
        panel.Children.Add(grip)
        panel.Children.Add(text)
        button.Content = panel

    def refresh(self):
        composition = deep_copy_composition(self.host.composition)
        sample = self.host.get_token_sample_item()
        self.source_text = sample.CurrentName if sample is not None else ''
        self.samples = self.host.get_tokenizer_func()(self.source_text)
        signature = (serialize_composition(composition),
                     self.source_text, tuple(self.samples))
        if signature == self._signature:
            return
        sample_only = self._signature is not None and signature[:2] == self._signature[:2]
        previous_count = len(self._signature[2]) if self._signature is not None else -1
        self._signature = signature
        self.sample_label.Text = 'Sample (selection / first visible row): ' + (
            self.source_text if sample is not None else '(no visible rows)')
        self.sample_label.ToolTip = self.source_text
        if sample_only and self.items:
            if previous_count == len(self.samples):
                for index, value in enumerate(self.samples):
                    button = self.palette.Children[index + 1]
                    title = '{}: {}'.format(index + 1, value)
                    self.update_chip_label(button, title if len(title) < 38 else title[:35] + '...')
                    button.ToolTip = title + '\nClick to add, or drag into the bar.'
            else:
                self.render_palette()
            for index, item in enumerate(self.items):
                self.update_chip_label(
                    self.bar.Children[index],
                    describe_operation(item, self.samples))
            return
        try:
            validate_composition(composition)
            if repr(composition['operations']) != repr(self.items):
                self.items = deep_copy_composition(composition['operations'])
        except ValueError as ex:
            self.items = []
            self.status.Text = str(ex)
            self.bar.Children.Clear()
            return
        self.selected = min(self.selected, len(self.items) - 1)
        missing = sorted(set(
            item['parameter'] for item in self.items
            if item['kind'] == 'parameter'
            and item.get('parameter') not in self.host.available_params))
        self.status.Text = (
            'Unavailable parameter chip(s): {}. Right-click a parameter chip to edit.'
            .format(', '.join(missing)) if missing else
            'Drag to insert/reorder. Double-click to edit. Right-click for options.')
        if self.clear_button:
            self.clear_button.IsEnabled = bool(self.items)
        self.render_palette()
        self.render_bar()

    def update_chip_label(self, button, text):
        button.Content.Children[1].Text = text
        AutomationProperties.SetName(button, text)

    def render_palette(self):
        self.palette.Children.Clear()
        entries = [('Original', operation('original'))]
        entries += [('{}: {}'.format(i + 1, sample),
                     operation('source', start={'direction': 'start', 'index': i + 1}))
                    for i, sample in enumerate(self.samples)]
        entries += [
            ('Last', operation('source', start={'direction': 'end', 'index': 1})),
            ('Range...', operation('source',
                                   start={'direction': 'start', 'index': 1},
                                   end={'direction': 'end', 'index': 1},
                                   separator='')),
            ('Parameter...', operation('parameter', parameter='')),
            ('Counter', operation('counter')),
            ('Space', operation('text', text=' ')),
            ('Hyphen', operation('text', text='-')),
            ('Underscore', operation('text', text='_')),
            ('Text...', operation('text', text='')),
        ]
        for title, item in entries:
            configure = title in ('Range...', 'Parameter...', 'Text...')
            self.palette.Children.Add(self.palette_button(title, item, configure))

    def palette_button(self, title, item, configure):
        # A normal click is a keyboard-accessible alternative to dragging.
        button = self.button(title if len(title) < 38 else title[:35] + '...',
                             lambda sender, args: self.add(item, configure))
        button.ToolTip = title + '\nClick to add, or drag into the bar.'
        self.icon_content(button, item['kind'])
        self.wire_drag(button, ('palette', copy.deepcopy(item), configure))
        return button

    def render_bar(self, focus=False):
        self.clear_insertion()
        self.bar.Children.Clear()
        for index, item in enumerate(self.items):
            button = self.button(describe_operation(item, self.samples),
                                 lambda sender, args, i=index: self.select(i))
            self.icon_content(button, item['kind'])
            button.Tag = index
            button.ToolTip = describe_operation(item, self.samples)
            if item['kind'] == 'text':
                button.ToolTip += '\n{} character(s); spaces are preserved.'.format(len(item['text']))
            button.BorderBrush = Brushes.MidnightBlue if index == self.selected else Brushes.SteelBlue
            button.BorderThickness = Thickness(2 if index == self.selected else 1)
            button.MouseDoubleClick += lambda sender, args, i=index: self.edit(i)
            button.ContextMenu = self.context_menu(index)
            button.PreviewKeyDown += lambda sender, args, i=index: self.key_down(i, args)
            self.wire_drag(button, ('bar', index, False))
            self.bar.Children.Add(button)
        if not self.items:
            hint = TextBlock()
            hint.Text = 'Drop tokens here, or use + Add.'
            hint.Margin = Thickness(8)
            self.bar.Children.Add(hint)
        if focus and 0 <= self.selected < len(self.items):
            self.bar.Children[self.selected].Focus()

    def select(self, index):
        self.selected = index
        for i in range(len(self.items)):
            child = self.bar.Children[i]
            child.BorderBrush = Brushes.MidnightBlue if i == index else Brushes.SteelBlue
            child.BorderThickness = Thickness(2 if i == index else 1)

    def key_down(self, index, args):
        if args.Key == Key.Delete:
            self.remove(index)
            args.Handled = True

    def menu_item(self, menu, text, callback=None, enabled=True):
        item = MenuItem()
        item.Header = text
        item.IsEnabled = enabled
        if callback is not None:
            item.Click += callback
        menu.Items.Add(item)
        return item

    def context_menu(self, index):
        menu = ContextMenu()
        item = self.items[index]
        self.menu_item(menu, 'Edit...', lambda sender, args: self.edit(index))
        if item['kind'] != 'text':
            case_menu = self.menu_item(menu, 'Text Case')
            for case in CASES:
                entry = self.menu_item(case_menu, CASE_LABELS[case],
                    lambda sender, args, value=case: self.set_case(index, value))
                entry.IsCheckable = True
                entry.IsChecked = item.get('case', 'Unchanged') == case
        if item['kind'] in ('source', 'parameter'):
            eligible = (item['kind'] == 'parameter' or
                        (item['start'].get('direction') == 'start'
                         and item.get('end') is None))
            progress = self.menu_item(menu, 'Progression', enabled=eligible)
            for title, operation in [('None', ''), ('Increment Each Value...', 'inc'),
                                     ('Sequence from First Row...', 'seq')]:
                self.menu_item(progress, title,
                    lambda sender, args, op=operation: self.edit(index, operation=op))
        if item['kind'] == 'source':
            self.menu_item(menu, 'Token Selection...', lambda sender, args: self.edit(index))
            if item.get('end'):
                joins = self.menu_item(menu, 'Join Separator')
                for title, separator in (('hyphen', '-'), ('space', ' '), ('underscore', '_')):
                    self.menu_item(joins, title,
                        lambda sender, args, value=separator: self.set_join(index, value))
                self.menu_item(joins, 'Custom...', lambda sender, args: self.edit(index))
        if item['kind'] == 'parameter':
            self.menu_item(menu, 'Choose Parameter...', lambda sender, args: self.edit(index))
        if item['kind'] == 'counter':
            self.menu_item(menu, 'Counter Settings...', lambda sender, args: self.edit(index))
        self.menu_item(menu, 'Duplicate', lambda sender, args: self.duplicate(index))
        self.menu_item(menu, 'Move Left', lambda sender, args: self.move(index, index - 1), index > 0)
        self.menu_item(menu, 'Move Right', lambda sender, args: self.move(index, index + 2),
                       index < len(self.items) - 1)
        self.menu_item(menu, 'Remove', lambda sender, args: self.remove(index))
        return menu

    def set_case(self, index, case):
        items = copy.deepcopy(self.items)
        items[index] = edit_operation(items[index], case=case)
        self.commit(items, index)

    def set_join(self, index, join):
        items = copy.deepcopy(self.items)
        items[index] = edit_operation(items[index], separator=join)
        self.commit(items, index)

    def add_menu(self, sender, args):
        menu = ContextMenu()
        for title, item in [
                ('Original', operation('original')),
                ('Source Token...', operation('source',
                                              start={'direction': 'start', 'index': 1})),
                ('Range...', operation('source',
                                       start={'direction': 'start', 'index': 1},
                                       end={'direction': 'end', 'index': 1},
                                       separator='')),
                ('Parameter...', operation('parameter', parameter='')),
                ('Counter...', operation('counter')),
                ('Space', operation('text', text=' ')),
                ('Hyphen', operation('text', text='-')),
                ('Underscore', operation('text', text='_')),
                ('Text...', operation('text', text=''))]:
            self.menu_item(menu, title,
                lambda sender, args, value=item, config=title.endswith('...'): self.add(value, config))
        menu.PlacementTarget = sender
        menu.IsOpen = True

    def add(self, item, configure=False, destination=None):
        if not self.host.commit_preview_edits():
            return
        if configure:
            result = TokenSettings(self, item).show()
            if result is None:
                return
            item, unused_result, unused_counter = result
        if destination is None:
            destination = self.selected + 1 if self.selected >= 0 else len(self.items)
        items, index = insert_operation(self.items, item, destination)
        self.commit(items, index)

    def edit(self, index, **values):
        if not self.host.commit_preview_edits():
            return
        item = copy.deepcopy(self.items[index])
        if 'operation' in values:
            operation_name = values['operation']
            item['progression'] = (
                {'kind': operation_name, 'step': item.get('progression', {}).get('step', 1)}
                if operation_name else None)
        else:
            item.update(values)
        result = TokenSettings(self, item).show()
        if result is not None:
            item, unused_result, unused_counter = result
            items = copy.deepcopy(self.items)
            items[index] = item
            self.commit(items, index)

    def duplicate(self, index):
        items, selected = insert_operation(self.items, self.items[index], index + 1)
        self.commit(items, selected)

    def remove(self, index):
        items = copy.deepcopy(self.items)
        items.pop(index)
        self.commit(items, min(index, len(items) - 1))

    def clear(self, sender=None, args=None):
        if not self.items:
            return
        self.commit([], -1)

    def move(self, index, destination):
        items, selected = insert_operation(self.items, None, destination, index)
        self.commit(items, selected)

    def commit(self, items, selected):
        if not self.host.commit_preview_edits():
            return
        suspended = self.host._suspend_events
        self.host._suspend_events = True
        try:
            self.selected = selected
            self.items = copy.deepcopy(items)
            self.host.composition = {
                'version': 1,
                'operations': copy.deepcopy(items),
            }
        finally:
            self.host._suspend_events = suspended
        self._signature = None
        self.host.OnSettingsChanged(None, None)
        self.refresh()
        self.render_bar(True)

    def wire_drag(self, button, payload):
        def down(sender, args):
            if args.ChangedButton.ToString() == 'Left':
                self._drag = (button, args.GetPosition(button), payload)

        def motion(sender, args):
            if self._drag is None or args.LeftButton != MouseButtonState.Pressed:
                return
            origin, start, data = self._drag
            if origin is not button:
                return
            point = args.GetPosition(button)
            if (abs(point.X - start.X) < SystemParameters.MinimumHorizontalDragDistance and
                    abs(point.Y - start.Y) < SystemParameters.MinimumVerticalDragDistance):
                return
            data_object = DataObject()
            data_object.SetData(self.DRAG_FORMAT, self.DRAG_FORMAT)
            try:
                effect = DragDropEffects.Move if data[0] == 'bar' else DragDropEffects.Copy
                DragDrop.DoDragDrop(button, data_object, effect)
            finally:
                self._drag = None
                self.clear_insertion()
            args.Handled = True
        button.PreviewMouseLeftButtonDown += down
        button.PreviewMouseMove += motion

    def drop_position(self, point):
        for index in range(len(self.items)):
            child = self.bar.Children[index]
            origin = child.TranslatePoint(Point(0, 0), self.bar)
            bottom = origin.Y + child.ActualHeight
            if point.Y < origin.Y:
                return index
            if point.Y <= bottom:
                if point.X < origin.X + child.ActualWidth / 2:
                    return index
                if point.X <= origin.X + child.ActualWidth:
                    return index + 1
                # If this is the last chip on the row, the trailing gap belongs to it.
                if index + 1 == len(self.items):
                    return index + 1
                next_origin = self.bar.Children[index + 1].TranslatePoint(Point(0, 0), self.bar)
                if next_origin.Y > origin.Y:
                    return index + 1
        return len(self.items)

    def clear_insertion(self):
        self.insertion_caret.Visibility = Visibility.Collapsed

    def show_insertion(self, gap, point):
        x, y = 2, 2
        if self.items:
            index = min(gap, len(self.items) - 1)
            child = self.bar.Children[index]
            origin = child.TranslatePoint(Point(0, 0), self.bar)
            trailing = gap == len(self.items)
            if gap > 0 and not trailing:
                previous = self.bar.Children[gap - 1]
                previous_origin = previous.TranslatePoint(Point(0, 0), self.bar)
                # The same gap can be the end of one wrapped row or start of the next.
                if previous_origin.Y < origin.Y and point.Y < origin.Y:
                    child, origin = previous, previous_origin
                    trailing = True
            x = origin.X + child.ActualWidth if trailing else origin.X - 4
            y = origin.Y + max(0, (child.ActualHeight - 22) / 2)
        Canvas.SetLeft(self.insertion_caret, max(0, min(x, self.bar.ActualWidth - 5)))
        Canvas.SetTop(self.insertion_caret, y)
        self.insertion_caret.Visibility = Visibility.Visible

    def drag_over(self, sender, args):
        self.clear_insertion()
        if self._drag is None or not args.Data.GetDataPresent(self.DRAG_FORMAT):
            args.Effects = getattr(DragDropEffects, 'None')
        else:
            args.Effects = (DragDropEffects.Move if self._drag[2][0] == 'bar'
                            else DragDropEffects.Copy)
            point = args.GetPosition(self.bar_scroll)
            if point.Y < 15:
                self.bar_scroll.LineUp()
            elif point.Y > self.bar_scroll.ActualHeight - 15:
                self.bar_scroll.LineDown()
            point = args.GetPosition(self.bar)
            self.show_insertion(self.drop_position(point), point)
        args.Handled = True

    def drag_leave(self, sender, args):
        self.clear_insertion()

    def point_in_token_field(self, args):
        point = args.GetPosition(self.bar_scroll)
        return (0 <= point.X <= self.bar_scroll.ActualWidth
                and 0 <= point.Y <= self.bar_scroll.ActualHeight)

    def outside_drag_over(self, sender, args):
        self.clear_insertion()
        if (self._drag is not None
                and self._drag[2][0] == 'bar'
                and args.Data.GetDataPresent(self.DRAG_FORMAT)
                and not self.point_in_token_field(args)):
            args.Effects = DragDropEffects.Move
        else:
            args.Effects = getattr(DragDropEffects, 'None')
        args.Handled = True

    def drop(self, sender, args):
        self.clear_insertion()
        if self._drag is not None and args.Data.GetDataPresent(self.DRAG_FORMAT):
            kind, value, configure = self._drag[2]
            destination = self.drop_position(args.GetPosition(self.bar))
            if kind == 'bar':
                self.move(value, destination)
            else:
                self.add(value, configure, destination)
        args.Handled = True

    def outside_drop(self, sender, args):
        self.clear_insertion()
        if (self._drag is not None
                and self._drag[2][0] == 'bar'
                and args.Data.GetDataPresent(self.DRAG_FORMAT)
                and not self.point_in_token_field(args)):
            index = self._drag[2][1]
            if 0 <= index < len(self.items):
                self.remove(index)
            args.Effects = DragDropEffects.Move
        else:
            args.Effects = getattr(DragDropEffects, 'None')
        args.Handled = True
