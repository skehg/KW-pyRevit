# -*- coding: utf-8 -*-
"""Run inside Revit via MCP run_modify(dry_run=True); never against a live project."""
import uuid
from pyrevit import DB
import filter_model as fm


def run(doc, uidoc):
    service = fm.FilterService(doc)
    prefix = 'FM BETA test ' + str(uuid.uuid4())[:8]
    checks = []
    wall = fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))
    comments = fm.id_value(DB.ElementId(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS))
    categories = [wall]
    wall_type = DB.FilteredElementCollector(doc).OfClass(DB.WallType).FirstElement()
    level_fixture = DB.FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
    assert wall_type is not None and level_fixture is not None
    fixture = service.atomic('Create disposable wall fixture', lambda: DB.Wall.Create(
        doc, DB.Line.CreateBound(DB.XYZ(500, 500, 0), DB.XYZ(510, 500, 0)),
        wall_type.Id, level_fixture.Id, 10.0, 0.0, False, True))

    def rule(pid=comments, family='string', op='Equals', value='FM test', epsilon=None):
        return {'kind': 'rule', 'pid': pid, 'family': family, 'op': op,
                'value': value, 'epsilon': epsilon}

    def record(fid):
        service.refresh()
        return service.get_record(fid)

    def rejects(action):
        try:
            action()
        except ValueError:
            return
        raise AssertionError('Invalid operation did not reject')

    def create(suffix, tree):
        return service.save(prefix + ' ' + suffix, categories, tree,
                            acknowledged=[r.id for r in service.matches(categories, tree)])

    eligible = service.eligible_parameters(categories)
    assert any(p.id == comments and p.profile == 'text' for p in eligible)
    assert set(p.id for p in eligible) == set(fm.id_value(i) for i in
        DB.ParameterFilterUtilities.GetFilterableParametersInCommon(doc, fm.ids(categories)))
    checks.append('native eligibility intersection includes unplaced categories')
    assert len(service.all_categories()) > 150

    tree = fm.group([rule(), fm.group([rule(op='NotContains', value='Excluded'),
                                      rule(op='HasNoValue', family='presence', value=None)], 'OR')])
    fid = create('Nested', tree)
    r = record(fid)
    assert r.signature == fm.definition_signature(categories, tree)
    native_before = DB.ParameterFilterElement.GetElementFilter(service.assert_current(r))
    assert fm.definition_signature(categories, fm.read_tree(native_before)) == r.signature
    checks.append('nested AND/OR, inverse strings and presence round-trip')

    numeric = next((p for p in service.eligible_parameters(categories)
                    if p.storage == 'Double' and p.profile == 'number'), None)
    if numeric:
        double_tree = fm.group([rule(numeric.id, 'double', 'GreaterOrEqual', 1.25, 0.000123)])
        double_id = create('Double', double_tree)
        assert record(double_id).signature == fm.definition_signature(categories, double_tree)
        checks.append('double typed value and epsilon round-trip')
    integer = next((p for p in service.eligible_parameters(categories) if p.profile == 'yesno'), None)
    if integer:
        int_tree = fm.group([rule(integer.id, 'integer', 'Equals', 1)])
        assert record(create('YesNo', int_tree)).signature == fm.definition_signature(categories, int_tree)
        checks.append('Yes/No typed integer round-trip')
    else:
        bool_element, bool_category = next(
            (e, cid) for e in DB.FilteredElementCollector(doc).OfClass(DB.ParameterElement)
            if e.GetDefinition().GetDataType() == DB.SpecTypeId.Boolean.YesNo
            for cid, name in service.all_categories()
            if e.Id in DB.ParameterFilterUtilities.GetFilterableParametersInCommon(doc, fm.ids([cid])))
        bool_info = next(p for p in service.eligible_parameters([bool_category])
                         if p.id == fm.id_value(bool_element.Id))
        assert bool_info.profile == 'yesno'
        bool_tree = fm.group([rule(bool_info.id, 'integer', 'Equals', 1)])
        bool_id = service.save(prefix + ' YesNo', [bool_category], bool_tree,
                               acknowledged=[r.id for r in service.matches([bool_category], bool_tree)])
        assert record(bool_id).signature == fm.definition_signature([bool_category], bool_tree)
        checks.append('eligible Yes/No project parameter and typed integer round-trip')
    level = next((p for p in service.eligible_parameters(categories) if p.profile == 'level'), None)
    if level and service.references(level):
        level_id = service.references(level)[0][0]
        ref_tree = fm.group([rule(level.id, 'reference', 'GreaterOrEqual', level_id)])
        assert record(create('Level', ref_tree)).signature == fm.definition_signature(categories, ref_tree)
        checks.append('level reference identity and at/above round-trip')
    empty_id = create('Categories only', fm.group())
    assert record(empty_id).signature == fm.definition_signature(categories, fm.group())
    checks.append('category-only definition round-trip')

    rejects(lambda: service.save(prefix + ' Duplicate blocked', categories, tree))
    duplicate_id = create('Duplicate approved', tree)
    service.refresh()
    assert any(set(x.id for x in members) >= set([fid, duplicate_id]) for members in service.duplicate_groups()[0])
    checks.append('duplicate save blocked without acknowledgement and detected after approval')
    assert fm.signature(fm.group([rule(), rule(value='Other')])) == fm.signature(
        fm.group([rule(value='Other'), rule()]))
    assert fm.signature(fm.group([rule(), fm.group([rule(value='Other')])])) == fm.signature(
        fm.group([rule(value='Other'), rule()]))
    assert fm.signature(rule(family='double', value=1, epsilon=0.1)) != fm.signature(
        rule(family='double', value=1, epsilon=0.2))
    assert fm.definition_signature([wall], tree) != fm.definition_signature([wall, wall - 1], tree)
    checks.append('signatures distinguish categories, values and epsilon; ignore sibling order')

    target = next(v for v in service.views if not v.IsTemplate and fm.supports_filters(v)
                  and not service.template_controls(doc.GetElement(v.ViewTemplateId)))
    template = service.atomic('Create disposable test template', lambda: target.CreateViewTemplate())
    service.refresh()
    target_filters = list(fm.id_value(i) for i in target.GetOrderedFilters())
    service.apply([record(fid)], target)
    service.apply([record(fid)], template)
    r = record(fid)
    assert any(v.Id == target.Id for v in r.usage) and any(v.Id == template.Id for v in r.usage)
    overrides = DB.OverrideGraphicSettings()
    overrides.SetProjectionLineColor(DB.Color(67, 120, 154))
    service.atomic('Configure disposable attachment', lambda: (
        target.SetFilterOverrides(fm.element_id(fid), overrides),
        target.SetFilterVisibility(fm.element_id(fid), False),
        target.SetIsFilterEnabled(fm.element_id(fid), False)))
    before_order = list(fm.id_value(i) for i in target.GetOrderedFilters())
    result = service.apply([record(fid), record(empty_id)], target)
    assert result['skipped'] == [record(fid).name] and len(result['added']) == 1
    assert list(fm.id_value(i) for i in target.GetOrderedFilters())[:len(before_order)] == before_order
    assert target.GetFilterVisibility(fm.element_id(fid)) is False
    assert target.GetIsFilterEnabled(fm.element_id(fid)) is False
    assert target.GetFilterOverrides(fm.element_id(fid)).ProjectionLineColor.Blue == 154
    checks.append('single view/template apply, idempotent skip, existing order/graphics/visibility/enabled preserved')

    r = record(fid)
    unique, usage = r.unique_id, service.usage_token(r)
    updated_tree = fm.group([rule(value='Edited FM test')])
    service.save(prefix + ' Edited', categories, updated_tree, r)
    current = record(fid)
    assert current.unique_id == unique and service.usage_token(current) == usage
    assert current.signature == fm.definition_signature(categories, updated_tree)
    assert target.GetFilterOverrides(fm.element_id(fid)).ProjectionLineColor.Blue == 154
    service.save(current.name, categories, fm.clone_tree(current.tree), current)
    assert record(fid).signature == current.signature
    rejects(lambda: service.rename([r], {r.id: 'Stale snapshot'}))
    checks.append('in-place and no-change edit preserve identity, usage and graphics; stale snapshot rejected')

    a, b = record(fid), record(empty_id)
    service.rename([a, b], {a.id: b.name, b.id: a.name})
    assert record(fid).name == b.name and record(empty_id).name == a.name
    rejects(lambda: service.rename([record(fid), record(empty_id)], {fid: 'collision', empty_id: 'collision'}))
    rejects(lambda: service.rename([record(fid)], {fid: 'Invalid | Name'}))
    rejects(lambda: service.rename([record(fid)], {empty_id: 'Outside approved set'}))
    checks.append('atomic rename swaps and collision/invalid-name/approved-set validation')

    patterns = record(fid)
    patterns.rules = 'Comments equals {literal}'
    assert '{literal}' in service.pattern_name(patterns, '{rules}')
    rejects(lambda: service.pattern_name(patterns, '{unknown}'))
    rejects(lambda: service.pattern_name(patterns, '{rules'))
    checks.append('pattern syntax rejects invalid tokens without rejecting braces in literal values')

    any_ids = service.collect_matches([record(fid), record(empty_id)])
    all_ids = service.collect_matches([record(fid), record(empty_id)], all_filters=True)
    assert set(fm.id_value(i) for i in all_ids).issubset(set(fm.id_value(i) for i in any_ids))
    assert all(not isinstance(doc.GetElement(i), DB.ElementType) for i in any_ids)
    assert len(any_ids) == len(set(fm.id_value(i) for i in any_ids))
    assert not record(duplicate_id).usage
    assert record(fid).usage
    checks.append('ANY/ALL native selection is unique/non-type; unused index includes template-only consumers')

    pending = record(fid)
    tokens = {pending.id: service.usage_token(pending)}
    deleted = service.delete([pending], tokens)
    assert deleted == set([fid]) and doc.GetElement(fm.element_id(fid)) is None
    assert fid not in set(fm.id_value(i) for i in target.GetFilters())
    assert fixture.IsValidObject
    checks.append('used deletion removes definition/attachments only')

    marker = record(empty_id).name
    def fail():
        doc.GetElement(fm.element_id(empty_id)).Name = prefix + ' temporary failure'
        raise ValueError('Injected failure')
    rejects(lambda: service.atomic('Injected rollback test', fail))
    assert record(empty_id).name == marker
    checks.append('operation failure rolls back all writes')
    return {'version': doc.Application.VersionNumber, 'checks': checks,
            'test_prefix': prefix, 'checks_passed': len(checks),
            'template_id': fm.id_value(template.Id), 'target_id': fm.id_value(target.Id),
            'remaining_test_filter_ids': [r.id for r in service.records if r.name.startswith(prefix)]}
