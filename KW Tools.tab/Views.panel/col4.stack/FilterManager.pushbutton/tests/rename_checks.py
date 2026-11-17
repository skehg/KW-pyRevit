# -*- coding: utf-8 -*-
"""Read-only name rendering and row-specific rename validation checks."""
from pyrevit import DB
import filter_model as fm
import filter_ui as ui


def run(doc):
    service = fm.FilterService(doc)
    assert len(service.records) >= 4
    original_names = dict((r.id, r.name) for r in service.records)
    records = [fm.FilterRecord(service, service.assert_current(r)) for r in service.records[:3]]
    category = fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))
    pid = fm.id_value(DB.ElementId(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS))

    def rule(value):
        return {'kind': 'rule', 'pid': pid, 'family': 'string', 'op': 'Equals',
                'value': value, 'epsilon': None}
    a, b, c = rule('Alpha'), rule('Beta'), rule('Gamma')
    checks = []
    assert service.describe(fm.group([fm.group([a])])) == 'Comments equals Alpha'
    assert service.describe(fm.group([fm.group([a, b]), c])) == (
        'Comments equals Alpha AND Comments equals Beta AND Comments equals Gamma')
    assert service.describe(fm.group([a, fm.group([b, c], 'OR')])) == (
        'Comments equals Alpha AND (Comments equals Beta OR Comments equals Gamma)')
    assert service.describe(fm.group([fm.group([a, fm.group([b, c], 'OR')])], 'OR')) == (
        'Comments equals Alpha AND (Comments equals Beta OR Comments equals Gamma)')
    assert service.describe(fm.group([fm.group([a, b]), c], 'OR')) == (
        '(Comments equals Alpha AND Comments equals Beta) OR Comments equals Gamma')
    assert service.describe(fm.group([rule('Literal (parentheses)')])) == (
        'Comments equals Literal (parentheses)')
    checks.append('descriptions remove unary/outer/same-operator brackets while retaining mixed logic and literal parentheses')

    records[0].tree = fm.group([fm.group([a])])
    records[1].tree = fm.group()
    records[2].tree = fm.group([fm.group([b])])
    for record in records:
        record.categories, record.category_names = [category], ['Walls']
        record.problem = ''
        record.rules = service.describe(record.tree)
    generated = [service.pattern_name(r, '{categories} - {rules}') for r in records]
    assert generated == ['Walls - Comments equals Alpha',
                         'Walls - Category-only - no additional conditions',
                         'Walls - Comments equals Beta']
    assert all(DB.NamingUtils.IsValidName(name) for name in generated)
    assert service.describe(records[1].tree) == 'Category-only: no additional conditions'
    checks.append('rule naming removes redundant brackets and category-only token avoids the invalid colon')

    first, second, third = [r.id for r in records]
    errors = service.name_errors({first: 'Invalid | Name', second: 'z' * 256,
                                 third: 'FM rename valid unique'})
    assert set(errors) == set([first, second])
    assert "'|'" in errors[first] and '256' not in errors[first]
    assert '256 characters' in errors[second] and 'Invalid' not in errors[second]
    assert not service.name_errors({first: 'z' * 255})
    assert first in service.name_errors({first: None})
    assert first in service.name_errors({first: ' '})
    assert 'leading/trailing' in service.name_errors({first: ' name '})[first]
    checks.append('per-ID errors distinguish blank, padding, offending characters and actual length; 255 characters remains valid')

    errors = service.name_errors({first: 'FM rename DUPLICATE', second: 'fm rename duplicate',
                                 third: 'FM rename valid unique'})
    assert set(errors) == set([first, second]) and all('collide' in e for e in errors.values())
    outside = service.records[3]
    assert 'already exists' in service.name_errors({first: outside.name})[first]
    assert not service.name_errors({first: original_names[second], second: original_names[first]})
    try:
        service.validate_names({first: 'Invalid : Name'})
    except ValueError as error:
        assert 'Invalid : Name' in unicode(error) and "':'" in unicode(error)
    else:
        raise AssertionError('Atomic writer validation must reject invalid names')
    checks.append('both collision participants are marked, unapproved existing names block, swaps remain valid and writer shares validation')

    window = ui.RenameDialog(service, records)
    window.pattern.Text = '{categories} - {rules}'
    window.update_preview(None, None)
    rows = window.rows
    symbols = fm.load_naming_symbols()
    symbol_generated = [service.pattern_name(r, '{categories} - {rules}', symbols) for r in records]
    assert symbol_generated == ['Walls - Comments = Alpha',
                                'Walls - Category-only - no additional conditions',
                                'Walls - Comments = Beta']
    assert [value.Text for r, check, value, validation in rows] == symbol_generated
    assert records[0].rules == 'Comments equals Alpha'
    generated = symbol_generated
    assert all(validation.Text == 'Ready' for r, check, value, validation in rows)
    assert window.rename_button.IsEnabled
    rows[0][2].Text = 'Invalid : Name'
    assert "':'" in rows[0][3].Text
    assert rows[1][3].Text == rows[2][3].Text == 'Ready'
    assert not window.rename_button.IsEnabled and '1 need correction' in window.status.Text
    rows[0][1].IsChecked = False
    assert rows[0][3].Text == 'Not approved' and window.rename_button.IsEnabled
    rows[0][1].IsChecked = True
    assert not window.rename_button.IsEnabled
    rows[0][2].Text = generated[0]
    rows[1][2].Text = 'x' * 300
    assert '300 characters' in rows[1][3].Text and rows[0][3].Text == rows[2][3].Text == 'Ready'
    rows[1][2].Text = generated[1]
    rows[0][2].Text = rows[2][2].Text
    assert 'collide' in rows[0][3].Text and 'collide' in rows[2][3].Text
    assert rows[1][3].Text == 'Ready'
    window.update_preview(None, None)
    assert window.rename_button.IsEnabled and all(row[3].Text == 'Ready' for row in rows)
    checks.append('dialog warnings belong only to offending rows; approval/manual corrections/update preview recalculate button and summary')

    original_pattern_name = service.pattern_name
    def fail_one(record, pattern, symbols=None):
        if record.id == second:
            raise ValueError('This row cannot render its native rule')
        return original_pattern_name(record, pattern, symbols)
    service.pattern_name = fail_one
    try:
        window.update_preview(None, None)
        assert rows[0][3].Text == rows[2][3].Text == 'Ready'
        assert rows[1][3].Text == 'This row cannot render its native rule'
        assert not window.rename_button.IsEnabled
        rows[1][2].Text = 'Manual corrected name'
        assert rows[1][3].Text == 'Ready' and window.rename_button.IsEnabled
    finally:
        service.pattern_name = original_pattern_name
    window.Close()
    checks.append('one pattern-rendering failure stays local and can be manually corrected; previews make no model writes')

    checks.extend(settings_checks(service, records, rule, ui))
    assert dict((fm.id_value(e.Id), fm.name_of(e)) for e in
                DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)) == original_names
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks), 'checks': checks,
            'category_only_generated_name': generated[1]}


