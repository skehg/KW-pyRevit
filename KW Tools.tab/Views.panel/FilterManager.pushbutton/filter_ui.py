# -*- coding: utf-8 -*-
"""Modal, resizable WPF dialogs translated from the Filter Manager concept."""
import io
import os
import traceback
from xml.sax.saxutils import escape

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
from System.Windows.Markup import ParserContext
clr.AddReference(clr.GetClrType(ParserContext).GetProperty('BaseUri').PropertyType.Assembly)
from System import Uri, EventHandler
from System.ComponentModel import DependencyPropertyDescriptor
from System.Windows import (
    Thickness, GridLength, GridUnitType, Visibility, SystemParameters,
    HorizontalAlignment, VerticalAlignment)
from System.Windows.Automation import AutomationProperties
from System.Windows.Controls import (
    StackPanel, WrapPanel, Grid, RowDefinition, ColumnDefinition, Border,
    TextBlock, TextBox, ComboBox, ComboBoxItem, CheckBox, RadioButton, Button,
    ScrollViewer, ScrollBarVisibility, ListBox, ListBoxItem, ContextMenu, MenuItem,
    Expander, Orientation, SelectionMode)
from System.Windows.Input import Keyboard, ModifierKeys
from System.Windows.Media import BrushConverter
from pyrevit import forms, script
from pyrevit import DB
import filter_model as model

ROOT = os.path.dirname(__file__)
INK, MUTED, BLUE, PALE, LINE = '#172838', '#6E6E71', '#43789A', '#EDF3F7', '#D7E1E7'


def brush(color):
    return BrushConverter().ConvertFromString(color)


def label(value, size=14, color=INK):
    obj = TextBlock()
    obj.Text = unicode(value)
    obj.FontSize = size
    obj.Foreground = brush(color)
    obj.Margin = Thickness(0, 3, 0, 5)
    return obj


def panel(*children):
    obj = StackPanel()
    for child in children:
        obj.Children.Add(child)
    return obj


def scroll(child):
    obj = ScrollViewer()
    obj.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    obj.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
    obj.Content = child
    return obj


def card(child, warning=False):
    obj = Border()
    obj.Background = brush('#FFF5DF' if warning else '#FFFFFF')
    obj.BorderBrush = brush('#C59339' if warning else LINE)
    obj.BorderThickness = Thickness(1)
    obj.Padding = Thickness(12)
    obj.Margin = Thickness(4)
    obj.Child = child
    return obj


def button(text, action, kind=None):
    obj = Button()
    obj.Content = text
    obj.Tag = kind
    if action:
        obj.Click += action
    return obj


def field(text=''):
    obj = TextBox()
    obj.Text = unicode(text)
    obj.Margin = Thickness(2, 3, 2, 5)
    return obj


def combo(options, selected=None):
    obj = ComboBox()
    obj.Margin = Thickness(2, 3, 2, 5)
    obj.IsTextSearchEnabled = True
    for value, text in options:
        item = ComboBoxItem()
        item.Content = text
        item.Tag = value
        obj.Items.Add(item)
        if selected == value:
            obj.SelectedItem = item
    return obj


def chosen(obj):
    return obj.SelectedItem.Tag if obj.SelectedItem else None


def add_row(grid, child, index):
    Grid.SetRow(child, index)
    grid.Children.Add(child)


class Dialog(forms.WPFWindow):
    def __init__(self, title, subtitle='', width=1060, height=780):
        with io.open(os.path.join(ROOT, 'FilterManager.xaml'), encoding='utf-8') as source:
            xaml = source.read().replace('ButtonStyles.xaml', escape(
                Uri(os.path.join(ROOT, 'ButtonStyles.xaml')).AbsoluteUri))
        forms.WPFWindow.__init__(self, xaml, literal_string=True, handle_esc=False)
        self.Title = 'Filter Manager - BETA' if title == 'Filter Manager' else title + ' - Filter Manager BETA'
        self.heading.Text = title
        self.subtitle.Text = subtitle
        work = SystemParameters.WorkArea
        self.MinWidth = min(620, work.Width - 40)
        self.MinHeight = min(460, work.Height - 40)
        self.Width = min(width, work.Width - 40)
        self.Height = min(height, work.Height - 40)
        self.result = None

    def run(self, action):
        try:
            return action()
        except Exception as error:
            script.get_logger().error('Filter Manager: %s\n%s', error, traceback.format_exc())
            self.status.Text = unicode(error)
            forms.alert(unicode(error), title='Filter Manager - operation not completed')
            return None

    def footer(self, text, handler, kind=None):
        obj = button(text, handler, kind)
        self.actions.Children.Add(obj)
        return obj

    def show(self, owner=None):
        if owner:
            self.Owner = owner
        self.ShowDialog()
        return self.result


class ReviewDialog(Dialog):
    def __init__(self, title, subtitle, rows, warning='', acknowledgement=False,
                 primary='Confirm', destructive=False):
        Dialog.__init__(self, title, subtitle)
        self.row_checks = []
        self.rows = rows
        content = StackPanel()
        for key, name, detail in rows:
            check = CheckBox()
            check.Content = panel(label(name, 16), label(detail, 13, MUTED))
            check.IsChecked = True
            check.Margin = Thickness(7)
            check.Checked += self.changed
            check.Unchecked += self.changed
            content.Children.Add(card(check))
            self.row_checks.append((key, check))
        if warning:
            content.Children.Add(card(label(warning, 14, '#865B14'), True))
        self.ack = None
        if acknowledgement:
            self.ack = CheckBox()
            self.ack.Content = label('I understand the impact of this operation.')
            self.ack.Margin = Thickness(9)
            content.Children.Add(self.ack)
            self.ack.Checked += self.changed
            self.ack.Unchecked += self.changed
        self.body.Children.Add(scroll(content))
        self.footer('Cancel', lambda s, e: self.Close())
        self.confirm = self.footer(primary, self.accept, 'destructive' if destructive else 'primary')
        self.changed(None, None)

    def selected(self):
        return [key for key, check in self.row_checks if check.IsChecked]

    def changed(self, sender, event):
        if hasattr(self, 'confirm'):
            self.confirm.IsEnabled = bool(self.selected()) and (
                self.ack is None or self.ack.IsChecked is True)
            self.status.Text = '{} approved / {} selected'.format(len(self.selected()), len(self.rows))
        if sender is not None and sender is not getattr(self, 'ack', None):
            if getattr(self, 'ack', None):
                self.ack.IsChecked = False

    def accept(self, sender, event):
        self.result = self.selected()
        self.Close()


class ResultsDialog(Dialog):
    def __init__(self, title, lines):
        Dialog.__init__(self, title, 'Operation results')
        self.body.Children.Add(scroll(panel(*[label(line) for line in lines])))
        self.footer('Back to Manager', lambda s, e: self.Close(), 'primary')


