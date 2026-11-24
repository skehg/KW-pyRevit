"""WPF token editing; model writes remain in the existing ReValue Apply path."""
import copy
from clr import GetClrType

from System.Windows import (
    CornerRadius, DataObject, DragDrop, DragDropEffects, FontWeights,
    HorizontalAlignment, Point, VerticalAlignment,
    SystemParameters, Thickness, Visibility, Window, WindowStartupLocation,
    SizeToContent,
)
from System.Windows.Controls import (
    Border, Button, Canvas, CheckBox, ComboBox, ColumnDefinition, ContextMenu, Grid, MenuItem, Orientation,
    RadioButton, RowDefinition, ScrollViewer,
    ScrollBarVisibility, StackPanel, TextBlock, TextBox,
)
from System.Windows.Automation import AutomationProperties
from System.Windows.Input import Key, Keyboard, ModifierKeys, MouseButtonState
from System.Windows.Media import Brushes
from System.Windows.Shapes import Ellipse
from rule_model import (
    CASES, CASE_LABELS, deep_copy_composition, edit_operation,
    insert_operation, operation, position_controls,
    position_value, describe_operation,
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
            self.selection_editor(panel, item)
        elif kind == 'parameter':
            self.note('Choose the Revit parameter read directly by this chip.')
            self.combo('Parameter', 'parameter', [''] + list(editor.host.available_params),
                       item.get('parameter', ''))
            tokenize = CheckBox()
            tokenize.Content = 'Tokenise parameter value'
            tokenize.IsChecked = bool(item.get('tokenize', False))
            tokenize.Margin = Thickness(0, 3, 0, 6)
            self.fields['tokenize'] = tokenize
            panel.Children.Add(tokenize)
            token_panel = StackPanel()
            token_panel.Visibility = (
                Visibility.Visible if tokenize.IsChecked else Visibility.Collapsed)
            self.fields['token_panel'] = token_panel
            panel.Children.Add(token_panel)
            self.selection_editor(token_panel, item, include_delimiters=True)
            tokenize.Checked += self.parameter_tokenize_changed
            tokenize.Unchecked += self.parameter_tokenize_changed
        elif kind == 'counter':
            self.note('Repeated Counter chips use the same row value.\n'
                      'Configure Start and Increment directly on this chip.')
            self.text('Start', 'counter_start', item.get('start', 'A'))
            self.text('Increment (nonnegative integer)', 'counter_increment',
                      str(item.get('increment', 1)))
        if kind != 'text':
            self.combo('Text case (this chip)', 'case', [CASE_LABELS[case] for case in CASES],
                       CASE_LABELS[item.get('case', 'Unchanged')])
        if kind in ('source', 'parameter', 'original'):
            if kind == 'original':
                self.note('Progression uses the complete original value.')
            elif kind == 'parameter' and item.get('tokenize'):
                self.note('Progression supports a single parameter token counted from Start.')
            else:
                self.note('Progression supports a single Start position or a parameter name, not ranges.')
            progression = item.get('progression')
            operation_label = TextBlock()
            operation_label.Text = 'Progression'
            operation_label.Margin = Thickness(0, 0, 8, 0)
            operation_label.VerticalAlignment = VerticalAlignment.Center
            operation = ComboBox()
            operation.Width = 128
            for label in ('None', 'Increment', 'Sequence'):
                operation.Items.Add(label)
            operation.SelectedItem = {'inc': 'Increment', 'seq': 'Sequence'}.get(
                progression['kind'] if progression else '', 'None')
            operation.Margin = Thickness(0, 0, 12, 0)
            step_label = TextBlock()
            step_label.Text = 'Step'
            step_label.Margin = Thickness(0, 0, 8, 0)
            step_label.VerticalAlignment = VerticalAlignment.Center
            step = TextBox()
            step.Text = str(progression['step'] if progression else 1)
            step.Width = 62
            step.ToolTip = 'Signed integer, for example 2 or -1'
            compact_row = StackPanel()
            compact_row.Orientation = Orientation.Horizontal
            compact_row.Children.Add(operation_label)
            compact_row.Children.Add(operation)
            compact_row.Children.Add(step_label)
            compact_row.Children.Add(step)
            panel.Children.Add(compact_row)
            self.fields['operation'] = operation
            self.fields['step'] = step
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

    def note(self, text, parent=None):
        block = TextBlock()
        block.Text = text
        from System.Windows import TextWrapping
        block.TextWrapping = TextWrapping.Wrap
        block.Margin = Thickness(0, 3, 0, 6)
        (parent or self.panel).Children.Add(block)
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

    def selection_editor(self, parent, item, include_delimiters=False):
        self.note('Selections combine ranges and individual positions.', parent)
        if include_delimiters:
            self.note('Delimiters', parent)
            delimiters = TextBox()
            delimiters.Text = item.get('delimiters', r'-_/,\|')
            delimiters.Margin = Thickness(0, 0, 0, 6)
            delimiters.ToolTip = 'Characters used to split the parameter value into tokens.'
            self.fields['delimiters'] = delimiters
            parent.Children.Add(delimiters)
        self.fields['selections'] = copy.deepcopy(item.get('selections', [
            {'kind': 'single',
             'position': {'direction': 'start', 'index': 1}},
        ]))
        self.selection_host = StackPanel()
        parent.Children.Add(self.selection_host)
        self.selection_containers = []
        self.position_hint = self.note('', parent)
        self.render_selections()
        add_row = StackPanel()
        add_row.Orientation = Orientation.Horizontal
        add_button = self.editor.button(
            '+ Add selection', lambda sender, args: self.add_selection())
        add_row.Children.Add(add_button)
        join_hint = TextBlock()
        join_hint.Text = 'Join with'
        join_hint.Margin = Thickness(8, 5, 6, 0)
        join_hint.VerticalAlignment = VerticalAlignment.Center
        add_row.Children.Add(join_hint)
        join_combo = ComboBox()
        join_combo.IsEditable = True
        join_combo.Width = 88
        join_options = ('', '-', ' ', '_', '/', '.')
        for option in join_options:
            join_combo.Items.Add(option)
        separator = item.get('separator', '')
        if separator not in join_options:
            join_combo.Items.Add(separator)
        join_combo.SelectedItem = separator
        join_combo.SelectionChanged += self.positions_changed
        add_row.Children.Add(join_combo)
        self.fields['join'] = join_combo
        parent.Children.Add(add_row)
        self.positions_changed(None, None)

    def parameter_tokenize_changed(self, sender, args):
        panel = self.fields.get('token_panel')
        if panel is not None:
            panel.Visibility = (
                Visibility.Visible if bool(sender.IsChecked)
                else Visibility.Collapsed)

    def compact_position_row(self, title, name, spec, is_end=False):
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        direction, number = position_controls(spec)
        label = TextBlock()
        label.Text = title
        label.Margin = Thickness(0, 0, 6, 0)
        row.Children.Add(label)
        count_from = ComboBox()
        count_from.Width = 82
        count_from.Margin = Thickness(0, 0, 6, 0)
        options = ('Start', 'End', 'Following') if is_end else ('Start', 'End')
        for option in options:
            count_from.Items.Add(option)
        count_from.SelectedItem = direction
        count_from.SelectionChanged += self.positions_changed
        row.Children.Add(count_from)
        field = TextBox()
        field.Text = number
        field.Width = 62
        field.TextChanged += self.positions_changed
        row.Children.Add(field)
        return row, {'direction': count_from, 'number': field}

    def read_compact_position(self, name, fields, is_end=False):
        direction = str(fields['direction'].SelectedItem)
        return position_value(direction, fields['number'].Text, is_end)

    def render_selections(self):
        self._rendering_selections = True
        self.selection_host.Children.Clear()
        self.selection_containers = []
        for index, selection in enumerate(self.fields['selections']):
            card = Border()
            card.BorderBrush = Brushes.LightSlateGray
            card.BorderThickness = Thickness(1)
            card.CornerRadius = self.corner_radius()
            card.Margin = Thickness(0, 3, 0, 3)
            card.Padding = Thickness(8)
            card_stack = StackPanel()
            header = StackPanel()
            header.Orientation = Orientation.Horizontal
            number = TextBlock()
            number.Text = '{:02d}'.format(index + 1)
            number.Width = 34
            number.FontWeight = FontWeights.Bold
            number.Foreground = Brushes.DimGray
            header.Children.Add(number)
            kind = ComboBox()
            kind.Width = 120
            kind.Items.Add('Range')
            kind.Items.Add('Single position')
            kind.SelectedItem = ('Range' if selection['kind'] == 'range'
                                 else 'Single position')
            kind.SelectionChanged += lambda sender, args, i=index: self.selection_kind_changed(i, sender.SelectedItem)
            header.Children.Add(kind)
            up = self.editor.button('\u2191', lambda sender, args, i=index: self.move_selection(i, i - 1))
            up.Width = 30
            up.IsEnabled = index > 0
            header.Children.Add(up)
            down = self.editor.button('\u2193', lambda sender, args, i=index: self.move_selection(i, i + 1))
            down.Width = 30
            down.IsEnabled = index < len(self.fields['selections']) - 1
            header.Children.Add(down)
            remove = self.editor.button('\u00d7', lambda sender, args, i=index: self.remove_selection(i))
            remove.Width = 30
            remove.IsEnabled = len(self.fields['selections']) > 1
            header.Children.Add(remove)
            card_stack.Children.Add(header)
            body = StackPanel()
            body.Margin = Thickness(34, 6, 0, 0)
            container = {'kind': kind}
            if selection['kind'] == 'range':
                start_row, start_fields = self.compact_position_row(
                    'FROM', 'start', selection['start'], False)
                end_row, end_fields = self.compact_position_row(
                    'TO', 'end', selection['end'], True)
                body.Children.Add(start_row)
                end_row.Margin = Thickness(0, 6, 0, 0)
                body.Children.Add(end_row)
                container['start'] = start_fields
                container['end'] = end_fields
            else:
                position_row, position_fields = self.compact_position_row(
                    'COUNT FROM', 'position', selection['position'], False)
                body.Children.Add(position_row)
                container['position'] = position_fields
            card_stack.Children.Add(body)
            card.Child = card_stack
            self.selection_host.Children.Add(card)
            self.selection_containers.append(container)
        self._rendering_selections = False
        self.positions_changed(None, None)

    def corner_radius(self):
        from System.Windows import CornerRadius
        return CornerRadius(4)

    def add_selection(self):
        selections = copy.deepcopy(self.fields['selections'])
        selections.append({'kind': 'single',
                           'position': {'direction': 'start', 'index': 1}})
        self.fields['selections'] = selections
        self.render_selections()

    def remove_selection(self, index):
        selections = copy.deepcopy(self.fields['selections'])
        if 0 <= index < len(selections) and len(selections) > 1:
            selections.pop(index)
            self.fields['selections'] = selections
            self.render_selections()

    def move_selection(self, index, destination):
        selections = copy.deepcopy(self.fields['selections'])
        if not (0 <= destination < len(selections)):
            return
        selection = selections.pop(index)
        selections.insert(destination, selection)
        self.fields['selections'] = selections
        self.render_selections()

    def selection_kind_changed(self, index, selected):
        if getattr(self, '_rendering_selections', False):
            return
        kind = 'range' if str(selected) == 'Range' else 'single'
        selections = copy.deepcopy(self.fields['selections'])
        if kind == 'range':
            selections[index] = {
                'kind': 'range',
                'start': {'direction': 'start', 'index': 1},
                'end': {'direction': 'end', 'index': 1},
            }
        else:
            selections[index] = {
                'kind': 'single',
                'position': {'direction': 'start', 'index': 1},
            }
        self.fields['selections'] = selections
        self.render_selections()

    def accept(self, sender, args):
        candidate = copy.deepcopy(self.item)
        candidate.pop('raw', None)
        counter = None
        try:
            for name in ('text', 'step'):
                if name in self.fields:
                    value = self.fields[name].Text
                    candidate[name] = value if name == 'text' else value.strip()
            tokenized_parameter = (
                candidate['kind'] == 'parameter'
                and bool(self.fields.get('tokenize').IsChecked)
                if 'tokenize' in self.fields else False)
            if candidate['kind'] == 'source' or tokenized_parameter:
                selections = []
                for container in self.selection_containers:
                    if str(container['kind'].SelectedItem) == 'Range':
                        selections.append({
                            'kind': 'range',
                            'start': self.read_compact_position(
                                'start', container['start'], False),
                            'end': self.read_compact_position(
                                'end', container['end'], True),
                        })
                    else:
                        selections.append({
                            'kind': 'single',
                            'position': self.read_compact_position(
                                'position', container['position'], False),
                        })
                candidate['selections'] = selections
                if candidate['kind'] == 'source':
                    candidate.pop('start', None)
                    candidate.pop('end', None)
            if 'case' in self.fields:
                case_index = self.fields['case'].SelectedIndex
                if case_index < 0:
                    raise ValueError('Choose a text case.')
                candidate['case'] = CASES[case_index]
            if 'join' in self.fields:
                join_field = self.fields['join']
                candidate['separator'] = (join_field.Text
                                          if hasattr(join_field, 'Text')
                                          else '')
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
                candidate['tokenize'] = tokenized_parameter
                if 'delimiters' in self.fields:
                    delimiters = self.fields['delimiters'].Text
                    if tokenized_parameter and not delimiters:
                        raise ValueError('Enter at least one parameter token delimiter.')
                    candidate['delimiters'] = delimiters
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

    def positions_changed(self, sender, args):
        if not hasattr(self, 'selection_containers'):
            return
        descriptions = []
        try:
            for container in self.selection_containers:
                if str(container['kind'].SelectedItem) == 'Range':
                    start = self.read_compact_position(
                        'start', container['start'], False)
                    end = self.read_compact_position(
                        'end', container['end'], True)
                    start_direction = start['direction']
                    start_number = start.get('index')
                    end_direction = end['direction']
                    if end_direction == 'following':
                        descriptions.append('{} {} + {} following'.format(
                            start_direction.title(), start_number, end['count']))
                    else:
                        descriptions.append('{} {} to {} {}'.format(
                            start_direction.title(), start_number,
                            end_direction.title(), end.get('index', 1)))
                else:
                    position = self.read_compact_position(
                        'position', container['position'], False)
                    descriptions.append('{} {}'.format(
                        position['direction'].title(),
                        position.get('index', 1)))
            self.position_hint.Text = 'Selection: ' + ' | '.join(descriptions)
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
        signature = (repr(composition), self.source_text, tuple(self.samples))
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
            if self.clear_button:
                self.clear_button.IsEnabled = False
            return
        self.selected = min(self.selected, len(self.items) - 1)
        missing = sorted(set(
            item['parameter'] for item in self.items
            if item['kind'] == 'parameter'
            and item.get('parameter') not in self.host.available_params))
        self.status.Text = (
            'Unavailable parameter chip(s): {}. Right-click a parameter chip to edit.'
            .format(', '.join(missing)) if missing else
            'Drag to insert/reorder. Hold Ctrl while dragging a composition chip to copy it. '
            'Double-click to edit. Right-click for options.')
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
        if not self.samples or not str(self.samples[0]).strip():
            entries.append(('Token', operation('source')))
        entries += [('{}: {}'.format(i + 1, sample),
                     operation('source', selections=[
                         {'kind': 'single',
                          'position': {'direction': 'start', 'index': i + 1}},
                     ]))
                    for i, sample in enumerate(self.samples)]
        entries += [
            ('Last', operation('source', selections=[
                {'kind': 'single',
                 'position': {'direction': 'end', 'index': 1}},
            ])),
            ('Range...', operation('source', selections=[
                {'kind': 'range',
                 'start': {'direction': 'start', 'index': 1},
                 'end': {'direction': 'end', 'index': 1}},
            ], separator='')),
            ('Parameter...', operation('parameter', parameter='')),
            ('Counter', operation('counter')),
            ('Space', operation('text', text=' ')),
            ('Hyphen', operation('text', text='-')),
            ('Underscore', operation('text', text='_')),
            ('Text...', operation('text', text='')),
        ]
        for title, item in entries:
            configure = title in ('Token', 'Range...', 'Parameter...', 'Text...')
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
            button.ToolTip += '\nHold Ctrl while dragging to copy this chip.'
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
        if item['kind'] in ('source', 'parameter', 'original'):
            eligible = item['kind'] in ('parameter', 'original')
            if item['kind'] == 'source':
                selections = item['selections']
                eligible = (len(selections) == 1
                            and selections[0].get('kind') == 'single'
                            and selections[0].get('position', {}).get('direction') == 'start')
            elif item['kind'] == 'parameter' and item.get('tokenize'):
                selections = item['selections']
                eligible = (len(selections) == 1
                            and selections[0].get('kind') == 'single'
                            and selections[0].get('position', {}).get('direction') == 'start')
            progress = self.menu_item(menu, 'Progression', enabled=eligible)
            for title, operation in [('None', ''), ('Increment Each Value...', 'inc'),
                                     ('Sequence from First Row...', 'seq')]:
                self.menu_item(progress, title,
                    lambda sender, args, op=operation: self.edit(index, operation=op))
        if item['kind'] == 'source':
            self.menu_item(menu, 'Token Selection...', lambda sender, args: self.edit(index))
            selections = item['selections']
            has_range_or_multiple = (
                len(selections) > 1
                or any(selection.get('kind') == 'range'
                       for selection in selections))
            if has_range_or_multiple:
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
                ('Token...', operation('source')),
                ('Range...', operation('source', selections=[
                    {'kind': 'range',
                     'start': {'direction': 'start', 'index': 1},
                     'end': {'direction': 'end', 'index': 1}},
                ], separator='')),
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

    def ctrl_copy_requested(self):
        return bool(Keyboard.Modifiers & ModifierKeys.Control)

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
                allowed_effects = (DragDropEffects.Move | DragDropEffects.Copy
                                   if data[0] == 'bar' else DragDropEffects.Copy)
                effect = (DragDropEffects.Copy
                          if data[0] == 'palette' or self.ctrl_copy_requested()
                          else DragDropEffects.Move)
                if data[0] == 'bar':
                    effect = allowed_effects
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
            kind = self._drag[2][0]
            args.Effects = (DragDropEffects.Copy
                            if kind == 'palette'
                            or (kind == 'bar' and self.ctrl_copy_requested())
                            else DragDropEffects.Move)
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
                and not self.point_in_token_field(args)
                and not self.ctrl_copy_requested()):
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
                if self.ctrl_copy_requested():
                    if 0 <= value < len(self.items):
                        items, selected = insert_operation(
                            self.items,
                            copy.deepcopy(self.items[value]),
                            destination)
                        self.commit(items, selected)
                else:
                    self.move(value, destination)
            else:
                self.add(value, configure, destination)
        args.Handled = True

    def outside_drop(self, sender, args):
        self.clear_insertion()
        if (self._drag is not None
                and self._drag[2][0] == 'bar'
                and args.Data.GetDataPresent(self.DRAG_FORMAT)
                and not self.point_in_token_field(args)
                and not self.ctrl_copy_requested()):
            index = self._drag[2][1]
            if 0 <= index < len(self.items):
                self.remove(index)
            args.Effects = DragDropEffects.Move
        else:
            args.Effects = getattr(DragDropEffects, 'None')
        args.Handled = True