def settings_checks(service, records, rule, ui):
    checks = []
    symbols = fm.load_naming_symbols()
    assert symbols['Equals'] == u'=' and symbols['NotEquals'] == u'\u2260'
    assert all(DB.NamingUtils.IsValidName(v) for v in symbols.values())
    assert set(symbols).issubset(set(fm.NAMING_OPERATOR_KEYS))
    a = rule('Alpha')
    ne = dict(a, op='NotEquals')
    inverse_greater = dict(a, op='NOT:Greater')
    tree = fm.group([a, fm.group([ne, inverse_greater], 'OR')])
    assert service.describe(tree, symbols=symbols) == (
        u'Comments = Alpha AND (Comments \u2260 Alpha OR Comments NOT \uff1e Alpha)')
    assert service.describe(tree) == (
        'Comments equals Alpha AND (Comments does not equal Alpha OR Comments NOT Greater Alpha)')
    record = records[0]
    record.tree, record.rules = fm.group([ne]), service.describe(fm.group([ne]))
    assert service.pattern_name(record, '{rules}', symbols) == u'Comments \u2260 Alpha'
    assert service.pattern_name(record, '{rules}') == record.rules == 'Comments does not equal Alpha'
    assert service.pattern_name(record, '{rules}', {}) == record.rules
    checks.append('settings symbols render only in naming (=, \u2260, NOT prefix); summaries and no-settings naming keep words')

    import os
    from System.IO import Path
    folder = os.path.join(Path.GetTempPath(), 'fm_naming_' + fm.uuid.uuid4().hex)
    os.mkdir(folder)
    def write(name, text):
        path = os.path.join(folder, name)
        with fm.io.open(path, 'w', encoding='utf-8') as stream:
            stream.write(text)
        return path
    def rejected(path, *fragments):
        try:
            fm.load_naming_symbols(path)
        except ValueError as error:
            message = unicode(error)
            assert path in message, message
            for fragment in fragments:
                assert fragment in message, (fragment, message)
            return
        raise AssertionError('Settings must be rejected: ' + path)
    try:
        assert fm.load_naming_symbols(os.path.join(folder, 'missing.json')) == {}
        bom = os.path.join(folder, 'bom.json')
        with open(bom, 'wb') as stream:
            stream.write(b'\xef\xbb\xbf' + u'{"operator_symbols": {"Equals": "\u2261"}}'.encode('utf-8'))
        assert fm.load_naming_symbols(bom) == {'Equals': u'\u2261'}
        rejected(write('bad.json', u'{"operator_symbols": {'), 'not valid JSON')
        rejected(write('list.json', u'[]'), 'JSON object')
        rejected(write('top.json', u'{"symbols": {}}'), 'Unknown setting "symbols"')
        rejected(write('shape.json', u'{"operator_symbols": ["="]}'), 'must be an object')
        rejected(write('values.json', u'{"operator_symbols": {"Equal": "=", "Greater": ">", '
                                      u'"Less": "", "Contains": " has", "BeginsWith": 3}}'),
                 'Unknown operator key "Equal"', '"Greater" value ">"', "'>'",
                 '"Less" must be nonempty', '"Contains" has leading/trailing', '"BeginsWith" must be nonempty')
        assert fm.load_naming_symbols(write('notes.json', u'{"_notes": ["x"]}')) == {}
    finally:
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
    checks.append('missing file falls back to words; BOM accepted; malformed JSON, unknown keys, invalid Revit characters and blank/padded/non-text values are rejected with the file path')

    for r, value in zip(records[:2], ('Alpha', 'Beta')):
        r.tree = fm.group([rule(value)])
        r.rules = service.describe(r.tree)
    original_loader = fm.load_naming_symbols
    def broken(path=None):
        raise ValueError('Naming settings file is invalid: test')
    fm.load_naming_symbols = broken
    try:
        window = ui.RenameDialog(service, records[:2])
        assert [row[2].Text for row in window.rows] == [r.name for r in records[:2]]
        assert 'Naming settings file is invalid: test' in window.status.Text
        assert not window.rename_button.IsEnabled
        assert all(row[3].Text == 'Ready' for row in window.rows)
        fm.load_naming_symbols = original_loader
        window.update_preview(None, None)
        assert not window.settings_error and window.rename_button.IsEnabled
        assert [row[2].Text for row in window.rows] == ['Walls - Comments = Alpha', 'Walls - Comments = Beta']
        assert all(row[3].Text == 'Ready' for row in window.rows)
        window.Close()
    finally:
        fm.load_naming_symbols = original_loader
    checks.append('invalid settings produce one dialog-level error, keep proposals unchanged, disable Rename and recover on Update Preview')
    return checks