class TemplateDialog(Dialog):
    def __init__(self, service, selected=None):
        Dialog.__init__(self, 'Select View Template',
                        'Choose one template as the configuration target. This does not assign it to the current view.',
                        1100, 800)
        self.MinHeight = min(680, SystemParameters.WorkArea.Height - 40)
        self.service, self.selected = service, selected
        self.search = field()
        self.search.ToolTip = 'Search templates by name'
        self.list = ListBox()
        self.list.SelectionMode = SelectionMode.Single
        self.templates = [v for v in service.views if v.IsTemplate and model.supports_filters(v)]
        self.templates.sort(key=lambda v: model.name_of(v).lower())
        self.types = combo([(None, 'All template types')] + [
            (value, value) for value in sorted(set(str(v.ViewType) for v in self.templates))])
        self.types.SelectedIndex = 0
        self.types.Width = 210
        filters = Grid()
        for width in (GridLength(1, GridUnitType.Star), GridLength.Auto):
            col = ColumnDefinition()
            col.Width = width
            filters.ColumnDefinitions.Add(col)
        filters.Children.Add(self.search)
        Grid.SetColumn(self.types, 1)
        filters.Children.Add(self.types)
        self.summary = label('', 13, MUTED)
        self.impact = label('', 14, '#865B14')
        layout = Grid()
        for height in (GridLength.Auto, GridLength.Auto, GridLength.Auto,
                       GridLength(1, GridUnitType.Star), GridLength.Auto):
            row = RowDefinition()
            row.Height = height
            layout.RowDefinitions.Add(row)
        add_row(layout, panel(label('Search templates', 12, MUTED), filters), 0)
        add_row(layout, self.summary, 1)
        add_row(layout, self.template_row('TEMPLATE NAME', 'VIEW TYPE', 'DEPENDENT VIEWS', 'STATUS'), 2)
        add_row(layout, self.list, 3)
        impact_scroll = scroll(self.impact)
        impact_scroll.MaxHeight = 90
        add_row(layout, card(impact_scroll, True), 4)
        self.body.Children.Add(layout)
        self.search.TextChanged += self.populate
        self.types.SelectionChanged += self.populate
        self.list.SelectionChanged += self.selection_changed
        self.footer('Cancel', lambda s, e: self.Close())
        self.accept_button = self.footer('Use This Template', self.accept, 'primary')
        self.Loaded += lambda s, e: self.search.Focus()
        self.populate(None, None)

    def template_row(self, name, view_type, dependents, status):
        row = Grid()
        for index, (text, weight) in enumerate(zip(
                (name, view_type, dependents, status), (3, 1.4, 1.4, 1))):
            col = ColumnDefinition()
            col.Width = GridLength(weight, GridUnitType.Star)
            row.ColumnDefinitions.Add(col)
            cell = label(text, 13)
            cell.Margin = Thickness(6)
            Grid.SetColumn(cell, index)
            row.Children.Add(cell)
        return row

    def populate(self, sender, event):
        self.list.Items.Clear()
        for view in self.templates:
            if (self.search.Text.lower() not in model.name_of(view).lower() or
                    (chosen(self.types) is not None and chosen(self.types) != str(view.ViewType))):
                continue
            item = ListBoxItem()
            item.Tag = model.id_value(view.Id)
            item.HorizontalContentAlignment = HorizontalAlignment.Stretch
            item.Content = self.template_row(model.name_of(view), str(view.ViewType),
                                              '{} views'.format(len(self.service.dependents(view))), 'Compatible')
            self.list.Items.Add(item)
            if item.Tag == self.selected:
                self.list.SelectedItem = item
        self.selection_changed(None, None)

    def selection_changed(self, sender, event):
        selected = self.list.SelectedItem
        self.summary.Text = '{} compatible templates / {} selected - select exactly one'.format(
            self.list.Items.Count, 1 if selected else 0)
        if selected:
            self.selected = selected.Tag
            view = self.service.doc.GetElement(model.element_id(selected.Tag))
            self.impact.Text = '{} selected / {} dependent views.\n{}'.format(
                model.name_of(view), len(self.service.dependents(view)),
                'This template controls Filters for its dependent views. Confirm their impact before applying.'
                if self.service.template_controls(view) else
                'This template does not currently control Filters in assigned views. Template assignments stay unchanged.')
        else:
            self.impact.Text = 'No matching templates.' if not self.list.Items.Count else (
                'Choose exactly one configuration target. Existing template assignments stay unchanged.')
        if hasattr(self, 'accept_button'):
            self.accept_button.IsEnabled = selected is not None

    def accept(self, sender, event):
        def accept():
            if self.list.SelectedItem is None:
                raise ValueError('Select exactly one compatible template.')
            view = self.service.doc.GetElement(model.element_id(self.list.SelectedItem.Tag))
            if not model.supports_filters(view) or not view.IsTemplate:
                raise ValueError('The selected template changed. Reopen the template picker.')
            self.result = model.id_value(view.Id)
            self.Close()
        self.run(accept)


class DuplicateDialog(Dialog):
    def __init__(self, service, matches, categories, tree, existing=None):
        Dialog.__init__(self, 'Confirm Duplicate Definition',
                        'Identical rules are allowed only after explicit acknowledgement.')
        self.matches = matches
        content = panel(label('Matching definitions', 18))
        self.use_combo = combo([(r.id, r.name) for r in matches], matches[0].id)
        content.Children.Add(self.use_combo)
        for record in matches:
            content.Children.Add(card(panel(label(record.name, 16),
                                           label(record.usage_text, 13, MUTED))))
        content.Children.Add(card(panel(
            label(', '.join(service.category_name(c) for c in categories)),
            label(service.describe(tree)))))
        if existing:
            content.Children.Add(card(label('Saving "{}" updates {}. Attachments and graphics are retained.'.format(
                existing.name, existing.usage_text)), True))
        self.ack = CheckBox()
        self.ack.Content = label('Keep a separate definition with these identical categories and rules.')
        self.ack.Margin = Thickness(8)
        self.ack.Checked += self.changed
        self.ack.Unchecked += self.changed
        content.Children.Add(self.ack)
        content.Children.Add(label('Use Existing explicitly discards this draft and focuses the match. No merge, deletion or application.', 13, MUTED))
        self.body.Children.Add(scroll(content))
        self.footer('Back to Editor', lambda s, e: self.Close())
        self.footer('Use Existing', self.use_existing)
        self.save = self.footer('Save Changes' if existing else 'Create Duplicate', self.accept, 'primary')
        self.save.IsEnabled = False

    def changed(self, sender, event):
        if hasattr(self, 'save'):
            self.save.IsEnabled = self.ack.IsChecked is True

    def use_existing(self, sender, event):
        self.result = ('use', chosen(self.use_combo))
        self.Close()

    def accept(self, sender, event):
        self.result = ('save', [r.id for r in self.matches])
        self.Close()


