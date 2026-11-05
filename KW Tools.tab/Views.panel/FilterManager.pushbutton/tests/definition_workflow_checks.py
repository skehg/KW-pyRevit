# -*- coding: utf-8 -*-
"""Native definition regressions; run() needs an approved disposable test scope."""
import uuid

import filter_model as fm
from pyrevit import DB


def run_readonly(doc, uidoc=None):
    service = fm.FilterService(doc)
    records = [r for r in service.records if not r.problem][:3]
    assert len(records) == 3, 'Three readable definitions are required.'
    a, b, c = records
    names = {a.id: b.name, b.id: 'Invalid | Name', c.id: a.name}
    errors = service.rename_preview(records, names)
    assert set(errors) == set(names), 'Blocked vacancies must propagate transitively.'
    assert not service.rename_preview(records, dict((r.id, r.name) for r in records))
    for r in records:
        draft = service.duplicate_draft(r)
        assert draft['tree'] is not r.tree
        assert draft['name'].lower() not in service.filter_names()
        assert fm.definition_signature(draft['categories'], draft['tree']) == r.signature
    return ['current-name defaults', 'invalid-vacancy dependency fixed point',
            'lossless independent duplicate drafts']


def run(doc, uidoc=None):
    service = fm.FilterService(doc)
    prefix = 'FM workflow test ' + str(uuid.uuid4())[:8]
    categories = [fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))]
    fixture_ids = []
    checks = []

    def create(suffix):
        tree = fm.group()
        fid = service.save(prefix + suffix, categories, tree,
                           acknowledged=[r.id for r in service.matches(categories, tree)])
        fixture_ids.append(fid)
        service.refresh()
        return fid

    a, b, c = [create(suffix) for suffix in (' A', ' B', ' C')]
    record = service.get_record
    a_name, b_name = record(a).name, record(b).name
    result = service.rename_partial([record(a), record(b), record(c)],
                                   {a: b_name, b: a_name, c: 'Invalid | Name'})
    assert result['renamed'] == [a, b] and c in result['errors']
    assert record(a).name == b_name and record(b).name == a_name
    checks.append('valid subset swaps atomically while invalid row remains')
    result = service.rename_partial([record(a), record(c)],
                                   {a: record(a).name, c: prefix + ' Corrected'})
    assert result['unchanged'] == [a] and result['renamed'] == [c] and not result['errors']
    checks.append('unchanged no-op and correction retry')
    before = record(a).name

    def rejected_readback(_):
        raise ValueError('Forced readback failure')

    try:
        service.atomic('Test rollback after committed transaction',
                       lambda: setattr(service.assert_current(record(a)), 'Name', prefix + ' Rollback'),
                       rejected_readback)
    except ValueError as error:
        assert str(error) == 'Forced readback failure'
    else:
        raise AssertionError('Failed readback must reject the transaction group.')
    service.refresh()
    assert record(a).name == before
    checks.append('post-commit verification failure rolls group back')
    unused = dict((r.id, r) for r in service.unused_records())
    reviewed = [unused[fid] for fid in fixture_ids]
    usage = dict((r.id, service.usage_token(r)) for r in reviewed)
    assert set(service.purge_unused(reviewed, usage)) == set(fixture_ids)
    assert all(doc.GetElement(fm.element_id(fid)) is None for fid in fixture_ids)
    checks.append('fresh exact zero-use purge and readback')
    return checks
