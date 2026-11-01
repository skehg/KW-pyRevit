# -*- coding: utf-8 -*-
"""Focused regression tests for application flow, row focus and value completion."""
import uuid
from System.Windows import Size, Rect
from System.Windows.Input import Mouse, MouseButton, MouseButtonEventArgs
from pyrevit import DB
import filter_model as fm
import filter_ui as ui


def choose(control, value):
    for item in control.Items:
        if item.Tag == value:
            control.SelectedItem = item
            return
    raise AssertionError('Missing choice: ' + str(value))


def run(doc, uidoc):
    service = fm.FilterService(doc)
    prefix = 'FM improvement ' + str(uuid.uuid4())[:8]
    wall_category = fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))
    comments = fm.id_value(DB.ElementId(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS))
    offset = fm.id_value(DB.ElementId(DB.BuiltInParameter.WALL_BASE_OFFSET))
    wall_type = DB.FilteredElementCollector(doc).OfClass(DB.WallType).FirstElement()
    level = DB.FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
    checks = []
    windows = []
    exact_numbers = [1.2345678901234, 1.2345678905678]
    spaced = prefix.replace(' ', '  ')
    texts = [prefix, prefix, spaced, prefix.lower()]

    def fixtures():
        walls = []
        for index, text in enumerate(texts):
            wall = DB.Wall.Create(doc, DB.Line.CreateBound(
                DB.XYZ(600, 600 + index * 20, 0), DB.XYZ(610, 600 + index * 20, 0)),
                wall_type.Id, level.Id, 10.0, 0.0, False, True)
            assert wall.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(text)
            assert wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).Set(exact_numbers[index % 2])
            walls.append(wall)
        assert wall_type.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_COMMENTS).Set(prefix + ' type')
        return walls
    walls = service.atomic('Suggestion fixtures', fixtures)
    metadata = service.eligible_parameters([wall_category])
    info = next(p for p in metadata if p.id == comments)
    numeric = next(p for p in metadata if p.id == offset)
    type_info = next(p for p in metadata if p.id == fm.id_value(
        DB.ElementId(DB.BuiltInParameter.ALL_MODEL_TYPE_COMMENTS)))
    options = service.assigned_values([wall_category], info)
    values = [v for v, text in options]
    assert values.count(prefix) == 1
    assert spaced in values and prefix.lower() in values
    assert prefix + ' type' in dict(service.assigned_values([wall_category], type_info))
    other = fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Doors))
    assert prefix not in dict(service.assigned_values([other], info))
    assert service.assigned_values([wall_category], info) is options
    checks.append('suggestions deduplicate exact values, retain case/whitespace, include types and isolate categories/parameter IDs')

    numeric_options = service.assigned_values([wall_category], numeric)
    assert all(v in dict(numeric_options) for v in exact_numbers)
    assert len(set(text for v, text in numeric_options)) == len(numeric_options)
    positive = next((p for p in metadata if p.id > 0 and p.profile in ('text', 'integer', 'number')), None)
    if positive:
        options = service.assigned_values([wall_category], positive)
        assert isinstance(options, list)
    checks.append('numeric suggestions keep exact raw values with unambiguous project-unit labels')

    editor = ui.EditorDialog(service)
    windows.append(editor)
    editor.loading = True
    for check in editor.category_checks:
        check.IsChecked = check.Tag == wall_category
    editor.load_parameters()
    editor.render_rules()
    editor.loading = False
    editor.add_node(editor.tree, False)
    row = editor.rule_rows[0]
    choose(row.param, comments)
    choose(row.operator, 'Equals')
    assert row.value.IsEditable and prefix in [item.Tag for item in row.value.Items]
    choose(row.value, prefix)
    assert row.read()['value'] == prefix
    row.value.SelectedItem = None
    row.value.Text = prefix + ' free text'
    assert row.read()['value'] == prefix + ' free text'
    choose(row.operator, 'NotEquals')
    assert row.value.Text == prefix + ' free text'
    assert prefix in [item.Tag for item in row.value.Items]
    choose(row.operator, 'Contains')
    assert row.value.Items.Count == 0 and row.read()['value'] == prefix + ' free text'
    choose(row.operator, 'HasValue')
    assert row.read()['value'] is None and str(row.value.Visibility) == 'Collapsed'
    checks.append('Equals/NotEquals offer editable assigned suggestions; other operators preserve manual text without suggestions')

    choose(row.param, offset)
    choose(row.operator, 'Equals')
    choose(row.value, exact_numbers[0])
    assert row.read()['value'] == exact_numbers[0]
    choose(row.operator, 'NotEquals')
    assert row.read()['value'] == exact_numbers[0]
    row.epsilon.Text = '0.0009'
    assert row.read()['value'] == exact_numbers[0] and row.read()['epsilon'] == 0.0009
    row.value.Text = '2.5'
    expected = DB.UnitFormatUtils.TryParse(doc.GetUnits(), numeric.spec, '2.5')[1]
    assert row.read()['value'] == expected
    checks.append('choosing numeric completion preserves exact operand through operator/tolerance changes; manual text parses units')

    categories = [wall_category]
    tree = fm.group([{'kind': 'rule', 'pid': comments, 'family': 'string',
                      'op': 'Equals', 'value': prefix, 'epsilon': None}])
    first = service.save(prefix + ' first', categories, tree)
    second = service.save(prefix + ' second', categories, fm.group(),
                          acknowledged=[r.id for r in service.matches(categories, fm.group())])
    service.refresh()
    manager = ui.ManagerDialog(service, uidoc, checked=[first], focused=first)
    windows.append(manager)
    item = next(i for i in manager.list.Items if i.Tag == second)
    manager.Content.Measure(Size(manager.Width - 32, manager.Height - 48))
    manager.Content.Arrange(Rect(0, 0, manager.Width - 32, manager.Height - 48))
    manager.list.ScrollIntoView(item)
    manager.UpdateLayout()
    name_label = item.Content.Children[1]
    click = MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Left)
    click.RoutedEvent = Mouse.PreviewMouseDownEvent
    name_label.RaiseEvent(click)
    assert manager.focused == second and manager.list.SelectedItem == item
    assert manager.checked == set([first]) and not manager.row_checks[second].IsChecked
    assert manager.description.Children[0].Text == service.get_record(second).name
    manager.row_checks[second].IsChecked = True
    assert manager.checked == set([first, second]) and manager.focused == second
    manager.right_click(item, None)
    assert manager.checked == set([first, second])
    manager.row_checks[second].IsChecked = False
    manager.right_click(item, None)
    assert manager.checked == set([second]) and manager.row_checks[second].IsChecked
    checks.append('routed name click focuses summary without ticking; checkbox and context-menu scopes remain independent')

    original_review, original_results, original_alert = ui.ReviewDialog.show, ui.ResultsDialog.show, ui.forms.alert
    events = []
    messages = []
    def approve(window, owner=None):
        events.append(window.heading.Text)
        return window.selected()
    def unexpected_results(window, owner=None):
        raise AssertionError('Successful application must not show results')
    ui.ReviewDialog.show = approve
    ui.ResultsDialog.show = unexpected_results
    ui.forms.alert = lambda message, **kwargs: messages.append(message)
    try:
        target = next(v for v in service.views if not v.IsTemplate and fm.supports_filters(v)
                      and not service.template_controls(doc.GetElement(v.ViewTemplateId)))
        target_before = [fm.id_value(i) for i in target.GetFilters()]
        manager.checked = set([first])
        manager.resolve_target = lambda: target
        manager.apply_clicked(None, None)
        assert not messages and events == ['Review Application']
        assert first in [fm.id_value(i) for i in target.GetFilters()]
        assert '1 added / 0 already applied' in manager.status.Text
        manager.apply_clicked(None, None)
        assert not messages and events == ['Review Application', 'Review Application']
        assert '0 added / 1 already applied' in manager.status.Text
        assert all(i in [fm.id_value(j) for j in target.GetFilters()] for i in target_before)
        original_apply = service.apply
        def fail(records, target):
            raise ValueError('Injected apply failure')
        service.apply = fail
        manager.apply_clicked(None, None)
        assert messages == ['Injected apply failure'] and manager.status.Text == messages[0]
        service.apply = original_apply
    finally:
        ui.ReviewDialog.show, ui.ResultsDialog.show, ui.forms.alert = original_review, original_results, original_alert
    checks.append('apply success/already-attached skip results and refresh status; failures remain explicit')

    service.atomic('Change suggestion fixture', lambda: walls[0].get_Parameter(
        DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(prefix + ' refreshed'))
    service.refresh()
    assert not service.value_suggestions
    assert prefix + ' refreshed' in dict(service.assigned_values([wall_category], info))
    checks.append('refresh invalidates assigned-value cache')
    for window in windows:
        window.Close()
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks), 'checks': checks,
            'positive_parameter_checked': positive.id if positive else None}
