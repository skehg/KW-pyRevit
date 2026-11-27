# -*- coding: utf-8 -*-
"""Read-only WPF/controller checks. run(doc, uidoc); never ShowDialog or write."""
from System.Windows import Size, Rect, Point, Visibility, RoutedEventArgs
from System.Windows.Controls import Button
from copy import deepcopy
import filter_model as model
import filter_workspace as workspace


def run_close_actions(doc, uidoc):
    """Revit 2023 native WPF checks; writes are replaced at the controller boundary."""
    assert doc.Application.VersionNumber == '2023', 'Revit 2023 ONLY'
    original_modified = doc.IsModified
    service = model.FilterService(doc)
    assert service.records, 'Requires a filter'
    record = service.records[0]
    tid = model.id_value(uidoc.ActiveView.Id)
    pair = (tid, record.id)
    checks = []

    class ClosingEvent(object):
        Cancel = False

    def selected():
        dialog = workspace.WorkspaceDialog(service, uidoc)
        dialog.set_source('project')
        dialog.filters.checked.add(record.id)
        dialog.targets.checked.add(tid)
        dialog.filters.focus(record.id)
        dialog.refresh_lists()
        return dialog

    def dispose(dialog):
        dialog._allow_close = True
        dialog.Close()

    dialog = selected()
    try:
        assert not dialog.has_pending()
        event = ClosingEvent()
        dialog.closing(dialog, event)
        assert not event.Cancel
        dialog.plan = {'rows': [{'key': pair, 'action': 'Add'}]}
        assert not dialog.has_pending(), 'Reviewed selection is not an edit'
        dialog.plan['rows'][0]['action'] = 'Blocked'
        assert not dialog.has_pending(), 'Unsupported selection is not an edit'
        checks.append('selection alone, reviewed additions and blocked selection do not warn on X')

        dialog.rename_proposals[record.id] = record.name + ' draft'
        dialog.filters.clear()
        assert dialog.has_pending(), 'Unchecked rename must remain pending'
        dialog.targets.clear()
        dialog.apply_and_close()
        assert not dialog._allow_close
        dialog.rename_proposals.clear()
        dialog.pair_graphic_errors[pair] = {'transparency': 'Invalid number'}
        dialog.dirty_graphics_pairs.add(pair)
        dialog.sync_graphics_dirty()
        assert dialog.has_pending(), 'Unchecked invalid graphics must remain pending'
        event = ClosingEvent()
        dialog.closing(dialog, event)
        assert event.Cancel and dialog.management.startswith('Pending work')
        checks.append('inactive rename/invalid graphic drafts keep Apply and Close open and warn on X')
    finally:
        dispose(dialog)

    dialog = selected()
    try:
        dialog.pair_patches[pair] = {'transparency': {'mode': 'set', 'value': 35}}
        dialog.dirty_graphics_pairs.add(pair)
        dialog.sync_graphics_dirty()
        dialog.rename_proposals[record.id] = record.name + ' draft'
        dialog.editor_states[record.id] = {'dirty': True}
        dialog._initial['new_draft'] = {'dirty': True}
        dialog.receipts.append({'key': pair, 'fixture': True})
        dialog.dismiss_button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
        assert dialog._allow_close and not dialog.has_pending()
        assert not dialog.pair_patches and not dialog.editor_states
        assert not dialog.rename_proposals and 'new_draft' not in dialog._initial
        assert dialog.receipts, 'Cancel must not undo previous commits'
        checks.append('actual Cancel click discards graphics/rules/names/new draft without prompt; receipts survive')
    finally:
        dispose(dialog)

    for outcome in ('complete', 'pending', 'error'):
        dialog = selected()
        calls = []
        try:
            dialog.dirty_graphics_pairs.add(pair)
            dialog.sync_graphics_dirty()
            def apply():
                calls.append('apply')
                if outcome == 'error':
                    raise ValueError('fixture apply failure')
                if outcome == 'complete':
                    dialog.dirty_graphics_pairs.clear()
                    dialog.sync_graphics_dirty()
            dialog.apply_attachments = apply
            if outcome == 'error':
                try:
                    dialog.apply_and_close()
                except ValueError as error:
                    assert unicode(error) == 'fixture apply failure'
                else:
                    raise AssertionError('Apply failure swallowed')
            else:
                dialog.apply_close_button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
            assert calls == ['apply']
            assert dialog._allow_close == (outcome == 'complete')
            checks.append('Apply and Close delegates existing apply path: ' + outcome)
        finally:
            dispose(dialog)

    for action in ('Blocked', 'Update'):
        dialog = selected()
        try:
            native = dialog.graphics
            writes = []
            class PendingApproval(object):
                def __getattr__(self, key):
                    return getattr(native, key)
                def apply(self, plan):
                    writes.append(plan)
                    raise AssertionError('Pending {} plan attempted a write'.format(action))
            dialog.graphics = PendingApproval()
            dialog.plan = {'rows': [
                {'key': pair, 'action': action, 'approved': False,
                 'reason': 'fixture pending {}'.format(action), 'delta': {}, 'impact': []}]}
            assert dialog.apply_attachments() is False
            assert not writes and dialog.changes.IsExpanded and not dialog._allow_close
            assert 'No model changes.' in dialog.status.Text
            if action == 'Update':
                assert dialog.apply_button.IsEnabled
                assert dialog.apply_button.Content == 'Review 1 Existing Update'
                assert 'additional approval' in dialog.changes.Header
            dialog.apply_close_button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
            assert not writes and not dialog._allow_close
            checks.append('{} remains inline pending with no write/traceback path and Apply and Close stays open'.format(action))
        finally:
            dispose(dialog)

    dialog = selected()
    try:
        native = dialog.graphics
        calls = []
        class AutoApproval(object):
            def __getattr__(self, key):
                return getattr(native, key)
            def approve_updates(self, plan, row_keys=None):
                calls.append(plan)
                return {'rows': [
                    dict(row, approved=True) for row in plan['rows']]}
        dialog.graphics = AutoApproval()
        dialog.plan = {'rows': [
            {'key': pair, 'action': 'Update', 'approved': False,
             'reason': 'fixture current view update'}]}
        if uidoc.ActiveView.IsTemplate:
            assert not dialog.approve_current_view_updates()
        else:
            assert dialog.approve_current_view_updates()
        expected_calls = [] if uidoc.ActiveView.IsTemplate else [dict(rows=[
            {'key': pair, 'action': 'Update', 'approved': False,
             'reason': 'fixture current view update'}])]
        assert calls == expected_calls
        if not uidoc.ActiveView.IsTemplate:
            assert dialog.plan['rows'][0]['approved']
            assert 'approved automatically' in dialog.status.Text
        dialog.targets.checked.add(tid + 1)
        dialog.plan['rows'][0]['approved'] = False
        assert not dialog.approve_current_view_updates()
        checks.append('current-view-only scope auto-approves existing Updates; additional targets retain explicit approval')
    finally:
        dispose(dialog)

    for action in ('Add', 'Unchanged'):
        dialog = selected()
        try:
            native = dialog.graphics
            calls = []
            class ReceiptOnly(object):
                def __getattr__(self, key):
                    return getattr(native, key)
                def apply(self, plan):
                    assert action == 'Add', 'Unchanged plan attempted a write'
                    calls.append('apply')
                    return {'counts': {'added': 1}, 'receipts': [{'key': pair}]}
                def plan(self, request, completed=(), cancel=None, progress=None):
                    assert completed, 'Completed addition lost its receipt'
                    return {'rows': [{'key': pair, 'action': 'Completed'}]}
            dialog.graphics = ReceiptOnly()
            dialog.plan = {'rows': [{'key': pair, 'action': action}]}
            dialog.apply_close_button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
            assert dialog._allow_close
            assert calls == (['apply'] if action == 'Add' else [])
            checks.append('existing apply pipeline closes after {} (controller receipt stub; no native writes)'.format(action))
        finally:
            dispose(dialog)

    dialog = selected()
    try:
        dialog.filters.clear()
        dialog.targets.clear()
        dialog.apply_close_button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
        assert dialog._allow_close
        checks.append('Apply and Close with no selection or drafts simply closes')
    finally:
        dispose(dialog)

    dialog = selected()
    try:
        class EscapeEvent(object):
            Key = workspace.Key.Escape
            Handled = False
        dialog.rename_proposals[record.id] = record.name + ' draft'
        dialog.show_close_choices()
        event = EscapeEvent()
        dialog.key_down(dialog, event)
        assert event.Handled and not dialog.management and dialog.has_pending()
        event = EscapeEvent()
        dialog.key_down(dialog, event)
        assert event.Handled and dialog._allow_close and not dialog.has_pending()
        checks.append('Escape leaves a management panel first; Escape from workspace discards drafts and closes')
    finally:
        dispose(dialog)

    dialog = selected()
    try:
        captions = ('Add Filters', 'Apply Filters + Graphics', 'Apply Filters + Visibility',
                    'Apply Graphic Changes', 'Apply Visibility Changes')
        for width, height in ((1440, 960), (900, 720), (760, 640)):
            dialog.Width, dialog.Height = width, height
            positions = []
            for caption in captions:
                dialog.apply_button.Content = caption
                dialog.Content.Measure(Size(width - 32, height - 48))
                dialog.Content.Arrange(Rect(0, 0, width - 32, height - 48))
                dialog.UpdateLayout()
                point = dialog.apply_button.TranslatePoint(Point(0, 0), dialog.actions)
                close_point = dialog.apply_close_button.TranslatePoint(Point(0, 0), dialog.actions)
                positions.append((point.X, point.Y, close_point.X, close_point.Y,
                                  dialog.actions.ActualHeight))
                assert dialog.apply_button.ActualWidth == 250
                assert dialog.apply_button.ActualHeight == 44
                assert close_point.Y == point.Y
                assert close_point.X + dialog.apply_close_button.ActualWidth <= dialog.actions.ActualWidth
            assert all(position == positions[0] for position in positions)
        checks.append('all five dynamic labels retain exact size, positions and footer height at 1440/900/760 widths')
        dialog.busy = True
        dialog.cancel_workspace()
        assert dialog.cancelled and not dialog._allow_close
        dialog.apply_and_close()
        assert not dialog._allow_close
        dialog.busy = False
        checks.append('busy Cancel cancels only reading; Apply and Close cannot close mid-read')
    finally:
        dispose(dialog)
    assert doc.IsModified == original_modified
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks),
            'checks': checks, 'model_writes': 0,
            'not_run': ['native apply commit/Undo', 'attended ribbon keyboard/high-DPI checks']}


