"""Visual filter editing without modifying the active filter until confirmed."""
import copy
import io
import os

from System.Windows import Thickness
from System.Windows.Controls import (
    Border, Button, CheckBox, ComboBox, Orientation, StackPanel, TextBox,
)
from System.Windows.Markup import XamlReader
from System.Windows.Media import Brushes

from filter_expression import (
    COMPARISONS, count_rules, group, parse_expression, rule,
    serialize_expression, validate_expression,
)


CONDITIONS = (
    'Equals', 'Does not equal', 'Contains', 'Starts with', 'Ends with',
    'Is blank', 'Is not blank', 'Greater than', 'Less than',
    'Greater than or equal to', 'Less than or equal to',
    'Equals (numeric)', 'Does not equal (numeric)',
)


class FilterEditor(object):
    def __init__(self, owner, parameters, active_filter):
        path = os.path.join(os.path.dirname(__file__), 'FilterEditor.xaml')
        with io.open(path, encoding='utf-8') as source:
            self.window = XamlReader.Parse(source.read())
        self.window.Owner = owner
        self.parameters = list(parameters)
        self.tree = copy.deepcopy(active_filter)
        self.result = None
        self.accepted = False
        self._syncing = False
        self.rules_panel = self.window.FindName('rules_panel')
        self.expression_text = self.window.FindName('expression_text')
        self.status = self.window.FindName('validation_status')
        self.use_button = self.window.FindName('use_filters')
        self.window.FindName('clear_rules').Click += self.clear
        self.window.FindName('cancel_editor').Click += self.cancel
        self.use_button.Click += self.accept
        self.expression_text.TextChanged += self.expression_changed
        self.render()
        self.visual_changed()

    def new_rule(self):
        return rule(self.parameters[0] if self.parameters else '')

    def button(self, label, callback):
        button = Button()
        button.Content = label
        button.Click += callback
        return button

    def combo(self, options, selection, width):
        combo = ComboBox()
        combo.Width = width
        for option in options:
            combo.Items.Add(option)
        if selection not in options:
            combo.Items.Add(selection)
        combo.SelectedItem = selection
        return combo

    def render(self):
        self._syncing = True
        try:
            if self.tree is None:
                self.tree = group()
            if self.tree['kind'] != 'group':
                self.tree = group(children=[self.tree])
            self.rules_panel.Children.Clear()
            self.render_group(self.tree, self.rules_panel, None)
        finally:
            self._syncing = False

    def remove(self, parent, node):
        parent['children'].remove(node)
        self.render()
        self.visual_changed()

    def add(self, node, is_group):
        node['children'].append(
            group(children=[self.new_rule()]) if is_group else self.new_rule())
        self.render()
        self.visual_changed()

    def render_group(self, node, host, parent):
        negated = node['operator'] == 'NOT'
        inner = node['children'][0] if negated else node
        if inner['kind'] != 'group' or inner['operator'] == 'NOT':
            inner = group(children=[inner])
            if negated:
                node['children'] = [inner]
        border = Border()
        border.BorderBrush = Brushes.LightGray
        border.BorderThickness = Thickness(1)
        border.Margin = Thickness(3)
        border.Padding = Thickness(5)
        panel = StackPanel()
        border.Child = panel
        host.Children.Add(border)
        header = StackPanel()
        header.Orientation = Orientation.Horizontal
        panel.Children.Add(header)
        logical = self.combo(
            ['All conditions (AND)', 'Any conditions (OR)'],
            'Any conditions (OR)' if inner['operator'] == 'OR' else 'All conditions (AND)',
            190)
        header.Children.Add(logical)

        def logical_changed(sender, args):
            inner['operator'] = 'OR' if logical.SelectedIndex == 1 else 'AND'
            self.visual_changed()
        logical.SelectionChanged += logical_changed
        exclude = CheckBox()
        exclude.Content = 'Exclude this group (NOT)'
        exclude.Margin = Thickness(8, 6, 8, 3)
        exclude.IsChecked = negated
        header.Children.Add(exclude)

        def negation_changed(sender, args):
            if self._syncing:
                return
            replacement = (group('NOT', [copy.deepcopy(node)])
                           if exclude.IsChecked else copy.deepcopy(node['children'][0]))
            node.clear()
            node.update(replacement)
            self.render()
            self.visual_changed()
        exclude.Checked += negation_changed
        exclude.Unchecked += negation_changed
        if parent is not None:
            header.Children.Add(self.button('Remove Group',
                lambda sender, args: self.remove(parent, node)))
        for child in inner['children']:
            if child['kind'] == 'group':
                self.render_group(child, panel, inner)
            else:
                self.render_rule(child, panel, inner)
        actions = StackPanel()
        actions.Orientation = Orientation.Horizontal
        actions.Children.Add(self.button('+ Add Condition',
            lambda sender, args: self.add(inner, False)))
        actions.Children.Add(self.button('+ Add Group',
            lambda sender, args: self.add(inner, True)))
        panel.Children.Add(actions)

    def render_rule(self, node, host, parent):
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        host.Children.Add(panel)
        parameter = self.combo(self.parameters, node['parameter'], 210)
        parameter.ToolTip = 'Parameter (read-only filter source)'
        condition_name = node['condition']
        if node['numeric'] and condition_name in ('Equals', 'Does not equal'):
            condition_name += ' (numeric)'
        condition = self.combo(CONDITIONS, condition_name, 195)
        condition.ToolTip = 'Condition; text comparisons ignore case'
        value = TextBox()
        value.Width = 140
        value.Text = node['value']
        value.ToolTip = 'Value; numbers use a decimal point, no thousands separators or units'
        value.IsEnabled = node['condition'] not in ('Is blank', 'Is not blank')
        for control in (parameter, condition, value):
            panel.Children.Add(control)
        panel.Children.Add(self.button('Remove',
            lambda sender, args: self.remove(parent, node)))

        def changed(sender, args):
            if self._syncing:
                return
            selected = str(condition.SelectedItem)
            node['parameter'] = str(parameter.SelectedItem)
            node['condition'] = selected.replace(' (numeric)', '')
            node['numeric'] = ('(numeric)' in selected or
                               selected in tuple(COMPARISONS[key] for key in ('>', '<', '>=', '<=')))
            node['value'] = value.Text
            value.IsEnabled = selected not in ('Is blank', 'Is not blank')
            self.visual_changed()
        parameter.SelectionChanged += changed
        condition.SelectionChanged += changed
        value.TextChanged += changed

    def empty_root(self):
        return (self.tree is None or
                (self.tree['kind'] == 'group' and self.tree['operator'] != 'NOT'
                 and not self.tree['children']))

    def feedback(self, error=None, node=None):
        self.use_button.IsEnabled = error is None
        self.status.Foreground = Brushes.Firebrick if error else Brushes.DarkGreen
        self.status.Text = ('Invalid expression: ' + str(error) if error else
                            'Valid expression - {} rule(s). Use Filters to update the preview.'.format(
                                count_rules(node)))

    def visual_changed(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            text = '' if self.empty_root() else serialize_expression(self.tree)
            self.expression_text.Text = text
            node = parse_expression(text)
            validate_expression(node, self.parameters)
            self.feedback(node=node)
        except ValueError as ex:
            self.feedback(error=ex)
        finally:
            self._syncing = False

    def expression_changed(self, sender, args):
        if self._syncing:
            return
        try:
            node = parse_expression(self.expression_text.Text)
            validate_expression(node, self.parameters)
        except ValueError as ex:
            self.feedback(error=ex)
            self.rules_panel.IsEnabled = False
            return
        self.tree = node
        self.rules_panel.IsEnabled = True
        self.render()
        self.feedback(node=node)

    def clear(self, sender, args):
        self.tree = None
        self.rules_panel.IsEnabled = True
        self.render()
        self.visual_changed()

    def accept(self, sender, args):
        try:
            node = parse_expression(self.expression_text.Text)
            validate_expression(node, self.parameters)
        except ValueError as ex:
            self.feedback(error=ex)
            return
        self.result = node
        self.accepted = True
        self.window.DialogResult = True

    def cancel(self, sender, args):
        self.window.DialogResult = False

    def show(self):
        self.window.ShowDialog()
        return self.accepted, self.result
