# -*- coding: utf-8 -*-
"""Noninteractive WPF/controller checks inside each supported Revit runtime."""
import uuid
from System.Windows import Size, Rect, Visibility
from pyrevit import DB
import filter_model as fm
import filter_ui as ui


def choose(control, value):
    for item in control.Items:
        if item.Tag == value:
            control.SelectedItem = item
            return
    raise AssertionError('Control lacks expected typed choice: ' + str(value))


def leaves(node):
    if node['kind'] == 'group':
        return [r for c in node['children'] for r in leaves(c)]
    return [node]


def run(doc, uidoc):
    s = fm.FilterService(doc)
    checks = []
    prefix = 'FM BETA UI test ' + str(uuid.uuid4())[:8]
    wall = fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))
    comments = fm.id_value(DB.ElementId(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS))
    editor = ui.EditorDialog(s)
    editor.loading = True
    for check in editor.category_checks:
        check.IsChecked = check.Tag == wall
    editor.load_parameters()
    editor.render_rules()
    editor.loading = False
    editor.name.Text = prefix
    editor.add_node(editor.tree, False)
    row = editor.rule_rows[0]
    choose(row.param, comments)
    choose(row.operator, 'Contains')
    row.value.Text = 'Typed text'
    assert editor.read_tree()['children'][0]['value'] == 'Typed text'
    editor.add_node(editor.tree, True)
    assert editor.rule_rows[0].value.Text == 'Typed text'
    nested = editor.tree['children'][1]
    editor.add_node(nested, False)
    row = editor.rule_rows[1]
    choose(row.param, comments)
    choose(row.operator, 'HasNoValue')
    assert row.value.Visibility == Visibility.Collapsed
    assert editor.read_tree()['children'][1]['children'][0]['value'] is None
    editor.save()
    fid = editor.result
    assert fid is not None
    s.refresh()
    r = s.get_record(fid)
    checks.append('new editor typed choices, nested add, draft preservation and presence hides operand')

    edit = ui.EditorDialog(s, r)
    assert fm.definition_signature(r.categories, edit.read_tree()) == r.signature
    edit.rule_rows[0].value.Text = 'Changed text'
    assert edit.rule_rows[0].node.get('native') is None
    assert leaves(edit.read_tree())[0]['value'] == 'Changed text'
    edit.save()
    s.refresh()
    r = s.get_record(fid)
    assert 'Changed text' in r.rules
    checks.append('edit invalidates original native operand only when changed and saves directly')

    numeric = next(p for p in s.eligible_parameters([wall]) if p.profile == 'number')
    precise = 1.2345678901234
    numeric_tree = fm.group([{'kind': 'rule', 'pid': numeric.id, 'family': 'double',
                             'op': 'Equals', 'value': precise, 'epsilon': 0.000123456789}])
    numeric_id = s.save(prefix + ' Double', [wall], numeric_tree,
                        acknowledged=[r.id for r in s.matches([wall], numeric_tree)])
    s.refresh()
    numeric_editor = ui.EditorDialog(s, s.get_record(numeric_id))
    nr = numeric_editor.rule_rows[0]
    choose(nr.operator, 'NotEquals')
    assert leaves(numeric_editor.read_tree())[0]['value'] == precise
    nr.epsilon.Text = '0.0009'
    changed = leaves(numeric_editor.read_tree())[0]
    assert changed['value'] == precise and changed['epsilon'] == 0.0009
    nr.value.Text = '2.5'
    expected = DB.UnitFormatUtils.TryParse(doc.GetUnits(), numeric.spec, '2.5')[1] if (
        DB.UnitUtils.IsMeasurableSpec(numeric.spec)) else 2.5
    assert leaves(numeric_editor.read_tree())[0]['value'] == expected
    numeric_editor.Close()
    checks.append('operator/tolerance-only changes preserve exact double operands; explicit numeric input parses project units')

    manager = ui.ManagerDialog(s, uidoc, checked=[fid], focused=fid)
    assert manager.edit_button.IsEnabled
    manager.search.Text = 'no possible match ' + prefix
    assert fid in manager.checked and manager.list.Items.Count == 0
    manager.unselect_all(None, None)
    assert not manager.checked and manager.search.Text.startswith('no possible match')
    manager.select_unused(None, None)
    assert fid in manager.checked and manager.search.Text == '' and not manager.applied_only.IsChecked
    checks.append('hidden checks survive search; Unselect All clears hidden checks; Select Unused reveals checked rows')

    review = ui.ReviewDialog('Delete Test', '', [(fid, r.name, r.usage_text)], acknowledgement=True)
    assert not review.confirm.IsEnabled
    review.ack.IsChecked = True
    assert review.confirm.IsEnabled
    review.row_checks[0][1].IsChecked = False
    assert not review.confirm.IsEnabled and not review.ack.IsChecked
    checks.append('used-impact acknowledgement resets when approval changes')

    original_presence = list(fm.PRESENCE)
    for record in s.records[:8]:
        loaded = ui.EditorDialog(s, record)
        if not record.problem:
            assert fm.definition_signature(record.categories, loaded.read_tree()) == record.signature
            loaded.capture_partial()
            assert fm.definition_signature(record.categories, loaded.read_tree()) == record.signature
        loaded.Close()
    assert fm.PRESENCE == original_presence
    checks.append('existing definitions load losslessly without mutating shared operator menus')

    windows = [manager, ui.EditorDialog(s), ui.TemplateDialog(s),
               ui.ResultsDialog('Test Results', ['Test line']), review,
               ui.MatchingDialog(s, [r], uidoc.ActiveView), ui.RenameDialog(s, [r]),
               ui.DuplicateDialog(s, [r], r.categories, r.tree)]
    measured = []
    for window in windows:
        assert str(window.ResizeMode) == 'CanResize'
        window.Width, window.Height = window.MinWidth, window.MinHeight
        if isinstance(window, ui.ManagerDialog):
            window.adapt_layout(None, None)
        window.Content.Measure(Size(window.Width - 32, window.Height - 48))
        window.Content.Arrange(Rect(0, 0, window.Width - 32, window.Height - 48))
        window.UpdateLayout()
        assert window.body.ActualWidth > 0 and window.body.ActualHeight > 0
        assert window.actions.ActualHeight > 0
        if isinstance(window, ui.ManagerDialog):
            assert window.list.ActualHeight > 140
        measured.append((window.heading.Text, window.body.ActualWidth, window.body.ActualHeight))
        window.Close()
    checks.append('all eight dialog types load and arrange at resizable minima with visible body and actions')
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks),
            'checks': checks, 'minimum_layouts': measured, 'created_filter_id': fid}
