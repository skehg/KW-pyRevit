# -*- coding: utf-8 -*-
"""Persistent native Filter Manager workspace (IronPython 2.7).

This module owns presentation/drafts only. Definition writes belong to
FilterService; attachment reading, planning, approval and writes belong to
GraphicService. No Revit worker threads and no automatic save on navigation.
"""
import traceback
from copy import deepcopy

import clr
from System import Action, Byte
from System.Diagnostics import Stopwatch
from System.Windows import (Thickness, GridLength, GridUnitType, Visibility,
                            HorizontalAlignment, VerticalAlignment, TextWrapping, TextTrimming)
from System.Windows.Automation import AutomationProperties
from System.Windows.Controls import (StackPanel, WrapPanel, Grid, Border,
    RowDefinition, ColumnDefinition, TextBlock, TextBox, CheckBox, Button,
    ListBox, ListBoxItem, ContextMenu, MenuItem, Expander, TabControl, TabItem,
    Orientation, SelectionMode, ScrollBarVisibility)
from System.Windows.Input import Keyboard, ModifierKeys, Key
from System.Windows.Threading import DispatcherFrame, DispatcherPriority
from pyrevit import script, DB, UI
import filter_model as model
import filter_ui as ui


SOURCE_MODES = [
    ('current', 'Current View / Template',
     'Effective current origin; use the assigned template only if it controls Filters.'),
    ('browser', 'Browser View / Template',
     'Captured Project Browser snapshot; effective origins are deduplicated.'),
    ('selected', 'Selected Views / Templates',
     'Choose independent source views/templates. Loads project names on request.'),
    ('project', 'All Project Filters',
     'Shared definitions, including unused. No implicit attachment graphics.')]
TARGET_MODES = [
    ('view', 'View', 'Current View', 'Only the current view; controlled views are not redirected.'),
    ('template', 'Template', "Current View's Template", 'Explicit template target; affects every inheriting view.'),
    ('browser', 'Browser', 'Browser Selected', 'Candidates captured before this workspace opened.'),
    ('project', 'Project', 'Project Search', 'Load the project name/type catalogue on demand.')]


def text(value='', size=14, color=ui.INK):
    control = ui.label(value, size, color)
    control.TextWrapping = TextWrapping.Wrap
    return control


def row(*children):
    result = WrapPanel()
    for child in children:
        result.Children.Add(child)
    return result


def check(caption, selected=False, handler=None):
    result = CheckBox()
    result.Content = caption
    result.IsChecked = selected
    result.Margin = Thickness(4)
    if handler:
        result.Checked += handler
        result.Unchecked += handler
    return result


def named(control, name):
    AutomationProperties.SetName(control, name)
    control.ToolTip = name
    return control


def small_button(caption, action):
    control = ui.button(caption, action)
    control.FontSize = 12
    control.Padding = Thickness(8, 3, 8, 3)
    control.Margin = Thickness(2)
    control.MinHeight = 32
    return control


def choose(control, value):
    for item in control.Items:
        if item.Tag == value:
            control.SelectedItem = item
            return True
    return False


def slot(parent, child):
    parent.Children.Clear()
    parent.Children.Add(child)


def stacked_grid(header, body, footer=None):
    result = Grid()
    for height in (GridLength.Auto, GridLength(1, GridUnitType.Star)):
        definition = RowDefinition()
        definition.Height = height
        result.RowDefinitions.Add(definition)
    ui.add_row(result, header, 0)
    ui.add_row(result, body, 1)
    if footer is not None:
        definition = RowDefinition()
        definition.Height = GridLength.Auto
        result.RowDefinitions.Add(definition)
        ui.add_row(result, footer, 2)
    return result


def independent_patch(patch):
    return dict((key, dict(value)) for key, value in patch.items())


def display_value(descriptor, value):
    if value is None or (descriptor.get('can_clear') and value == -1):
        return 'Unset'
    if descriptor['kind'] == 'color':
        return '#{:02X}{:02X}{:02X}'.format(*value)
    if descriptor['kind'] == 'bool':
        return 'On' if value else 'Off'
    return unicode(value)


class CheckedSelection(object):
    """Checks are identities, focus is independent; ranges use visible order."""
    def __init__(self, values=()):
        self.checked = set(values)
        self.focused = None
        self.anchor = None

    def focus(self, identity):
        self.focused = identity

    def toggle(self, identity, value, visible, shift=False):
        scope = [identity]
        if shift and self.anchor in visible and identity in visible:
            a, b = visible.index(self.anchor), visible.index(identity)
            scope = visible[min(a, b):max(a, b) + 1]
        for key in scope:
            if value:
                self.checked.add(key)
            else:
                self.checked.discard(key)
        self.anchor = identity

    def hidden(self, visible):
        return len(self.checked - set(visible))

    def clear(self):
        self.checked.clear()
        self.anchor = None


class InlineEditor(ui.EditorDialog):
    """Reuse the tested typed rule/category controls, never its modal save path."""
    def __init__(self, workspace, existing=None, draft=None):
        self.workspace = workspace
        self.dirty = False
        self.initializing = True
        self.duplicate_ids = ()
        self.acknowledged_ids = ()
        self.draft_source_id = draft.get('source_id') if draft else None
        self.draft_source_token = draft.get('source_token') if draft else None
        ui.EditorDialog.__init__(self, workspace.service, existing)
        if self.draft_source_id is not None:
            origin = next((r for r in workspace.service.records if r.id == self.draft_source_id), None)
            self.content.Children.Insert(0, text('Independent duplicate draft from {} [id {}]. '
                'No attachments or graphics copied.'.format(origin.name if origin else 'source',
                self.draft_source_id), 12, '#865B14'))
        if existing and existing.inherited:
            self.content.Children.Add(ui.card(text('Inherited shared impact:\n' +
                '\n'.join(model.name_of(view) for view in existing.inherited), 12, '#865B14'), True))
        self.embedded = self.body.Children[0]
        self.body.Children.Remove(self.embedded)
        if existing:
            self.name.IsReadOnly = True
            self.name.ToolTip = 'Edit Rules preserves the current name. Use Rename to change names.'
        if draft:
            self.restore(draft)
        self.changed()
        self.initializing = False
        self.dirty = bool(draft and draft.get('dirty'))

    def run(self, action):
        return self.workspace.run(action)

    def changed(self, message=''):
        # EditorDialog constructor invokes changed before extraction.
        if self.loading:
            return
        if not self.initializing:
            self.dirty = True
            self.acknowledged_ids = ()
        try:
            tree = self.read_tree()
            self.preview.Text = self.service.describe(tree)
            matches = self.service.matches(self.categories(), tree,
                                          self.existing.id if self.existing else None)
            self.duplicate_ids = tuple(sorted(r.id for r in matches))
            self.duplicates.Text = ('Identical definitions: ' + ', '.join(r.name for r in matches)
                if matches else 'No identical definition. Draft only; no model changes.')
        except (ValueError, TypeError, OverflowError) as error:
            self.preview.Text = 'Needs correction: ' + unicode(error)
            self.duplicates.Text = 'Comparison waits for a complete typed draft.'
            self.duplicate_ids = ()
        if not self.initializing:
            self.workspace.editor_changed(self)

    def save(self):
        return self.workspace.save_definition(self)

    def save_clicked(self, sender, event):
        self.workspace.run(self.save)

    def detach_rows(self, sender, event):
        for rule in self.rule_rows:
            if not getattr(rule, '_workspace_detached', False):
                rule.detach()
                rule._workspace_detached = True

    def export(self):
        self.capture_partial()
        return {'name': self.name.Text, 'categories': self.categories(),
                'tree': model.clone_tree(self.tree), 'dirty': self.dirty,
                'source_id': self.draft_source_id, 'source_token': self.draft_source_token,
                'record': self.existing,
                'raw': [{'pid': ui.chosen(r.param), 'op': ui.chosen(r.operator),
                         'text': r.value.Text, 'picker': ui.chosen(r.value_picker),
                         'epsilon': r.epsilon.Text,
                         'value_dirty': r.value_dirty, 'epsilon_dirty': r.epsilon_dirty}
                        for r in self.rule_rows]}

    def restore(self, draft):
        self.loading = True
        self.name.Text = draft.get('name', self.name.Text)
        categories = draft.get('categories', [])
        for item in self.category_checks:
            item.IsChecked = item.Tag in categories
        self.tree = model.clone_tree(draft.get('tree', model.group()))
        self.load_parameters()
        self.render_rules()
        self.loading = True
        for rule, raw in zip(self.rule_rows, draft.get('raw', [])):
            rule.loading = True
            choose(rule.param, raw['pid'])
            choose(rule.operator, raw['op'])
            rule.value.Text = raw['text']
            choose(rule.value_picker, raw['picker'])
            rule.epsilon.Text = raw['epsilon']
            rule.value_dirty = raw['value_dirty']
            rule.epsilon_dirty = raw['epsilon_dirty']
            rule.loading = False
        self.loading = False