class RuleRow(object):
    def __init__(self, editor, container, node):
        self.editor, self.container, self.node = editor, container, node
        self.original = dict(node)
        self.value_dirty = False
        self.epsilon_dirty = False
        self.loading = True
        self.root = StackPanel()
        self.wrap = WrapPanel()
        self.param = combo([(p.id, '{} [id {}]'.format(p.name, p.id)) for p in editor.parameters], node.get('pid'))
        self.param.Width = 260
        self.operator = combo([])
        self.operator.Width = 230
        self.value = combo([])
        self.value.IsEditable = True
        self.value.Width = 230
        self.value_picker = combo([])
        self.value_picker.Width = 230
        self.epsilon = field(node.get('epsilon') if node.get('epsilon') is not None else '0.000001')
        self.epsilon.Width = 170
        self.notice = label('', 12, MUTED)
        self.wrap.Children.Add(self.param)
        self.wrap.Children.Add(self.operator)
        self.wrap.Children.Add(self.value)
        self.wrap.Children.Add(self.value_picker)
        self.wrap.Children.Add(button('Remove', self.remove))
        self.root.Children.Add(self.wrap)
        self.root.Children.Add(self.notice)
        self.tolerance = panel(label('Double tolerance (internal units; existing value preserved)', 12, MUTED), self.epsilon)
        self.root.Children.Add(self.tolerance)
        container.Children.Add(card(self.root))
        self.param.SelectionChanged += self.parameter_changed
        self.operator.SelectionChanged += self.operator_changed
        # Observe Text even before the editable ComboBox's inner TextBox exists.
        self.text_descriptor = DependencyPropertyDescriptor.FromProperty(
            ComboBox.TextProperty, clr.GetClrType(ComboBox))
        self.text_handler = EventHandler(self.value_changed)
        self.text_descriptor.AddValueChanged(self.value, self.text_handler)
        self.value.SelectionChanged += self.value_changed
        self.value_picker.SelectionChanged += self.value_changed
        self.epsilon.TextChanged += self.value_changed
        self.configure(True)
        self.loading = False

    def info(self):
        pid = chosen(self.param)
        return next((p for p in self.editor.parameters if p.id == pid), None)

    def detach(self):
        self.text_descriptor.RemoveValueChanged(self.value, self.text_handler)

    def configure(self, initial=False):
        info = self.info()
        self.operator.Items.Clear()
        if info is None:
            self.notice.Text = 'Choose an eligible parameter. An incompatible existing rule is retained until corrected.'
            return
        options = list(self.editor.service.operators(info))
        op = self.node.get('op') if initial else None
        if op and op not in dict(options):
            options += [(op, op + ' (existing native rule; preserve or replace)')]
        for key, text in options:
            item = ComboBoxItem()
            item.Tag, item.Content = key, text
            self.operator.Items.Add(item)
            if key == op:
                self.operator.SelectedItem = item
        self.value.Text = self.node.get('draft_value', self.editor.service.format_operand(
            self.node) if initial and self.node.get('family') else '')
        self.value_picker.Items.Clear()
        self.notice.Text = info.problem
        if info.profile == 'number':
            self.notice.Text = '{} - enter project display units; tolerance is in internal units.'.format(
                DB.LabelUtils.GetLabelForSpec(info.spec))
        if info.profile in ('level', 'phase', 'material', 'yesno'):
            choices = [(0, 'No'), (1, 'Yes')] if info.profile == 'yesno' else self.editor.service.references(info)
            for key, text in choices:
                item = ComboBoxItem()
                item.Tag, item.Content = key, text
                self.value_picker.Items.Add(item)
                if initial and key == self.node.get('value'):
                    self.value_picker.SelectedItem = item
        self.update_controls()

    def update_controls(self):
        info = self.info()
        op = chosen(self.operator)
        presence = op in ('HasValue', 'HasNoValue')
        picker = info is not None and info.profile in ('level', 'phase', 'material', 'yesno')
        self.value.Visibility = Visibility.Collapsed if presence or picker else Visibility.Visible
        self.value_picker.Visibility = Visibility.Visible if picker and not presence else Visibility.Collapsed
        self.tolerance.Visibility = Visibility.Visible if info and info.storage == 'Double' and not presence else Visibility.Collapsed
        loading = self.loading
        self.loading = True
        try:
            selected = self.suggested_value()
            text = self.value.Text
            if selected is not None:
                self.original.update({'pid': info.id, 'family': {
                    'String': 'string', 'Double': 'double', 'Integer': 'integer'}[info.storage],
                    'value': selected})
                self.value_dirty = False
                text = self.editor.service.format_operand(dict(self.original, op='Equals'))
            self.value.Items.Clear()
            self.value.Text = text
            self.value.ToolTip = 'Enter a value.'
            if info and info.profile in ('text', 'number', 'integer') and op in ('Equals', 'NotEquals'):
                options = self.editor.service.assigned_values(self.editor.categories(), info)
                for value, display in options:
                    item = ComboBoxItem()
                    item.Tag, item.Content = value, display
                    self.value.Items.Add(item)
                self.value.ToolTip = '{} assigned values from selected-category instances and types. Choose a suggestion or type any value.'.format(len(options))
        finally:
            self.loading = loading

    def suggested_value(self):
        item = self.value.SelectedItem
        return item.Tag if item is not None and self.value.Text == unicode(item.Content) else None

    def parameter_changed(self, sender, event):
        if self.loading:
            return
        def change():
            self.loading = True
            try:
                self.node.pop('native', None)
                self.value_dirty = True
                self.node['pid'] = chosen(self.param)
                self.node['op'] = None
                self.configure()
            finally:
                self.loading = False
            self.editor.changed('Parameter changed: choose a valid operator and operand.')
        self.editor.run(change)

    def operator_changed(self, sender, event):
        if self.loading:
            return
        self.node.pop('native', None)
        def change():
            self.update_controls()
            self.editor.changed()
        self.editor.run(change)

    def value_changed(self, sender, event):
        if not self.loading:
            self.node.pop('native', None)
            if sender is self.epsilon:
                self.epsilon_dirty = True
            else:
                self.value_dirty = True
            self.editor.changed()

    def remove(self, sender, event):
        self.editor.remove_node(self.node)

    def read(self):
        info, op = self.info(), chosen(self.operator)
        if info is None or op is None:
            raise ValueError('Every rule needs an eligible parameter and operator.')
        if self.node.get('native') is not None:
            return self.node
        if op not in dict(self.editor.service.operators(info)):
            raise ValueError('Choose a supported operator.')
        value, epsilon = None, None
        family = {'String': 'string', 'Integer': 'integer', 'Double': 'double',
                  'ElementId': 'reference'}.get(info.storage)
        if op in ('HasValue', 'HasNoValue'):
            family = 'presence'
        else:
            if info.profile is None or info.profile == 'enum':
                raise ValueError(info.problem)
            preserve_value = (not self.value_dirty and self.original.get('pid') == info.id and
                              self.original.get('family') == family and self.original.get('value') is not None)
            suggestion = self.suggested_value()
            if suggestion is not None:
                value = suggestion
            elif preserve_value:
                value = self.original['value']
            elif info.profile in ('level', 'phase', 'material', 'yesno'):
                value = chosen(self.value_picker)
                if value is None:
                    raise ValueError('Choose a typed value for "{}".'.format(info.name))
            elif family == 'double':
                if DB.UnitUtils.IsMeasurableSpec(info.spec):
                    ok, value = DB.UnitFormatUtils.TryParse(self.editor.service.doc.GetUnits(),
                                                           info.spec, self.value.Text)
                    if not ok:
                        raise ValueError('Invalid project-unit value for "{}".'.format(info.name))
                else:
                    value = float(self.value.Text)
                if model.math.isnan(value) or model.math.isinf(value):
                    raise ValueError('Numeric operands must be finite.')
            elif family == 'integer':
                value = int(self.value.Text)
                if value < -2147483648 or value > 2147483647:
                    raise ValueError('Integer operand is outside Revit Int32 range.')
            else:
                value = unicode(self.value.Text)
            if family == 'double':
                epsilon = (self.original['epsilon'] if not self.epsilon_dirty and
                           self.original.get('family') == 'double' and self.original.get('epsilon') is not None
                           else float(self.epsilon.Text))
                if epsilon < 0 or model.math.isnan(epsilon) or model.math.isinf(epsilon):
                    raise ValueError('Tolerance must be finite and nonnegative.')
        return {'kind': 'rule', 'pid': info.id, 'op': op, 'family': family,
                'value': value, 'epsilon': epsilon}


