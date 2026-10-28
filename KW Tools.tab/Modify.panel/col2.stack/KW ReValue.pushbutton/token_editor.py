"""WPF token editing; model writes remain in the existing ReValue Apply path."""
import copy

from System.Windows import (
    DataObject, DragDrop, DragDropEffects, HorizontalAlignment, Point,
    SystemParameters, Thickness, Visibility, Window, WindowStartupLocation,
    SizeToContent,
)
from System.Windows.Controls import (
    Button, ComboBox, ContextMenu, MenuItem, Orientation, ScrollViewer,
    ScrollBarVisibility, StackPanel, TextBlock, TextBox,
)
from System.Windows.Automation import AutomationProperties
from System.Windows.Input import Key, MouseButtonState
from System.Windows.Media import Brushes, Geometry, Stretch
from System.Windows.Shapes import Path
from token_pattern import (
    CASES, edited, expression, insert_item, label, parameter_slot, parse_pattern,
    serialize_pattern, token,
)


class TokenSettings(object):
    """Draft-only settings; shared mappings are returned, never changed in place."""
    def __init__(self, editor, item):
        self.editor = editor
        self.item = copy.deepcopy(item)
        self.mappings = list(editor.mappings())
        self.result = None
        self.fields = {}
        self.window = Window()
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
            self.note('Start: val1, val2, end, end-1, ...\n'
                      'End: blank for a single token; otherwise 3, end, end-1 or +2.')
            self.text('Start', 'start', item.get('start', 'val1'))
            self.text('End', 'end', item.get('end', ''))
            self.combo('Join separator (ranges)', 'join',
                       ['', 'hyphen', 'space', 'underscore', '/', '.'],
                       item.get('join', ''), editable=True)
        elif kind == 'parameter':
            self.note('Five shared slots. Reassigning a slot changes EVERY chip using it.\n'
                      'Existing mappings are reused; otherwise an empty slot is selected.')
            self.combo('Parameter', 'parameter', [''] + list(editor.host.available_params),
                       self.mappings[item['slot'] - 1] if item.get('slot') else '')
            options = ['{}: {}'.format(i + 1, name or '(empty)')
                       for i, name in enumerate(self.mappings)]
            self.combo('Shared slot (choose explicitly if all five are occupied)',
                       'slot', options,
                       options[item['slot'] - 1] if item.get('slot') else None)
            self.fields['parameter'].SelectionChanged += self.parameter_changed
        elif kind == 'counter':
            self.note('Start and increment are SHARED by every Counter chip.\n'
                      'Repeated Counter chips use the same value within each row.')
            self.text('Start', 'counter_start', editor.host.txt_counter_start.Text)
            self.text('Increment (nonnegative integer)', 'counter_increment',
                      editor.host.txt_counter_increment.Text)
        if kind != 'text':
            self.combo('Text case (this chip)', 'case', list(CASES),
                       item.get('case', 'Unchanged'))
        if kind in ('source', 'parameter'):
            self.note('Progression supports a single valN or parameter slot, not ranges or end-relative tokens.\n'
                      'Increment: each row independently. Sequence: first unfiltered row plus row position.')
            self.combo('Progression', 'operation', ['None', 'Increment', 'Sequence'],
                       {'inc': 'Increment', 'seq': 'Sequence'}.get(item.get('operation'), 'None'))
            self.text('Step (signed integer, e.g. 2 or -1)', 'step', item.get('step', '1'))
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

    def parameter_changed(self, sender, args):
        slot = parameter_slot(self.mappings, self.fields['parameter'].SelectedItem)
        self.fields['slot'].SelectedIndex = slot - 1 if slot else -1

    def accept(self, sender, args):
        candidate = copy.deepcopy(self.item)
        candidate.pop('raw', None)
        mappings = list(self.mappings)
        counter = None
        try:
            for name in ('text', 'start', 'end', 'step'):
                if name in self.fields:
                    value = self.fields[name].Text
                    candidate[name] = value if name == 'text' else value.strip()
            for name in ('case', 'join'):
                if name in self.fields:
                    candidate[name] = self.fields[name].Text
            if 'operation' in self.fields:
                candidate['operation'] = {
                    'None': '', 'Increment': 'inc', 'Sequence': 'seq',
                }[self.fields['operation'].SelectedItem]
            if candidate['kind'] == 'parameter':
                slot = self.fields['slot'].SelectedIndex + 1
                name = self.fields['parameter'].SelectedItem
                if not slot or not name:
                    raise ValueError('Choose an available parameter and a shared slot.')
                if name not in self.editor.host.available_params:
                    raise ValueError('This parameter is unavailable in the current mode.')
                candidate['slot'] = slot
                mappings[slot - 1] = name
            if candidate['kind'] == 'text' and not candidate['text']:
                raise ValueError('Enter literal text, including at least one character or space.')
            if candidate['kind'] == 'counter':
                start = self.fields['counter_start'].Text
                increment = self.fields['counter_increment'].Text
                unused, error = self.editor.counter_builder(start, increment)
                if error:
                    raise ValueError(error)
                counter = (start, increment)
            expression(candidate)
        except ValueError as ex:
            self.error.Text = str(ex)
            return
        self.result = candidate, mappings, counter
        self.window.DialogResult = True

    def show(self):
        self.window.ShowDialog()
        return self.result


