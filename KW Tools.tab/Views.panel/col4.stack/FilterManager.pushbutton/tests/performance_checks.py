# -*- coding: utf-8 -*-
"""Read-only Revit/WPF regressions for cached browsing and dialog cancellation."""
from System.Diagnostics import Stopwatch
from System.Windows import Size, Rect
from System.Windows.Input import ModifierKeys
import filter_model as fm
import filter_ui as ui


def run(doc, uidoc):
    service = fm.FilterService(doc)
    assert len(service.records) >= 4
    checks, timings = [], {}
    original_tokens = dict((r.id, (r.token, r.signature)) for r in service.records)
    selection = set(fm.id_value(i) for i in uidoc.Selection.GetElementIds())

    for record in service.records:
        templates = set(fm.id_value(v.Id) for v in record.usage if v.IsTemplate)
        expected = set(fm.id_value(v.Id) for v in service.views if not v.IsTemplate
                       and fm.id_value(v.ViewTemplateId) in templates
                       and service.template_controls(doc.GetElement(v.ViewTemplateId)))
        assert set(fm.id_value(v.Id) for v in record.inherited) == expected
    checks.append('indexed inherited usage matches the full per-filter view scan')

    numeric = [r for r in service.records if has_double(r.tree)]
    for record in numeric:
        before = service.describe(record.tree)
        service.eligible_parameters(record.categories)
        assert service.describe(record.tree) == before
    checks.append('lightweight double-rule metadata preserves authoring-metadata unit formatting')

    categories = service.records[0].categories
    eligible = service.eligible_parameters(categories)
    assert service.eligible_parameters(list(reversed(categories))) is eligible
    specimens = service.specimens
    service.refresh()
    assert not service.eligible_cache and not service.value_suggestions
    assert service.specimens is not specimens
    assert service.eligible_parameters(categories) is not eligible
    checks.append('eligibility and specimen caches are reused and invalidated on refresh')

    manager = ui.ManagerDialog(service, uidoc, checked=[service.records[0].id], search_scope='all')
    original_methods, calls = {}, {}
    names = ('eligible_parameters', 'assigned_values', 'collect_matches',
             'category_specimens', 'refresh', 'filter_names')
    for name in names:
        original_methods[name] = getattr(service, name)
        calls[name] = 0

        def watch(name=name):
            def counted(*args, **kwargs):
                calls[name] += 1
                return original_methods[name](*args, **kwargs)
            return counted
        setattr(service, name, watch())

    original_editor_show = ui.EditorDialog.show
    original_rename_show = ui.RenameDialog.show

    def measure(name, action):
        clock = Stopwatch.StartNew()
        value = action()
        clock.Stop()
        timings[name] = clock.Elapsed.TotalMilliseconds
        return value

    def cancel(window, owner=None):
        window.Close()
        return None

    try:
        items = dict((item.Tag, item) for item in manager.list.Items)
        defaults = ui.ManagerDialog(service, uidoc)
        try:
            assert ui.chosen(defaults.search_scope) == 'name'
        finally:
            defaults.Close()
        queries = ['Comments', 'Walls', service.records[0].name,
                   'no matching filter 012345', '']
        for item in manager.search_scope.Items:
            manager.search_scope.SelectedItem = item
            for query in queries:
                manager.search.Text = query.upper()
                scope = item.Tag
                expected = []
                for record in service.records:
                    fields = {'name': record.name, 'category': ', '.join(record.category_names),
                              'rule': record.rules, 'all': u'{} {} {}'.format(
                                  record.name, ', '.join(record.category_names), record.rules)}
                    if query.lower() in fields[scope].lower():
                        expected.append(record.id)
                assert [row.Tag for row in manager.list.Items] == expected
                assert service.records[0].id in manager.checked
            manager.search.Text = 'Walls'
            restored = ui.ManagerDialog(service, uidoc, **manager.state())
            try:
                assert ui.chosen(restored.search_scope) == scope
                assert restored.search.Text == 'Walls'
                assert [row.Tag for row in restored.list.Items] == [
                    row.Tag for row in manager.list.Items]
            finally:
                restored.Close()
        checks.append('Name is the default; all four scopes match only their case-insensitive fields and survive state handoff')

        manager.search.Text = ''
        manager.category.SelectedItem = manager.category.Items[1]
        category = ui.chosen(manager.category)
        assert [row.Tag for row in manager.list.Items] == [
            record.id for record in service.records if category in record.categories]
        manager.category.SelectedIndex = 0
        manager.Width, manager.Height = manager.MinWidth, manager.MinHeight
        manager.adapt_layout(None, None)
        manager.Content.Measure(Size(manager.Width - 32, manager.Height - 48))
        manager.Content.Arrange(Rect(0, 0, manager.Width - 32, manager.Height - 48))
        manager.UpdateLayout()
        assert manager.search.ActualWidth > 40 and manager.search_scope.ActualWidth >= 100
        checks.append('scope composes with the category selector and both search controls fit the minimum manager layout')

        for index, query in enumerate(['a', 'al', 'all', 'no matching filter 012345', '']):
            measure('search_{}'.format(index), lambda query=query: setattr(manager.search, 'Text', query))
            assert [item.Tag for item in manager.list.Items] == [
                r.id for r in service.records if query in r.search_text]
        assert all(items[item.Tag] is item for item in manager.list.Items)
        assert service.records[0].id in manager.checked
        checks.append('search reuses row controls and cached rule text without losing hidden checks')

        measure('select', lambda: manager.select_row(
            service.records[3].id, getattr(ModifierKeys, 'None')))
        measure('summary', manager.show_description)
        assert all(calls[name] == 0 for name in names), calls
        ui.EditorDialog.show = cancel
        ui.RenameDialog.show = cancel
        measure('new_cancel', lambda: manager.open_editor(None))
        assert calls['eligible_parameters'] == 1  # Empty-category editor initialization.
        measure('rename_open_cancel', lambda: manager.rename_clicked(None, None))
        assert calls['filter_names'] == 1
        rename = ui.RenameDialog(service, service.records[:3])
        try:
            names_read = calls['filter_names']
            rename.update_preview(None, None)
            rename.rows[0][2].Text = 'FM performance preview only'
            assert calls['filter_names'] == names_read
        finally:
            rename.Close()
        assert calls['eligible_parameters'] == 1
        assert all(calls[name] == 0 for name in names
                   if name not in ('filter_names', 'eligible_parameters')), calls
        checks.append('search, summaries, rename previews and Cancel never scan eligibility, values, matches or usage')
        names_read = calls['filter_names']
        try:
            service.validate_names({service.records[0].id: service.records[1].name})
        except ValueError:
            pass
        else:
            raise AssertionError('Write validation must reject an existing name')
        assert calls['filter_names'] == names_read + 1
        checks.append('rename text validation reuses a name snapshot; write validation still reads live names')

        # A non-null editor result and a successful rename must still refresh.
        def accepted_editor(window, owner=None):
            window.Close()
            return service.records[0].id

        def accepted_rename(window, owner=None):
            window.Close()
            return True

        ui.EditorDialog.show = accepted_editor
        ui.RenameDialog.show = accepted_rename
        manager.open_editor(None)
        assert calls['refresh'] == 1
        manager.rename_clicked(None, None)
        assert calls['refresh'] == 2
        assert manager.row_records is service.records
        assert all(items[item.Tag] is not item for item in manager.list.Items)
        checks.append('successful dialog results still refresh definitions, usage and row controls')
    finally:
        ui.EditorDialog.show = original_editor_show
        ui.RenameDialog.show = original_rename_show
        for name, method in original_methods.items():
            setattr(service, name, method)
        manager.Close()

    assert dict((r.id, (r.token, r.signature)) for r in service.records) == original_tokens
    assert set(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) == selection
    return {'version': doc.Application.VersionNumber, 'filters': len(service.records),
            'views': len(service.views), 'checks_passed': len(checks),
            'checks': checks, 'timings_ms': timings}


def has_double(node):
    if node['kind'] == 'group':
        return any(has_double(child) for child in node['children'])
    return node['kind'] == 'rule' and node['family'] == 'double'