class EditorDialog(Dialog):
    def __init__(self, service, existing=None):
        Dialog.__init__(self, 'Edit Filter' if existing else 'New Filter',
                        'BETA - typed native rules. Saving a shared definition updates every consumer.',
                        1100, 850)
        self.service, self.existing = service, existing
        self.tree = model.clone_tree(existing.tree) if existing else model.group()
        self.parameters = []
        self.rule_rows = []
        self.Closed += self.detach_rows
        self.loading = True
        self.name = field(existing.name if existing else '')
        self.cat_search = field()
        self.category_checks = []
        self.categories_panel = StackPanel()
        for pid, name in service.all_categories():
            chk = CheckBox()
            chk.Content, chk.Tag = name, pid
            chk.Margin = Thickness(4)
            chk.IsChecked = existing is not None and pid in existing.categories
            chk.Checked += self.category_changed
            chk.Unchecked += self.category_changed
            self.categories_panel.Children.Add(chk)
            self.category_checks.append(chk)
        self.cat_search.TextChanged += self.search_categories
        cats = Expander()
        cats.Header = '1  Categories - choose first (common parameters only)'
        cats.IsExpanded = existing is None
        sc = scroll(self.categories_panel)
        sc.MaxHeight = 220
        cats.Content = panel(label('Search categories', 12, MUTED), self.cat_search, sc)
        self.rules_panel = StackPanel()
        self.preview = label('', 13, '#335D78')
        self.duplicates = label('', 13, '#865B14')
        self.content = panel(label('Filter name', 12, MUTED), self.name, card(cats),
                             label('2  Conditions', 18), self.rules_panel,
                             card(self.preview), card(self.duplicates, True))
        if existing:
            self.content.Children.Add(card(label('Shared definition: ' + existing.usage_text +
                                                '\n' + '\n'.join(model.name_of(v) for v in existing.usage)), True))
        self.body.Children.Add(scroll(self.content))
        self.footer('Cancel', lambda s, e: self.Close())
        self.save_button = self.footer('Save Changes' if existing else 'Create Filter', self.save_clicked, 'primary')
        self.save_button.IsEnabled = not service.doc.IsReadOnly and not (existing and existing.problem)
        self.name.TextChanged += lambda s, e: self.changed()
        self.load_parameters()
        self.render_rules()
        self.loading = False
        self.changed()

    def categories(self):
        return [c.Tag for c in self.category_checks if c.IsChecked]

    def search_categories(self, sender, event):
        query = self.cat_search.Text.lower()
        for c in self.category_checks:
            c.Visibility = Visibility.Visible if query in unicode(c.Content).lower() else Visibility.Collapsed

    def load_parameters(self):
        self.parameters = self.service.eligible_parameters(self.categories())
        eligible = set(p.id for p in self.parameters)
        def preserve(node):
            if node['kind'] == 'group':
                for child in node['children']:
                    preserve(child)
            elif node['kind'] == 'rule' and node.get('native') is not None and node['pid'] not in eligible:
                info = model.ParameterInfo(node['pid'], self.service.parameter_name(node['pid']), 'None')
                info.problem = 'Existing native rule is retained. This parameter is not currently in the common eligible set; replacement must pass Revit validation.'
                self.parameters.append(info)
                eligible.add(info.id)
        preserve(self.tree)

    def category_changed(self, sender, event):
        if self.loading:
            return
        self.run(self.reload_categories)

    def reload_categories(self):
        self.capture_partial()
        self.load_parameters()
        self.render_rules()
        self.changed('Categories changed. Incompatible rules are retained and must be corrected.')

    def capture_partial(self):
        for row in self.rule_rows:
            try:
                value = row.read()
                if value is not row.node:
                    row.node.clear()
                    row.node.update(value)
            except ValueError:
                if row.node.get('native') is None:
                    row.node['pid'] = chosen(row.param)
                    row.node['op'] = chosen(row.operator)
                    row.node['draft_value'] = row.value.Text

    def read_tree(self):
        values = dict((id(row.node), row.read()) for row in self.rule_rows)
        def visit(node, root=False):
            if node['kind'] == 'rule':
                return values[id(node)]
            if node['kind'] == 'unsupported':
                raise ValueError(node['reason'])
            if not root and not node['children']:
                raise ValueError('Remove empty nested groups or add a rule.')
            return model.group([visit(c) for c in node['children']], node['op'])
        return visit(self.tree, True)

    def render_rules(self):
        self.loading = True
        self.detach_rows(None, None)
        self.rules_panel.Children.Clear()
        self.rule_rows = []
        self.render_group(self.tree, self.rules_panel)
        self.loading = False

    def detach_rows(self, sender, event):
        for row in self.rule_rows:
            row.detach()

    def render_group(self, node, parent):
        if node['kind'] == 'unsupported':
            parent.Children.Add(label(node['reason'], 14, '#865B14'))
            return
        if node['kind'] == 'rule':
            self.rule_rows.append(RuleRow(self, parent, node))
            return
        contents = StackPanel()
        head = WrapPanel()
        kind = combo([('AND', 'All conditions (AND)'), ('OR', 'Any condition (OR)')], node['op'])
        kind.Width = 220
        kind.SelectionChanged += lambda s, e: self.group_changed(node, chosen(kind))
        head.Children.Add(kind)
        head.Children.Add(button('+ Add Condition', lambda s, e: self.add_node(node, False)))
        head.Children.Add(button('+ Add Group', lambda s, e: self.add_node(node, True)))
        if node is not self.tree:
            head.Children.Add(button('Remove Group', lambda s, e: self.remove_node(node)))
        contents.Children.Add(head)
        for child in node['children']:
            self.render_group(child, contents)
        parent.Children.Add(card(contents))

    def group_changed(self, node, op):
        if not self.loading:
            node['op'] = op
            self.changed()

    def add_node(self, parent, nested):
        self.capture_partial()
        parent['children'].append(model.group() if nested else {
            'kind': 'rule', 'pid': None, 'op': None, 'family': None, 'value': None})
        self.render_rules()
        self.changed('Choose a parameter, operator and operand.')

    def remove_node(self, node):
        self.capture_partial()
        def remove(parent):
            if parent['kind'] != 'group':
                return False
            for i, child in enumerate(parent['children']):
                if child is node:
                    del parent['children'][i]
                    return True
                if remove(child):
                    return True
            return False
        remove(self.tree)
        self.render_rules()
        self.changed()

    def changed(self, message=''):
        if self.loading:
            return
        try:
            tree = self.read_tree()
            self.preview.Text = self.service.describe(tree)
            matches = self.service.matches(self.categories(), tree, self.existing.id if self.existing else None)
            self.duplicates.Text = ('Same categories and rules: ' + ', '.join(r.name for r in matches)
                                    if matches else 'No identical existing definition. Saving returns directly to the manager.')
            self.status.Text = message or 'Draft only - no model changes until Save.'
        except (ValueError, TypeError, OverflowError) as error:
            self.preview.Text = 'Draft needs correction: ' + unicode(error)
            self.duplicates.Text = 'Duplicate comparison waits for a complete valid draft.'
            self.status.Text = message or unicode(error)

    def save_clicked(self, sender, event):
        self.run(self.save)

    def save(self):
        tree, cats, name = self.read_tree(), self.categories(), self.name.Text
        self.service.refresh()
        self.service.eligible_parameters(cats)
        self.service.validate_definition(name, cats, tree, self.existing)
        matches = self.service.matches(cats, tree, self.existing.id if self.existing else None)
        acknowledged = []
        if matches:
            decision = DuplicateDialog(self.service, matches, cats, tree, self.existing).show(self)
            if not decision:
                return
            if decision[0] == 'use':
                self.result = decision[1]
                self.Close()
                return
            acknowledged = decision[1]
        self.result = self.service.save(name, cats, tree, self.existing, acknowledged)
        self.Close()