class TokenEditor(object):
    DRAG_FORMAT = 'KW.ReValue.Token'
    ICONS = {
        'source': 'M0,2 L12,2 12,12 0,12 Z M4,2 L4,12 M8,2 L8,12',
        'parameter': 'M0,3 L12,3 M0,9 L12,9 M4,0 L4,6 M8,6 L8,12',
        'counter': 'M4,0 L2,12 M10,0 L8,12 M0,4 L12,4 M0,8 L12,8',
        'text': 'M0,1 L12,1 M6,1 L6,12 M3,12 L9,12',
        'original': 'M2,0 L9,0 12,3 12,12 2,12 Z M5,5 L9,5 M5,8 L9,8',
    }

    def __init__(self, host, counter_builder):
        self.host = host
        self.counter_builder = counter_builder
        self.items = []
        self.selected = -1
        self.samples = []
        self.source_text = ''
        self._signature = None
        self._syncing = False
        self._drag = None
        self._insertion = None
        window = host.window
        self.mode = window.FindName('combo_editor_mode')
        self.panel = window.FindName('token_editor_panel')
        self.palette = window.FindName('token_palette')
        self.bar = window.FindName('token_bar')
        self.bar_scroll = window.FindName('token_bar_scroll')
        self.status = window.FindName('token_status')
        self.sample_label = window.FindName('token_sample')
        self.mode.SelectionChanged += self.mode_changed
        window.FindName('btn_add_token').Click += self.add_menu
        self.bar.AllowDrop = True
        self.bar.DragOver += self.drag_over
        self.bar.DragLeave += self.drag_leave
        self.bar.Drop += self.drop
        self.refresh()
        try:
            parse_pattern(host.txt_pattern.Text)
            self.mode.SelectedIndex = 0
        except ValueError:
            self.mode.SelectedIndex = 1
        self.mode_changed(None, None)

    def mappings(self):
        return [self.host._selected_combo_text(combo) for combo in self.host.param_combos]

    def button(self, text, callback):
        button = Button()
        button.Content = text
        button.Padding = Thickness(6, 3, 6, 3)
        button.Margin = Thickness(2)
        button.Click += callback
        return button

    def icon_content(self, button, kind):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        icon = Path()
        icon.Data = Geometry.Parse(self.ICONS[kind])
        icon.Width = 12
        icon.Height = 12
        icon.Stretch = Stretch.Uniform
        icon.Stroke = Brushes.DarkSlateGray
        icon.StrokeThickness = 1.2
        icon.Margin = Thickness(0, 0, 5, 0)
        text = TextBlock()
        text.Text = button.Content
        AutomationProperties.SetName(button, text.Text)
        panel.Children.Add(icon)
        panel.Children.Add(text)
        button.Content = panel

    def mode_changed(self, sender, args):
        if self._syncing:
            return
        if self.mode.SelectedIndex == 0:
            try:
                parse_pattern(self.host.txt_pattern.Text)
            except ValueError as ex:
                self.status.Text = str(ex)
                self.mode.SelectedIndex = 1
                return
        visual = self.mode.SelectedIndex == 0
        self.panel.Visibility = Visibility.Visible if visual else Visibility.Collapsed
        self.host.window.MinHeight = 660 if visual else 500
        self.host.txt_pattern.IsReadOnly = visual
        self.host.txt_pattern.ToolTip = (
            'Generated pattern. Choose Advanced Pattern to edit syntax directly.' if visual
            else 'Existing pattern syntax; unsupported expressions are preserved.')

    def refresh(self):
        pattern = self.host.txt_pattern.Text
        mappings = self.mappings()
        sample = self.host.get_token_sample_item()
        self.source_text = sample.CurrentName if sample is not None else ''
        self.samples = self.host.get_tokenizer_func()(self.source_text)
        signature = pattern, tuple(mappings), self.source_text, tuple(self.samples)
        if signature == self._signature:
            return
        sample_only = self._signature is not None and signature[:2] == self._signature[:2]
        previous_count = len(self._signature[3]) if self._signature is not None else -1
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
                self.update_chip_label(self.bar.Children[index], label(item, self.samples, mappings))
            return
        try:
            if serialize_pattern(self.items) != pattern:
                self.items = parse_pattern(pattern)
        except ValueError as ex:
            self.items = []
            self.status.Text = str(ex)
            self.bar.Children.Clear()
            self.mode.SelectedIndex = 1
            self.mode_changed(None, None)
            return
        self.selected = min(self.selected, len(self.items) - 1)
        used_slots = set(item['slot'] for item in self.items if item['kind'] == 'parameter')
        missing = [str(slot) for slot in sorted(used_slots)
                   if not mappings[slot - 1] or mappings[slot - 1] not in self.host.available_params]
        self.status.Text = ('Unmapped/unavailable parameter slot(s): {}. Right-click a parameter chip to edit.'
                            .format(', '.join(missing)) if missing else
                            'Drag to insert/reorder. Double-click to edit. Right-click for options.')
        self.render_palette()
        self.render_bar()

    def update_chip_label(self, button, text):
        button.Content.Children[1].Text = text
        AutomationProperties.SetName(button, text)

    def render_palette(self):
        self.palette.Children.Clear()
        entries = [('Original', token('original'))]
        entries += [('{}: {}'.format(i + 1, sample), token('source', start='val{}'.format(i + 1)))
                    for i, sample in enumerate(self.samples)]
        entries += [
            ('Last', token('source', start='end')),
            ('Range...', token('source', start='val1', end='end')),
            ('Parameter...', token('parameter')),
            ('Counter', token('counter')),
            ('Space', token('text', text=' ')),
            ('Hyphen', token('text', text='-')),
            ('Underscore', token('text', text='_')),
            ('Text...', token('text', text='')),
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
        mappings = self.mappings()
        colours = {'source': Brushes.AliceBlue, 'parameter': Brushes.Honeydew,
                   'counter': Brushes.LemonChiffon, 'text': Brushes.WhiteSmoke,
                   'original': Brushes.Lavender}
        for index, item in enumerate(self.items):
            button = self.button(label(item, self.samples, mappings),
                                 lambda sender, args, i=index: self.select(i))
            button.Background = colours[item['kind']]
            self.icon_content(button, item['kind'])
            button.Tag = index
            button.ToolTip = serialize_pattern([item])
            if item['kind'] == 'text':
                button.ToolTip += '\n{} character(s); spaces are preserved.'.format(len(item['text']))
            button.BorderBrush = Brushes.SteelBlue if index == self.selected else Brushes.Gray
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
            child.BorderBrush = Brushes.SteelBlue if i == index else Brushes.Gray
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
                entry = self.menu_item(case_menu, case,
                    lambda sender, args, value=case: self.set_case(index, value))
                entry.IsCheckable = True
                entry.IsChecked = item.get('case', 'Unchanged') == case
        if item['kind'] in ('source', 'parameter'):
            eligible = (item['kind'] == 'parameter' or
                        (item['start'].startswith('val') and not item.get('end') and not item.get('join')))
            progress = self.menu_item(menu, 'Progression', enabled=eligible)
            for title, operation in [('None', ''), ('Increment Each Value...', 'inc'),
                                     ('Sequence from First Row...', 'seq')]:
                self.menu_item(progress, title,
                    lambda sender, args, op=operation: self.edit(index, operation=op))
        if item['kind'] == 'source':
            self.menu_item(menu, 'Token Selection...', lambda sender, args: self.edit(index))
            if item.get('end'):
                joins = self.menu_item(menu, 'Join Separator')
                for title in ('hyphen', 'space', 'underscore'):
                    self.menu_item(joins, title,
                        lambda sender, args, value=title: self.set_join(index, value))
                self.menu_item(joins, 'Custom...', lambda sender, args: self.edit(index))
        if item['kind'] == 'parameter':
            self.menu_item(menu, 'Choose Parameter...', lambda sender, args: self.edit(index))
        if item['kind'] == 'counter':
            self.menu_item(menu, 'Counter Settings (shared)...', lambda sender, args: self.edit(index))
        self.menu_item(menu, 'Duplicate', lambda sender, args: self.duplicate(index))
        self.menu_item(menu, 'Move Left', lambda sender, args: self.move(index, index - 1), index > 0)
        self.menu_item(menu, 'Move Right', lambda sender, args: self.move(index, index + 2),
                       index < len(self.items) - 1)
        self.menu_item(menu, 'Remove', lambda sender, args: self.remove(index))
        return menu

    def set_case(self, index, case):
        items = copy.deepcopy(self.items)
        items[index] = edited(items[index], case=case)
        self.commit(items, index)

    def set_join(self, index, join):
        items = copy.deepcopy(self.items)
        items[index] = edited(items[index], join=join)
        self.commit(items, index)

    def add_menu(self, sender, args):
        menu = ContextMenu()
        for title, item in [('Original', token('original')),
                            ('Source Token...', token('source', start='val1')),
                            ('Range...', token('source', start='val1', end='end')),
                            ('Parameter...', token('parameter')),
                            ('Counter...', token('counter')),
                            ('Space', token('text', text=' ')),
                            ('Hyphen', token('text', text='-')),
                            ('Underscore', token('text', text='_')),
                            ('Text...', token('text', text=''))]:
            self.menu_item(menu, title,
                lambda sender, args, value=item, config=title.endswith('...'): self.add(value, config))
        menu.PlacementTarget = sender
        menu.IsOpen = True

    def add(self, item, configure=False, destination=None):
        if not self.host.commit_preview_edits():
            return
        mappings, counter = None, None
        if configure:
            result = TokenSettings(self, item).show()
            if result is None:
                return
            item, mappings, counter = result
        if destination is None:
            destination = self.selected + 1 if self.selected >= 0 else len(self.items)
        items, index = insert_item(self.items, item, destination)
        self.commit(items, index, mappings, counter)

    def edit(self, index, **values):
        if not self.host.commit_preview_edits():
            return
        item = copy.deepcopy(self.items[index])
        item.update(values)
        result = TokenSettings(self, item).show()
        if result is not None:
            item, mappings, counter = result
            items = copy.deepcopy(self.items)
            items[index] = item
            self.commit(items, index, mappings, counter)

    def duplicate(self, index):
        items, selected = insert_item(self.items, self.items[index], index + 1)
        self.commit(items, selected)

    def remove(self, index):
        items = copy.deepcopy(self.items)
        items.pop(index)
        self.commit(items, min(index, len(items) - 1))

    def move(self, index, destination):
        items, selected = insert_item(self.items, None, destination, index)
        self.commit(items, selected)

    def commit(self, items, selected, mappings=None, counter=None):
        if not self.host.commit_preview_edits():
            return
        pattern = serialize_pattern(items)
        suspended = self.host._suspend_events
        self.host._suspend_events = True
        try:
            if mappings is not None:
                for combo, name in zip(self.host.param_combos, mappings):
                    combo.SelectedItem = name
            if counter is not None:
                self.host.txt_counter_start.Text, self.host.txt_counter_increment.Text = counter
            self.selected = selected
            self.items = copy.deepcopy(items)
            self.host.txt_pattern.Text = pattern
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
        if self._insertion is not None:
            child = self._insertion
            selected = child.Tag == self.selected
            child.BorderBrush = Brushes.SteelBlue if selected else Brushes.Gray
            child.BorderThickness = Thickness(2 if selected else 1)
            child.Padding = Thickness(6, 3, 6, 3)
            self._insertion = None
        self.bar.Background = Brushes.Transparent

    def drag_over(self, sender, args):
        self.clear_insertion()
        if self._drag is None or not args.Data.GetDataPresent(self.DRAG_FORMAT):
            args.Effects = getattr(DragDropEffects, 'None')
        else:
            args.Effects = (DragDropEffects.Move if self._drag[2][0] == 'bar'
                            else DragDropEffects.Copy)
            gap = self.drop_position(args.GetPosition(self.bar))
            if self.items:
                child = self.bar.Children[min(gap, len(self.items) - 1)]
                child.BorderBrush = Brushes.DodgerBlue
                base = 2 if child.Tag == self.selected else 1
                if gap == len(self.items):
                    child.BorderThickness = Thickness(base, base, 4, base)
                    child.Padding = Thickness(6, 3, 6 - (4 - base), 3)
                else:
                    child.BorderThickness = Thickness(4, base, base, base)
                    child.Padding = Thickness(6 - (4 - base), 3, 6, 3)
                self._insertion = child
            else:
                self.bar.Background = Brushes.AliceBlue
            point = args.GetPosition(self.bar_scroll)
            if point.Y < 15:
                self.bar_scroll.LineUp()
            elif point.Y > self.bar_scroll.ActualHeight - 15:
                self.bar_scroll.LineDown()
        args.Handled = True

    def drag_leave(self, sender, args):
        self.clear_insertion()

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