def run_graphics_selection(doc, uidoc):
    """Actual WPF Checked/Unchecked/SelectionChanged path, no manual render."""
    assert doc.Application.VersionNumber == '2023', 'Revit 2023 ONLY'
    original_modified = doc.IsModified
    service = model.FilterService(doc)
    assert len(service.records) >= 2, 'Requires two filters for unchecked-focus regression'
    results = []
    probe = workspace.WorkspaceDialog(service, uidoc)
    try:
        tids = [model.id_value(view.Id) for view in service.views
                if probe.graphics.target_info(model.id_value(view.Id))['supported'] and
                not probe.graphics.target_info(model.id_value(view.Id))['controlled']]
    finally:
        probe._allow_close = True
        probe.Close()
    assert tids, 'Requires a writable target'
    tid = tids[0]
    first, second = service.records[:2]

    def checkbox(dialog, source, identity, selected):
        listing = dialog.filter_list if source else dialog.target_list
        item = next(item for item in listing.Items if item.Tag == identity)
        control = item.Content.Children[0]
        assert control.IsEnabled
        events = []
        control.Checked += lambda s, e: events.append('Checked')
        control.Unchecked += lambda s, e: events.append('Unchecked')
        control.IsChecked = selected
        assert events == ['Checked' if selected else 'Unchecked']
        # No render_task/render_graphics calls here: only production handlers
        # reached by the real WPF routed checkbox event may refresh the grid.

    def editable(dialog, fid, target_id):
        pair = (target_id, fid)
        assert not dialog.together and workspace.ui.chosen(dialog.graphics_mode) == 'single'
        assert dialog.graphics_pair_scope() == [pair], ('Wrong Per Filter scope', dialog.graphics_pair_scope())
        assert pair in dialog.pair_before, 'Checking did not populate native target snapshot'
        assert not dialog.graphics_read_errors and dialog._graphics_editable, dialog.status.Text
        for key in ('transparency', 'visibility', 'halftone', 'projection_line_color', 'projection_line_pattern_id'):
            assert dialog.field_controls[key][1].IsEnabled, 'Disabled after Checked: ' + key
        assert not dialog.field_controls['halftone'][1].IsThreeState
        assert not any(dialog.pair_patches.values()) and not any(
            dialog.source_values(pair) for pair in dialog.pair_sources), 'Checking manufactured a proposal'

    for target_first in (False, True):
        dialog = workspace.WorkspaceDialog(service, uidoc, browser_ids=[tid])
        try:
            dialog.set_source('project')
            assert not dialog.together
            if target_first:
                checkbox(dialog, False, tid, True)
                checkbox(dialog, True, first.id, True)
            else:
                checkbox(dialog, True, first.id, True)
                checkbox(dialog, False, tid, True)
            editable(dialog, first.id, tid)
            control = dialog.field_controls['transparency'][1]
            control.Text = '37'
            assert dialog.pair_patches[(tid, first.id)]['transparency']['value'] == 37
            dialog.revert_field('transparency')
            halftone = dialog.field_controls['halftone'][1]
            original_halftone = bool(halftone.IsChecked)
            halftone.IsChecked = not original_halftone
            assert dialog.pair_patches[(tid, first.id)]['halftone']['value'] is (not original_halftone)
            dialog.revert_field('halftone')
            results.append('actual {}-first checkbox events immediately load editable Per Filter TARGET cells; native numeric event creates scoped patch without mode toggle'.format(
                'target' if target_first else 'filter'))
            if not target_first:
                checkbox(dialog, True, first.id, False)
                # Actual list inspection event focuses an unchecked row, which
                # previously kept graphics_scope empty after checking another.
                dialog.filter_list.SelectedItem = next(item for item in dialog.filter_list.Items if item.Tag == first.id)
                assert dialog.filters.focused == first.id
                checkbox(dialog, True, second.id, True)
                editable(dialog, second.id, tid)
                assert dialog.filters.focused == second.id
                # Another checked filter keeps its existing navigation focus.
                checkbox(dialog, True, first.id, True)
                assert dialog.filters.focused == second.id
                checkbox(dialog, True, second.id, False)
                editable(dialog, first.id, tid)
                checkbox(dialog, False, tid, False)
                assert not dialog.field_controls['transparency'][1].IsEnabled
                checkbox(dialog, False, tid, True)
                editable(dialog, first.id, tid)
                # Select visible is another explicit check boundary.
                checkbox(dialog, True, first.id, False)
                dialog.select_visible(True)
                assert dialog.filters.focused in dialog.filters.checked
                assert dialog._graphics_editable
                results.append('actual unchecked-row inspection plus first/new check recovers Per Filter scope; focused uncheck selects remaining check; target uncheck/recheck refreshes without Together')
        finally:
            dialog._allow_close = True
            dialog.Close()
    dialog = workspace.WorkspaceDialog(service, uidoc)
    try:
        controlled = next((dialog.graphics.target_info(model.id_value(view.Id))
                           for view in service.views
                           if dialog.graphics.target_info(model.id_value(view.Id))['controlled'] and
                           dialog.graphics.membership(dialog.graphics.target_info(
                               model.id_value(view.Id))['controlling_template_id'])), None)
        assert controlled, 'Requires a Filters-controlled view with attached template filters'
        view_id, template_id = controlled['id'], controlled['controlling_template_id']
        dialog.browser_ids = [view_id]
        dialog.switch_target('browser')
        dialog.set_source('selected', [view_id])
        fid = next(fid for fid in dialog.visible_filters if fid in dialog.source_map)
        checkbox(dialog, True, fid, True)
        assert dialog.origins == [template_id]
        item = next(item for item in dialog.target_list.Items if item.Tag == view_id)
        assert not item.Content.Children[0].IsEnabled
        assert not dialog._graphics_editable
        names = item.Content.Children[1]
        button = next(control for control in names.Children if isinstance(control, Button))
        button.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
        editable(dialog, fid, template_id)
        assert template_id in dialog.targets.checked and view_id not in dialog.targets.checked
        original = dialog.original_value((template_id, fid), 'transparency')
        dialog.field_controls['transparency'][1].Text = str((original + 1) % 101)
        plan = dialog.build_plan()
        assert len(plan['rows']) == 1
        assert plan['rows'][0]['key'] == (template_id, fid)
        assert plan['rows'][0]['action'] == 'Update', plan['rows'][0]['reason']
        assert not plan['rows'][0]['sources']
        results.append('actual Select controlling template button immediately populates editable Per Filter cells; source equals target template allows custom Update without mode toggle or source copy')
    finally:
        dialog._allow_close = True
        dialog.Close()
    assert doc.IsModified == original_modified
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(results),
            'checks': results, 'model_writes': 0,
            'not_run': ['attended ribbon mouse/keyboard reproduction']}