class RenameDialog(Dialog):
    def __init__(self, service, records):
        Dialog.__init__(self, 'Rename Filters', 'Pattern preview and manual corrections. Only approved rows are renamed.')
        self.service, self.records = service, records
        self.existing_names = service.filter_names()
        self.config = script.get_config('filter_manager')
        self.pattern = field(getattr(self.config, 'name_pattern', '{categories} - {rules}'))
        self.rows = []
        self.preview_errors = {}
        self.settings_error = ''
        self.updating = True
        content = panel(label('Naming pattern: {categories}, {rules}', 13, MUTED), self.pattern)
        content.Children.Add(button('Update Preview', self.update_preview))
        for record in records:
            approved = CheckBox()
            approved.IsChecked = True
            approved.Content = label(record.name)
            value = field(record.name)
            validation = label('', 12, MUTED)
            content.Children.Add(card(panel(approved, label('Proposed name', 12, MUTED), value, validation)))
            self.rows.append((record, approved, value, validation))
            value.TextChanged += self.validate_preview
            approved.Checked += self.validate_preview
            approved.Unchecked += self.validate_preview
        self.body.Children.Add(scroll(content))
        self.footer('Cancel', lambda s, e: self.Close())
        self.rename_button = self.footer('Rename Approved', self.accept, 'primary')
        self.updating = False
        self.update_preview(None, None)

    def update_preview(self, sender, event):
        def update():
            self.updating = True
            self.rename_button.IsEnabled = False
            self.preview_errors = {}
            try:
                try:
                    symbols = model.load_naming_symbols()
                    self.settings_error = ''
                except ValueError as error:
                    symbols, self.settings_error = None, unicode(error)
                for record, check, value, validation in self.rows:
                    if self.settings_error:
                        break
                    try:
                        record.rules = self.service.describe(record.tree)
                        value.Text = self.service.pattern_name(record, self.pattern.Text, symbols)
                    except ValueError as error:
                        self.preview_errors[record.id] = unicode(error)
            finally:
                self.updating = False
            self.validate_preview(None, None)
        self.run(update)

    def validate_preview(self, sender, event):
        if self.updating:
            return
        if sender is not None:
            for r, check, value, validation in self.rows:
                if sender is value:
                    self.preview_errors.pop(r.id, None)
        names = dict((r.id, value.Text) for r, check, value, validation in self.rows if check.IsChecked)
        errors = self.service.name_errors(names, self.existing_names)
        for fid, error in self.preview_errors.items():
            if fid in names:
                errors[fid] = error + (' ' + errors[fid] if fid in errors else '')
        for r, check, value, validation in self.rows:
            validation.Text = (errors.get(r.id, 'Ready') if check.IsChecked else 'Not approved')
            validation.Foreground = brush('#865B14' if r.id in errors else MUTED)
        self.rename_button.IsEnabled = bool(names) and not errors and not self.settings_error
        self.status.Text = '{} approved / {} need correction. Preview only; no names changed.'.format(
            len(names), len(errors))
        if self.settings_error:
            self.status.Text = self.settings_error + '\nFix the file, then Update Preview. Rename is disabled.'

    def accept(self, sender, event):
        def write():
            names = dict((r.id, value.Text) for r, check, value, validation in self.rows if check.IsChecked)
            if not names:
                raise ValueError('Approve at least one row.')
            self.service.rename([r for r in self.records if r.id in names], names)
            self.config.name_pattern = self.pattern.Text
            script.save_config()
            self.result = True
            self.Close()
        self.run(write)


class MatchingDialog(Dialog):
    def __init__(self, service, records, view):
        Dialog.__init__(self, 'Select Matching Elements', 'Native definitions determine matches, not filter graphics.')
        self.service, self.records, self.view = service, records, view
        self.scope = combo([('view', 'Current view: ' + model.name_of(view)),
                            ('project', 'Entire active project')], 'view')
        self.logic = combo([(False, 'Match ANY selected filter (OR)'),
                            (True, 'Match ALL selected filters (AND)')], False)
        content = panel(card(label('\n'.join(r.name for r in records))), label('Where to look', 18),
                        self.scope, label('Combine selected filters', 18), self.logic)
        self.count = label('Refresh count before confirming.', 18)
        content.Children.Add(card(self.count))
        content.Children.Add(card(label('Confirmation replaces the current Revit selection and closes the manager. Cancel, no matches or errors preserve selection. No view switch, unhiding, isolation or zoom.'), True))
        self.body.Children.Add(scroll(content))
        self.footer('Cancel', lambda s, e: self.Close())
        self.footer('Refresh Count', self.refresh_count)
        self.select = self.footer('Select Elements in Revit', self.accept, 'primary')
        self.scope.SelectionChanged += self.scope_changed
        self.logic.SelectionChanged += self.scope_changed
        self.match_ids = []
        self.scope_changed(None, None)

    def scope_changed(self, sender, event):
        self.match_ids = []
        self.select.IsEnabled = False
        self.count.Text = 'Options changed. Refresh count before selection.'

    def collect(self):
        return self.service.collect_matches(self.records, self.view if chosen(self.scope) == 'view' else None,
                                            chosen(self.logic))

    def refresh_count(self, sender, event):
        def refresh():
            self.match_ids = self.collect()
            self.count.Text = '{} unique matching model elements'.format(len(self.match_ids))
            self.select.Content = 'Select {} Elements in Revit'.format(len(self.match_ids))
            self.select.IsEnabled = bool(self.match_ids)
            if not self.match_ids:
                self.status.Text = 'No matches. Existing Revit selection is unchanged.'
        self.run(refresh)

    def accept(self, sender, event):
        def accept():
            current = self.collect()
            if set(model.id_value(i) for i in current) != set(model.id_value(i) for i in self.match_ids):
                self.scope_changed(None, None)
                raise ValueError('Matches changed. Refresh the count and confirm again.')
            self.result = current
            self.Close()
        self.run(accept)