class WorkspaceDialog(ui.Dialog):
    """One modal workspace; constructor and state() are safe read-only operations."""
    def __init__(self, service, uidoc, browser_ids=None, state=None):
        from filter_graphics import GraphicService
        self.service, self.uidoc = service, uidoc
        self._initial = dict(state or {})
        saved_graphics = self._initial.get('graphics_service')
        self.graphics = saved_graphics if saved_graphics is not None and saved_graphics.filter_service is service else GraphicService(service)
        self.browser_ids = list(browser_ids or self._initial.get('browser_ids', []))
        self.filters = CheckedSelection(self._initial.get('checked_filters', []))
        self.targets = CheckedSelection(self._initial.get('checked_targets', []))
        self.filters.focused = self._initial.get('focused_filter')
        self.targets.focused = self._initial.get('focused_target')
        self.filter_highlights = set(self._initial.get('filter_highlights', []))
        self.target_highlights = set(self._initial.get('target_highlights', []))
        self.pair_patches = dict((tuple(pair), independent_patch(patch)) for pair, patch in
                                 self._initial.get('pair_patches', {}).items())
        self.pair_sources = {}
        for pair, records in self._initial.get('pair_sources', {}).items():
            self.pair_sources[tuple(pair)] = deepcopy(records if isinstance(records, list) else [records])
        self.pair_before = deepcopy(self._initial.get('pair_before', {}))
        self.pair_defaults = deepcopy(self._initial.get('pair_defaults', {}))
        self.graphics_read_errors = {}
        self.resource_names = dict(self._initial.get('resource_names', {}))
        self.pair_graphic_inputs = dict((tuple(pair), dict(values)) for pair, values in
                                       self._initial.get('pair_graphic_inputs', {}).items())
        self.pair_graphic_errors = dict((tuple(pair), dict(values)) for pair, values in
                                       self._initial.get('pair_graphic_errors', {}).items())
        # A previous in-memory workspace may have per-filter drafts. Bind them
        # only to destinations already checked in that saved state. With none,
        # retain them explicitly unassigned; never create a future broadcast.
        self.unassigned_graphics = dict((fid, dict(draft)) for fid, draft in
                                       self._initial.get('unassigned_graphics', {}).items())
        legacy_patches = self._initial.get('patches', {})
        legacy_inputs = self._initial.get('graphic_inputs', {})
        legacy_errors = self._initial.get('graphic_errors', {})
        for fid in set(legacy_patches).union(legacy_inputs, legacy_errors):
            draft = {'patch': independent_patch(legacy_patches.get(fid, {})),
                     'inputs': dict(legacy_inputs.get(fid, {})),
                     'errors': dict(legacy_errors.get(fid, {}))}
            if self.targets.checked:
                for tid in self.targets.checked:
                    pair = (tid, fid)
                    self.pair_patches.setdefault(pair, independent_patch(draft['patch']))
                    self.pair_graphic_inputs.setdefault(pair, dict(draft['inputs']))
                    self.pair_graphic_errors.setdefault(pair, dict(draft['errors']))
            else:
                self.unassigned_graphics[fid] = draft
        self.source_choices = dict(self._initial.get('source_choices', {}))
        self.receipts = list(self._initial.get('receipts', []))
        was_dirty = self._initial.get('graphics_dirty', bool(self.pair_patches or self.unassigned_graphics or self.pair_sources))
        fallback_pairs = set(self.pair_patches).union(self.pair_graphic_inputs,
                                                     self.pair_graphic_errors, self.pair_sources) if was_dirty else set()
        self.dirty_graphics_pairs = set(tuple(pair) for pair in
                                       self._initial.get('dirty_graphics_pairs', fallback_pairs))
        self.dirty_graphics_ids = set(self._initial.get('dirty_graphics_ids', []))
        self.sync_graphics_dirty()
        self.rename_proposals = dict(self._initial.get('rename_proposals', {}))
        self.rename_completed = set(self._initial.get('rename_completed', []))
        self.rename_errors = dict(self._initial.get('rename_errors', {}))
        self.rename_config = script.get_config('filter_manager')
        self.rename_pattern_value = self._initial.get('rename_pattern',
            getattr(self.rename_config, 'name_pattern', '{categories} | {rules}'))
        self.naming_generated = self._initial.get('naming_generated', False)
        self.editors = {}
        self.editor_states = dict(self._initial.get('rule_drafts', {}))
        self.new_editor = None
        self.catalogue = self._initial.get('catalogue')
        self.source_ids = list(self._initial.get('source_ids', []))
        self.revealed_filters = set(self._initial.get('revealed_filters', []))
        self.source_exempt_ids = set(self._initial.get('source_exempt_ids', []))
        self.source_map, self.target_candidates = {}, []
        self.source_mode = self._initial.get('source_mode', 'current')
        self.target_mode = self._initial.get('target_mode', 'browser' if self.browser_ids else 'view')
        self.include_graphics = self._initial.get('include_graphics', True)
        self.include_visibility = self._initial.get('include_visibility', True)
        self.together = self._initial.get('together', False)
        self.plan = (self._initial.get('plan') if self.graphics is saved_graphics and
                     not legacy_patches and not legacy_inputs and not legacy_errors else None)
        self.visible_filters, self.visible_targets = [], []
        self.busy, self.cancelled, self.loading = False, False, True
        self._allow_close, self._handoff = False, False
        self.management = None
        self._task = self._initial.get('tab', 'Graphics')
        self._source_change = None
        self._close_requested = False
        self.changes_query = ''
        self.review_checks = {}
        self.picker_checks = set()
        self._last_source_mode = self.source_mode
        ui.Dialog.__init__(self, 'Filter Manager',
            'Definitions are shared project-wide. Inspect and draft freely; only labelled actions write.',
            1440, 960)
        self.MinWidth = min(760, ui.SystemParameters.WorkArea.Width - 40)
        self.MinHeight = min(640, self.Height)
        self.heading.FontSize = 23
        self.subtitle.TextWrapping = TextWrapping.Wrap
        self.build()
        self.loading = False
        self.resolve_sources()
        self.run(self.resolve_targets)
        self.refresh_lists()
        self.select_tab(self._task)
        self.SizeChanged += self.adapt_layout
        self.Closing += self.closing
        self.Closed += self.dispose_editors
        self.PreviewKeyDown += self.key_down
        self.adapt_layout(None, None)

    def run(self, action):
        """All routine errors stay inline and are logged, never forms.alert."""
        try:
            return action()
        except Exception as error:
            script.get_logger().error('Filter workspace: %s\n%s', error, traceback.format_exc())
            self.status.Text = unicode(error)
            return None

    def build(self):
        self.body.Children.Clear()
        self.actions.Children.Clear()
        self.global_clear = ui.button('Clear Selection', lambda s, e: self.clear_selection())
        self.source_drawer_button = ui.button('Filters', lambda s, e: self.toggle_drawer('left'))
        self.target_drawer_button = ui.button('Targets', lambda s, e: self.toggle_drawer('right'))
        top = row(self.source_drawer_button, self.target_drawer_button, self.global_clear)
        self.columns = Grid()
        for value in (300, 1, 300):
            col = ColumnDefinition()
            col.Width = GridLength(value, GridUnitType.Star if value == 1 else GridUnitType.Pixel)
            self.columns.ColumnDefinitions.Add(col)
        self.left = self.build_library()
        self.right = self.build_targets()
        self.centre = self.build_centre()
        for index, control in enumerate((self.left, self.centre, self.right)):
            Grid.SetColumn(control, index)
            self.columns.Children.Add(control)
        self.attachment_strip = self.build_strip()
        self.body.Children.Add(stacked_grid(top, self.columns, self.attachment_strip))
        self.dismiss_button = self.footer('Cancel', lambda s, e: self.run(self.cancel_workspace))
        self.dismiss_button.ToolTip = 'Discard all unapplied drafts and close. Already applied changes are kept.'
        self.cancel_button = self.footer('Cancel reading', lambda s, e: self.cancel_read())
        self.cancel_button.Visibility = Visibility.Hidden
        self.apply_button = self.footer('Add Filters', lambda s, e: self.run(self.apply_attachments), 'primary')
        self.apply_button.IsEnabled = False
        self.apply_close_button = self.footer('Apply and Close', lambda s, e: self.run(self.apply_and_close))
        self.apply_close_button.ToolTip = 'Apply ready attachments/graphics and close only when no unapplied drafts remain.'
        for control, width in ((self.dismiss_button, 90), (self.cancel_button, 140),
                               (self.apply_button, 250), (self.apply_close_button, 170)):
            control.Width = width
            control.Height = 44

    def make_source_combo(self, source=True):
        options = [(key, title + '\n' + description) for key, title, description in SOURCE_MODES] if source else [
            (key, long_name + '\n' + description) for key, short, long_name, description in TARGET_MODES]
        result = ui.combo(options, self.source_mode if source else self.target_mode)
        result.MaxDropDownHeight = 340
        named(result, 'Filter source' if source else 'Target source')
        if source:
            result.SelectionChanged += self.source_changed
        else:
            result.SelectionChanged += self.target_changed
        return result

    def search_header(self, source):
        query = named(ui.field(self._initial.get('filter_query' if source else 'target_query', '')),
                      'Search filters' if source else 'Search targets')
        query.MinWidth = 100
        options_button = small_button('Options', None)
        menu = ContextMenu()
        options_button.ContextMenu = menu
        options_button.Click += lambda s, e: self.open_menu(options_button)
        reset = small_button('Reset search', lambda s, e: self.reset_search(source))
        show = check('Show selected', self._initial.get('filter_selected' if source else 'target_selected', False),
                     lambda s, e: self.refresh_lists())
        show.FontSize = 12
        modes = ui.combo([(v, v.title()) for v in ('name', 'category', 'rule', 'all')] if source else
                         [('both', 'Views and Templates'), ('views', 'Views'), ('templates', 'Templates')],
                         self._initial.get('filter_field' if source else 'target_kind', 'all' if source else 'both'))
        modes.SelectionChanged += lambda s, e: self.refresh_lists()
        menu.Items.Add(self.menu_control('Search field' if source else 'Target kind', modes))
        if source:
            unused = check('Project-unused only', self._initial.get('unused', False),
                           lambda s, e: self.refresh_lists())
            cats = sorted(set(name for record in self.service.records for name in record.category_names))
            restriction = ui.combo([(None, 'All categories')] + [(name, name) for name in cats],
                                   self._initial.get('category'))
            restriction.SelectionChanged += lambda s, e: self.refresh_lists()
            menu.Items.Add(self.menu_control('Category', restriction))
            menu.Items.Add(self.menu_control('', unused))
            self.filter_search, self.filter_field, self.filter_category = query, modes, restriction
            self.filter_selected, self.unused = show, unused
        else:
            restriction = ui.combo([(None, 'All view types')], None)
            restriction.SelectedIndex = 0
            restriction.SelectionChanged += lambda s, e: self.refresh_lists()
            menu.Items.Add(self.menu_control('View type', restriction))
            self.target_search, self.target_kind, self.target_type = query, modes, restriction
            self.target_selected = show
        query.TextChanged += lambda s, e: self.refresh_lists()
        # A single query/options control, not separate duplicate search fields.
        search_grid = Grid()
        for width in (GridLength(1, GridUnitType.Star), GridLength.Auto):
            col = ColumnDefinition()
            col.Width = width
            search_grid.ColumnDefinitions.Add(col)
        search_grid.Children.Add(query)
        Grid.SetColumn(options_button, 1)
        search_grid.Children.Add(options_button)
        return ui.panel(search_grid, row(show, reset))

    def menu_control(self, title, control):
        item = MenuItem()
        item.StaysOpenOnClick = True
        item.Header = ui.panel(text(title, 12, ui.MUTED), control)
        return item

    def open_menu(self, button):
        button.ContextMenu.PlacementTarget = button
        button.ContextMenu.IsOpen = True

    def build_library(self):
        self.source_combo = self.make_source_combo()
        # A compact closed label with full names/descriptions in the menu.
        # Keep the internal ComboBox as the existing typed selection controller.
        self.source_button = small_button('', None)
        self.source_button.ContextMenu = ContextMenu()
        for key, title, description in SOURCE_MODES:
            item = MenuItem()
            item.Header = ui.panel(text(title), text(description, 12, ui.MUTED))
            item.Tag = key
            item.IsCheckable = True
            item.IsChecked = key == self.source_mode
            item.Click += lambda s, e: self.source_menu_selected(s.Tag)
            self.source_button.ContextMenu.Items.Add(item)
        self.source_button.Click += lambda s, e: self.open_menu(self.source_button)
        self.source_label = text('', 12, ui.MUTED)
        actions = small_button('Actions', None)
        actions.ContextMenu = self.filter_menu()
        actions.Click += lambda s, e: self.open_menu(actions)
        self.filter_count = text('', 12, ui.MUTED)
        self.filter_count.FontSize = 11
        self.filter_count.Margin = Thickness(0)
        self.filter_restrictions = text('', 12, ui.MUTED)
        self.library_options = Expander()
        self.library_options.Header = 'Source and search'
        self.library_options.IsExpanded = True
        self.library_options.Content = ui.panel(self.source_button, self.source_label,
                                                self.search_header(True), self.filter_restrictions)
        header = ui.panel(row(text('Filters', 18),
            small_button('+ New', lambda s, e: self.run(self.new_definition)), actions),
            self.library_options,
            row(small_button('Select visible', lambda s, e: self.select_visible(True)),
                small_button('Clear filters', lambda s, e: self.clear_filters())),
            self.filter_count)
        self.filter_list = ListBox()
        self.filter_list.SelectionMode = SelectionMode.Extended
        self.filter_list.SelectionChanged += self.filter_focused
        self.filter_list.MouseDoubleClick += lambda s, e: self.select_tab('Edit Rules')
        self.filter_list.ContextMenu = self.filter_menu()
        self.filter_list.PreviewKeyDown += lambda s, e: self.list_key(True, e)
        box = Border()
        box.Padding = Thickness(8)
        box.Margin = Thickness(0, 0, 6, 0)
        box.Background = ui.brush('#FFFFFF')
        box.Child = stacked_grid(header, self.filter_list)
        return box

    def source_menu_selected(self, mode):
        if mode == self.source_mode and mode == 'selected':
            self.run(self.open_source_picker)
        else:
            choose(self.source_combo, mode)

    def filter_menu(self):
        menu = ContextMenu()
        actions = [
            ('Edit Rules', lambda: self.select_tab('Edit Rules')),
            ('Duplicate Filter (focused only)', self.duplicate_definition),
            ('Rename checked filters', lambda: self.select_tab('Rename')),
            ('Analyse Duplicates', self.analyse_duplicates),
            ('Delete checked filters', self.review_delete),
            ('Purge Unused', self.review_purge),
            ('Clear Selected Filters', self.clear_filters),
            ('Select matching elements in Revit', self.matching)]
        for title, action in actions:
            item = MenuItem()
            item.Header = title
            item.Click += lambda s, e, fn=action: self.run(fn)
            menu.Items.Add(item)
        return menu

    def build_targets(self):
        self.target_source = small_button(self.target_mode.title(), None)
        self.target_source.ContextMenu = ContextMenu()
        for key, short, long_name, description in TARGET_MODES:
            item = MenuItem()
            item.Header = ui.panel(text(long_name), text(description, 12, ui.MUTED))
            item.Tag = key
            item.IsCheckable = True
            item.IsChecked = key == self.target_mode
            item.Click += lambda s, e: self.switch_target(s.Tag)
            self.target_source.ContextMenu.Items.Add(item)
        item = MenuItem()
        item.Header = ui.panel(text('Clear Targets'), text('Untick every target, then return to Project Search.', 12, ui.MUTED))
        item.Click += lambda s, e: self.clear_targets()
        self.target_source.ContextMenu.Items.Add(item)
        self.target_source.Click += lambda s, e: self.open_menu(self.target_source)
        self.target_count = text('', 12, ui.MUTED)
        self.target_count.FontSize = 11
        self.target_count.Margin = Thickness(0)
        self.target_restrictions = text('', 12, ui.MUTED)
        self.target_notice = text('', 12, '#865B14')
        self.target_options = Expander()
        self.target_options.Header = 'Search / options'
        self.target_options.IsExpanded = True
        self.target_options.Content = ui.panel(self.search_header(False), self.target_restrictions)
        header = ui.panel(row(text('Targets', 18), self.target_source),
            self.target_options,
            row(small_button('Select visible', lambda s, e: self.select_visible(False)),
                small_button('Clear', lambda s, e: self.clear_targets())),
            self.target_count, self.target_notice)
        self.target_list = ListBox()
        self.target_list.SelectionMode = SelectionMode.Extended
        self.target_list.SelectionChanged += self.target_focused
        self.target_list.PreviewKeyDown += lambda s, e: self.list_key(False, e)
        box = Border()
        box.Margin = Thickness(6, 0, 0, 0)
        box.Padding = Thickness(8)
        box.Background = ui.brush('#FFFFFF')
        box.Child = stacked_grid(header, self.target_list)
        return box

    def build_centre(self):
        self.tabs = TabControl()
        self.tabs.SelectionChanged += self.tab_changed
        self.tab_hosts = {}
        for title in ('Graphics', 'Edit Rules', 'Rename'):
            tab = TabItem()
            tab.Header = title
            host = Grid()
            tab.Content = host
            self.tabs.Items.Add(tab)
            self.tab_hosts[title] = host
        self.management_host = Grid()
        self.management_host.Visibility = Visibility.Collapsed
        result = Grid()
        result.Children.Add(self.tabs)
        result.Children.Add(self.management_host)
        return result

    def build_strip(self):
        self.graphics_check = check('Graphics', self.include_graphics, self.channel_changed)
        self.visibility_check = check('Visibility', self.include_visibility, self.channel_changed)
        self.graphics_check.ToolTip = 'Channels for the next explicit Load from source; existing drafts are unchanged.'
        self.visibility_check.ToolTip = self.graphics_check.ToolTip
        self.source_summary = text('', 12, ui.MUTED)
        self.attachment_summary = text('', 13, '#335D78')
        self.changes = Expander()
        self.changes.Header = 'Changes (optional details and existing-update approvals)'
        self.changes.Expanded += lambda s, e: self.run(self.show_changes)
        self.changes_host = StackPanel()
        details = ui.scroll(self.changes_host)
        details.MaxHeight = 190
        self.changes.Content = details
        strip = ui.panel(self.source_summary, self.attachment_summary, self.changes)
        return strip

    def cancel_read(self):
        self.cancelled = True
        self.status.Text = 'Cancellation requested; loaded drafts and checks are retained.'

    def progress(self, info):
        now = self._read_watch.Elapsed.TotalMilliseconds
        elapsed = max(info.get('elapsed_ms', 0), now)
        if elapsed < 1000 or now - self._last_pump_ms < 50:
            return
        self._last_pump_ms = now
        self.lock_read_controls()
        self.status.Text = '{}: {} / {} · Cancel reading is available'.format(
            info.get('phase', 'Reading'), info.get('done', 0), info.get('total', '?'))
        # API work remains on this thread. Disable all interactive scopes while
        # pumping just enough WPF messages for paint/cancel, never a worker task.
        frame = DispatcherFrame()
        self.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(lambda: self.end_frame(frame)))
        from System.Windows.Threading import Dispatcher
        Dispatcher.PushFrame(frame)

    def end_frame(self, frame):
        frame.Continue = False

    def lock_read_controls(self):
        if not self._read_controls_locked:
            self.columns.IsEnabled = False
            self.global_clear.IsEnabled = False
            self.attachment_strip.IsEnabled = False
            self._read_controls_locked = True

    def read(self, fn):
        if self.busy:
            raise ValueError('Another read is in progress.')
        self.busy, self.cancelled = True, False
        self._read_watch = Stopwatch.StartNew()
        self._last_pump_ms = 0
        self._read_controls_locked = False
        # No message pumping during a short read, so no UI/API re-entry is
        # possible. Disable the large visual tree only before the first pump.
        self.apply_button.IsEnabled = False
        self.apply_close_button.IsEnabled = False
        self.cancel_button.Visibility = Visibility.Visible
        try:
            return fn()
        finally:
            self._read_watch.Stop()
            self.busy = False
            if self._read_controls_locked:
                self.columns.IsEnabled = True
                self.global_clear.IsEnabled = True
                self.attachment_strip.IsEnabled = True
            self.cancel_button.Visibility = Visibility.Hidden
            self.update_summary()

    def catalogue_requested(self):
        if self.catalogue is None:
            result = self.read(lambda: self.graphics.project_targets(
                cancel=lambda: self.cancelled, progress=self.progress))
            if self.cancelled:
                raise ValueError('Project catalogue incomplete; retry Project Search. No targets restored or added.')
            self.catalogue = result
        return self.catalogue

    def current_id(self):
        return model.id_value(self.uidoc.ActiveView.Id) if self.uidoc.ActiveView else None

    def resolve_sources(self):
        previous_candidates = getattr(self, 'source_candidate_ids', self._initial.get('source_candidate_ids'))
        previous_origins = getattr(self, 'origins', self._initial.get('effective_origin_ids'))
        if self.source_mode == 'current':
            origins = [self.current_id()] if self.current_id() is not None else []
        elif self.source_mode == 'browser':
            origins = self.browser_ids
        elif self.source_mode == 'selected':
            origins = self.source_ids
        else:
            origins = []
        valid, unavailable = [], []
        for origin in origins:
            try:
                info = self.graphics.target_info(origin)
                if info.get('supported'):
                    valid.append(origin)
                else:
                    unavailable.append('{} [id {}]: Filters unavailable ({})'.format(
                        info['name'], origin, info['view_type']))
            except ValueError as error:
                unavailable.append(unicode(error))
        # Keep the user's view/template selections, not just their effective
        # templates. Apply must revalidate the original view's assignment.
        self.source_candidate_ids = []
        for identity in valid:
            if identity not in self.source_candidate_ids:
                self.source_candidate_ids.append(identity)
        self.origins = self.graphics.effective_sources(self.source_candidate_ids) if valid else []
        # Browsing is not a proposal. Previously loaded records retain their
        # original assignment/value guards, independent of this new selection.
        self.source_map = self.graphics.source_filters(self.origins) if self.origins else {}
        available = self.source_mode != 'project' and bool(self.origins)
        self.graphics_check.IsEnabled = available
        self.visibility_check.IsEnabled = available
        self.source_label.Text = ('No implicit attachment source.' if self.source_mode == 'project' else
            '{} effective source(s) · no graphics loaded until requested{}'.format(len(self.origins),
                '\nUnavailable: ' + '; '.join(unavailable) if unavailable else ''))
        if self.revealed_filters and self.source_mode != 'project':
            self.source_label.Text += '\n{} explicitly revealed definition(s), separate from attachment origins.'.format(len(self.revealed_filters))
        origin_names = ['{} {} [id {}]'.format('Template' if info['is_template'] else 'View',
                        info['name'], info['id']) for info in
                        [self.graphics.target_info(identity) for identity in self.origins]]
        if origin_names:
            self.source_label.Text += '\nEffective: ' + '; '.join(origin_names[:2])
            if len(origin_names) > 2:
                self.source_label.Text += ' · +{} more'.format(len(origin_names) - 2)
            self.source_label.ToolTip = '\n'.join(origin_names)
        self.source_button.Content = {'current': 'Current View / Template', 'browser': 'Browser View / Template',
                                      'selected': 'Selected Sources', 'project': 'All Project Filters'}[self.source_mode]
        for item in self.source_button.ContextMenu.Items:
            item.IsChecked = item.Tag == self.source_mode
        self.source_summary.Text = '{} · {} effective origins · {} checked filters'.format(
            dict((x[0], x[1]) for x in SOURCE_MODES)[self.source_mode], len(self.origins),
            len(self.filters.checked))

    def resolve_targets(self):
        if self.target_mode == 'project':
            self.target_candidates = self.catalogue_requested()
        else:
            ids = [self.current_id()] if self.target_mode == 'view' else self.browser_ids
            if self.target_mode == 'template':
                current = self.graphics.target_info(self.current_id()) if self.current_id() is not None else None
                template_id = current.get('template_id') if current else None
                ids = [template_id] if template_id and template_id > 0 else []
            self.target_candidates = []
            unavailable = []
            for identity in ids:
                try:
                    self.target_candidates.extend(self.graphics.targets([identity]))
                except ValueError as error:
                    unavailable.append(unicode(error))
            if unavailable:
                self.status.Text = 'Ignored target candidates: ' + '; '.join(unavailable)
        self.target_source.Content = dict((key, short) for key, short, long_name, description in TARGET_MODES)[self.target_mode]
        for item in self.target_source.ContextMenu.Items:
            if item.Tag is not None:
                item.IsChecked = item.Tag == self.target_mode
        types = sorted(set(info['view_type'] for info in self.target_candidates))
        previous = ui.chosen(self.target_type)
        self.loading = True
        self.target_type.Items.Clear()
        for key, caption in [(None, 'All view types')] + [(value, value) for value in types]:
            item = ui.ComboBoxItem()
            item.Tag, item.Content = key, caption
            self.target_type.Items.Add(item)
        if not choose(self.target_type, previous):
            self.target_type.SelectedIndex = 0
        self.loading = False
        self.target_notice.Text = ('Captured Browser selection; not live-synchronised.' if self.target_mode == 'browser' else
                                  'Project names cached.' if self.target_mode == 'project' else '')

    def target_changed(self, sender, event):
        if not self.loading:
            self.switch_target(ui.chosen(sender))

    def switch_target(self, mode):
        if self.busy:
            return
        self.target_mode = mode
        # Empty candidate state on failure, never stale rows posing as Project.
        self.target_candidates = []
        self.target_source.Content = mode.title()
        for item in self.target_source.ContextMenu.Items:
            if item.Tag is not None:
                item.IsChecked = item.Tag == mode
        def action():
            try:
                self.resolve_targets()
            except Exception:
                self.target_notice.Text = 'Project search incomplete; retry Project Search.' if mode == 'project' else 'Candidate load incomplete; retry this target source.'
                raise
            self.refresh_lists()
        self.run(action)
        self.refresh_lists()
        self.render_task()

    def source_changed(self, sender, event):
        if self.loading or self.busy:
            return
        mode = ui.chosen(self.source_combo)
        if mode == self.source_mode:
            return
        if mode == 'selected':
            try:
                self.run(self.open_source_picker)
            finally:
                self.loading = True
                choose(self.source_combo, self.source_mode)
                self.loading = False
            return
        self.set_source(mode)

    def set_source(self, mode, ids=None):
        self.source_mode = mode
        if ids is not None:
            self.source_ids = list(ids)
        self.source_choices.clear()
        self.source_exempt_ids.clear()
        self.resolve_sources()
        self.loading = True
        choose(self.source_combo, mode)
        self.loading = False
        self.management = None
        self.show_normal()
        self.refresh_lists()
        self.render_task()

    def channel_changed(self, sender, event):
        if self.loading or self.busy:
            return
        self.include_graphics = self.graphics_check.IsChecked is True
        self.include_visibility = self.visibility_check.IsChecked is True
        self.render_task()

    def invalidate(self):
        self.plan = None
        if hasattr(self, 'changes_host'):
            self.changes_host.Children.Clear()
        self.update_summary()

    def refresh_lists(self):
        if self.loading or not hasattr(self, 'target_list'):
            return
        self.loading = True
        try:
            query = self.filter_search.Text.lower()
            field_name = ui.chosen(self.filter_field) or 'all'
            category = ui.chosen(self.filter_category)
            records = [r for r in self.service.records if self.source_mode == 'project' or
                       r.id in self.source_map or r.id in self.revealed_filters or
                       (self.filter_selected.IsChecked and r.id in self.filters.checked)]
            self.library_records = records
            visible = [r for r in records if
                       (self.filter_selected.IsChecked and r.id in self.filters.checked) or
                       (not self.filter_selected.IsChecked and
                        (r.id in self.revealed_filters or (query in r.search_fields[field_name] and
                       (not category or category in r.category_names) and
                       (not self.unused.IsChecked or not r.usage))))]
            self.visible_filters = [r.id for r in visible]
            self.filter_list.Items.Clear()
            for record in visible:
                detail = record.usage_text
                if record.id in self.source_map:
                    detail += ' · {} origins · graphics on demand'.format(len(self.source_map[record.id]))
                elif record.id in self.revealed_filters:
                    detail += ' · explicitly revealed · no attachment source'
                self.filter_list.Items.Add(self.selection_row(record.id, record.name, detail, True))
            self.filter_count.Text = '{} checked · {} hidden'.format(
                len(self.filters.checked), self.filters.hidden(self.visible_filters))
            self.filter_restrictions.Text = '{}{}{}'.format(field_name.title(),
                ' · ' + category if category else '', ' · Project-unused' if self.unused.IsChecked else '')
            if self.filter_selected.IsChecked:
                self.filter_restrictions.Text = 'All checked filters · search/source restrictions bypassed'
            target_query = self.target_search.Text.lower()
            kind, view_type = ui.chosen(self.target_kind), ui.chosen(self.target_type)
            candidates = list(self.target_candidates)
            if self.target_selected.IsChecked:
                known = set(i['id'] for i in candidates)
                for tid in sorted(self.targets.checked - known):
                    try:
                        candidates.append(self.graphics.target_info(tid))
                    except ValueError:
                        candidates.append(dict(id=tid, name='Unavailable target', is_template=False,
                                               view_type='Unknown', supported=False, controlled=False))
            targets = [i for i in candidates if
                       (self.target_selected.IsChecked and i['id'] in self.targets.checked) or
                       (not self.target_selected.IsChecked and target_query in i['name'].lower() and
                       (kind == 'both' or i['is_template'] == (kind == 'templates')) and
                       (view_type is None or i['view_type'] == view_type))]
            self.visible_targets = [i['id'] for i in targets]
            self.target_list.Items.Clear()
            for info in targets:
                detail = '{} · {} · id {}'.format('Template' if info['is_template'] else 'View',
                                                   info['view_type'], info['id'])
                if info.get('controlled'):
                    detail += ' · Filters controlled: select template explicitly'
                if not info.get('supported'):
                    detail += ' · Unsupported'
                self.target_list.Items.Add(self.selection_row(info['id'], info['name'], detail, False,
                                                              bool(info.get('supported') and not info.get('controlled'))))
            self.target_count.Text = '{} checked · {} hidden'.format(
                len(self.targets.checked), self.targets.hidden(self.visible_targets))
            self.target_restrictions.Text = '{}{}'.format(
                {'views': 'Views', 'templates': 'Templates', 'both': 'Views + Templates'}.get(kind, ''),
                ' · ' + view_type if view_type else '')
            if self.target_selected.IsChecked:
                self.target_restrictions.Text = 'All checked targets · search/source restrictions bypassed'
        finally:
            self.loading = False
        self.update_summary()

    def selection_row(self, identity, name, detail, source, enabled=True):
        selection = self.filters if source else self.targets
        box = check('', identity in selection.checked)
        box.IsEnabled = enabled
        box.Tag = identity
        named(box, ('Check filter ' if source else 'Check target ') + name)
        box.Checked += lambda s, e: self.selection_changed(source, identity, True)
        box.Unchecked += lambda s, e: self.selection_changed(source, identity, False)
        content = Grid()
        for width in (GridLength.Auto, GridLength(1, GridUnitType.Star)):
            col = ColumnDefinition()
            col.Width = width
            content.ColumnDefinitions.Add(col)
        content.Children.Add(box)
        names = ui.panel(text(name), text(detail, 11, ui.MUTED))
        if not source:
            info = next((i for i in self.target_candidates if i['id'] == identity), None)
            if info and info.get('controlled') and info.get('controlling_template_id'):
                template_id = info['controlling_template_id']
                names.Children.Add(ui.button('Select controlling template', lambda s, e, tid=template_id:
                    self.run(lambda: self.select_template_target(tid))))
        Grid.SetColumn(names, 1)
        content.Children.Add(names)
        item = ListBoxItem()
        item.Tag, item.Content = identity, content
        item.HorizontalContentAlignment = HorizontalAlignment.Stretch
        highlights = self.filter_highlights if source else self.target_highlights
        item.IsSelected = identity in highlights
        return item

    def selection_changed(self, source, identity, value):
        if self.loading or self.busy:
            return
        selection = self.filters if source else self.targets
        visible = self.visible_filters if source else self.visible_targets
        shift = bool(Keyboard.Modifiers & ModifierKeys.Shift)
        highlights = self.filter_highlights if source else self.target_highlights
        if identity in highlights and len(highlights.intersection(visible)) > 1 and not shift:
            for highlighted in highlights.intersection(visible):
                if source or self.target_eligible(highlighted):
                    selection.toggle(highlighted, value, visible)
                    if source and value:
                        self.rename_completed.discard(highlighted)
        else:
            selection.toggle(identity, value, visible, shift)
        if source:
            # A newly checked row is a new rename attempt; tab switches/refresh
            # never resurrect already processed rows.
            if value:
                self.rename_completed.discard(identity)
            self.focus_checked_graphics(identity if value else None)
        self.invalidate()
        self.refresh_lists()
        self.render_task()

    def list_key(self, source, event):
        if event.Key != Key.Space or self.busy:
            return
        control = self.filter_list if source else self.target_list
        selection = self.filters if source else self.targets
        items = list(control.SelectedItems)
        if not items:
            return
        value = not all(item.Tag in selection.checked for item in items)
        for item in items:
            if source or self.target_eligible(item.Tag):
                self.selection_changed(source, item.Tag, value)
        event.Handled = True

    def target_eligible(self, tid):
        info = next((i for i in self.target_candidates if i['id'] == tid), None)
        if info is None and tid in self.targets.checked:
            try:
                info = self.graphics.target_info(tid)
            except ValueError:
                return False
        return bool(info and info.get('supported') and not info.get('controlled'))

    def filter_focused(self, sender, event):
        if self.loading or self.busy:
            return
        self.filter_highlights = set(item.Tag for item in sender.SelectedItems)
        if sender.SelectedItem is None:
            return
        self.filters.focus(event.AddedItems[event.AddedItems.Count - 1].Tag if event.AddedItems.Count else sender.SelectedItem.Tag)
        self.render_task()

    def target_focused(self, sender, event):
        if self.loading or self.busy:
            return
        self.target_highlights = set(item.Tag for item in sender.SelectedItems)
        if sender.SelectedItem is None:
            return
        self.targets.focus(event.AddedItems[event.AddedItems.Count - 1].Tag if event.AddedItems.Count else sender.SelectedItem.Tag)
        if self._task == 'Graphics':
            self.render_task()

    def select_visible(self, source):
        selection = self.filters if source else self.targets
        ids = self.visible_filters if source else [tid for tid in self.visible_targets if self.target_eligible(tid)]
        for identity in ids:
            new_check = identity not in selection.checked
            selection.checked.add(identity)
            if source and new_check:
                self.rename_completed.discard(identity)
        if source:
            self.focus_checked_graphics()
        self.invalidate()
        self.refresh_lists()
        self.render_task()

    def clear_filters(self):
        self.filters.clear()
        self.review_checks.clear()
        self.invalidate()
        self.refresh_lists()
        self.render_task()

    def clear_targets(self):
        self.targets.clear()
        self.invalidate()
        self.switch_target('project')

    def clear_selection(self):
        self.filters.clear()
        self.targets.clear()
        self.review_checks.clear()
        self.picker_checks.clear()
        if self.management == 'Selected source views / templates' and hasattr(self, 'picker_refresh'):
            self.picker_refresh()
        self.plan = None
        if hasattr(self, 'management_checks'):
            for key, box in self.management_checks:
                box.IsChecked = False
        if hasattr(self, 'used_ack'):
            self.used_ack.IsChecked = False
        self.invalidate()
        self.refresh_lists()
        self.render_task()

    def reset_search(self, source):
        self.loading = True
        if source:
            self.filter_search.Text = ''
            choose(self.filter_field, 'all')
            choose(self.filter_category, None)
            self.filter_selected.IsChecked = False
            self.unused.IsChecked = False
        else:
            self.target_search.Text = ''
            choose(self.target_kind, 'both')
            choose(self.target_type, None)
            self.target_selected.IsChecked = False
        self.loading = False
        self.refresh_lists()

    def ordered_checked(self):
        return [r.id for r in self.service.records if r.id in self.filters.checked]

    def focus_checked_graphics(self, preferred=None):
        """A check gesture must leave Per Filter on an editable checked row.

        Checking a CheckBox does not select/focus its ListBoxItem in WPF. An
        earlier inspected (or just unchecked) row must not keep the graphics
        scope empty. Highlight-only inspection remains independent: this runs
        at explicit check/uncheck boundaries, never on a render or mode toggle.
        """
        if self.filters.focused not in self.filters.checked:
            identities = self.ordered_checked()
            if identities:
                self.filters.focus(preferred if preferred in identities else identities[0])

    def focused_record(self):
        return next((r for r in self.service.records if r.id == self.filters.focused), None)

    def displayed_record(self):
        ids = self.ordered_checked()
        focused = self.focused_record()
        return focused if focused else self.service.get_record(ids[0]) if ids else None

    def navigate(self, offset):
        ids = self.ordered_checked()
        record = self.displayed_record()
        if record and record.id in ids:
            index = ids.index(record.id) + offset
            if 0 <= index < len(ids):
                self.filters.focus(ids[index])
                self.refresh_lists()
                self.render_task()
        elif ids and offset > 0:
            self.filters.focus(ids[0])
            self.refresh_lists()
            self.render_task()

    def navigator(self):
        ids = self.ordered_checked()
        record = self.displayed_record()
        index = ids.index(record.id) if record and record.id in ids else -1
        previous = small_button('Previous', lambda s, e: self.navigate(-1))
        following = small_button('Next', lambda s, e: self.navigate(1))
        previous.IsEnabled = index > 0
        following.IsEnabled = bool(ids) and index < len(ids) - 1
        self.previous_button, self.next_button = previous, following
        caption = '{} of {} · {}'.format(index + 1, len(ids), record.name) if index >= 0 else (
            'Inspection (not checked) · ' + record.name if record else 'Focus a filter to inspect')
        self.navigator_text = text(caption, 14)
        self.navigator_text.TextWrapping = TextWrapping.NoWrap
        self.navigator_text.TextTrimming = TextTrimming.CharacterEllipsis
        self.navigator_text.ToolTip = caption
        navigator = Grid()
        for width in (GridLength.Auto, GridLength(1, GridUnitType.Star), GridLength.Auto):
            column = ColumnDefinition()
            column.Width = width
            navigator.ColumnDefinitions.Add(column)
        for index, control in enumerate((previous, self.navigator_text, following)):
            Grid.SetColumn(control, index)
            navigator.Children.Add(control)
        return navigator

    def select_tab(self, title):
        self.show_normal()
        for tab in self.tabs.Items:
            if tab.Header == title:
                self._task = title
                self.tabs.SelectedItem = tab
                break
        self.render_task()

    def tab_changed(self, sender, event):
        if self.loading or event.Source != self.tabs:
            return
        if self.tabs.SelectedItem:
            self._task = unicode(self.tabs.SelectedItem.Header)
            self.render_task()

    def render_task(self):
        if self.loading or self.busy or not hasattr(self, 'tabs'):
            return
        if self.management:
            return
        if self._task == 'Graphics':
            self.run(self.render_graphics)
        elif self._task == 'Edit Rules':
            self.run(self.render_rules)
        else:
            self.run(self.render_rename)

    def show_normal(self):
        self.management = None
        self.tabs.Visibility = Visibility.Visible
        self.management_host.Visibility = Visibility.Collapsed
        self.render_task()

    def show_management(self, title, contents, footer=None):
        self.management = title
        self.tabs.Visibility = Visibility.Collapsed
        self.management_host.Visibility = Visibility.Visible
        head = row(ui.button('Back to workspace', lambda s, e: self.show_normal()), text(title, 18))
        slot(self.management_host, stacked_grid(head, ui.scroll(contents), footer))

    def graphics_scope(self):
        if self.together:
            return self.ordered_checked()
        record = self.displayed_record()
        return [record.id] if record and record.id in self.filters.checked else []

    def graphics_pair_scope(self):
        return [(tid, fid) for fid in self.graphics_scope() for tid in sorted(self.targets.checked)]

    def active_pair_scope(self):
        return [(tid, fid) for fid in self.ordered_checked() for tid in sorted(self.targets.checked)]

    def sync_graphics_dirty(self):
        self.graphics_dirty = bool(self.dirty_graphics_ids or self.dirty_graphics_pairs or
                                   self.unassigned_graphics)

    def source_values(self, pair):
        """Presentation projection of guarded, field-disjoint contributions."""
        values = {}
        for record in self.pair_sources.get(pair, []):
            values.update(record['values'])
        return values

    def remove_source_fields(self, pair, fields):
        for record in self.pair_sources.get(pair, []):
            for field in fields:
                record['values'].pop(field, None)
        if pair in self.pair_sources:
            self.pair_sources[pair] = [record for record in self.pair_sources[pair] if record['values']]

    def prune_source_drafts(self):
        # Include inactive pairs: unchecked drafts and ReValue continuation
        # still own their tokens. Pending unpublished mints own none.
        tokens = set(record['token'] for records in self.pair_sources.values()
                     for record in records if record['values'])
        self.graphics.prune_source_drafts(tokens)

    def assign_legacy_graphics(self):
        pairs = self.active_pair_scope()
        if not pairs:
            raise ValueError('Check filters and destinations before explicitly assigning retained legacy drafts.')
        for pair in pairs:
            draft = self.unassigned_graphics.get(pair[1])
            if draft:
                self.pair_patches[pair] = self.graphics.patch_draft(
                    self.pair_patches.get(pair, {}), draft['patch'])
                self.pair_graphic_inputs.setdefault(pair, {}).update(draft['inputs'])
                self.pair_graphic_errors.setdefault(pair, {}).update(draft['errors'])
                self.dirty_graphics_pairs.add(pair)
        for fid in self.ordered_checked():
            self.unassigned_graphics.pop(fid, None)
        self.sync_graphics_dirty()
        self.invalidate()
        self.render_graphics()

    def discard_legacy_graphics(self):
        self.unassigned_graphics.clear()
        self.sync_graphics_dirty()
        self.render_graphics()

    def render_graphics(self):
        host = self.tab_hosts['Graphics']
        record = self.displayed_record()
        pairs = self.graphics_pair_scope()
        navigation = (tuple(pairs), self.together)
        same_navigation = getattr(self, '_graphics_navigation', None) == navigation
        previous_scroll = getattr(self, 'graphics_scroll', None)
        offset = previous_scroll.VerticalOffset if same_navigation and previous_scroll is not None else 0
        if not same_navigation or any(pair not in self.pair_before for pair in pairs):
            self.populate_target_values(pairs)
        self._graphics_editable = self.graphics_pairs_writable(pairs)
        top = ui.panel(self.navigator())
        self.previous_button.Content, self.next_button.Content = u'\u2039', u'\u203a'
        self.previous_button.ToolTip, self.next_button.ToolTip = 'Previous checked filter', 'Next checked filter'
        self.graphics_previous, self.graphics_next = self.previous_button, self.next_button
        self.graphics_navigator = self.navigator_text
        mode = ui.combo([('single', 'Per Filter'), ('together', 'Together ({})'.format(len(self.filters.checked)))],
                        'together' if self.together else 'single')
        mode.MinHeight, mode.Height = 28, 28
        mode.SelectionChanged += lambda s, e: self.change_graphics_mode(ui.chosen(mode) == 'together')
        self.graphics_mode = mode
        self.graphics_scope_hint = text('TARGET values · {} filter(s) × {} target(s) · {} pair(s)'.format(
            len(self.graphics_scope()), len(self.targets.checked), len(pairs)), 12, ui.MUTED)
        top.Children.Add(mode)
        top.Children.Add(self.graphics_scope_hint)
        contents = StackPanel()
        self.field_controls, self.field_cells, self.clear_controls = {}, {}, {}
        self.display_values = {}
        top_cells = row(text('Visible', 12), self.graphics_field(self.field_descriptor('visibility')),
                        text('Halftone', 12), self.graphics_field(self.field_descriptor('halftone')),
                        text('Transparency %', 12), self.graphics_field(self.field_descriptor('transparency')))
        self.field_cells['transparency'].Width = 62
        contents.Children.Add(top_cells)
        grid = Grid()
        self.graphics_grid = grid
        grid.MinWidth = 550
        for width in (GridLength(168), GridLength(64), GridLength(88),
                      GridLength(1, GridUnitType.Star), GridLength(68)):
            column = ColumnDefinition()
            column.Width = width
            grid.ColumnDefinitions.Add(column)
        rows = [
            ('Projection lines', 'projection_line_weight', 'projection_line_color', 'projection_line_pattern_id', None),
            ('Surface foreground', None, 'surface_foreground_pattern_color', 'surface_foreground_pattern_id', 'surface_foreground_pattern_visible'),
            ('Surface background', None, 'surface_background_pattern_color', 'surface_background_pattern_id', 'surface_background_pattern_visible'),
            ('Cut lines', 'cut_line_weight', 'cut_line_color', 'cut_line_pattern_id', None),
            ('Cut foreground', None, 'cut_foreground_pattern_color', 'cut_foreground_pattern_id', 'cut_foreground_pattern_visible'),
            ('Cut background', None, 'cut_background_pattern_color', 'cut_background_pattern_id', 'cut_background_pattern_visible')]
        for index, values in enumerate([('Label', 'Weight', 'Colour', 'Pattern', 'Visible')] + rows):
            definition = RowDefinition()
            definition.Height = GridLength(36)
            grid.RowDefinitions.Add(definition)
            for column, value in enumerate(values):
                if index == 0 or column == 0:
                    control = text(value or '', 12, ui.MUTED if index == 0 else ui.INK)
                    control.Margin = Thickness(6, 0, 2, 0)
                    control.VerticalAlignment = VerticalAlignment.Center
                    control.TextWrapping = TextWrapping.NoWrap
                elif value:
                    control = self.graphics_field(self.field_descriptor(value))
                else:
                    control = text(u'\u2014', 12, ui.MUTED)
                Grid.SetRow(control, index)
                Grid.SetColumn(control, column)
                grid.Children.Add(control)
        contents.Children.Add(grid)
        enabled = self.aggregate_value('enabled', proposed=False)
        self.graphics_enabled = text('Enabled (read-only): {} · new attachments On; existing preserved'.format(
            self.value_caption(self.field_descriptor('enabled'), enabled)), 12, ui.MUTED)
        contents.Children.Add(self.graphics_enabled)
        load_name = ('choose variant' if len(self.origins) > 1 else
                     self.graphics.target_info(self.origins[0])['name'] if self.origins else 'unavailable')
        self.load_source_button = small_button('Load from source: ' + load_name,
                                              lambda s, e: self.run(self.load_from_source))
        self.load_source_button.ToolTip = 'Load exact selected channels, including Unset, into only the currently checked pairs.'
        self.load_source_button.IsEnabled = bool(pairs and self.origins and self.source_mode != 'project' and
                                                (self.include_graphics or self.include_visibility) and
                                                self._graphics_editable)
        # The checkboxes are existing controller objects; move them, do not
        # reinitialize them (which could manufacture a source request).
        for control in (self.graphics_check, self.visibility_check):
            if control.Parent is not None:
                control.Parent.Children.Remove(control)
        contents.Children.Add(row(self.load_source_button, self.graphics_check, self.visibility_check))
        loaded_count = sum(bool(self.source_values(pair)) for pair in pairs)
        self.graphics_context = text('{} loaded source pair(s) · blue edited / amber removal · right-click to revert'.format(
            loaded_count), 12, ui.MUTED)
        if self.graphics_read_errors:
            self.graphics_context.Text = 'Target read failed/incomplete; edits disabled. ' + '; '.join(
                self.graphics_read_errors.values())
            contents.Children.Add(small_button('Retry target read', lambda s, e: self.run(self.inspect_graphics)))
        elif not pairs:
            self.graphics_context.Text = 'Check filters and targets to load current TARGET values. No future broadcast.'
        contents.Children.Add(self.graphics_context)
        self.variant_host = StackPanel()
        contents.Children.Add(self.variant_host)
        if self.unassigned_graphics:
            contents.Children.Add(ui.panel(text(
                '{} retained unassigned draft(s)'.format(len(self.unassigned_graphics)), 12, '#865B14'),
                row(ui.button('Assign to currently checked pairs', lambda s, e: self.run(self.assign_legacy_graphics)),
                    ui.button('Discard unassigned drafts', lambda s, e: self.discard_legacy_graphics()))))
        self.graphics_rule_summary = text(record.rules if record else '', 12, ui.MUTED)
        self.graphics_usage_summary = text(record.usage_text if record else '', 12, ui.MUTED)
        if previous_scroll is not None:
            self.graphics_scroll = previous_scroll
            self.graphics_scroll.Content = contents
            self.graphics_root.Children.Remove(self.graphics_header)
            ui.add_row(self.graphics_root, top, 0)
            self.graphics_scroll.ScrollToVerticalOffset(offset)
        else:
            self.graphics_scroll = ui.scroll(contents)
            self.graphics_scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
            self.graphics_root = stacked_grid(top, self.graphics_scroll)
            slot(host, self.graphics_root)
        self.graphics_header = top
        self._graphics_navigation = navigation

    def field_descriptor(self, key):
        return next(field for field in self.graphics.FIELDS if field['key'] == key)

    def populate_target_values(self, pairs):
        """Active Graphics pairs only, synchronous API slices, no proposals."""
        self.graphics_read_errors = {}
        if not pairs:
            return
        data = self.read(lambda: self.graphics.read_batch(pairs, max_pairs=5, max_ms=100,
            refresh=True, cancel=lambda: self.cancelled, progress=self.progress))
        if data['cancelled'] or data['remaining'] or data['errors']:
            self.graphics_read_errors = dict((pair, unicode(error)) for pair, error in data['errors'].items())
            if data['cancelled'] or data['remaining']:
                self.graphics_read_errors[('read',)] = 'Cancelled/incomplete target read; retry Graphics.'
            return
        for pair in pairs:
            # Never mutate or replace an original after edits or an explicit
            # source load. A fresh untouched navigation gets fresh model data.
            if pair not in self.pair_before or not (
                    self.pair_patches.get(pair) or self.source_values(pair) or
                    self.pair_graphic_inputs.get(pair)):
                self.pair_before[pair] = deepcopy(data['snapshots'][pair])
            values = self.graphics.grid_values(self.pair_before[pair])
            if not self.pair_before[pair]['attached']:
                self.pair_defaults[pair] = dict(values)

    def graphics_pairs_writable(self, pairs):
        if not pairs or self.graphics_read_errors or self.service.doc.IsReadOnly:
            return False
        if any(pair not in self.pair_before for pair in pairs):
            return False
        for tid in set(pair[0] for pair in pairs):
            try:
                info = self.graphics.target_info(tid)
            except ValueError:
                return False
            if not info.get('supported') or info.get('controlled'):
                return False
        return True

    def original_value(self, pair, key):
        snapshot = self.pair_before.get(pair)
        if snapshot is None:
            return ('unread',)
        if snapshot['attached']:
            return snapshot['values'].get(key, ('unread',))
        # Missing is not an observed override. The backend derives real native
        # defaults once per pair; presentation never guesses or plans them.
        return self.pair_defaults.get(pair, {}).get(key, ('unread',))

    def proposed_value(self, pair, key):
        operation = self.pair_patches.get(pair, {}).get(key)
        if operation is not None:
            return operation['value']
        source = self.source_values(pair)
        return source[key] if key in source else self.original_value(pair, key)

    def aggregate_value(self, key, proposed=True):
        pairs = self.graphics_pair_scope()
        values = [(self.proposed_value(pair, key) if proposed else self.original_value(pair, key)) for pair in pairs]
        if not values:
            return ('unread',)
        return values[0] if all(value == values[0] for value in values) else ('mixed',)

    def value_caption(self, descriptor, value):
        if value == ('mixed',):
            return 'Mixed'
        if value == ('unread',):
            return u'\u2014'
        if descriptor['kind'] == 'resource' and value not in (None, -1):
            identity = (descriptor['resource_kind'], value)
            if identity not in self.resource_names:
                # Resolve only the already loaded cells' unique pattern IDs.
                # No project resource catalogue until the compact picker opens.
                if identity[0] == 'line' and value == model.id_value(DB.LinePatternElement.GetSolidPatternId()):
                    caption = 'Solid'
                else:
                    element = self.service.doc.GetElement(model.element_id(value))
                    caption = model.name_of(element) if element is not None else 'Missing pattern [id {}]'.format(value)
                self.resource_names[identity] = caption
            return self.resource_names[identity]
        return display_value(descriptor, value)

    def change_graphics_mode(self, together):
        self.together = together
        # No patching, approvals, or planning on a mode toggle.
        self.render_graphics()

    def patch_display(self, key):
        pairs = self.graphics_pair_scope()
        value = self.aggregate_value(key)
        touched = any(key in self.pair_patches.get(pair, {}) or
                      key in self.source_values(pair) for pair in pairs)
        entry = {'op': 'set', 'value': value} if touched else None
        return entry, self.value_caption(self.field_descriptor(key), value)

    def graphics_field(self, descriptor):
        key, kind = descriptor['key'], descriptor['kind']
        entry, caption = self.patch_display(key)
        pairs = list(self.graphics_pair_scope())
        value = self.aggregate_value(key)
        state = text(caption, 12, '#335D78')
        state.Visibility = Visibility.Collapsed  # automation/test value, not a paragraph
        if value not in (('mixed',), ('unread',)):
            self.display_values[key] = value
        controls = Grid()
        for width in (GridLength(1, GridUnitType.Star), GridLength.Auto):
            column = ColumnDefinition()
            column.Width = width
            controls.ColumnDefinitions.Add(column)
        if kind in ('bool', 'boolean'):
            value_control = CheckBox()
            value_control.IsThreeState = value == ('mixed',)
            value_control.IsChecked = value if isinstance(value, bool) else None
            value_control.HorizontalAlignment = HorizontalAlignment.Center
            # Attach after populating. Ordinary booleans use the direct
            # Checked/Unchecked path; Mixed is the only tri-state value.
            value_control.Checked += lambda s, e: self.field_boolean(key, s, pairs)
            value_control.Unchecked += lambda s, e: self.field_boolean(key, s, pairs)
            value_control.Indeterminate += lambda s, e: self.indeterminate_edited(key, pairs)
        elif kind == 'color':
            value_control = ui.button(caption, lambda s, e: self.run(lambda: self.pick_colour(key)))
            if value is not None and value not in (('mixed',), ('unread',)):
                value_control.Background = ui.brush('#{:02X}{:02X}{:02X}'.format(*value))
                value_control.Content = ''
            else:
                value_control.ClearValue(Button.BackgroundProperty)
        elif descriptor.get('resource_kind'):
            resource_text = text(caption, 12)
            resource_text.Margin = Thickness(0)
            resource_text.TextWrapping = TextWrapping.NoWrap
            resource_text.TextTrimming = TextTrimming.CharacterEllipsis
            resource_text.MaxWidth = 210
            value_control = ui.button(resource_text, lambda s, e: self.run(lambda: self.choose_resource(descriptor)))
            value_control.MaxWidth = 220
            value_control.HorizontalContentAlignment = HorizontalAlignment.Left
        else:
            raw_values = [self.pair_graphic_inputs.get(pair, {}).get(key) for pair in pairs]
            raw = raw_values[0] if raw_values and all(v == raw_values[0] for v in raw_values) else None
            value_control = ui.field(raw if raw is not None else
                                     value if value not in (('mixed',), ('unread',), None, -1) else '')
            value_control.TextChanged += lambda s, e, scope=list(pairs): self.numeric_edited(
                key, s.Text, scope, state)
            if any(key in self.pair_graphic_errors.get(pair, {}) for pair in pairs):
                state.Text = 'Needs correction: ' + next(self.pair_graphic_errors[pair][key] for pair in pairs
                                                        if key in self.pair_graphic_errors.get(pair, {}))
        value_control.FontSize = 12
        value_control.MinHeight, value_control.Height = 26, 26
        value_control.Margin = Thickness(2)
        if isinstance(value_control, Button):
            value_control.Padding = Thickness(3, 0, 3, 0)
        original = self.value_caption(descriptor, self.aggregate_value(key, proposed=False))
        tooltip = '{}: {} · Original TARGET: {}'.format(descriptor['label'], caption, original)
        if any(not self.pair_before.get(pair, {}).get('attached') for pair in pairs):
            tooltip += ' · Not attached: new-attachment default'
        if entry:
            tooltip += ' · Proposed on Apply'
        named(value_control, tooltip)
        value_control.Tag = key
        controls.Children.Add(value_control)
        if descriptor.get('can_clear'):
            clear = ui.button(u'\u00d7', lambda s, e: self.run(lambda: self.patch_field(key, {'op': 'clear'}, pairs)))
            clear.MinHeight, clear.Height, clear.Width = 24, 24, 18
            clear.Padding, clear.Margin = Thickness(0), Thickness(1)
            clear.FontSize = 14
            named(clear, 'Remove override on Apply: ' + descriptor['label'])
            Grid.SetColumn(clear, 1)
            controls.Children.Add(clear)
            self.clear_controls[key] = clear
        controls.IsEnabled = self._graphics_editable
        menu = ContextMenu()
        revert = MenuItem()
        revert.Header = 'Revert this edit'
        revert.IsEnabled = bool(entry or any(key in self.pair_graphic_inputs.get(pair, {}) for pair in pairs))
        revert.Click += lambda s, e: self.run(lambda: self.revert_field(key, pairs))
        menu.Items.Add(revert)
        controls.ContextMenu = menu
        value_control.ContextMenu = menu
        cell = Border()
        cell.Margin = Thickness(0)
        cell.Padding = Thickness(1)
        cell.BorderBrush, cell.BorderThickness = ui.brush('#D9DEE5'), Thickness(0, 0, 0, 1)
        is_clear = entry and descriptor.get('can_clear') and value in (None, -1)
        cell.Background = ui.brush('#FFF3DB' if is_clear else '#EAF3FF' if entry else '#FFFFFF')
        cell.Child = controls
        if kind == 'bool':
            cell.Width = 38
        self.field_controls[key] = (state, value_control)
        self.field_cells[key] = cell
        return cell

    def indeterminate_edited(self, key, pairs):
        # WPF cycles True -> None in tri-state mode. For a single/common
        # value that user gesture means explicit Off, not an invented Unset.
        # Otherwise True could never be unchecked. Initial Mixed population
        # happens before handlers are attached and never creates a patch.
        if set(pairs) != set(self.graphics_pair_scope()):
            return
        value = self.aggregate_value(key)
        if isinstance(value, bool):
            self.run(lambda: self.patch_field(key, {'op': 'set', 'value': False}, pairs))

    def field_boolean(self, key, control, pairs=None):
        if pairs is not None and set(pairs) != set(self.graphics_pair_scope()):
            return
        value = control.IsChecked
        if value is not None:
            self.run(lambda: self.patch_field(key, {'op': 'set', 'value': bool(value)}, pairs))

    def set_numeric(self, key, value):
        self.patch_field(key, {'op': 'set', 'value': int(value)})

    def numeric_edited(self, key, value, pairs, status):
        """Keystrokes create a draft, never writes; invalid raw text is retained."""
        if not pairs:
            return
        # Ignore a stale detached editor event after a selection change.
        if set(pairs) != set(self.graphics_pair_scope()) or not self.graphics_pairs_writable(pairs):
            return
        for pair in pairs:
            self.pair_graphic_inputs.setdefault(pair, {})[key] = value
        try:
            operation = {'op': 'set', 'value': int(value)}
            normalized = self.graphics.validate_patch({key: operation})
        except (ValueError, TypeError, OverflowError) as error:
            for pair in pairs:
                self.pair_graphic_errors.setdefault(pair, {})[key] = unicode(error)
            status.Text = 'Needs correction: ' + unicode(error)
            self.field_controls[key][1].ToolTip = status.Text
            self.field_cells[key].Background = ui.brush('#FFF3DB')
        else:
            for pair in pairs:
                self.pair_patches[pair] = self.graphics.patch_draft(self.pair_patches.get(pair, {}), normalized)
                self.pair_graphic_errors.setdefault(pair, {}).pop(key, None)
            status.Text = value
            self.field_controls[key][1].ToolTip = 'Proposed {}: {}'.format(key, value)
            self.field_cells[key].Background = ui.brush('#EAF3FF')
        self.dirty_graphics_pairs.update(pairs)
        self.sync_graphics_dirty()
        self.invalidate()

    def patch_field(self, key, operation, scope=None):
        pairs = list(self.graphics_pair_scope()) if scope is None else list(scope)
        if not pairs:
            raise ValueError('Check filters and destinations before custom editing.')
        if set(pairs) != set(self.graphics_pair_scope()):
            raise ValueError('Checked pair scope changed; no draft was changed.')
        if not self.graphics_read_errors and any(pair not in self.pair_before for pair in pairs):
            self.populate_target_values(pairs)
        if not self.graphics_pairs_writable(pairs):
            raise ValueError('Target read incomplete/failed. Retry Graphics before editing.')
        # Snapshot scope NOW; new checks never replay a Together patch.
        for pair in pairs:
            self.pair_patches[pair] = self.graphics.patch_draft(self.pair_patches.get(pair, {}), {key: operation})
            if operation['op'] == 'keep':
                # Revert is stronger than an old "Keep custom" operation:
                # remove source contribution as well, never reintroduce it.
                self.remove_source_fields(pair, [key])
            self.pair_graphic_inputs.setdefault(pair, {}).pop(key, None)
            self.pair_graphic_errors.setdefault(pair, {}).pop(key, None)
            if self.pair_patches[pair] or self.pair_graphic_inputs.get(pair) or self.source_values(pair):
                self.dirty_graphics_pairs.add(pair)
            else:
                self.dirty_graphics_pairs.discard(pair)
        self.sync_graphics_dirty()
        if operation['op'] == 'keep':
            self.prune_source_drafts()
        self.invalidate()
        self.render_graphics()

    def revert_field(self, key, scope=None):
        self.patch_field(key, {'op': 'keep'}, scope)

    def pick_colour(self, key):
        pairs = list(self.graphics_pair_scope())
        if not pairs:
            raise ValueError('Check filters and destinations before choosing a colour.')
        entry, caption = self.patch_display(key)
        initial = self.aggregate_value(key)
        dialog = UI.ColorSelectionDialog()
        try:
            if initial is not None and initial not in (('mixed',), ('unread',)):
                rgb = initial
                dialog.OriginalColor = DB.Color(Byte(rgb[0]), Byte(rgb[1]), Byte(rgb[2]))
            # API has no Owner overload in 2023. Activate this modal host
            # before Show; ownership/focus return needs an attended host check.
            self.Activate()
            if dialog.Show() != UI.ItemSelectionDialogResult.Confirmed:
                return
            color = dialog.SelectedColor
            if not color.IsValid:
                raise ValueError('The colour picker did not return a valid colour.')
            operation = {'op': 'set', 'value': (int(color.Red), int(color.Green), int(color.Blue))}
            self.patch_field(key, operation, pairs)
        finally:
            dialog.Dispose()
            self.Activate()

    def choose_resource(self, descriptor):
        pairs = list(self.graphics_pair_scope())
        if not pairs:
            raise ValueError('Check filters and destinations before choosing a resource.')
        resources = self.read(lambda: self.graphics.resources(descriptor['resource_kind'],
            cancel=lambda: self.cancelled, progress=self.progress))
        if self.cancelled:
            raise ValueError('Resource read cancelled; no draft changed.')
        for resource in resources:
            self.resource_names[(descriptor['resource_kind'], resource['id'])] = resource['name']
        query = named(ui.field(), 'Search ' + descriptor['label'])
        listing = StackPanel()
        def refresh(sender=None, event=None):
            listing.Children.Clear()
            for resource in resources:
                if query.Text.lower() in resource['name'].lower():
                    listing.Children.Add(ui.button(resource['name'], lambda s, e, value=resource['id']:
                        self.run(lambda: self.resource_selected(descriptor['key'], value, pairs))))
        refresh()
        self.show_management('Choose ' + descriptor['label'], ui.panel(query, listing),
                             row(ui.button('Cancel', lambda s, e: self.show_normal())))
        query.TextChanged += refresh

    def resource_selected(self, key, value, scope=None):
        if scope is not None and set(scope) != set(self.graphics_pair_scope()):
            raise ValueError('Checked filters or destinations changed while choosing a resource. '
                             'Reopen the resource chooser for the current pairs; no draft was changed.')
        self.patch_field(key, {'op': 'set', 'value': value}, scope)
        self.show_normal()

    def inspect_graphics(self):
        self.populate_target_values(self.graphics_pair_scope())
        self.render_graphics()

    def load_variants(self):
        """Per-filter choices for the NEXT load; never populate target cells."""
        scope = self.graphics_scope()
        if not scope or self.source_mode == 'project':
            raise ValueError('Check filters with valid sources before loading.')
        if not (self.include_graphics or self.include_visibility):
            raise ValueError('Choose a source channel first.')
        options = []
        for fid in scope:
            origins = self.source_map.get(fid, [])
            if not origins:
                raise ValueError('Filter {} has no attachment in the selected sources. No draft changed.'.format(fid))
            data = self.read(lambda: self.graphics.source_variants(fid, origins,
                include_graphics=self.include_graphics, include_visibility=self.include_visibility,
                cancel=lambda: self.cancelled, progress=self.progress, source_mode='exact'))
            if not data.get('complete') or not data.get('groups'):
                raise ValueError('Source read failed/incomplete. No draft changed.')
            options.append((fid, data['groups']))
        self.variant_host.Children.Clear()
        self.variant_host.Children.Add(text('Choose a variant for each differing filter, then Load. Existing draft unchanged.', 12))
        for fid, groups in options:
            self.variant_host.Children.Add(text(self.service.get_record(fid).name, 13))
            if len(groups) == 1:
                self.variant_host.Children.Add(text('One common variant; no choice required.', 12, ui.MUTED))
                continue
            for group in groups:
                # An explicit button, never the first source by default.
                oid = group['origin_ids'][0]
                caption = ' / '.join(self.graphics.target_info(identity)['name'] for identity in group['origin_ids'])
                button = small_button(caption, lambda s, e, filter_id=fid, origin_id=oid:
                                      self.choose_source(filter_id, origin_id))
                button.Tag = (fid, oid)
                button.Background = ui.brush('#EAF3FF' if self.source_choices.get(fid) in group['origin_ids'] else '#FFFFFF')
                button.ToolTip = '\n'.join('{}: {}'.format(self.field_descriptor(key)['label'],
                    self.value_caption(self.field_descriptor(key), value)) for key, value in group['values'].items())
                self.variant_host.Children.Add(button)
        self.variant_host.Children.Add(row(
            small_button('Load chosen variants', lambda s, e: self.run(self.load_from_source)),
            small_button('Cancel', lambda s, e: self.variant_host.Children.Clear())))

    def choose_source(self, fid, oid):
        self.source_choices[fid] = oid
        for control in self.variant_host.Children:
            if isinstance(control, Button) and isinstance(control.Tag, tuple) and control.Tag[0] == fid:
                control.Background = ui.brush('#EAF3FF' if control.Tag[1] == oid else '#FFFFFF')
        self.status.Text = 'Variant chosen for filter {}; click Load to change the draft.'.format(fid)

    def load_from_source(self, replace=False):
        try:
            return self._load_from_source(replace)
        finally:
            # A Together batch can mint one filter then fail/cancel on another.
            # Publish atomically below; registry ownership follows only the
            # successfully published pair contributions, including inactive.
            self.prune_source_drafts()

    def _load_from_source(self, replace=False):
        """Mint guarded backend records, then publish the exact scoped load."""
        pairs = list(self.graphics_pair_scope())
        if self.source_mode == 'project' or not self.origins:
            raise ValueError('All Project/unavailable sources cannot load attachment values.')
        if not self.graphics_pairs_writable(pairs):
            raise ValueError('Check filters/targets and complete the target read before loading.')
        if not (self.include_graphics or self.include_visibility):
            raise ValueError('Choose a channel for the next load.')
        channels = [f['key'] for f in self.graphics.FIELDS if f['editable'] and
                    (self.include_visibility if f['key'] == 'visibility' else self.include_graphics)]
        if not replace and any(key in self.pair_patches.get(pair, {}) or
                               key in self.pair_graphic_inputs.get(pair, {}) or
                               key in self.source_values(pair)
                               for pair in pairs for key in channels):
            self.show_management('Replace graphics draft',
                text('Load replaces the selected channels for the currently checked pairs, including Unset. Other pairs and channels remain unchanged.'),
                row(ui.button('Replace and load', lambda s, e: self.run(lambda: self.load_from_source(True))),
                    ui.button('Cancel', lambda s, e: self.show_normal())))
            return False
        pending = {}
        def mint():
            for fid in self.graphics_scope():
                origins = self.source_map.get(fid, [])
                if not origins:
                    raise ValueError('Filter {} is missing in the selected sources. No draft changed.'.format(fid))
                # Preserve the complete selected source/candidate boundary.
                # Membership above is only a presence check: this filter may
                # exist in a subset of the union, but all selected candidates
                # must still match the backend's effective-origin guards.
                pending[fid] = self.graphics.load_source_draft(fid, list(self.origins),
                    source_candidate_ids=list(self.source_candidate_ids),
                    source_choice=self.source_choices.get(fid),
                    include_graphics=self.include_graphics, include_visibility=self.include_visibility,
                    cancel=lambda: self.cancelled, progress=self.progress)
                if self.cancelled or not pending[fid].get('token') or set(pending[fid]['values']) != set(channels):
                    raise ValueError('Source read failed/incomplete/cancelled; no draft changed.')
        try:
            self.read(mint)
        except ValueError as error:
            if 'variant' in unicode(error).lower() and 'cho' in unicode(error).lower():
                self.show_normal()
                self.load_variants()
                self.status.Text = 'Choose source variants; no draft has changed.'
                return False
            raise
        for pair in pairs:
            # Replace only the loaded fields. Unrelated earlier channels keep
            # their own immutable source token and stale-value guards.
            self.remove_source_fields(pair, channels)
            self.pair_sources.setdefault(pair, []).append(deepcopy(pending[pair[1]]))
            for key in channels:
                self.pair_patches.setdefault(pair, {}).pop(key, None)
                self.pair_graphic_inputs.setdefault(pair, {}).pop(key, None)
                self.pair_graphic_errors.setdefault(pair, {}).pop(key, None)
            self.dirty_graphics_pairs.add(pair)
        self.invalidate()
        self.sync_graphics_dirty()
        self.show_normal()
        self.render_graphics()
        self.status.Text = 'Loaded exact source channels into {} pair(s). Review existing updates before Apply.'.format(len(pairs))
        return True

    def request(self):
        return {'filter_ids': self.ordered_checked(), 'target_ids': sorted(self.targets.checked),
                'origin_ids': [], 'source_candidate_ids': [],
                'include_graphics': False, 'include_visibility': False,
                'source_choices': {}, 'source_mode': 'exact', 'source_exempt_ids': [],
                'patches': {},
                'pair_sources': dict((pair, [{'token': record['token'], 'fields': list(record['values'])}
                                            for record in self.pair_sources[pair] if record['values']])
                    for pair in self.active_pair_scope() if self.source_values(pair)),
                'pair_patches': dict((pair, independent_patch(self.pair_patches[pair]))
                    for pair in self.active_pair_scope() if self.pair_patches.get(pair))}

    def build_plan(self):
        if not self.filters.checked or not self.targets.checked:
            raise ValueError('Check filters and explicit destinations first.')
        invalid = [(pair, key, reason) for pair in self.active_pair_scope()
                   for key, reason in self.pair_graphic_errors.get(pair, {}).items()]
        if invalid:
            raise ValueError('Correct active graphic drafts before planning: ' + '; '.join(
                'target {} / filter {} / {}: {}'.format(pair[0], pair[1], key, reason)
                for pair, key, reason in invalid))
        self.plan = self.read(lambda: self.graphics.plan(self.request(), completed=self.receipts,
            cancel=lambda: self.cancelled, progress=self.progress))
        self.approve_current_view_updates()
        for fid in self.ordered_checked():
            pending = any(r['key'][1] == fid and r['action'] in ('Add', 'Update', 'Blocked', 'Invalid')
                          and not r.get('excluded') for r in self.plan['rows'])
            if not pending:
                self.dirty_graphics_ids.discard(fid)
        for pair in self.active_pair_scope():
            pending = any(tuple(r['key']) == pair and r['action'] in ('Add', 'Update', 'Blocked', 'Invalid')
                          and not r.get('excluded') for r in self.plan['rows'])
            if not pending and not self.pair_graphic_errors.get(pair):
                self.dirty_graphics_pairs.discard(pair)
        self.sync_graphics_dirty()
        self.update_summary()
        return self.plan

    def approve_current_view_updates(self):
        """Auto-approve only an operation scoped entirely to the active view."""
        current_view = self.uidoc.ActiveView
        if (current_view is None or current_view.IsTemplate or
                self.targets.checked != set([model.id_value(current_view.Id)])):
            return False
        updates = [row for row in self.plan['rows']
                   if row['action'] == 'Update' and not row.get('excluded')]
        if not updates or any(row['key'][0] != model.id_value(current_view.Id)
                              for row in self.plan['rows']):
            return False
        self.plan = self.graphics.approve_updates(self.plan)
        self.status.Text = (
            'Current view only: {} existing attachment update{} approved automatically. '
            'Click Apply to update the view.'.format(
                len(updates), '' if len(updates) == 1 else 's'))
        return True

    def show_changes(self):
        if self.busy:
            return
        if self.plan is None:
            self.build_plan()
        self.render_changes()

    def render_changes(self):
        self.changes_host.Children.Clear()
        if not self.plan:
            return
        query = named(ui.field(self.changes_query), 'Search attachment changes')
        query.TextChanged += lambda s, e: self.filter_changes(s.Text)
        self.changes_host.Children.Add(query)
        self.change_cards = []
        update_count = sum(r['action'] == 'Update' and not r.get('excluded') for r in self.plan['rows'])
        self.changes_host.Children.Add(row(
            ui.button('Approve All Updates ({})'.format(update_count), lambda s, e: self.approve()),
            ui.button('Clear approvals', lambda s, e: self.clear_approvals())))
        for plan_row in self.plan['rows']:
            key, action = plan_row['key'], plan_row['action']
            record = next((r for r in self.service.records if r.id == key[1]), None)
            try:
                info = self.graphics.target_info(key[0])
            except ValueError:
                info = {'name': 'Unavailable target'}
            caption = '{} · {} [target {}] / {} [filter {}] · {}'.format(
                action, info['name'], key[0], record.name if record else '', key[1], plan_row.get('reason', ''))
            content = ui.panel(text(caption, 12))
            if plan_row.get('source_exempt'):
                content.Children.Add(text('Independent new definition: source channels explicitly inactive; custom edits/native defaults only.', 12, ui.MUTED))
            if plan_row.get('delta'):
                content.Children.Add(text('\n'.join('{}: {} → {}'.format(field, change['before'], change['after'])
                    for field, change in plan_row['delta'].items()), 12, ui.MUTED))
            if plan_row.get('impact'):
                content.Children.Add(text('Inherited impact: ' + ', '.join(
                    '{} [id {}]'.format(item.get('name', ''), item.get('id', '')) for item in plan_row['impact']), 12, '#865B14'))
            if action == 'Update':
                approve = check('Approve this exact existing update', plan_row.get('approved', False))
                approve.Checked += lambda s, e, k=key: self.approve([k])
                approve.Unchecked += lambda s, e, k=key: self.unapprove(k)
                content.Children.Add(approve)
            if action in ('Blocked', 'Invalid'):
                content.Children.Add(ui.button('Explicitly exclude this pair', lambda s, e, k=key: self.exclude_pair(k)))
                if (plan_row.get('before') or {}).get('controlling_template_id'):
                    tid = plan_row['before']['controlling_template_id']
                    content.Children.Add(ui.button('Select controlling template explicitly', lambda s, e, t=tid:
                        self.select_template_target(t)))
            card = ui.card(content)
            self.changes_host.Children.Add(card)
            self.change_cards.append((caption.lower(), card))
        self.filter_changes(self.changes_query)
        self.update_summary()

    def filter_changes(self, query):
        self.changes_query = query
        for caption, card in getattr(self, 'change_cards', []):
            card.Visibility = Visibility.Visible if query.lower() in caption else Visibility.Collapsed

    def approve(self, keys=None):
        if self.plan:
            self.plan = self.graphics.approve_updates(self.plan, keys)
            self.render_changes()

    def clear_approvals(self):
        if self.plan:
            self.plan = self.graphics.clear_approvals(self.plan)
            self.render_changes()

    def unapprove(self, key):
        if self.plan:
            remaining = [r['key'] for r in self.plan['rows']
                         if r['action'] == 'Update' and r.get('approved') and r['key'] != key]
            self.plan = self.graphics.clear_approvals(self.plan)
            if remaining:
                self.plan = self.graphics.approve_updates(self.plan, remaining)
            self.render_changes()

    def exclude_pair(self, key):
        if self.plan:
            self.plan = self.graphics.exclude_rows(self.plan, [key])
            self.render_changes()

    def select_template_target(self, tid):
        info = self.graphics.target_info(tid)
        if not info.get('supported') or not info.get('is_template'):
            raise ValueError('The controlling template is not an eligible destination.')
        self.targets.checked.add(tid)
        self.invalidate()
        self.refresh_lists()
        self.render_task()

    def apply_attachments(self):
        if self.busy:
            return False
        if self.plan is None:
            self.build_plan()
        active = [r for r in self.plan['rows'] if not r.get('excluded')]
        blocked = [r for r in active if r['action'] in ('Blocked', 'Invalid')]
        pending = [r for r in active if r['action'] == 'Update' and not r.get('approved')]
        ready = any(r['action'] == 'Add' or (r['action'] == 'Update' and r.get('approved')) for r in active)
        if blocked or not ready:
            self.changes.IsExpanded = True
            self.render_changes()
            if blocked:
                self.status.Text = (
                    '{} blocked/invalid pair(s) require correction or explicit exclusion in Changes. '
                    'No model changes.'.format(len(blocked)))
                return False
            if pending:
                self.status.Text = (
                    '{} existing attachment update(s) await approval. '
                    'Approve individual rows or Approve All Updates in Changes. '
                    'No model changes.'.format(len(pending)))
                return False
            self.status.Text = 'All selected pairs are unchanged or already completed. No model changes.'
            return True
        result = self.graphics.apply(self.plan)
        self.receipts.extend(result.get('receipts', []))
        counts = result.get('counts', {})
        self.status.Text = '{} added · {} updated · {} unchanged · {} existing attachments await approval · {} excluded'.format(
            counts.get('added', 0), counts.get('updated', 0), counts.get('unchanged', 0),
            counts.get('unapproved', 0), counts.get('excluded', 0))
        # Replan with receipts so completed Adds are never queued as Updates.
        self.plan = None
        self.build_plan()
        completed_pairs = set(tuple(receipt['key']) for receipt in result.get('receipts', []))
        for planned in self.plan['rows']:
            pair = tuple(planned['key'])
            if pair in completed_pairs and planned.get('before') is not None:
                # A verified commit ends the old editing baseline. Subsequent
                # Revert restores the actual committed TARGET, not pre-Apply
                # values. Do not mutate the immutable earlier snapshot.
                self.pair_before[pair] = deepcopy(planned['before'])
                if not planned['before']['attached']:
                    self.pair_defaults[pair] = self.graphics.grid_values(planned['before'])
        self.render_changes()
        self.sync_graphics_dirty()
        self.refresh_after_definition(False)
        return True

    def update_summary(self):
        if not hasattr(self, 'attachment_summary'):
            return
        self.apply_close_button.IsEnabled = not self.busy
        count_f, count_t = len(self.filters.checked), len(self.targets.checked)
        available = getattr(self, 'source_mode', '') != 'project' and bool(getattr(self, 'origins', []))
        requested_graphics = any(key != 'visibility' for pair in self.active_pair_scope()
            for key in set(self.pair_patches.get(pair, {})).union(self.source_values(pair)))
        requested_visibility = any('visibility' in self.pair_patches.get(pair, {}) or
            'visibility' in self.source_values(pair) for pair in self.active_pair_scope())
        graphics, visibility = requested_graphics, requested_visibility
        self.apply_button.Content = ('Apply Filters + Graphics' if graphics else
                                     'Apply Filters + Visibility' if visibility else 'Add Filters')
        self.apply_button.IsEnabled = bool(count_f and count_t and not self.busy and not self.service.doc.IsReadOnly)
        if self.plan is None:
            self.attachment_summary.Text = '{} checked filter(s) × {} destinations · not yet compared; Apply checks exact differences.'.format(count_f, count_t)
            self.changes.Header = 'Changes (optional details and existing-update approvals)'
        else:
            rows = self.plan['rows']
            adds = sum(r['action'] == 'Add' and not r.get('excluded') for r in rows)
            updates = sum(r['action'] == 'Update' and r.get('approved') and not r.get('excluded') for r in rows)
            pending = sum(r['action'] == 'Update' and not r.get('approved') and not r.get('excluded') for r in rows)
            blocked = sum(r['action'] in ('Blocked', 'Invalid') and not r.get('excluded') for r in rows)
            if pending:
                self.changes.Header = 'Changes — {} update{} need{} additional approval'.format(
                    pending, '' if pending == 1 else 's', 's' if pending == 1 else '')
                self.attachment_summary.Text = (
                    '{} ready additions · {} approved updates · Additional approval required for {} '
                    'existing update{} · {} blocked. Review Changes before applying.'.format(
                        adds, updates, pending, '' if pending == 1 else 's', blocked))
            else:
                self.changes.Header = 'Changes (optional details and existing-update approvals)'
                self.attachment_summary.Text = '{} ready additions · {} approved updates · {} await approval · {} blocked'.format(
                    adds, updates, pending, blocked)
            self.apply_button.IsEnabled = bool((adds or updates or pending) and not blocked and
                                               not self.busy and not self.service.doc.IsReadOnly)
            if pending and not adds and not updates:
                self.apply_button.Content = 'Review {} Existing Update{}'.format(
                    pending, '' if pending == 1 else 's')
            elif not adds and (graphics or visibility):
                self.apply_button.Content = 'Apply Graphic Changes' if graphics else 'Apply Visibility Changes'
        if hasattr(self, 'source_summary'):
            self.source_summary.Text = '{} effective source(s) · {} checked filter(s) · {}'.format(
                len(getattr(self, 'origins', [])), count_f,
                'Browse only; Load unavailable' if not available else 'Browse only; use Load from source to propose values')

    def editor_for(self, record):
        if record.id not in self.editors:
            draft = self.editor_states.pop(record.id, None)
            # Retain the original token for stale/shared-impact checks.
            original = draft.get('record', record) if draft else record
            self.editors[record.id] = InlineEditor(self, original, draft)
        return self.editors[record.id]

    def render_rules(self):
        host = self.tab_hosts['Edit Rules']
        record = self.displayed_record()
        nav = self.navigator()
        if not record:
            slot(host, ui.panel(nav, text('Check filters to edit their independent rule drafts.')))
            return
        editor = self.editor_for(record)
        parent = editor.embedded.Parent
        if parent is not None:
            # Scroll content is detached before reparenting, not cloned.
            if hasattr(parent, 'Children'):
                parent.Children.Remove(editor.embedded)
        content_host = Grid()
        content_host.Children.Add(editor.embedded)
        self.rule_ack = check('Keep a separate identical definition',
                              bool(editor.duplicate_ids and editor.acknowledged_ids == editor.duplicate_ids))
        self.rule_ack.Checked += lambda s, e: self.ack_duplicates(editor, self.rule_ack.IsChecked is True)
        self.rule_ack.Unchecked += lambda s, e: self.ack_duplicates(editor, False)
        self.rule_duplicate_combo = ui.combo([(r.id, r.name) for r in self.service.records if r.id in editor.duplicate_ids])
        if self.rule_duplicate_combo.Items.Count:
            self.rule_duplicate_combo.SelectedIndex = 0
        save = ui.button('Save Rule Changes', lambda s, e: self.run(lambda: self.save_definition(editor)), 'primary')
        self.rule_save_button = save
        save.IsEnabled = bool(record.id in self.filters.checked and not record.problem and not self.service.doc.IsReadOnly)
        duplicate_review = Expander()
        duplicate_review.Header = '{} exact matches · review'.format(len(editor.duplicate_ids))
        duplicate_review.ToolTip = 'Acknowledge an intentional duplicate or Use Existing instead.'
        duplicate_review.Visibility = Visibility.Visible if editor.duplicate_ids else Visibility.Collapsed
        duplicate_review.Content = ui.panel(self.rule_ack, row(self.rule_duplicate_combo,
                ui.button('Use Existing', lambda s, e: self.use_existing(editor, ui.chosen(self.rule_duplicate_combo)))))
        self.rule_duplicate_review = duplicate_review
        footer = ui.panel(text('Shared project-wide save. Name and attachment graphics preserved.', 12, '#865B14'),
            duplicate_review,
            row(ui.button('Discard draft', lambda s, e: self.discard_rule(record.id)), save))
        self.rule_ack.Visibility = Visibility.Visible if editor.duplicate_ids else Visibility.Collapsed
        self.rule_duplicate_combo.Visibility = self.rule_ack.Visibility
        slot(host, stacked_grid(nav, content_host, footer))

    def editor_changed(self, editor):
        if hasattr(self, 'rule_ack'):
            self.rule_ack.IsChecked = False
        if editor is self.new_editor and hasattr(self, 'new_ack'):
            self.new_ack.IsChecked = False
        self.status.Text = 'Rule/category draft only. Save Rule Changes commits the displayed definition everywhere.'

    def ack_duplicates(self, editor, approved):
        editor.acknowledged_ids = editor.duplicate_ids if approved else ()
        if approved:
            review = getattr(self, 'new_duplicate_review' if editor is self.new_editor else 'rule_duplicate_review', None)
            if review:
                review.IsExpanded = False

    def discard_rule(self, fid):
        editor = self.editors.pop(fid, None)
        if editor:
            editor.dirty = False
            editor.Close()
        self.editor_states.pop(fid, None)
        self.render_rules()

    def new_definition(self, draft=None):
        if self.new_editor:
            self.show_new_editor()
            self.status.Text = 'Existing unsaved new-definition draft retained. Cancel it before starting another.'
            return
        self.new_editor = InlineEditor(self, draft=draft)
        if draft:
            self.new_editor.dirty = True
        self.show_new_editor()

    def duplicate_definition(self):
        record = self.focused_record()
        if not record:
            raise ValueError('Focus exactly one filter to duplicate; batch checks are not duplicate sources.')
        draft = self.service.duplicate_draft(record)
        self.new_definition(draft)
        self.status.Text = 'Independent duplicate draft from "{}". No definition or attachment created.'.format(record.name)

    def show_new_editor(self):
        editor = self.new_editor
        if not editor:
            return
        parent = editor.embedded.Parent
        if parent is not None and hasattr(parent, 'Children'):
            parent.Children.Remove(editor.embedded)
        ack = check('Keep a separate identical definition')
        ack.Checked += lambda s, e: self.ack_duplicates(editor, True)
        ack.Unchecked += lambda s, e: self.ack_duplicates(editor, False)
        matches = ui.combo([(r.id, r.name) for r in self.service.records if r.id in editor.duplicate_ids])
        if matches.Items.Count:
            matches.SelectedIndex = 0
        self.new_ack, self.new_matches = ack, matches
        create = ui.button('Create Filter', lambda s, e: self.run(lambda: self.save_definition(editor)), 'primary')
        create.IsEnabled = not self.service.doc.IsReadOnly
        self.new_create_button = create
        duplicate_review = Expander()
        duplicate_review.Header = '{} exact matches · review'.format(len(editor.duplicate_ids))
        duplicate_review.ToolTip = 'Acknowledge an intentional duplicate or Use Existing instead.'
        duplicate_review.Visibility = Visibility.Visible if editor.duplicate_ids else Visibility.Collapsed
        duplicate_review.Content = ui.panel(ack, row(matches,
            ui.button('Use Existing', lambda s, e: self.use_existing(editor, ui.chosen(matches)))))
        self.new_duplicate_review = duplicate_review
        footer = ui.panel(duplicate_review,
            row(ui.button('Cancel new draft', lambda s, e: self.cancel_new()),
                create))
        self.management = 'New Filter'
        self.tabs.Visibility = Visibility.Collapsed
        self.management_host.Visibility = Visibility.Visible
        content_host = Grid()
        content_host.Children.Add(editor.embedded)
        slot(self.management_host, stacked_grid(row(
            small_button('Back (keep draft)', lambda s, e: self.show_normal()), text('New Filter', 18)),
            content_host, footer))

    def cancel_new(self):
        if self.new_editor:
            self.new_editor.dirty = False
            self.new_editor.Close()
            self.new_editor = None
        self._initial.pop('new_draft', None)
        self.show_normal()
        self.status.Text = 'New definition draft discarded. No model changes.'

    def save_definition(self, editor):
        existing = editor.existing
        if existing and existing.id not in self.filters.checked:
            raise ValueError('Check the displayed filter before saving its rules.')
        tree, cats = editor.read_tree(), editor.categories()
        name = existing.name if existing else editor.name.Text
        # Review exact matches inline; service revalidates the full match set.
        self.service.refresh()
        self.service.eligible_parameters(cats)
        self.service.validate_definition(name, cats, tree, existing)
        matches = self.service.matches(cats, tree, existing.id if existing else None)
        ids = tuple(sorted(r.id for r in matches))
        if ids and tuple(editor.acknowledged_ids) != ids:
            editor.duplicate_ids = ids
            if existing:
                self.render_rules()
                self.rule_duplicate_review.IsExpanded = True
            else:
                self.show_new_editor()
                self.new_duplicate_review.IsExpanded = True
            raise ValueError('Review the exact identical definitions inline, then acknowledge or Use Existing.')
        fid = self.service.save(name, cats, tree, existing, ids)
        editor.dirty = False
        editor.Close()
        if existing:
            self.editors.pop(existing.id, None)
            self.editor_states.pop(existing.id, None)
        else:
            self.new_editor = None
            self._initial.pop('new_draft', None)
        self.filters.checked.add(fid)
        self.filters.focus(fid)
        self.refresh_after_definition()
        # New definitions are independent of every attachment source. Reveal one
        # without replacing other filters' pending source-copy requests.
        if not existing:
            self.revealed_filters.add(fid)
            self.source_exempt_ids.add(fid)
            self.resolve_sources()
            self.refresh_lists()
        self.management = None
        self.select_tab('Edit Rules' if existing else 'Graphics')
        self.status.Text = 'Saved shared definition. Other drafts and target checks retained.'
        return fid

    def use_existing(self, editor, fid):
        if fid is None:
            self.status.Text = 'Choose an identical existing definition first.'
            return
        if editor.existing:
            self.editors.pop(editor.existing.id, None)
            self.editor_states.pop(editor.existing.id, None)
        else:
            self.new_editor = None
            self._initial.pop('new_draft', None)
        editor.dirty = False
        editor.Close()
        self.filters.focus(fid)
        self.revealed_filters.add(fid)
        self.resolve_sources()
        self.refresh_lists()
        self.show_normal()
        self.status.Text = 'Existing definition focused. Draft discarded; no merge, deletion, or attachment transfer.'

    def refresh_after_definition(self, invalidate=True):
        self.service.refresh()
        existing = set(record.id for record in self.service.records)
        for pair in list(self.pair_sources):
            if pair[1] not in existing:
                self.pair_sources.pop(pair)
        self.prune_source_drafts()
        if invalidate:
            self.graphics.invalidate()
            self.invalidate()
        self.resolve_sources()
        self.refresh_lists()

    def active_rename_records(self):
        return [r for r in self.service.records if r.id in self.filters.checked and r.id not in self.rename_completed]

    def render_rename(self):
        records = self.active_rename_records()
        for record in records:
            self.rename_proposals.setdefault(record.id, record.name)
        pattern = ui.field(self.rename_pattern_value)
        pattern.TextChanged += lambda s, e: self.pattern_edited(s.Text)
        self.rename_pattern = pattern
        self.rename_rows = {}
        body = StackPanel()
        # Native grid columns; no arrows or row approvals.
        body.Children.Add(self.rename_grid_row(text('Current Name', 13), text('Proposed Name', 13), text('Status', 13)))
        for record in records:
            proposal = named(ui.field(self.rename_proposals[record.id]), 'Proposed name for ' + record.name)
            status = text(self.rename_errors.get(record.id, 'Current name' if proposal.Text == record.name else 'Draft'), 12, ui.MUTED)
            proposal.TextChanged += lambda s, e, fid=record.id: self.rename_edited(fid, s.Text)
            self.rename_rows[record.id] = (proposal, status)
            body.Children.Add(self.rename_grid_row(text(record.name, 13), proposal, status))
        if not records:
            body.Children.Add(text('No unresolved rename rows. Check another filter to start a new rename attempt.'))
        heading = text('Rename shared definitions', 19)
        heading.Margin = Thickness(0, 0, 0, 2)
        summary = text('{} active rows · hidden checks included · unresolved only'.format(len(records)), 12, ui.MUTED)
        summary.Margin = Thickness(0, 0, 0, 2)
        head = ui.panel(heading, summary, Expander())
        generator = head.Children[2]
        generator.Header = 'Optional rule-name generator'
        generator.Content = ui.panel(text('Tokens: {categories}, {rules}', 12), pattern,
            ui.button('Generate proposals', lambda s, e: self.run(self.generate_names)))
        footer = row(ui.button('Edit in ReValue (drafts only)', lambda s, e: self.handoff_revalue()),
                     ui.button('Rename', lambda s, e: self.run(self.rename), 'primary'))
        self.rename_button = footer.Children[1]
        footer.Children[1].IsEnabled = bool(records and not self.service.doc.IsReadOnly)
        slot(self.tab_hosts['Rename'], stacked_grid(head, ui.scroll(body), footer))

    def rename_grid_row(self, current, proposed, status):
        result = Grid()
        for weight in (1, 1.2, 0.9):
            col = ColumnDefinition()
            col.Width = GridLength(weight, GridUnitType.Star)
            result.ColumnDefinitions.Add(col)
        for index, control in enumerate((current, proposed, status)):
            Grid.SetColumn(control, index)
            control.Margin = Thickness(4)
            result.Children.Add(control)
        return result

    def rename_edited(self, fid, value):
        self.rename_proposals[fid] = value
        self.rename_errors.pop(fid, None)
        # Pure UI feedback; authoritative live vacancy checks occur on Rename.
        if fid in self.rename_rows:
            self.rename_rows[fid][1].Text = 'Draft; validated on Rename'

    def pattern_edited(self, value):
        self.rename_pattern_value = value

    def generate_names(self):
        symbols = model.load_naming_symbols()
        records = self.active_rename_records()
        generated = dict((r.id, self.service.pattern_name(r, self.rename_pattern.Text, symbols)) for r in records)
        self.rename_proposals.update(generated)
        self.naming_generated = True
        self._initial['rename_pattern'] = self.rename_pattern.Text
        self.render_rename()
        self.status.Text = '{} generated proposals. No names saved.'.format(len(generated))

    def rename(self):
        records = self.active_rename_records()
        if not records:
            raise ValueError('No unresolved rename rows.')
        names = dict((r.id, self.rename_proposals.get(r.id, r.name)) for r in records)
        result = self.service.rename_partial(records, names)
        completed = list(result['renamed']) + list(result['unchanged'])
        self.rename_completed.update(completed)
        for fid in completed:
            self.rename_proposals.pop(fid, None)
        self.rename_errors = dict(result['errors'])
        self.refresh_after_definition()
        for fid in result['renamed']:
            if fid in self.editors:
                editor = self.editors[fid]
                was_dirty = editor.dirty
                editor.existing = self.service.get_record(fid)
                editor.initializing = True
                editor.name.Text = editor.existing.name
                editor.initializing = False
                editor.dirty = was_dirty
            if fid in self.editor_states:
                current = self.service.get_record(fid)
                self.editor_states[fid]['record'] = current
                self.editor_states[fid]['name'] = current.name
        self.render_rename()
        self.status.Text = '{} renamed · {} unchanged · {} need correction'.format(
            len(result['renamed']), len(result['unchanged']), len(result['errors']))
        if result['renamed'] and self.naming_generated:
            try:
                self.rename_config.name_pattern = self.rename_pattern_value
                script.save_config()
            except Exception as error:
                script.get_logger().warning('Names saved, but naming-pattern preference was not saved: %s', error)
                self.status.Text += ' · names saved; pattern preference could not be saved'

    def handoff_revalue(self):
        records = self.active_rename_records()
        if not records:
            self.status.Text = 'Check filters with unresolved rename rows first.'
            return
        proposals = dict((r.id, self.rename_proposals.get(r.id, r.name)) for r in records)
        self.result = ('revalue', records, proposals)
        self._handoff = True
        self._allow_close = True
        self.Close()

    def review_delete(self):
        records = [r for r in self.service.records if r.id in self.filters.checked]
        if not records:
            raise ValueError('Check definitions to delete.')
        self.service.refresh()
        records = [self.service.get_record(r.id) for r in records]
        self.management_records = records
        self.management_tokens = dict((r.id, self.service.usage_token(r)) for r in records)
        self.render_delete(False)

    def review_purge(self):
        records = self.service.unused_records()
        self.management_records = records
        self.management_tokens = dict((r.id, self.service.usage_token(r)) for r in records)
        self.render_delete(True)

    def render_delete(self, purge):
        self.management_checks = []
        self.used_ack = check('I understand these used definitions are removed from every listed consumer.')
        listing = StackPanel()
        query = named(ui.field(), 'Search reviewed unused definitions' if purge else 'Search reviewed definitions')
        review_cards = []
        for record in self.management_records:
            detail = record.usage_text + '\n' + '\n'.join(model.name_of(v) for v in record.usage + record.inherited)
            box = check(record.name + ' [id {}]'.format(record.id), True)
            box.Checked += lambda s, e: changed()
            box.Unchecked += lambda s, e: changed()
            self.management_checks.append((record.id, box))
            card = ui.card(ui.panel(box, text(detail, 12, ui.MUTED)))
            listing.Children.Add(card)
            review_cards.append((record, box, card))
        count_label = text()
        commit = small_button('', lambda s, e: self.run(lambda: self.commit_delete(purge)))
        commit.Tag = 'destructive'
        self.delete_commit_button = commit
        def changed(sender=None, event=None):
            ids = set(fid for fid, box in self.management_checks if box.IsChecked)
            used = any(r.usage for r in self.management_records if r.id in ids)
            self.used_ack.Visibility = Visibility.Visible if used and not purge else Visibility.Collapsed
            if sender is not self.used_ack:
                self.used_ack.IsChecked = False
            hidden = sum(box.IsChecked and query.Text.lower() not in record.name.lower()
                         for record, box, card in review_cards)
            count_label.Text = '{} approved definitions · {} hidden approved · exact impact above'.format(len(ids), hidden)
            commit.Content = 'Purge {} Unused Filters'.format(len(ids)) if purge else 'Delete Approved Definitions ({})'.format(len(ids))
            commit.IsEnabled = bool(ids and not self.service.doc.IsReadOnly and (purge or not used or self.used_ack.IsChecked))
        def search(sender=None, event=None):
            hidden = 0
            for record, box, card in review_cards:
                visible = query.Text.lower() in record.name.lower()
                card.Visibility = Visibility.Visible if visible else Visibility.Collapsed
                if box.IsChecked and not visible:
                    hidden += 1
            changed(self.used_ack)
        query.TextChanged += search
        self.used_ack.Checked += lambda s, e: changed(s, e)
        self.used_ack.Unchecked += lambda s, e: changed(s, e)
        changed()
        self.show_management('Purge Unused' if purge else 'Delete definitions',
            ui.panel(text('No attachments anywhere, including unassigned templates. Fresh complete usage is revalidated before the atomic purge.' if purge else
                          'Deletion affects shared definitions everywhere, not just checked targets.', 13, '#865B14'),
                     query, count_label, listing), ui.panel(self.used_ack, row(
                         small_button('Refresh review', lambda s, e: self.run(self.review_purge if purge else self.review_delete)),
                         commit)))

    def commit_delete(self, purge):
        ids = set(fid for fid, box in self.management_checks if box.IsChecked)
        records = [r for r in self.management_records if r.id in ids]
        if not records:
            raise ValueError('Approve at least one definition in the counted review.')
        if not purge and any(r.usage for r in records) and not self.used_ack.IsChecked:
            raise ValueError('Acknowledge the exact used-definition impact first.')
        tokens = dict((fid, self.management_tokens[fid]) for fid in ids)
        deleted = self.service.purge_unused(records, tokens) if purge else self.service.delete(records, tokens)
        for fid in ids:
            self.filters.checked.discard(fid)
            for table in (self.pair_patches, self.pair_graphic_inputs, self.pair_graphic_errors,
                          self.pair_sources, self.pair_before, self.pair_defaults):
                for pair in list(table):
                    if pair[1] == fid:
                        table.pop(pair, None)
            self.dirty_graphics_pairs = set(pair for pair in self.dirty_graphics_pairs if pair[1] != fid)
            self.unassigned_graphics.pop(fid, None)
            self.dirty_graphics_ids.discard(fid)
            self.rename_proposals.pop(fid, None)
            self.rename_completed.discard(fid)
            self.revealed_filters.discard(fid)
            self.source_exempt_ids.discard(fid)
            editor = self.editors.pop(fid, None)
            if editor:
                editor.dirty = False
                editor.Close()
            self.editor_states.pop(fid, None)
            if self.filters.focused == fid:
                self.filters.focused = None
        self.sync_graphics_dirty()
        self.refresh_after_definition()
        self.show_normal()
        self.status.Text = '{} definitions {}. No unrelated filters removed.'.format(len(ids), 'purged' if purge else 'deleted')
        return deleted

    def analyse_duplicates(self):
        self.service.refresh()
        groups = {}
        unsupported = []
        for record in self.service.records:
            if record.signature is None:
                unsupported.append(record)
            else:
                groups.setdefault(record.signature, []).append(record)
        matches = [records for records in groups.values() if len(records) > 1]
        content = ui.panel(text('{} groups · {} definitions · {} unsupported comparisons'.format(
            len(matches), sum(len(g) for g in matches), len(unsupported)), 15),
            text('Conservative full typed signatures. Equal definitions may have different attachment graphics. No automatic merge.', 12, '#865B14'))
        for records in matches:
            group = ui.panel(text(records[0].rules, 12, ui.MUTED))
            for record in records:
                group.Children.Add(ui.panel(text(record.name + ' · ' + record.usage_text),
                    row(ui.button('Keep / inspect', lambda s, e, fid=record.id: self.inspect_duplicate(fid)),
                        ui.button('Use Existing', lambda s, e, fid=record.id: self.analysis_use_existing(fid)),
                        ui.button('Rename', lambda s, e, fid=record.id: self.duplicate_action(fid, 'Rename')),
                        ui.button('Delete', lambda s, e, fid=record.id: self.duplicate_delete(fid)),
                        ui.button('Graphics variants (on demand)', lambda s, e, fid=record.id: self.inspect_duplicate_variants(fid)))))
            content.Children.Add(ui.card(group))
        for record in unsupported:
            content.Children.Add(text(record.name + ': ' + record.problem, 12, '#865B14'))
        self.duplicate_detail = text('', 12)
        content.Children.Add(self.duplicate_detail)
        self.show_management('Analyse Duplicates', content)

    def inspect_duplicate(self, fid):
        self.filters.focus(fid)
        self.select_tab('Graphics')

    def analysis_use_existing(self, fid):
        if self.new_editor:
            self.use_existing(self.new_editor, fid)
        else:
            self.filters.focus(fid)
            self.revealed_filters.add(fid)
            self.refresh_lists()
            self.select_tab('Graphics')
            self.status.Text = 'Existing definition focused. No merge, deletion, or automatic application.'

    def duplicate_action(self, fid, title):
        self.filters.checked.add(fid)
        self.filters.focus(fid)
        self.rename_completed.discard(fid)
        self.invalidate()
        self.refresh_lists()
        self.select_tab(title)

    def duplicate_delete(self, fid):
        # Explicit follow-up scope; don't silently delete the unrelated batch.
        record = self.service.get_record(fid)
        self.management_records = [record]
        self.management_tokens = {fid: self.service.usage_token(record)}
        self.render_delete(False)

    def inspect_duplicate_variants(self, fid):
        record = self.service.get_record(fid)
        origins = [model.id_value(v.Id) for v in record.usage]
        if not origins:
            self.duplicate_detail.Text = record.name + ': no attachments.'
            return
        data = self.read(lambda: self.graphics.source_variants(fid, origins,
            include_graphics=True, include_visibility=True,
            cancel=lambda: self.cancelled, progress=self.progress))
        lines = [record.name]
        if not data.get('complete'):
            lines.append('Incomplete graphics comparison; retry. No variants/defaults inferred.')
        else:
            lines.append('{} exact attachment variants'.format(len(data.get('groups', []))))
            for index, variant in enumerate(data.get('groups', [])):
                names = [self.graphics.target_info(identity)['name'] + ' [id {}]'.format(identity)
                         for identity in variant['origin_ids']]
                lines.append('Variant {} · {}'.format(index + 1, ', '.join(names)))
                lines.extend('{} / {}: {}'.format(field['group'], field['label'],
                    display_value(field, variant['values'][field['key']])) for field in self.graphics.FIELDS
                    if field['key'] in variant['values'])
        self.duplicate_detail.Text = '\n'.join(lines)

    def open_source_picker(self):
        catalogue = self.catalogue_requested()
        self.picker_checks = set(self.source_ids)
        query = named(ui.field(), 'Search source views and templates')
        kind = ui.combo([('both', 'Views + Templates'), ('views', 'Views'), ('templates', 'Templates')], 'both')
        types = sorted(set(info['view_type'] for info in catalogue))
        view_type = ui.combo([(None, 'All view types')] + [(v, v) for v in types], None)
        listing = StackPanel()
        count = text('', 12)
        def refresh(sender=None, event=None):
            listing.Children.Clear()
            visible = [i for i in catalogue if query.Text.lower() in i['name'].lower() and
                       (ui.chosen(kind) == 'both' or i['is_template'] == (ui.chosen(kind) == 'templates')) and
                       (ui.chosen(view_type) is None or ui.chosen(view_type) == i['view_type'])]
            for info in visible:
                box = check('{} · {} · id {}'.format(info['name'], info['view_type'], info['id']),
                            info['id'] in self.picker_checks)
                box.IsEnabled = info.get('supported', False)
                box.Checked += lambda s, e, identity=info['id']: toggled(identity, True)
                box.Unchecked += lambda s, e, identity=info['id']: toggled(identity, False)
                listing.Children.Add(box)
            count.Text = '{} checked · {} hidden'.format(len(self.picker_checks),
                len(self.picker_checks - set(i['id'] for i in visible)))
        def toggled(identity, value):
            if value:
                self.picker_checks.add(identity)
            else:
                self.picker_checks.discard(identity)
            count.Text = '{} checked (search-hidden selections retained)'.format(len(self.picker_checks))
        for control in (query,):
            control.TextChanged += refresh
        kind.SelectionChanged += refresh
        view_type.SelectionChanged += refresh
        self.picker_refresh = refresh
        refresh()
        self.show_management('Selected source views / templates', ui.panel(query, row(kind, view_type), count, listing),
            row(ui.button('Cancel (keep previous sources)', lambda s, e: self.cancel_source_picker()),
                ui.button('Use Sources', lambda s, e: self.set_source('selected', sorted(self.picker_checks)), 'primary')))

    def cancel_source_picker(self):
        self.loading = True
        choose(self.source_combo, self.source_mode)
        self.loading = False
        self.show_normal()

    def matching(self):
        records = [r for r in self.service.records if r.id in self.filters.checked]
        if not records:
            raise ValueError('Check filters before selecting matching elements.')
        if self.has_pending():
            self.status.Text = 'Resolve pending drafts before the external matching-selection handoff.'
            self.show_close_choices(False)
            return
        dialog = ui.MatchingDialog(self.service, records, self.uidoc.ActiveView)
        dialog.run = self.run
        result = dialog.show(self)
        if result:
            self.result = ('selection', [model.id_value(value) for value in result])
            self._allow_close = True
            self.Close()

    def has_pending(self):
        rules = any(e.dirty for e in self.editors.values()) or any(
            draft.get('dirty') for draft in self.editor_states.values())
        new = bool(self.new_editor and (self.new_editor.dirty or self.new_editor.name.Text or self.new_editor.categories()))
        rename = any(r.id in self.rename_proposals and self.rename_proposals[r.id] != r.name
                     for r in self.service.records)
        # Custom inactive drafts must not disappear silently on close either.
        return bool(rules or new or rename or self.graphics_dirty)

    def apply_and_close(self):
        if self.busy:
            return
        if self.filters.checked and self.targets.checked:
            if self.apply_attachments() is False:
                return
        if self.has_pending():
            self.status.Text = ('Unapplied drafts remain. Resolve rules, names, inactive graphics or '
                                'unapproved updates before closing, or Cancel to discard them.')
            return
        self._allow_close = True
        self.Close()

    def cancel_workspace(self):
        if self.busy:
            self.cancel_read()
            return
        self.discard_and_close(True)

    def closing(self, sender, event):
        if self._allow_close:
            return
        if self.busy:
            event.Cancel = True
            self.cancel_read()
            return
        if self.has_pending():
            event.Cancel = True
            self.show_close_choices(True)

    def show_close_choices(self, closing=True):
        self._close_requested = closing
        if self.management and not self.management.startswith('Pending work') and self.management_host.Children.Count:
            self._before_close_view = (self.management, self.management_host.Children[0])
        elif not self.management:
            self._before_close_view = None
        contents = ui.panel(text('There are unapplied drafts. Selecting sources, filters or targets alone is not an edit. '
            'No navigation or close action saves automatically. Committed operations are not undone by Discard.', 14),
            text('Save only the current definition, rename grid, or ready attachment operation below. '
                 'Invalid/unapproved work stays pending; closing is not forced.', 12, '#865B14'))
        buttons = row(ui.button('Stay', lambda s, e: self.stay_pending()),
                      ui.button('Discard drafts and close' if closing else 'Discard drafts',
                                lambda s, e: self.discard_and_close(closing)))
        if self.new_editor:
            buttons.Children.Add(ui.button('Create current new draft', lambda s, e: self.run(
                lambda: self.save_definition(self.new_editor))))
        record = self.displayed_record()
        if record and record.id in self.editors and self.editors[record.id].dirty:
            buttons.Children.Add(ui.button('Save displayed rule draft', lambda s, e: self.run(
                lambda: self.save_definition(self.editors[record.id]))))
        if self._task == 'Rename':
            buttons.Children.Add(ui.button('Rename valid subset', lambda s, e: self.run(self.rename)))
        if self.filters.checked and self.targets.checked:
            buttons.Children.Add(ui.button('Apply ready attachments', lambda s, e: self.run(self.apply_attachments)))
        self.show_management('Pending work — save, discard, or stay', contents, buttons)

    def stay_pending(self):
        previous = getattr(self, '_before_close_view', None)
        if previous:
            self.management = previous[0]
            self.tabs.Visibility = Visibility.Collapsed
            self.management_host.Visibility = Visibility.Visible
            slot(self.management_host, previous[1])
        else:
            self.show_normal()
        self._before_close_view = None

    def discard_and_close(self, closing):
        self.pair_patches.clear()
        self.pair_sources.clear()
        self.prune_source_drafts()
        self.pair_before.clear()
        self.pair_defaults.clear()
        self.pair_graphic_inputs.clear()
        self.pair_graphic_errors.clear()
        self.dirty_graphics_pairs.clear()
        self.unassigned_graphics.clear()
        self.dirty_graphics_ids.clear()
        self.graphics_dirty = False
        self.rename_proposals.clear()
        self.editor_states.clear()
        self._initial.pop('new_draft', None)
        for editor in self.editors.values():
            editor.dirty = False
            editor.Close()
        self.editors.clear()
        if self.new_editor:
            self.new_editor.dirty = False
            self.new_editor.Close()
            self.new_editor = None
        self.filters.clear()
        self.targets.clear()
        self.plan = None
        if closing:
            self._allow_close = True
            self.Close()
        else:
            self.show_normal()
            self.refresh_lists()

    def state(self):
        drafts = dict(self.editor_states)
        for fid, editor in self.editors.items():
            drafts[fid] = editor.export()
        # In-memory continuation only, not a document-independent preference file.
        return {'browser_ids': list(self.browser_ids), 'checked_filters': list(self.filters.checked),
                'checked_targets': list(self.targets.checked), 'focused_filter': self.filters.focused,
                'focused_target': self.targets.focused, 'source_mode': self.source_mode,
                'filter_highlights': list(self.filter_highlights), 'target_highlights': list(self.target_highlights),
                'target_mode': self.target_mode, 'source_ids': list(self.source_ids),
                'source_candidate_ids': list(self.source_candidate_ids),
                'effective_origin_ids': list(self.origins),
                'revealed_filters': list(self.revealed_filters), 'source_exempt_ids': list(self.source_exempt_ids),
                'include_graphics': self.include_graphics, 'include_visibility': self.include_visibility,
                'source_choices': dict(self.source_choices), 'patches': {},
                'pair_sources': deepcopy(self.pair_sources), 'pair_before': deepcopy(self.pair_before),
                'pair_defaults': deepcopy(self.pair_defaults),
                'resource_names': dict(self.resource_names),
                'pair_patches': dict((pair, independent_patch(patch)) for pair, patch in self.pair_patches.items()),
                'unassigned_graphics': dict((fid, {'patch': independent_patch(draft['patch']),
                    'inputs': dict(draft['inputs']), 'errors': dict(draft['errors'])})
                    for fid, draft in self.unassigned_graphics.items()),
                'receipts': list(self.receipts), 'catalogue': self.catalogue,
                'graphics_service': self.graphics, 'plan': self.plan,
                'graphics_dirty': self.graphics_dirty,
                'dirty_graphics_ids': list(self.dirty_graphics_ids),
                'dirty_graphics_pairs': list(self.dirty_graphics_pairs),
                'pair_graphic_inputs': dict((pair, dict(values)) for pair, values in self.pair_graphic_inputs.items()),
                'pair_graphic_errors': dict((pair, dict(values)) for pair, values in self.pair_graphic_errors.items()),
                'filter_query': self.filter_search.Text, 'target_query': self.target_search.Text,
                'filter_field': ui.chosen(self.filter_field), 'category': ui.chosen(self.filter_category),
                'unused': self.unused.IsChecked is True, 'filter_selected': self.filter_selected.IsChecked is True,
                'target_kind': ui.chosen(self.target_kind), 'target_type': ui.chosen(self.target_type),
                'target_selected': self.target_selected.IsChecked is True, 'together': self.together,
                'tab': self._task, 'rule_drafts': drafts,
                'new_draft': self.new_editor.export() if self.new_editor else self._initial.get('new_draft'),
                'rename_proposals': dict(self.rename_proposals), 'rename_completed': list(self.rename_completed),
                'rename_errors': dict(self.rename_errors),
                'rename_pattern': self.rename_pattern_value, 'naming_generated': self.naming_generated}

    def show(self, owner=None):
        # New-definition continuation is restored lazily, without showing a window.
        if self._initial.get('new_draft') and self.new_editor is None:
            self.new_editor = InlineEditor(self, draft=self._initial['new_draft'])
            self._initial.pop('new_draft', None)
        return ui.Dialog.show(self, owner)

    def dispose_editors(self, sender, event):
        # State must remain available to parent after Close/ReValue. Export before
        # detaching property-descriptor callbacks, then keep control data readable.
        for editor in list(self.editors.values()) + ([self.new_editor] if self.new_editor else []):
            editor.Close()

    def key_down(self, sender, event):
        if event.Key == Key.Escape:
            event.Handled = True
            if self.busy:
                self.cancel_read()
            elif self.management:
                self.show_normal()
            else:
                self.run(self.cancel_workspace)

    def toggle_drawer(self, side):
        control = self.left if side == 'left' else self.right
        control.Visibility = Visibility.Collapsed if control.Visibility == Visibility.Visible else Visibility.Visible
        if self.Width < 1120 and control.Visibility == Visibility.Visible:
            (self.right if side == 'left' else self.left).Visibility = Visibility.Collapsed
        self.drawer_widths()

    def drawer_widths(self):
        compact = self.Width < 1120
        for index, control in ((0, self.left), (2, self.right)):
            visible = control.Visibility == Visibility.Visible
            self.columns.ColumnDefinitions[index].Width = GridLength(
                250 if compact else 300, GridUnitType.Pixel) if visible else GridLength(0)
        # In compact mode one side at a time; centre stays usable.
        if compact and self.left.Visibility == Visibility.Visible and self.right.Visibility == Visibility.Visible:
            self.right.Visibility = Visibility.Collapsed
            self.columns.ColumnDefinitions[2].Width = GridLength(0)

    def adapt_layout(self, sender, event):
        if not hasattr(self, 'left'):
            return
        compact = self.Width < 1120
        compact_options = compact or self.Height < 760
        if getattr(self, '_compact_options', None) != compact_options:
            self.library_options.IsExpanded = not compact_options
            self.target_options.IsExpanded = not compact_options
            self._compact_options = compact_options
        self.target_notice.Visibility = Visibility.Collapsed if compact_options else Visibility.Visible
        if hasattr(self, 'graphics_scope_hint'):
            self.graphics_scope_hint.Visibility = Visibility.Collapsed if compact_options else Visibility.Visible
        self.changes.Content.MaxHeight = 80 if self.Height < 760 else 190
        self.source_drawer_button.Visibility = Visibility.Visible if compact else Visibility.Collapsed
        self.target_drawer_button.Visibility = Visibility.Visible if compact else Visibility.Collapsed
        if not compact:
            self.left.Visibility = self.right.Visibility = Visibility.Visible
        self.drawer_widths()