def run_source_draft_lifecycle(doc, uidoc):
    """Native registry ownership, including unpublished batch-mint failures."""
    assert doc.Application.VersionNumber == '2023', 'Revit 2023 ONLY'
    original_modified = doc.IsModified
    service = model.FilterService(doc)
    record = next(record for record in service.records if record.usage)
    other = next(item for item in service.records if item.id != record.id)
    source_id = model.id_value(record.usage[0].Id)
    dialog = workspace.WorkspaceDialog(service, uidoc, browser_ids=[source_id])
    results = []
    try:
        dialog.set_source('selected', [source_id])
        # Use a supported non-controlled destination (it need not be distinct
        # for this read-only mint/ownership test; no plan/write is invoked).
        tid = next(model.id_value(view.Id) for view in service.views
                   if dialog.graphics.target_info(model.id_value(view.Id))['supported'] and
                   not dialog.graphics.target_info(model.id_value(view.Id))['controlled'])
        dialog.filters.checked.add(record.id)
        dialog.filters.focus(record.id)
        dialog.targets.checked.add(tid)
        dialog.render_graphics()
        pair = (tid, record.id)
        native = dialog.graphics
        def retained_tokens():
            return set(item['token'] for records in dialog.pair_sources.values()
                       for item in records if item['values'])
        def exact_registry():
            assert set(native._source_loads) == retained_tokens(), 'Unreferenced token leak or lost inactive draft'
        assert dialog.load_from_source()
        for index in range(3):
            old = retained_tokens()
            assert dialog.load_from_source(True)
            exact_registry()
            assert len(native._source_loads) == 1 and not old.intersection(native._source_loads)
        # A partial reload must keep the previous channel/token alive.
        dialog.graphics_check.IsChecked = False
        assert dialog.load_from_source(True)
        exact_registry()
        assert len(native._source_loads) == 2
        dialog.graphics_check.IsChecked = True
        # Inactive pairs survive pruning, state and same-service continuation.
        dialog.targets.checked.clear()
        dialog.render_graphics()
        dialog.prune_source_drafts()
        exact_registry()
        saved = dialog.state()
        resumed = workspace.WorkspaceDialog(service, uidoc, state=saved)
        try:
            resumed.prune_source_drafts()
            assert resumed.graphics is native
            assert resumed.pair_sources == dialog.pair_sources
            exact_registry()
        finally:
            resumed._allow_close = True
            resumed.Close()
        dialog.targets.checked.add(tid)
        dialog.render_graphics()
        results.append('native repeated replacement releases old tokens; partial-channel tokens plus inactive pair/ReValue continuation references survive pruning')

        # Mint filter one successfully, then fail/cancel filter two. The first
        # unpublished token must be reclaimed while all old pair drafts remain.
        dialog.filters.checked.add(other.id)
        dialog.source_map[other.id] = list(dialog.origins)
        dialog.change_graphics_mode(True)
        sources_before = deepcopy(dialog.pair_sources)
        tokens_before = retained_tokens()
        class FailedBatch(object):
            calls = 0
            mode = 'fail'
            def __getattr__(self, key):
                return getattr(native, key)
            def load_source_draft(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return native.load_source_draft(record.id, list(dialog.origins),
                        source_candidate_ids=list(dialog.source_candidate_ids),
                        include_graphics=True, include_visibility=True)
                if self.mode == 'cancel':
                    dialog.cancel_read()
                raise ValueError('Failed/cancelled second-filter source-mint fixture')
        boundary = FailedBatch()
        dialog.graphics = boundary
        try:
            for mode in ('fail', 'cancel'):
                boundary.mode, boundary.calls = mode, 0
                try:
                    dialog.load_from_source(True)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Incomplete Together batch published draft')
                assert boundary.calls == 2
                assert dialog.pair_sources == sources_before
                assert set(native._source_loads) == tokens_before
        finally:
            dialog.graphics = native
        results.append('native first-filter token minted then second-filter failure/cancellation: no partial publication; finally-prune releases pending token and retains all old guards')
        dialog.filters.checked = set([record.id])
        dialog.change_graphics_mode(False)
        for field in list(dialog.source_values(pair)):
            dialog.revert_field(field)
        exact_registry()
        assert not native._source_loads
        assert dialog.load_from_source(True)
        # Controller refresh fixture models a definition removed elsewhere;
        # only Python service records change, never the Revit document.
        original_refresh, original_records = service.refresh, service.records
        try:
            service.refresh = lambda: setattr(service, 'records',
                [item for item in original_records if item.id != record.id])
            dialog.refresh_after_definition()
            assert pair not in dialog.pair_sources and not native._source_loads
        finally:
            service.refresh, service.records = original_refresh, original_records
        dialog.refresh_after_definition()
        dialog.render_graphics()
        assert dialog.load_from_source(True)
        dialog.discard_and_close(False)
        assert not native._source_loads
        results.append('last-field Revert, simulated definition-removal refresh and explicit Discard release native source token ownership')
        assert doc.IsModified == original_modified
        return {'version': doc.Application.VersionNumber, 'checks_passed': len(results),
                'checks': results, 'model_writes': 0}
    finally:
        dialog._allow_close = True
        dialog.Close()


def run_graphics_grid(doc, uidoc):
    """Actual unshown IronPython WPF + native reads/plan; no Show or writes."""
    assert doc.Application.VersionNumber == '2023', 'This acceptance run is Revit 2023 ONLY'
    original_modified = doc.IsModified
    service = model.FilterService(doc)
    candidates = [(record, view) for record in service.records for view in record.usage
                  if model.supports_filters(view)]
    assert candidates, 'Requires an existing attached filter for native original-value checks'
    record, target = candidates[0]
    dialog = workspace.WorkspaceDialog(service, uidoc)
    results = []
    try:
        # Selected source membership is browse-only even with both channels on.
        tid = model.id_value(target.Id)
        dialog.set_source('selected', [tid])
        dialog.filters.checked.add(record.id)
        dialog.filters.focus(record.id)
        pair = (tid, record.id)
        dialog.targets.checked.add(tid)
        dialog.Width, dialog.Height = 1440, 960
        dialog.render_graphics()
        original = deepcopy(dialog.pair_before[pair])
        assert original['attached']
        for key in original['values']:
            if key != 'detail_level':
                assert dialog.aggregate_value(key) == original['values'][key], key
        assert not dialog.pair_patches and not dialog.pair_sources
        request = dialog.request()
        assert request['include_graphics'] is False and request['include_visibility'] is False
        assert not request['origin_ids'] and not request['pair_sources']
        assert dialog.graphics_check.IsChecked and dialog.visibility_check.IsChecked
        results.append('actual selected TARGET populated on demand; source membership/options do not generate patches or copy requests')

        def layout():
            dialog.graphics_root.Measure(Size(664, 250))
            dialog.graphics_root.Arrange(Rect(0, 0, 664, 250))
            dialog.UpdateLayout()
        def position():
            layout()
            dialog.graphics_scroll.ScrollToVerticalOffset(950)
            layout()
            offset = dialog.graphics_scroll.VerticalOffset
            assert offset > 0, 'Actual compact scroll viewport did not move'
            return offset
        def retained(offset):
            layout()
            assert abs(dialog.graphics_scroll.VerticalOffset - offset) < 1, (
                'Graphics viewport reset', offset, dialog.graphics_scroll.VerticalOffset)
        color = 'projection_line_color'
        offset = position()
        dialog.patch_field(color, {'op': 'set', 'value': (20, 40, 60)})
        retained(offset)
        _, swatch = dialog.field_controls[color]
        assert swatch.Background.Color.R == 20
        dialog.clear_controls[color].RaiseEvent(RoutedEventArgs(Button.ClickEvent))
        retained(offset)
        status, swatch = dialog.field_controls[color]
        assert dialog.pair_patches[pair][color] == {'op': 'set', 'value': None}
        assert status.Text == 'Unset'
        assert not swatch.ReadLocalValue(Button.BackgroundProperty).__class__.__name__ == 'SolidColorBrush'
        assert swatch.Content == 'Unset'
        revert = swatch.ContextMenu.Items[0]
        assert revert.Header == 'Revert this edit'
        revert.RaiseEvent(RoutedEventArgs(workspace.MenuItem.ClickEvent))
        retained(offset)
        assert color not in dialog.pair_patches[pair]
        assert dialog.aggregate_value(color) == original['values'][color]
        assert dialog.pair_before[pair] == original
        results.append('actual tiny colour remove control immediately Unset/blank; context Revert restores immutable original TARGET; changed blue/clear amber, scroll retained')

        for descriptor in dialog.graphics.FIELDS:
            if not descriptor['editable'] or not descriptor.get('can_clear'):
                continue
            key = descriptor['key']
            dialog.patch_field(key, {'op': 'clear'})
            assert dialog.field_controls[key][0].Text == 'Unset', key
            expected = None if descriptor['kind'] == 'color' else -1
            assert dialog.pair_patches[pair][key] == {'op': 'set', 'value': expected}
            dialog.revert_field(key)
            assert key not in dialog.pair_patches[pair]
        assert 'halftone' not in dialog.clear_controls and 'visibility' not in dialog.clear_controls
        assert 'transparency' not in dialog.clear_controls
        assert not any(key.endswith('_visible') for key in dialog.clear_controls)
        results.append('all 14 clearable cells use canonical None/-1; boolean Off and transparency 0 have no reset control')

        offset = position()
        dialog.set_numeric('transparency', '42')
        retained(offset)
        assert dialog.field_controls['transparency'][1].Text == '42'
        dialog.field_controls['transparency'][1].Text = '55'
        retained(offset)
        assert dialog.pair_patches[pair]['transparency']['value'] == 55
        dialog.revert_field('transparency')
        retained(offset)
        control = dialog.field_controls['halftone'][1]
        control.IsChecked = not original['values']['halftone']
        retained(offset)
        assert dialog.pair_patches[pair]['halftone']['value'] == (not original['values']['halftone'])
        dialog.field_controls['halftone'][1].IsChecked = True
        dialog.field_controls['halftone'][1].IsChecked = None  # WPF True -> indeterminate click cycle
        assert dialog.pair_patches[pair]['halftone']['value'] is False
        assert dialog.field_controls['halftone'][1].IsChecked is False
        dialog.revert_field('halftone')
        retained(offset)
        offset = position()
        dialog.resource_selected('projection_line_weight', 4, list(dialog.graphics_pair_scope()))
        retained(offset)
        assert dialog.pair_patches[pair]['projection_line_weight']['value'] == 4
        dialog.revert_field('projection_line_weight')
        assert all(row.ActualHeight <= 44 for row in dialog.graphics_grid.RowDefinitions)
        assert dialog.graphics_grid.ActualHeight < 400
        results.append('actual WPF numeric, checkbox and resource return retain viewport; seven 36px grid rows (<400px); no cards/word Keep/Clear controls')

        # Native source load freezes exact channels in only current pairs.
        assert dialog.load_from_source()
        loaded = deepcopy(dialog.pair_sources[pair][0])
        assert len(loaded['values']) == 21
        assert 'enabled' not in loaded['values'] and 'detail_level' not in loaded['values']
        assert dialog.request()['pair_sources'][pair][0]['fields'] == list(loaded['values'])
        for key, value in loaded['values'].items():
            assert dialog.aggregate_value(key) == value
        dialog.patch_field(color, {'op': 'clear'})
        dialog.revert_field(color)
        assert color not in dialog.source_values(pair) and color not in dialog.pair_patches[pair]
        assert dialog.aggregate_value(color) == original['values'][color]
        before_options = deepcopy(dialog.pair_sources)
        dialog.graphics_check.IsChecked = False
        dialog.visibility_check.IsChecked = False
        assert dialog.pair_sources == before_options
        assert not dialog.load_source_button.IsEnabled
        dialog.graphics_check.IsChecked = True
        dialog.visibility_check.IsChecked = True
        assert dialog.pair_sources == before_options
        graphic_before = dict((key, value) for key, value in dialog.source_values(pair).items()
                              if key != 'visibility')
        old_graphic_token = dialog.pair_sources[pair][0]['token']
        dialog.graphics_check.IsChecked = False
        assert dialog.load_from_source(True)
        assert dict((key, value) for key, value in dialog.source_values(pair).items()
                    if key != 'visibility') == graphic_before
        assert dialog.pair_sources[pair][0]['token'] == old_graphic_token
        assert len(dialog.pair_sources[pair]) == 2
        visibility_token = next(record['token'] for record in dialog.pair_sources[pair]
                                if 'visibility' in record['values'])
        dialog.graphics_check.IsChecked = True
        dialog.visibility_check.IsChecked = False
        assert dialog.load_from_source(True)
        assert next(record['token'] for record in dialog.pair_sources[pair]
                    if 'visibility' in record['values']) == visibility_token
        assert len(dialog.source_values(pair)) == 21
        dialog.visibility_check.IsChecked = True
        results.append('sequential native Visibility-only/Graphics-only loads preserve the other channel and its original guarded token, without flattening source provenance')
        saved = dialog.state()
        resumed = workspace.WorkspaceDialog(service, uidoc, state=saved)
        try:
            assert resumed.graphics is dialog.graphics
            assert resumed.pair_sources == dialog.pair_sources and resumed.pair_before == dialog.pair_before
        finally:
            resumed._allow_close = True
            resumed.Close()
        results.append('native exact Load freezes 20 graphics + visibility (incl Unset), no enabled/detail; field Revert removes source independently; next-load checkboxes preserve draft/token; state preserves registry/originals')

        other = next((view for view in service.views if model.supports_filters(view) and
                      model.id_value(view.Id) != tid), None)
        assert other is not None, 'Requires a second target to verify no replay'
        other_pair = (model.id_value(other.Id), record.id)
        dialog.targets.checked.add(other_pair[0])
        dialog.render_graphics()
        assert other_pair not in dialog.pair_sources and other_pair not in dialog.pair_patches
        assert other_pair not in dialog.request()['pair_sources']
        # Isolated display fixture creates a deterministic Mixed boolean,
        # never mutates the native snapshot/model. Actual WPF is still tested.
        dialog.pair_before[other_pair] = deepcopy(dialog.pair_before[other_pair])
        dialog.pair_before[other_pair]['attached'] = True
        dialog.pair_before[other_pair]['values']['visibility'] = not dialog.proposed_value(pair, 'visibility')
        dialog.render_graphics()
        assert dialog.aggregate_value('visibility') == ('mixed',)
        assert dialog.field_controls['visibility'][1].IsChecked is None
        assert other_pair not in dialog.pair_patches
        results.append('new checked target retains fresh own values/no source replay; isolated display fixture verifies real WPF Mixed indeterminate without proposals')
        dialog.targets.checked = set([other_pair[0]])
        dialog.render_graphics()
        actual_other = dialog.graphics.snapshot(other_pair[0], record.id, refresh=True)
        assert dialog.pair_before[other_pair] == actual_other
        assert not dialog.source_values(other_pair)
        dialog.targets.checked = set([tid])
        dialog.render_graphics()
        assert dialog.pair_before[pair] == original
        dialog.targets.checked.add(other_pair[0])
        dialog.render_graphics()
        results.append('same-filter same-count target swap refreshes actual untouched TARGET snapshot; return to edited target preserves immutable before/source draft')
        before_sources = deepcopy(dialog.pair_sources)
        before_patches = deepcopy(dialog.pair_patches)
        native = dialog.graphics
        class FailedLoad(object):
            """Presentation failure fixture; no native mutations."""
            mode = 'fail'
            calls = 0
            def __getattr__(self, key):
                return getattr(native, key)
            def load_source_draft(self, *args, **kwargs):
                self.calls += 1
                if self.mode == 'cancel':
                    dialog.cancel_read()
                    return {'token': 'unused-fixture', 'values': {}}
                raise ValueError('Explicit failed source read fixture')
        failed = FailedLoad()
        dialog.graphics = failed
        try:
            for mode in ('fail', 'cancel'):
                failed.mode = mode
                try:
                    dialog.load_from_source(True)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Failed/cancelled load silently populated a default draft')
                assert dialog.pair_sources == before_sources and dialog.pair_patches == before_patches
            assert failed.calls == 2
        finally:
            dialog.graphics = native
        before_read = deepcopy(dialog.pair_before)
        class FailedTargetRead(object):
            def __getattr__(self, key):
                return getattr(native, key)
            def read_batch(self, pairs, **kwargs):
                assert kwargs['max_pairs'] == 5 and kwargs['refresh'] is True
                return {'snapshots': {}, 'errors': {pair: 'Explicit target-read failure fixture'},
                        'cancelled': False, 'remaining': []}
        dialog.graphics = FailedTargetRead()
        try:
            dialog.populate_target_values(dialog.graphics_pair_scope())
            dialog.render_graphics()
            assert dialog.pair_before == before_read and not dialog._graphics_editable
            assert not dialog.load_source_button.IsEnabled
            assert 'failed/incomplete' in dialog.graphics_context.Text
        finally:
            dialog.graphics = native
        dialog.inspect_graphics()
        assert not dialog.graphics_read_errors and dialog._graphics_editable
        dialog.set_source('project')
        assert not dialog.load_source_button.IsEnabled
        assert not dialog.graphics_check.IsEnabled and not dialog.visibility_check.IsEnabled
        assert dialog.pair_sources == before_sources
        results.append('explicit failed/cancelled Load and target-read fixtures publish no partial/default values, disable edits/Load and recover on explicit retry; All Project retains guarded drafts')
        dialog.set_source('selected', [tid])
        dialog.source_map[record.id] = [tid, other_pair[0]]
        variant_values = dict((f['key'], original['values'][f['key']])
                              for f in native.FIELDS if f['editable'])
        class VariantChoice(object):
            """Two-variant presentation fixture; successful mint is native."""
            choices = []
            def __getattr__(self, key):
                return getattr(native, key)
            def source_variants(self, *args, **kwargs):
                different = dict(variant_values)
                different[color] = (19, 39, 59)
                return {'complete': True, 'groups': [
                    {'origin_ids': [tid], 'values': dict(variant_values)},
                    {'origin_ids': [other_pair[0]], 'values': different}]}
            def load_source_draft(self, fid, origins, source_candidate_ids=None,
                                  source_choice=None, include_graphics=True, include_visibility=True,
                                  cancel=None, progress=None):
                self.choices.append(source_choice)
                if source_choice is None:
                    raise ValueError('Multiple source variants; choose an explicit source')
                assert source_choice == tid
                return native.load_source_draft(fid, [tid], source_candidate_ids=[tid],
                    source_choice=tid, include_graphics=include_graphics,
                    include_visibility=include_visibility, cancel=cancel, progress=progress)
        variant = VariantChoice()
        dialog.graphics = variant
        try:
            choices_before = deepcopy(dialog.pair_sources)
            assert dialog.load_from_source(True) is False
            assert variant.choices == [None] and not dialog.source_choices
            assert dialog.pair_sources == choices_before
            explicit = next(control for control in dialog.variant_host.Children
                            if isinstance(control, Button) and control.Tag == (record.id, tid))
            explicit.RaiseEvent(RoutedEventArgs(Button.ClickEvent))
            assert dialog.source_choices[record.id] == tid
            assert dialog.pair_sources == choices_before
            assert dialog.load_from_source(True) is True
            assert variant.choices == [None, tid]
        finally:
            dialog.graphics = native
        results.append('two-variant UI fixture requires explicit per-filter choice (actual button event), never defaults to first source or changes drafts on choice; chosen load mints native guarded values')
        class SourceUnion(object):
            """One filter in a subset of a multi-source selected union."""
            calls = 0
            def __getattr__(self, key):
                return getattr(native, key)
            def load_source_draft(self, fid, origins, source_candidate_ids=None,
                                  source_choice=None, include_graphics=True, include_visibility=True,
                                  cancel=None, progress=None):
                self.calls += 1
                assert origins == [tid, other_pair[0]], 'Mint must receive the FULL selected effective-origin union'
                assert source_candidate_ids == [tid, other_pair[0]], 'Original source candidates must stay intact'
                assert dialog.source_map[fid] == [tid], 'Fixture filter exists in only one selected source'
                return native.load_source_draft(fid, [tid], source_candidate_ids=[tid],
                    source_choice=tid, include_graphics=include_graphics,
                    include_visibility=include_visibility, cancel=cancel, progress=progress)
        union = SourceUnion()
        dialog.graphics = union
        dialog.origins = [tid, other_pair[0]]
        dialog.source_candidate_ids = [tid, other_pair[0]]
        dialog.source_map[record.id] = [tid]
        try:
            assert dialog.load_from_source(True) is True
            assert union.calls == 1
            assert all(dialog.source_values(active_pair) for active_pair in dialog.graphics_pair_scope())
        finally:
            dialog.graphics = native
        results.append('subset-membership union fixture passes full selected origins/candidates to mint, with native guarded values returned')
        assert doc.IsModified == original_modified
        return {'version': doc.Application.VersionNumber, 'checks_passed': len(results),
                'checks': results, 'model_writes': 0,
                'not_run': ['shown ribbon-window/keyboard/high-DPI; attended native picker confirm/Cancel; model writes']}
    finally:
        dialog._allow_close = True
        dialog.Close()

def run_graphics_presentation(doc, uidoc):
    return run_graphics_grid(doc, uidoc)


def run(doc, uidoc):
    original_modified = doc.IsModified
    checks = []
    selection = workspace.CheckedSelection([2, 99])
    selection.focus(7)
    assert selection.checked == set([2, 99]) and selection.focused == 7
    selection.toggle(2, True, [1, 2, 3, 4])
    selection.toggle(4, True, [1, 2, 3, 4], True)
    assert selection.checked == set([2, 3, 4, 99])
    assert selection.hidden([1, 2]) == 3
    selection.clear()
    assert not selection.checked and selection.focused == 7
    checks.append('independent focus/checks, stable Shift range, hidden counts and global clear')

    service = model.FilterService(doc)
    dialog = workspace.WorkspaceDialog(service, uidoc)
    try:
        assert dialog.catalogue is None
        assert not dialog.filters.checked and not dialog.targets.checked
        assert dialog.include_graphics and dialog.include_visibility
        assert dialog.plan is None and not dialog.pair_patches
        assert not dialog.graphics._cache
        if not model.supports_filters(uidoc.ActiveView):
            assert not dialog.origins and not dialog.source_map
            assert 'Unavailable' in dialog.source_label.Text
            assert any(not item['supported'] for item in dialog.target_candidates)
            assert not dialog.graphics_check.IsEnabled
        checks.append('zero launch project catalogue and no attachment plan/patch; source defaults checked')
        ids = [r.id for r in service.records[:3]]
        target_ids = [model.id_value(view.Id) for view in service.views if model.supports_filters(view)]
        target_a = target_ids[0] if target_ids else model.id_value(uidoc.ActiveView.Id)
        target_b = target_ids[1] if len(target_ids) > 1 else None
        if ids:
            dialog.set_source('project')
            dialog.filters.checked.update(ids[:2])
            dialog.filters.focus(ids[0])
            dialog.refresh_lists()
            dialog.render_task()
            assert not dialog.graphics_check.IsEnabled and not dialog.visibility_check.IsEnabled
            assert not dialog.request()['include_graphics'] and not dialog.request()['include_visibility']
            assert dialog.request()['origin_ids'] == []
            assert dialog.request()['source_candidate_ids'] == []
            assert dialog.catalogue is None
            dialog.filter_search.Text = '__does_not_match_workspace_test__'
            assert not dialog.visible_filters and set(ids[:2]).issubset(dialog.filters.checked)
            dialog.filter_selected.IsChecked = True
            assert set(dialog.visible_filters) == dialog.filters.checked
            dialog.reset_search(True)
            assert set(ids[:2]).issubset(dialog.filters.checked)
            checks.append('All Project source channels inactive, search/reset retains hidden checks without target catalogue')

            provenance = workspace.WorkspaceDialog(service, uidoc)
            provenance_native = provenance.graphics
            class SourceBoundary(object):
                """UI contract stub only; backend tests cover real preflight.

                No native assignment is changed and no write method is called.
                """
                candidate, template_one, template_two = 900000001, 900000002, 900000003
                effective = template_one
                accepted = 0
                def __getattr__(self, key):
                    return getattr(provenance_native, key)
                def target_info(self, identity):
                    if identity in (self.candidate, self.template_one, self.template_two):
                        return {'id': identity, 'name': 'Provenance fixture ' + str(identity),
                                'view_type': 'FloorPlan', 'is_template': identity != self.candidate,
                                'supported': True}
                    return provenance_native.target_info(identity)
                def effective_sources(self, identities):
                    if identities == [self.candidate]:
                        return [self.effective] if self.effective is not None else []
                    return provenance_native.effective_sources(identities)
                def source_filters(self, identities):
                    if all(identity in (self.template_one, self.template_two) for identity in identities):
                        return {ids[0]: list(identities)}
                    return provenance_native.source_filters(identities)
                def plan(self, request, completed=(), cancel=None, progress=None):
                    assert request['source_candidate_ids'] == [] and request['origin_ids'] == []
                    assert request['pair_sources'][(target_a, ids[0])][0]['token'] == 'guarded-ui-fixture'
                    return {'rows': [{'key': (target_a, ids[0]), 'action': 'Add',
                                      'reason': 'UI boundary receipt stub', 'delta': {}}],
                            'source_candidate_ids': [self.candidate],
                            'expected_effective': [self.template_one]}
                def load_source_draft(self, fid, origins, source_candidate_ids=None,
                                      source_choice=None, include_graphics=True,
                                      include_visibility=True, cancel=None, progress=None):
                    assert origins == [self.template_one] and source_candidate_ids == [self.candidate]
                    values = dict((f['key'], provenance.original_value((target_a, fid), f['key']))
                                  for f in self.FIELDS if f['editable'])
                    return {'token': 'guarded-ui-fixture', 'values': values,
                            'source_id': self.template_one, 'origin_ids': list(origins)}
                def apply(self, plan):
                    assert plan['source_candidate_ids'] == [self.candidate]
                    if [self.effective] != plan['expected_effective']:
                        raise ValueError('Source template assignment changed; reload and review.')
                    self.accepted += 1
                    raise AssertionError('The UI stale-source check unexpectedly accepted its stub plan')
            boundary = SourceBoundary()
            provenance.graphics = boundary
            try:
                # Duplicated selected candidates are deduplicated without
                # replacing the original view with its controlling template.
                provenance.set_source('selected', [boundary.candidate, boundary.candidate])
                provenance.filters.checked.add(ids[0])
                provenance.targets.checked.add(target_a)
                assert provenance.source_candidate_ids == [boundary.candidate]
                assert provenance.origins == [boundary.template_one]
                provenance.render_graphics()
                assert provenance.request()['pair_sources'] == {}
                provenance.load_from_source()
                provenance.build_plan()
                old_plan = provenance.plan
                saved_provenance = provenance.state()
                assert saved_provenance['source_candidate_ids'] == [boundary.candidate]
                assert saved_provenance['effective_origin_ids'] == [boundary.template_one]
                for changed in (boundary.template_two, None):
                    boundary.effective = changed
                    try:
                        provenance.apply_attachments()
                    except ValueError as error:
                        assert 'Source template assignment changed' in unicode(error)
                    else:
                        raise AssertionError('Stale original-source provenance reached an accepted write')
                    assert boundary.accepted == 0 and provenance.plan is old_plan
                boundary.effective = boundary.template_two
                resumed = workspace.WorkspaceDialog(service, uidoc, state=saved_provenance)
                try:
                    assert resumed.source_candidate_ids == [boundary.candidate]
                    assert resumed.origins == [boundary.template_two]
                    assert resumed.plan is old_plan
                finally:
                    resumed._allow_close = True
                    resumed.Close()
                provenance.browser_ids = [boundary.candidate]
                provenance.set_source('browser')
                assert provenance.request()['source_candidate_ids'] == []
                assert provenance.request()['origin_ids'] == []
                assert provenance.pair_sources[(target_a, ids[0])][0]['token'] == 'guarded-ui-fixture'
                provenance.set_source('current')
                current = model.id_value(uidoc.ActiveView.Id)
                assert provenance.source_candidate_ids == ([current] if model.supports_filters(uidoc.ActiveView) else [])
                provenance.set_source('project')
                assert provenance.request()['source_candidate_ids'] == []
                checks.append('UI provenance boundary stub: explicit guarded Load retains original selected-source assignment through browse/ReValue; stale assignment rejected by apply boundary; no automatic request (native guards tested separately)')
            finally:
                provenance._allow_close = True
                provenance.Close()

            dialog.change_graphics_mode(True)
            assert not dialog.graphics_pair_scope()
            assert not dialog.field_controls['transparency'][1].Parent.IsEnabled
            try:
                dialog.patch_field('transparency', {'op': 'set', 'value': 35})
            except ValueError as error:
                assert 'destinations' in unicode(error)
            else:
                raise AssertionError('Custom edits without destinations created a future broadcast')
            assert not dialog.pair_patches and not dialog.request()['patches']
            dialog.targets.checked.add(target_a)
            dialog.render_graphics()
            dialog.patch_field('transparency', {'op': 'set', 'value': 35})
            before = dict((pair, workspace.independent_patch(p)) for pair, p in dialog.pair_patches.items())
            dialog.change_graphics_mode(False)
            dialog.change_graphics_mode(True)
            assert before == dialog.pair_patches
            if len(ids) > 2:
                dialog.filters.checked.add(ids[2])
                assert (target_a, ids[2]) not in dialog.pair_patches
            dialog.filters.checked.discard(ids[0])
            assert ids[0] not in dialog.request()['filter_ids'] and (target_a, ids[0]) in dialog.pair_patches
            assert (target_a, ids[0]) not in dialog.request()['pair_patches']
            if target_b is not None and len(ids) > 1:
                dialog.selection_changed(False, target_b, True)
                assert not any(pair[0] == target_b for pair in dialog.pair_patches)
                assert not any(pair[0] == target_b for pair in dialog.request()['pair_patches'])
                dialog.targets.checked.discard(target_a)
                dialog.render_graphics()
                dialog.patch_field('halftone', {'op': 'set', 'value': True})
                assert not any('halftone' in patch for pair, patch in dialog.pair_patches.items()
                               if pair[0] == target_a)
                dialog.targets.checked.add(target_a)
                dialog.render_graphics()
                assert dialog.patch_display('transparency')[1].startswith('Mixed')
                dialog.targets.checked.discard(target_b)
                dialog.render_graphics()
                dialog.patch_field('transparency', {'op': 'keep'})
                assert all('transparency' not in patch for pair, patch in dialog.pair_patches.items()
                           if pair[0] == target_a and pair[1] in dialog.filters.checked)
                assert all(patch.get('halftone', {}).get('value') is True
                           for pair, patch in dialog.pair_patches.items() if pair[0] == target_b)
                assert not any(pair[0] == target_b for pair in dialog.request()['pair_patches'])
                # Same-count destination swap must rebind numeric editor scope,
                # not retain handlers for A when only B is selected.
                old_numeric = dialog.field_controls['transparency'][1]
                chooser_scope = list(dialog.graphics_pair_scope())
                dialog.targets.checked = set([target_b])
                dialog.render_graphics()
                old_numeric.Text = '71'
                assert 'transparency' not in dialog.pair_patches[(target_a, ids[1])]
                assert 'transparency' not in dialog.pair_patches[(target_b, ids[1])]
                try:
                    dialog.resource_selected('projection_line_weight', 4, chooser_scope)
                except ValueError as error:
                    assert 'no draft was changed' in unicode(error)
                else:
                    raise AssertionError('An old resource chooser silently edited a new target scope')
                dialog.field_controls['transparency'][1].Text = '62'
                assert dialog.pair_patches[(target_b, ids[1])]['transparency']['value'] == 62
                assert 'transparency' not in dialog.pair_patches[(target_a, ids[1])]
                dialog.targets.checked = set([target_a])
            checks.append('pair-only Together edits require destinations; no replay onto new filters/targets, same-count swaps rebind, inactive pairs retained, Revert scoped to active pairs')
            dialog.filters.checked.add(ids[0])
            dialog.filters.focus(ids[0])
            dialog.change_graphics_mode(False)
            numeric = dialog.field_controls['transparency'][1]
            numeric.Text = 'not a number'
            assert dialog.pair_graphic_inputs[(target_a, ids[0])]['transparency'] == 'not a number'
            assert 'transparency' in dialog.pair_graphic_errors[(target_a, ids[0])]
            try:
                dialog.build_plan()
            except ValueError as error:
                assert 'Correct active graphic drafts' in unicode(error)
            else:
                raise AssertionError('Invalid raw graphics input did not block planning')
            dialog.change_graphics_mode(True)
            dialog.change_graphics_mode(False)
            assert dialog.field_controls['transparency'][1].Text == 'not a number'
            dialog.patch_field('transparency', {'op': 'keep'})
            assert 'transparency' not in dialog.pair_graphic_errors.get((target_a, ids[0]), {})
            dialog.patch_field('transparency', {'op': 'set', 'value': 35})
            checks.append('invalid numeric graphic keystrokes persist across modes, block planning, and Revert explicitly removes invalid/custom contribution')

            dialog.filters.checked.update(ids[:2])
            dialog.select_tab('Rename')
            for record in dialog.active_rename_records():
                assert dialog.rename_proposals[record.id] == record.name
            dialog.rename_proposals[ids[0]] = 'Draft continuation only'
            dialog.rename_completed.add(ids[-1])
            dialog.render_rename()
            assert ids[-1] not in dialog.rename_rows
            saved = dialog.state()
            dialog._allow_close = True
            dialog.Close()
            resumed = workspace.WorkspaceDialog(service, uidoc, state=saved)
            try:
                assert resumed.rename_proposals[ids[0]] == 'Draft continuation only'
                assert ids[-1] in resumed.rename_completed
                resumed.select_tab('Rename')
                assert ids[-1] not in resumed.rename_rows
                assert resumed.catalogue is None
                checks.append('rename current-name defaults, continuation proposals, completed rows never resurrect on refresh/tab')
            finally:
                resumed._allow_close = True
                resumed.Close()

            dialog = workspace.WorkspaceDialog(service, uidoc)
            dialog.set_source('project')
            dialog.filters.checked.update(ids[:2])
            dialog.filters.focus(ids[0])
            dialog.select_tab('Graphics')
            assert not dialog.previous_button.IsEnabled
            if len(ids) > 1:
                assert dialog.next_button.IsEnabled
                dialog.navigate(1)
                assert not dialog.next_button.IsEnabled and dialog.previous_button.IsEnabled
            dialog.pair_patches[(target_a, ids[0])] = {'transparency': {'op': 'set', 'value': 35}}
            dialog.clear_selection()
            assert not dialog.filters.checked and not dialog.targets.checked and dialog.plan is None
            assert (target_a, ids[0]) in dialog.pair_patches
            assert dialog.catalogue is None
            checks.append('shared checked navigator endpoints; Clear Selection clears every selection without erasing inactive custom values/loading Project')

            editable = next((r for r in service.records if not r.problem), None)
            if editable:
                dialog.filters.checked.add(editable.id)
                dialog.filters.focus(editable.id)
                dialog.select_tab('Edit Rules')
                editor = dialog.editors[editable.id]
                assert not editor.dirty
                assert model.definition_signature(editor.categories(), editor.read_tree()) == editable.signature
                # An incomplete typed row must survive suspension, not be saved
                # or silently reduced to a category-only definition.
                editor.add_node(editor.tree, False)
                editor.rule_rows[-1].value.Text = 'unparsed draft text'
                assert editor.dirty
                dialog.select_tab('Rename')
                dialog.rename_proposals[editable.id] = 'Invalid < proposal retained'
                dialog.handoff_revalue()
                assert dialog.result[0] == 'revalue'
                assert dialog.result[2][editable.id] == 'Invalid < proposal retained'
                saved = dialog.state()
                assert saved['rule_drafts'][editable.id]['dirty']
                assert saved['rule_drafts'][editable.id]['raw'][-1]['text'] == 'unparsed draft text'
                assert saved['pair_patches'][(target_a, ids[0])]['transparency']['value'] == 35
                assert not saved['patches']
                assert saved['graphics_service'] is dialog.graphics
                restored = workspace.WorkspaceDialog(service, uidoc, state=saved)
                try:
                    restored.select_tab('Edit Rules')
                    replacement = restored.editors[editable.id]
                    assert replacement.dirty
                    assert replacement.rule_rows[-1].value.Text == 'unparsed draft text'
                    try:
                        replacement.read_tree()
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('Incomplete rule draft was silently treated as valid')
                    class ClosingEvent(object):
                        Cancel = False
                    event = ClosingEvent()
                    restored.closing(restored, event)
                    assert event.Cancel and restored.management.startswith('Pending work')
                    assert restored.rename_proposals[editable.id] == 'Invalid < proposal retained'
                    assert restored.pair_patches[(target_a, ids[0])]['transparency']['value'] == 35
                    assert not restored.request()['pair_patches']  # all targets still unchecked
                    restored.targets.checked.add(target_a)
                    assert restored.request()['pair_patches'][(target_a, ids[0])]['transparency']['value'] == 35
                    if target_b is not None:
                        restored.targets.checked = set([target_b])
                        assert (target_b, ids[0]) not in restored.request()['pair_patches']
                    checks.append('actual typed editor reuse, incomplete raw draft survives ReValue close/state/restore; ordinary close offers inline save/discard/stay')
                finally:
                    restored._allow_close = True
                    restored.Close()

                # Controller-only receipt simulation: native rename behavior is
                # exercised separately by the definition suite, not by this stub.
                mock = workspace.WorkspaceDialog(service, uidoc)
                original_rename = service.rename_partial
                try:
                    mock.set_source('project')
                    mock.filters.checked.add(editable.id)
                    mock.select_tab('Rename')
                    service.rename_partial = lambda records, names: {
                        'renamed': [], 'unchanged': [r.id for r in records], 'errors': {}}
                    mock.rename()
                    assert not mock.rename_rows and editable.id in mock.rename_completed
                    mock.select_tab('Graphics')
                    mock.select_tab('Rename')
                    mock.select_visible(True)
                    mock.select_tab('Rename')
                    assert editable.id not in mock.rename_rows
                    checks.append('controller receipt simulation removes unchanged rows; tab/refresh/Select visible do not resurrect completed rows')
                finally:
                    service.rename_partial = original_rename
                    mock._allow_close = True
                    mock.Close()
                dialog = workspace.WorkspaceDialog(service, uidoc)

            pair_dialog = workspace.WorkspaceDialog(service, uidoc)
            try:
                pair_dialog.set_source('project')
                pair_dialog.filters.checked.update(ids[:2])
                pair_dialog.filters.focus(ids[0])
                pair_dialog.targets.checked.add(target_a)
                pair_dialog.change_graphics_mode(True)
                pair_dialog.patch_field('projection_line_color', {'op': 'set', 'value': (12, 34, 56)})
                if target_b is not None:
                    pair_dialog.targets.checked = set([target_b])
                    pair_dialog.change_graphics_mode(True)
                    pair_dialog.field_controls['transparency'][1].Text = 'invalid B only'
                    pair_dialog.targets.checked = set([target_a])
                    pair_dialog.change_graphics_mode(False)
                    assert pair_dialog.field_controls['transparency'][1].Text != 'invalid B only'
                pair_dialog.select_tab('Rename')
                pair_dialog.handoff_revalue()
                saved_pairs = pair_dialog.state()
                continued = workspace.WorkspaceDialog(service, uidoc, state=saved_pairs)
                try:
                    assert continued.pair_patches == pair_dialog.pair_patches
                    assert continued.pair_graphic_inputs == pair_dialog.pair_graphic_inputs
                    assert continued.pair_graphic_errors == pair_dialog.pair_graphic_errors
                    assert continued.dirty_graphics_pairs == pair_dialog.dirty_graphics_pairs
                    assert continued.request()['patches'] == {}
                    assert all(pair[0] == target_a for pair in continued.request()['pair_patches'])
                    if target_b is not None:
                        continued.build_plan()  # inactive B raw errors cannot block valid A requests
                        assert all(r['key'][0] == target_a for r in continued.plan['rows'])
                        continued.targets.checked = set([target_b])
                        continued.select_tab('Graphics')
                        assert continued.field_controls['transparency'][1].Text == 'invalid B only'
                        continued.patch_field('transparency', {'op': 'keep'})
                        assert not continued.pair_graphic_errors.get((target_b, ids[0]), {})
                        assert continued.pair_patches[(target_a, ids[0])]['projection_line_color']['value'] == (12, 34, 56)
                        assert (target_a, ids[0]) not in continued.request()['pair_patches']
                    checks.append('ReValue suspension preserves per-target custom/invalid raw drafts and dirty state; restored active request excludes unchecked pairs; Revert never erases other targets')
                finally:
                    continued._allow_close = True
                    continued.Close()
            finally:
                pair_dialog._allow_close = True
                pair_dialog.Close()

            # Native snapshot+plan+approval is read-only. An actual opposite
            # visibility value guarantees an existing Update, without mutation.
            approved = workspace.WorkspaceDialog(service, uidoc)
            try:
                candidate = None
                for record in service.records:
                    for view in record.usage:
                        tid = model.id_value(view.Id)
                        info = approved.graphics.target_info(tid)
                        if info['supported'] and not info['controlled']:
                            candidate = (record, tid)
                            break
                    if candidate:
                        break
                if candidate:
                    record, tid = candidate
                    approved.set_source('project')
                    approved.filters.checked.add(record.id)
                    approved.filters.focus(record.id)
                    approved.targets.checked.add(tid)
                    current = approved.graphics.snapshot(tid, record.id, fields=['visibility'])
                    approved.patch_field('visibility', {'op': 'set', 'value': not current['values']['visibility']})
                    approved.build_plan()
                    assert any(r['action'] == 'Update' for r in approved.plan['rows'])
                    approved.approve()
                    assert any(r.get('approved') for r in approved.plan['rows'])
                    opaque = approved.plan
                    approved.change_graphics_mode(True)
                    approved.change_graphics_mode(False)
                    assert approved.plan is opaque
                    # Explicit edits and check changes invalidate reviewed
                    # tokens; reprocessing requires fresh approval.
                    approved.patch_field('halftone', {'op': 'set', 'value': True})
                    assert approved.plan is None
                    approved.build_plan()
                    current_view_only = (not uidoc.ActiveView.IsTemplate and
                                         tid == model.id_value(uidoc.ActiveView.Id))
                    assert any(r.get('approved') for r in approved.plan['rows']) == current_view_only
                    approved.approve()
                    approved.selection_changed(False, tid, False)
                    assert approved.plan is None and (tid, record.id) in approved.pair_patches
                    approved.selection_changed(False, tid, True)
                    approved.build_plan()
                    assert any(r.get('approved') for r in approved.plan['rows']) == current_view_only
                    checks.append('native read-only existing-update plan approval survives mode toggle only; pair edits and uncheck/recheck invalidate approval while retaining inactive drafts')
            finally:
                approved._allow_close = True
                approved.Close()

            legacy = workspace.WorkspaceDialog(service, uidoc, state={
                'checked_filters': [ids[0]], 'source_mode': 'project',
                'patches': {ids[0]: {'transparency': {'op': 'set', 'value': 27}}},
                'graphics_dirty': True})
            try:
                assert legacy.unassigned_graphics and not legacy.pair_patches
                legacy.targets.checked.add(target_a)
                assert not legacy.request()['pair_patches']
                legacy.assign_legacy_graphics()
                assert not legacy.unassigned_graphics
                assert legacy.request()['pair_patches'][(target_a, ids[0])]['transparency']['value'] == 27
                if target_b is not None:
                    legacy.targets.checked.add(target_b)
                    assert (target_b, ids[0]) not in legacy.request()['pair_patches']
                checks.append('legacy zero-target drafts stay explicitly unassigned; assignment is a separate deliberate current-pair action, never a future broadcast')
            finally:
                legacy._allow_close = True
                legacy.Close()

            source_record = next((r for r in service.records if not r.problem and r.usage), None)
            if source_record and len(service.records) > 1:
                # The native save service is replaced with an explicit receipt
                # stub. This tests UI context after creation, NOT native Create.
                creator = workspace.WorkspaceDialog(service, uidoc)
                original_save = service.save
                try:
                    creator.set_source('selected', [model.id_value(source_record.usage[0].Id)])
                    origin_ids = list(creator.origins)
                    original_ids = [fid for fid in creator.source_map
                                    if any(r.id == fid and not r.problem for r in service.records)]
                    if original_ids:
                        original_id = original_ids[0]
                        receipt_id = next(r.id for r in service.records if r.id != original_id)
                        original = service.get_record(original_id)
                        creator.filters.checked.add(original_id)
                        creator.source_choices[original_id] = creator.source_map[original_id][0]
                        creator.filter_search.Text = '__retain_existing_query__'
                        creator.targets.checked.add(origin_ids[0])
                        creator.new_definition(service.duplicate_draft(original))
                        new = creator.new_editor
                        new.acknowledged_ids = tuple(sorted(r.id for r in service.matches(new.categories(), new.read_tree())))
                        service.save = lambda name, categories, tree, existing, acknowledged: receipt_id
                        creator.save_definition(new)
                        assert creator.source_mode == 'selected' and creator.origins == origin_ids
                        assert creator.filter_search.Text == '__retain_existing_query__'
                        assert original_id in creator.filters.checked and receipt_id in creator.filters.checked
                        assert creator.targets.checked == set([origin_ids[0]])
                        assert creator.source_choices[original_id] == creator.source_map[original_id][0]
                        assert creator.request()['source_choices'] == {}
                        assert creator.request()['source_exempt_ids'] == []
                        assert creator.request()['pair_sources'] == {}
                        assert receipt_id in creator.visible_filters
                        checks.append('controller Create receipt stub: reveal/check new independent definition without replacing browse source/query/targets; no automatic copy request')
                finally:
                    service.save = original_save
                    creator._allow_close = True
                    creator.Close()

            if len(ids) > 1:
                fixture = workspace.WorkspaceDialog(service, uidoc)
                try:
                    fixture.set_source('project')
                    fixture.filters.checked.update(ids[:2])
                    tid = model.id_value(uidoc.ActiveView.Id)
                    fixture.targets.checked.add(tid)
                    native = fixture.graphics
                    class ReadOnlyReceipts(object):
                        """Only a controller receipt stub; no native mutation."""
                        applied = False
                        def __getattr__(self, key):
                            return getattr(native, key)
                        def apply(self, plan):
                            self.applied = True
                            assert any(r['action'] == 'Add' for r in plan['rows'])
                            return {'counts': {'added': 1, 'updated': 0, 'unapproved': 1},
                                    'receipts': []}
                        def plan(self, request, completed=(), cancel=None, progress=None):
                            return {'rows': [
                                {'key': (tid, ids[0]), 'action': 'Completed', 'reason': 'fixture receipt'},
                                {'key': (tid, ids[1]), 'action': 'Update', 'approved': False,
                                 'reason': 'fixture pending update', 'delta': {}, 'impact': []}]}
                    receipts = ReadOnlyReceipts()
                    fixture.graphics = receipts
                    fixture.plan = {'rows': [
                        {'key': (tid, ids[0]), 'action': 'Add', 'reason': 'fixture Add'},
                        {'key': (tid, ids[1]), 'action': 'Update', 'approved': False,
                         'reason': 'fixture Update', 'delta': {}, 'impact': []}]}
                    assert not fixture.changes.IsExpanded
                    fixture.apply_attachments()
                    assert receipts.applied and not fixture.changes.IsExpanded
                    assert fixture.plan['rows'][0]['action'] == 'Completed'
                    assert fixture.plan['rows'][1]['action'] == 'Update'
                    assert fixture.apply_button.IsEnabled
                    assert fixture.apply_button.Content == 'Review 1 Existing Update'
                    assert 'Additional approval required for 1' in fixture.attachment_summary.Text
                    assert 'additional approval' in fixture.changes.Header
                    checks.append('controller receipt stub: ready Add bypasses optional Changes/unapproved update; pending Update gets explicit review notification and action')
                finally:
                    fixture._allow_close = True
                    fixture.Close()

            # Deferred catalogue is shared between target Project and source
            # picker. Reset never starts it; Clear explicitly starts it.
            assert dialog.catalogue is None
            dialog.reset_search(False)
            assert dialog.catalogue is None
            dialog.targets.checked.add(model.id_value(uidoc.ActiveView.Id))
            dialog.clear_targets()
            assert dialog.target_mode == 'project' and not dialog.targets.checked
            assert dialog.catalogue is not None
            cached = dialog.catalogue
            dialog.open_source_picker()
            assert dialog.catalogue is cached
            previous_sources = list(dialog.source_ids)
            dialog.picker_checks.clear()
            dialog.cancel_source_picker()
            assert dialog.source_ids == previous_sources and dialog.catalogue is cached
            outside = next((info for info in cached if info['id'] != model.id_value(uidoc.ActiveView.Id)
                            and not info.get('controlled')), None)
            if outside:
                dialog.targets.checked.add(outside['id'])
                dialog.switch_target('view')
                assert outside['id'] not in dialog.visible_targets
                dialog.target_search.Text = '__no_target_match__'
                dialog.target_selected.IsChecked = True
                assert outside['id'] in dialog.visible_targets
                assert dialog.catalogue is cached
            checks.append('Clear explicitly loads Project after unticking all; source picker shares catalogue; Cancel preserves previous sources')

        measured = []
        for width, height in ((1440, 960), (900, 720), (760, 640)):
            dialog.Width, dialog.Height = width, height
            dialog.adapt_layout(None, None)
            dialog.Content.Measure(Size(width - 32, height - 48))
            dialog.Content.Arrange(Rect(0, 0, width - 32, height - 48))
            dialog.UpdateLayout()
            assert dialog.body.ActualWidth > 0 and dialog.body.ActualHeight > 0
            assert dialog.actions.ActualHeight > 0
            assert dialog.centre.ActualWidth > 180
            assert dialog.centre.ActualHeight > 120
            if dialog.left.Visibility == Visibility.Visible:
                assert dialog.filter_list.ActualHeight > 80
            measured.append({'width': width, 'height': height, 'centre': dialog.centre.ActualWidth,
                             'actions': dialog.actions.ActualHeight,
                             'pane_height': dialog.centre.ActualHeight,
                             'filter_list_height': dialog.filter_list.ActualHeight})
        checks.append('actual WPF control construction/measure at wide, compact and minimum; primary action strip remains outside scrollers')
        editable = next((r for r in service.records if not r.problem), None)
        if editable:
            dialog.filters.checked.add(editable.id)
            dialog.filters.focus(editable.id)
            dialog.select_tab('Edit Rules')
            def measure():
                dialog.Content.Measure(Size(728, 592))
                dialog.Content.Arrange(Rect(0, 0, 728, 592))
                dialog.UpdateLayout()
            measure()
            assert dialog.rule_save_button.ActualHeight > 0
            assert dialog.editors[editable.id].embedded.ActualHeight > 50
            dialog.new_definition()
            measure()
            assert dialog.new_create_button.ActualHeight > 0
            assert dialog.new_editor.embedded.ActualHeight > 50
            dialog.cancel_new()
            dialog.select_tab('Rename')
            measure()
            assert dialog.rename_button.ActualHeight > 0
            assert dialog.tab_hosts['Rename'].Children[0].Children[1].ActualHeight > 50
            dialog.review_delete()
            measure()
            assert dialog.delete_commit_button.ActualHeight > 0
            dialog.show_normal()
            dialog.review_purge()
            measure()
            assert dialog.delete_commit_button.ActualHeight > 0
            dialog.show_normal()
            dialog.analyse_duplicates()
            measure()
            assert dialog.management == 'Analyse Duplicates'
            dialog.show_normal()
            checks.append('same-dialog rule/new/rename/delete/purge/duplicate-analysis panels construct at minimum with primary buttons and draft viewports')
        # Construct native picker, never Show: verifies API object availability,
        # not ownership, OK/Cancel or keyboard return.
        picker = workspace.UI.ColorSelectionDialog()
        try:
            assert picker.IsValidObject
        finally:
            picker.Dispose()
        checks.append('native colour picker constructs/disposes without unattended modal; ownership not exercised')
        assert doc.IsModified == original_modified
        return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks),
                'checks': checks, 'layouts': measured, 'model_writes': 0,
                'not_run': ['attended colour picker ownership/OK/Cancel',
                            'real button/revalue/matching handoff', 'write/rollback/Undo',
                            'keyboard focus/high DPI visual review']}
    finally:
        dialog._allow_close = True
        dialog.Close()