class ManagerDialog(Dialog):
    def __init__(self, service, uidoc, checked=None, focused=None, search='', target_mode='view',
                 selected_template=None, category=None, applied_only=False, highlighted=None,
                 search_scope='name'):
        Dialog.__init__(self, 'Filter Manager', 'BETA - inspect, create, rename, delete and apply filters to one target.', 1180, 870)
        self.service, self.uidoc = service, uidoc
        self.checked = set(checked or [])
        self.focused = focused
        self.target_mode = target_mode
        self.selected_template = selected_template
        self.highlighted = set(highlighted if highlighted is not None else (
            [focused] if focused is not None else []))
        self.selection_anchor = focused
        self.MinHeight = min(680, SystemParameters.WorkArea.Height - 40)
        self.loading = False
        self.row_items = {}
        self.row_checks = {}
        self.row_records = None
        self.search = field(search)
        self.search.ToolTip = 'Search within the selected scope (case-insensitive)'
        self.search_scope = combo([('name', 'Name'), ('category', 'Category'),
                                   ('rule', 'Rule'), ('all', 'All')], search_scope)
        self.search_scope.Width = 105
        self.search_scope.ToolTip = 'Search in: Name, Category, Rule or All'
        AutomationProperties.SetName(self.search_scope, 'Search in')
        search_row = Grid()
        for width in (GridLength(1, GridUnitType.Star), GridLength.Auto):
            column = ColumnDefinition()
            column.Width = width
            search_row.ColumnDefinitions.Add(column)
        search_row.Children.Add(self.search)
        Grid.SetColumn(self.search_scope, 1)
        search_row.Children.Add(self.search_scope)
        self.category = combo([(None, 'All categories')] + service.all_categories(), category)
        self.category.SelectionChanged += self.search_changed
        self.applied_only = CheckBox()
        self.applied_only.Content = label('Applied to current view or its template', 12)
        self.applied_only.ToolTip = ('Show only filters attached directly to the current view '
                                     'or to its assigned view template.')
        self.applied_only.IsChecked = applied_only
        self.applied_only.Checked += self.search_changed
        self.applied_only.Unchecked += self.search_changed
        self.list = ListBox()
        self.list.SelectionMode = SelectionMode.Extended
        self.list.ToolTip = 'Click a name to inspect. Ctrl-click toggles highlights; Shift-click selects a range. Click a highlighted checkbox to check/uncheck the highlighted group.'
        self.list.Margin = Thickness(4)
        self.description = StackPanel()
        self.search.TextChanged += self.search_changed
        self.search_scope.SelectionChanged += self.search_changed
        self.list.SelectionChanged += self.focus_changed
        root = Grid()
        for size in ('*', 'Auto', 'Auto'):
            row = RowDefinition()
            row.Height = GridLength(1, GridUnitType.Star) if size == '*' else GridLength.Auto
            root.RowDefinitions.Add(row)
        columns = Grid()
        leftcol, rightcol = ColumnDefinition(), ColumnDefinition()
        leftcol.Width, rightcol.Width = GridLength(2, GridUnitType.Star), GridLength(3, GridUnitType.Star)
        columns.ColumnDefinitions.Add(leftcol)
        columns.ColumnDefinitions.Add(rightcol)
        left = Grid()
        for size in ('Auto', 'Auto', 'Auto', '*'):
            row = RowDefinition()
            row.Height = GridLength(1, GridUnitType.Star) if size == '*' else GridLength.Auto
            left.RowDefinitions.Add(row)
        add_row(left, label('PROJECT FILTERS - check for actions; focus to inspect', 12, MUTED), 0)
        add_row(left, search_row, 1)
        add_row(left, panel(self.category, self.applied_only), 2)
        add_row(left, self.list, 3)
        leftcard, rightcard = card(left), card(scroll(self.description))
        Grid.SetColumn(rightcard, 1)
        columns.Children.Add(leftcard)
        columns.Children.Add(rightcard)
        add_row(root, columns, 0)
        toolbar = WrapPanel()
        self.count = label('', 14)
        self.count.MinWidth = 135
        toolbar.Children.Add(self.count)
        toolbar.Children.Add(button('Analyse Duplicates', self.analyse))
        self.rename_button = button('Rename Selected', self.rename_clicked)
        toolbar.Children.Add(self.rename_button)
        toolbar.Children.Add(button('Select Unused', self.select_unused))
        toolbar.Children.Add(button('Unselect All', self.unselect_all))
        self.delete_button = button('Delete Selected', self.delete_clicked, 'destructive')
        toolbar.Children.Add(self.delete_button)
        self.management = Expander()
        self.management.Header = 'Manage selected filters'
        self.management.IsExpanded = True
        self.management.Content = toolbar
        add_row(root, self.management, 1)
        self.target = combo([('view', 'Current view'),
                             ('current_template', "Current view's template"),
                             ('selected_template', 'One selected view template')], target_mode)
        self.target.SelectionChanged += self.target_changed
        target_radios = WrapPanel()
        for index in range(self.target.Items.Count):
            item = self.target.Items[index]
            radio = RadioButton()
            radio.Content, radio.Tag = item.Content, index
            radio.GroupName = 'single_target'
            radio.Margin = Thickness(4, 5, 12, 5)
            radio.IsChecked = item.Tag == target_mode
            if item.Tag == 'view' and not model.supports_filters(uidoc.ActiveView):
                radio.IsEnabled = False
                radio.ToolTip = 'The current view does not support filter attachments.'
            if item.Tag == 'current_template' and service.doc.GetElement(uidoc.ActiveView.ViewTemplateId) is None:
                radio.IsEnabled = False
                radio.ToolTip = 'The current view has no assigned template.'
            radio.Checked += self.radio_changed
            target_radios.Children.Add(radio)
        self.template_wrap = WrapPanel()
        self.template_name = label('', 14)
        self.template_name.MaxWidth = 400
        self.template_wrap.Children.Add(self.template_name)
        self.template_wrap.Children.Add(button('Choose Template...', self.choose_template))
        self.target_notice = label('', 13, '#335D78')
        self.target_section = Expander()
        self.target_section.Header = 'Apply selected filters to one target'
        self.target_section.IsExpanded = True
        self.target_section.Content = card(panel(target_radios, self.template_wrap, self.target_notice))
        add_row(root, self.target_section, 2)
        self.body.Children.Add(root)
        self.footer('Close', lambda s, e: self.Close())
        self.new_button = self.footer('+ New Filter', self.new_clicked)
        self.edit_button = self.footer('Edit Filter', self.edit_clicked)
        self.apply_button = self.footer('Review & Apply', self.apply_clicked, 'primary')
        self.populate()
        self.target_changed(None, None)
        self.compact = None
        self.SizeChanged += self.adapt_layout
        self.adapt_layout(None, None)

    def adapt_layout(self, sender, event):
        compact = self.Width < 850 or self.Height < 760
        if compact != self.compact:
            self.compact = compact
            self.management.IsExpanded = not compact
            self.target_section.IsExpanded = not compact

    def selected_records(self):
        return [r for r in self.service.records if r.id in self.checked]

    def state(self):
        return {'checked': self.checked, 'focused': self.focused, 'search': self.search.Text,
                'search_scope': chosen(self.search_scope),
                'target_mode': chosen(self.target), 'selected_template': self.selected_template,
                'category': chosen(self.category), 'applied_only': self.applied_only.IsChecked is True,
                'highlighted': list(self.highlighted)}

    def populate(self):
        self.loading = True
        if self.row_records is not self.service.records:
            self.row_items.clear()
            self.row_checks.clear()
            self.row_records = self.service.records
        self.checked.intersection_update(r.id for r in self.service.records)
        if self.focused not in set(r.id for r in self.service.records):
            self.focused = None
        self.list.Items.Clear()
        query = self.search.Text.lower()
        scope = chosen(self.search_scope)
        applied = set()
        if self.applied_only.IsChecked:
            view = self.uidoc.ActiveView
            if view.AreGraphicsOverridesAllowed():
                applied.update(model.id_value(i) for i in view.GetFilters())
            template = self.service.doc.GetElement(view.ViewTemplateId)
            if template is not None and template.AreGraphicsOverridesAllowed():
                applied.update(model.id_value(i) for i in template.GetFilters())
        for record in self.service.records:
            if (query not in record.search_fields[scope] or
                    (chosen(self.category) is not None and chosen(self.category) not in record.categories) or
                    (self.applied_only.IsChecked and record.id not in applied)):
                continue
            if record.id in self.row_items:
                item = self.row_items[record.id]
                self.row_checks[record.id].IsChecked = record.id in self.checked
                self.list.Items.Add(item)
                item.IsSelected = record.id in self.highlighted
                continue
            item = ListBoxItem()
            item.Tag = record.id
            item.HorizontalContentAlignment = HorizontalAlignment.Stretch
            check = CheckBox()
            check.VerticalAlignment = VerticalAlignment.Center
            check.HorizontalAlignment = HorizontalAlignment.Left
            check.Margin = Thickness(0, 0, 10, 0)
            AutomationProperties.SetName(check, 'Include filter ' + record.name)
            check.IsChecked = record.id in self.checked
            check.Tag = record.id
            check.Checked += self.check_changed
            check.Unchecked += self.check_changed
            self.row_checks[record.id] = check
            content = Grid()
            tick_column, name_column = ColumnDefinition(), ColumnDefinition()
            tick_column.Width = GridLength.Auto
            name_column.Width = GridLength(1, GridUnitType.Star)
            content.ColumnDefinitions.Add(tick_column)
            content.ColumnDefinitions.Add(name_column)
            text = label(record.name, 13)
            Grid.SetColumn(text, 1)
            content.Children.Add(check)
            content.Children.Add(text)
            item.Content = content
            item.PreviewMouseLeftButtonDown += self.row_clicked
            item.PreviewMouseRightButtonDown += self.right_click
            menu = ContextMenu()
            for title, handler in [('Rename Filters with ReValue', self.revalue_clicked),
                                   ('Select Matching Elements in Revit', self.matching_clicked)]:
                action = MenuItem()
                action.Header = title
                action.Click += handler
                menu.Items.Add(action)
            item.ContextMenu = menu
            self.row_items[record.id] = item
            self.list.Items.Add(item)
            item.IsSelected = record.id in self.highlighted
        if not self.list.SelectedItems.Count and self.list.Items.Count and not self.highlighted:
            self.list.SelectedIndex = 0
            self.focused = self.list.SelectedItem.Tag
        self.highlighted = set(i.Tag for i in self.list.SelectedItems)
        self.loading = False
        self.update_actions()
        self.show_description()
        if not self.list.Items.Count:
            self.status.Text = 'No matching filters.' if self.service.records else 'No rule-based filters. Use New Filter to create the first.'

    def search_changed(self, sender, event):
        if not self.loading:
            self.populate()

    def check_changed(self, sender, event):
        if self.loading:
            return
        affected = self.highlighted if sender.Tag in self.highlighted else set([sender.Tag])
        self.loading = True
        try:
            for fid in affected:
                if sender.IsChecked:
                    self.checked.add(fid)
                else:
                    self.checked.discard(fid)
                self.row_checks[fid].IsChecked = sender.IsChecked
        finally:
            self.loading = False
        self.update_actions()

    def focus_changed(self, sender, event):
        if not self.loading:
            self.highlighted = set(i.Tag for i in self.list.SelectedItems)
            if event.AddedItems.Count:
                self.focused = event.AddedItems[event.AddedItems.Count - 1].Tag
            self.show_description()
            self.update_actions()

    def row_clicked(self, sender, event):
        source = event.OriginalSource
        check = self.row_checks[sender.Tag]
        while source is not None and source is not sender:
            if source is check:
                event.Handled = True
                check.IsChecked = not check.IsChecked
                return
            source = getattr(source, 'Parent', None) or getattr(source, 'TemplatedParent', None)
        event.Handled = True
        self.select_row(sender.Tag, Keyboard.Modifiers)
        sender.Focus()

    def select_row(self, fid, modifiers):
        visible = [item.Tag for item in self.list.Items]
        control = bool(modifiers & ModifierKeys.Control)
        shift = bool(modifiers & ModifierKeys.Shift)
        selected = set(self.highlighted) if control else set()
        if shift and self.selection_anchor in visible:
            start, end = sorted((visible.index(self.selection_anchor), visible.index(fid)))
            selected.update(visible[start:end + 1])
        elif control:
            selected.symmetric_difference_update([fid])
        else:
            selected.add(fid)
        if not shift or self.selection_anchor not in visible:
            self.selection_anchor = fid
        self.loading = True
        try:
            for item in self.list.Items:
                item.IsSelected = item.Tag in selected
        finally:
            self.loading = False
        self.highlighted = selected
        self.focused = fid
        self.show_description()
        self.update_actions()

    def right_click(self, sender, event):
        self.focused = sender.Tag
        if sender.Tag not in self.checked:
            self.checked = set([sender.Tag])
            self.loading = True
            for item in self.list.Items:
                self.row_checks[item.Tag].IsChecked = item.Tag in self.checked
            self.loading = False
        if sender.Tag not in self.highlighted:
            self.select_row(sender.Tag, getattr(ModifierKeys, 'None'))
        else:
            self.show_description()
        self.update_actions()
        self.status.Text = '{} selected filters for context action.'.format(len(self.checked))

    def update_actions(self):
        writable = not self.service.doc.IsReadOnly
        self.count.Text = '{} checked / {} highlighted'.format(len(self.checked), len(self.highlighted))
        self.rename_button.IsEnabled = self.delete_button.IsEnabled = writable and bool(self.checked)
        self.new_button.IsEnabled = writable
        self.edit_button.IsEnabled = writable and len(self.checked) == 1
        target = self.resolve_target()
        self.apply_button.IsEnabled = writable and bool(self.checked) and model.supports_filters(target) and (
            target.IsTemplate or not self.service.template_controls(self.service.doc.GetElement(target.ViewTemplateId)))
        if not writable:
            self.status.Text = 'Read-only document: browse, previews and selection only; writes are disabled.'

    def show_description(self):
        self.description.Children.Clear()
        if self.focused is None:
            return
        record = self.service.get_record(self.focused)
        def display():
            self.description.Children.Add(label(record.name, 23))
            self.description.Children.Add(label('RULE-BASED FILTER - id {}'.format(record.id), 12, MUTED))
            self.description.Children.Add(label('CATEGORIES', 12, MUTED))
            self.description.Children.Add(label(', '.join(record.category_names)))
            self.description.Children.Add(label('CONDITIONS', 12, MUTED))
            tree = StackPanel()
            self.describe_tree(record.tree, tree)
            self.description.Children.Add(card(tree))
            self.description.Children.Add(label('USED BY', 12, MUTED))
            self.description.Children.Add(label(record.usage_text, 16))
            for v in record.usage:
                self.description.Children.Add(label(model.name_of(v), 13, MUTED))
            if record.problem:
                self.description.Children.Add(card(label(record.problem), True))
        self.run(display)

    def describe_tree(self, node, parent, depth=0):
        if node['kind'] == 'group' and node['children']:
            heading = label('ALL (AND)' if node['op'] == 'AND' else 'ANY (OR)', 13, BLUE)
            heading.Margin = Thickness(depth * 14, 5, 0, 3)
            parent.Children.Add(heading)
            for child in node['children']:
                self.describe_tree(child, parent, depth + 1)
        else:
            text = label(self.service.describe(node), 14)
            text.Margin = Thickness(depth * 14, 3, 0, 5)
            parent.Children.Add(text)

    def radio_changed(self, sender, event):
        self.target.SelectedIndex = sender.Tag
        if chosen(self.target) == 'selected_template':
            self.choose_template(sender, event)

    def choose_template(self, sender, event):
        def choose():
            selected = TemplateDialog(self.service, self.selected_template).show(self)
            if selected is not None:
                self.selected_template = selected
                self.target_changed(None, None)
        self.run(choose)

    def resolve_target(self):
        mode = chosen(self.target)
        if mode == 'view':
            return self.uidoc.ActiveView
        if mode == 'current_template':
            return self.service.doc.GetElement(self.uidoc.ActiveView.ViewTemplateId)
        fid = self.selected_template
        return self.service.doc.GetElement(model.element_id(fid)) if fid is not None else None

    def target_changed(self, sender, event):
        if not hasattr(self, 'target_notice'):
            return
        mode = chosen(self.target)
        self.template_wrap.Visibility = Visibility.Visible if mode == 'selected_template' else Visibility.Collapsed
        target = self.resolve_target()
        template = self.service.doc.GetElement(model.element_id(self.selected_template)) if (
            self.selected_template is not None) else None
        self.template_name.Text = model.name_of(template) if template is not None else 'No template selected'
        if target is None:
            self.target_notice.Text = 'No assigned/selected template. Choose another target.'
        elif not model.supports_filters(target):
            self.target_notice.Text = 'This view does not support filter attachments. Choose an eligible template.'
        else:
            self.target_notice.Text = '{}: {}'.format('Template' if target.IsTemplate else 'View',
                                                      model.name_of(target))
            if target.IsTemplate:
                self.target_notice.Text += ' - affects {} inheriting views. Does not assign a template.'.format(
                    len(self.service.dependents(target)))
            elif self.service.template_controls(self.service.doc.GetElement(target.ViewTemplateId)):
                self.target_notice.Text += ' - template controls Filters; choose a template target.'
        if hasattr(self, 'target_section'):
            self.target_section.Header = 'Apply target: ' + (
                model.name_of(target) if target is not None else 'choose one template')
        if hasattr(self, 'apply_button'):
            self.update_actions()

    def refresh(self, focus=None):
        self.service.refresh()
        if focus is not None:
            self.focused = focus
        elif self.focused not in set(r.id for r in self.service.records):
            self.focused = None
        self.populate()

    def new_clicked(self, sender, event):
        self.run(lambda: self.open_editor(None))

    def edit_clicked(self, sender, event):
        self.run(lambda: self.open_editor(self.selected_records()[0]))

    def open_editor(self, record):
        result = EditorDialog(self.service, record).show(self)
        if result is not None:
            self.refresh(result)
            self.status.Text = 'Definition ready. Apply separately; configure graphics in Revit.'

    def select_unused(self, sender, event):
        def select():
            self.service.refresh()
            self.checked = set(r.id for r in self.service.records if not r.usage)
            self.category.SelectedIndex = 0
            self.applied_only.IsChecked = False
            self.search.Text = ''
            self.populate()
            self.status.Text = '{} unused filters selected. Nothing deleted.'.format(len(self.checked)) if self.checked else 'No unused filters found.'
        self.run(select)

    def unselect_all(self, sender, event):
        self.checked.clear()
        self.populate()
        self.status.Text = 'All manager checks cleared. Revit selection is unchanged.'

    def analyse(self, sender, event):
        def analyse():
            self.service.refresh()
            groups, unsupported = self.service.duplicate_groups()
            rows = []
            for index, members in enumerate(groups):
                for r in members:
                    r.rules = self.service.describe(r.tree)
                    rows.append((r.id, 'Group {} - {}'.format(index + 1, r.name),
                                 r.rules + '\n' + r.usage_text))
            lines = '{} duplicate groups / {} definitions not comparable.'.format(len(groups), len(unsupported))
            warning = '\n'.join(r.name + ': ' + r.problem for r in unsupported)
            if not rows:
                ResultsDialog('Duplicate Analysis', [lines, warning or 'Complete scan: no duplicates.']).show(self)
                return
            review = ReviewDialog('Duplicate Analysis', lines, rows, warning,
                                  primary='Select & Inspect Approved')
            focus = review.show(self)
            if focus:
                self.checked = set(focus)
                self.search.Text = ''
                self.category.SelectedIndex = 0
                self.applied_only.IsChecked = False
                self.refresh(focus[0])
        self.run(analyse)

    def rename_clicked(self, sender, event):
        def rename():
            if RenameDialog(self.service, self.selected_records()).show(self):
                self.refresh()
        self.run(rename)

    def delete_clicked(self, sender, event):
        def delete():
            self.service.refresh()
            records = self.selected_records()
            if not records:
                raise ValueError('Select filters to delete.')
            rows = [(r.id, r.name + ' [id {}]'.format(r.id),
                     ', '.join(r.category_names) + '\n' + r.usage_text + '\n' +
                     '\n'.join(model.name_of(v) for v in r.usage)) for r in records]
            used = any(r.usage for r in records)
            tokens = dict((r.id, self.service.usage_token(r)) for r in records)
            review = ReviewDialog('Delete Selected Filters', 'Approve only the definitions to delete.',
                                  rows, 'Used-filter deletion removes attachments, overrides and filtering effects everywhere. Matched model elements are not deleted.',
                                  used, 'Delete Approved Filters', True)
            approved = review.show(self)
            if not approved:
                return
            selected = [r for r in records if r.id in approved]
            self.service.delete(selected, tokens)
            self.refresh()
            ResultsDialog('Deletion Results', [
                '{} definitions deleted / {} unchecked definitions kept / 0 failures'.format(len(selected), len(records) - len(selected)),
                'Deleted: ' + ', '.join(r.name for r in selected),
                'One Revit Undo restores definitions and their attachments/graphics.',
                'No matching model elements were deleted.']).show(self)
        self.run(delete)

    def apply_clicked(self, sender, event):
        def apply():
            records, target = self.selected_records(), self.resolve_target()
            if not records or target is None:
                raise ValueError('Choose filters and exactly one target.')
            if not model.supports_filters(target):
                raise ValueError('Target does not support filters.')
            if not target.IsTemplate and self.service.template_controls(self.service.doc.GetElement(target.ViewTemplateId)):
                raise ValueError("Template controls Filters. Choose Current view's template or one selected template explicitly.")
            present = set(model.id_value(i) for i in target.GetFilters())
            rows = [(r.id, r.name, 'Already applied - skip' if r.id in present else 'Add attachment') for r in records]
            warning = 'Existing graphics, visibility, enable state and order are preserved. No definitions or template assignments change.'
            if target.IsTemplate:
                warning += '\n{} views inherit this template.'.format(len(self.service.dependents(target)))
            approved = ReviewDialog('Review Application', 'One target: ' + model.name_of(target),
                                    rows, warning, primary='Apply to Target').show(self)
            if not approved:
                return
            result = self.service.apply([r for r in records if r.id in approved], target)
            self.refresh()
            self.status.Text = '{}: {} added / {} already applied. Configure graphics in Revit.'.format(
                model.name_of(target), len(result['added']), len(result['skipped']))
        self.run(apply)

    def matching_clicked(self, sender, event):
        def select():
            self.service.refresh()
            selected = MatchingDialog(self.service, self.selected_records(), self.uidoc.ActiveView).show(self)
            if selected:
                self.result = ('selection', selected)
                self.Close()
        self.run(select)

    def revalue_clicked(self, sender, event):
        if not self.checked:
            self.status.Text = 'Choose filters to rename.'
            return
        self.result = ('revalue', self.selected_records())
        self.Close()
