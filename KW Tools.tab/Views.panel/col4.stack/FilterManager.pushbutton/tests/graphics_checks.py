# -*- coding: utf-8 -*-
"""Graphics checks: run(doc, uidoc=None) is strictly READ ONLY.

run_detached() exercises native detached OGS objects, then a fake document for
planner/atomic regression tests. model_fixture() is separate, MUTATING and must
only be called by the parent in an explicitly authorized disposable fixture.
No WPF instantiation, production writes, saved files or automatic model fixture.
"""
import copy
import logging
import time
import types
import uuid

from pyrevit import DB
import filter_model as fm
import filter_graphics as fg


def _reject(action, kind=ValueError):
    try:
        action()
    except kind:
        return
    raise AssertionError('Expected {}'.format(kind.__name__))


def _request(filters=(101,), targets=(2,), origins=(), patches=None, **extra):
    result = dict(filter_ids=list(filters), target_ids=list(targets),
                  origin_ids=list(origins), patches=patches or {})
    result.update(extra)
    return result


def _set(**values):
    return dict((key, dict(op='set', value=value)) for key, value in values.items())


class _FakeId(object):
    def __init__(self, value):
        self.IntegerValue = int(value)


class _FakeColor(object):
    def __init__(self, red=0, green=0, blue=0, valid=True):
        self.Red, self.Green, self.Blue, self.IsValid = red, green, blue, valid


_FakeColor.InvalidColorValue = _FakeColor(valid=False)


class _FakeOGS(object):
    InvalidPenNumber = -1

    def __init__(self, other=None):
        if other is not None:
            self.values = copy.deepcopy(other.values)
        else:
            self.values = {}
            for field in fg.FIELDS:
                if field['getter']:
                    kind = field['kind']
                    value = (_FakeColor.InvalidColorValue if kind == 'color' else
                             _FakeId(-1) if kind == 'resource' else
                             -1 if kind == 'weight' else
                             0 if kind == 'int' else
                             field['key'].endswith('_visible'))
                    self.values[field['getter']] = value
            self.values['DetailLevel'] = 'Undefined'

    def __getattr__(self, key):
        values = self.__dict__.get('values', {})
        if key in values:
            return values[key]
        fields = [f for f in fg.FIELDS if f['setter'] == key]
        if fields:
            def setter(value):
                self.values[fields[0]['getter']] = value
                return self
            return setter
        raise AttributeError(key)

    def Dispose(self):
        pass


class _FakeElement(object):
    IsValidObject = True

    def __init__(self, doc, numeric, name):
        self.Document, self.Id, self.Name = doc, _FakeId(numeric), name
        self.UniqueId, self.VersionGuid = 'unique-' + str(numeric), 'v1'


class _FakeFilter(_FakeElement):
    pass


class _FakeView(_FakeElement):
    def __init__(self, doc, numeric, template=False):
        _FakeElement.__init__(self, doc, numeric, 'View ' + str(numeric))
        self.IsTemplate, self.ViewType = template, 'FloorPlan'
        self.ViewTemplateId, self.controls = _FakeId(-1), False
        self.order, self.attachments = [], {}

    def seed(self, fid, enabled=True, visibility=True, **values):
        self.order.append(fid)
        ogs = _FakeOGS()
        for key, value in values.items():
            field = fg.BY_KEY[key]
            getattr(ogs, field['setter'])(fg._native_value(field, value))
        self.attachments[fid] = dict(ogs=ogs, enabled=enabled, visibility=visibility)

    def GetOrderedFilters(self):
        self.Document.reads += 1
        return [_FakeId(fid) for fid in self.order]

    def GetFilterOverrides(self, fid):
        self.Document.reads += 1
        self.Document.ogs_reads += 1
        return _FakeOGS(self.attachments[fid.IntegerValue]['ogs'])

    def GetFilterVisibility(self, fid):
        self.Document.reads += 1
        return self.attachments[fid.IntegerValue]['visibility']

    def GetIsFilterEnabled(self, fid):
        self.Document.reads += 1
        return self.attachments[fid.IntegerValue]['enabled']

    def AddFilter(self, fid):
        self.Document.writes.append(('add', self.Id.IntegerValue, fid.IntegerValue))
        self.seed(fid.IntegerValue)

    def SetIsFilterEnabled(self, fid, value):
        self.Document.writes.append(('enabled', self.Id.IntegerValue, fid.IntegerValue))
        self.attachments[fid.IntegerValue]['enabled'] = value

    def SetFilterOverrides(self, fid, value):
        self.Document.writes.append(('ogs', self.Id.IntegerValue, fid.IntegerValue))
        self.attachments[fid.IntegerValue]['ogs'] = _FakeOGS(value)

    def SetFilterVisibility(self, fid, value):
        self.Document.writes.append(('visibility', self.Id.IntegerValue, fid.IntegerValue))
        self.attachments[fid.IntegerValue]['visibility'] = value


class _FakeCollector(object):
    def __init__(self, doc):
        self.doc, self.expected = doc, object
        doc.collectors += 1

    def OfClass(self, expected):
        self.expected = expected
        return self

    def __iter__(self):
        return iter([e for e in self.doc.elements.values() if isinstance(e, self.expected)])

    def GetElementCount(self):
        return len(list(self))


class _FakeLine(_FakeElement):
    @staticmethod
    def GetSolidPatternId():
        return _FakeId(-3000010)


class _FakePattern(object):
    def __init__(self, target='Drafting', solid=False):
        self.Target, self.IsSolidFill = target, solid

    def Dispose(self):
        pass


class _FakeFill(_FakeElement):
    def __init__(self, doc, numeric, target='Drafting', solid=False):
        _FakeElement.__init__(self, doc, numeric, 'Fill ' + str(numeric))
        self.pattern = _FakePattern(target, solid)

    def GetFillPattern(self):
        return self.pattern


class _FakeDoc(object):
    IsReadOnly, IsModifiable = False, False

    def __init__(self):
        self.elements, self.reads, self.ogs_reads, self.collectors = {}, 0, 0, 0
        self.writes, self.events = [], []
        for fid in (101, 102, 103):
            self.elements[fid] = _FakeFilter(self, fid, 'Filter ' + str(fid))
        for tid in (1, 2, 3, 4, 5, 6):
            self.elements[tid] = _FakeView(self, tid, template=tid == 4)
        self.elements[201] = _FakeLine(self, 201, 'Dashed')
        self.elements[301] = _FakeFill(self, 301, solid=True)
        self.elements[302] = _FakeFill(self, 302, target='Model')

    def GetElement(self, eid):
        self.reads += 1
        return self.elements.get(eid.IntegerValue)


class _FakeService(object):
    def __init__(self, doc):
        self.doc, self.fail_verify = doc, False

    def template_controls(self, view):
        return view is not None and view.IsTemplate and view.controls

    def atomic(self, title, action, verify=None):
        # Model only transaction/group semantics, not a native execution proof.
        backups = dict((tid, (list(e.order), copy.deepcopy(e.attachments), e.VersionGuid))
                       for tid, e in self.doc.elements.items() if isinstance(e, _FakeView))
        write_start = len(self.doc.writes)
        self.doc.events.append('tx-start')
        try:
            result = action()
            for tid in set(w[1] for w in self.doc.writes[write_start:]):
                self.doc.elements[tid].VersionGuid += '-committed'
            self.doc.events.append('tx-commit')
            if self.fail_verify:
                # Simulate an updater altering an untouched field at commit.
                self.doc.elements[2].attachments[101]['visibility'] = False
            if verify:
                verify(result)
            self.doc.events.append('group-assimilate')
            return result
        except Exception:
            for tid, state in backups.items():
                (self.doc.elements[tid].order, self.doc.elements[tid].attachments,
                 self.doc.elements[tid].VersionGuid) = state
            self.doc.events.append('group-rollback')
            raise


def _fake_checks():
    original = (fg.DB, fg.element_id, fg.id_value, fg.name_of, fg.supports_filters)
    fake_db = types.ModuleType('fake_graphics_db')
    fake_db.View, fake_db.ParameterFilterElement = _FakeView, _FakeFilter
    fake_db.OverrideGraphicSettings, fake_db.Color = _FakeOGS, _FakeColor
    fake_db.FilteredElementCollector = _FakeCollector
    fake_db.LinePatternElement, fake_db.FillPatternElement = _FakeLine, _FakeFill
    fake_db.FillPatternTarget = type('Targets', (object,), dict(Drafting='Drafting'))
    fg.DB, fg.element_id, fg.id_value = fake_db, _FakeId, lambda e: e.IntegerValue
    fg.name_of, fg.supports_filters = lambda e: e.Name, lambda e: isinstance(e, _FakeView)
    checks = []
    messages = []
    class ExpectedFailures(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())
    handler = ExpectedFailures()
    old_propagate = fg._log.propagate
    fg._log.addHandler(handler)
    fg._log.propagate = False
    try:
        doc = _FakeDoc()
        native = _FakeService(doc)
        service = fg.GraphicService(native)
        assert not doc.reads and not doc.ogs_reads and not doc.collectors
        assert service.effective_sources([]) == [] and service.source_filters([]) == {}
        assert not doc.reads
        checks.append('constructor/All Project do zero native reads or implicit sources')

        assert len(set(f['group'] for f in fg.FIELDS if f['editable'])) == 7
        assert not fg.BY_KEY['enabled']['editable']
        assert len(fg.GRAPHICS) == 20
        for key in ('enabled', 'detail_level', 'typo'):
            _reject(lambda: service.validate_patch({key: dict(op='set', value=True)}))
        for key in ('visibility', 'halftone', 'transparency', 'surface_foreground_pattern_visible'):
            _reject(lambda: service.validate_patch({key: dict(op='clear')}))
        for patch in (_set(transparency=-1), _set(transparency=101),
                      _set(projection_line_weight=0), _set(projection_line_weight=17),
                      _set(visibility=1), _set(projection_line_color=(1, 2, 256)),
                      _set(projection_line_pattern_id=301),
                      _set(surface_foreground_pattern_id=302)):
            _reject(lambda: service.validate_patch(patch))
        _reject(lambda: service.plan(_request(patches={999: _set(halftone=object())})))
        assert service.validate_patch(_set(transparency=0))['transparency']['value'] == 0
        assert service.validate_patch(_set(transparency=100))['transparency']['value'] == 100
        patch = service.patch_draft(_set(visibility=False), dict(visibility=dict(op='keep')))
        assert patch == {}
        assert service.validate_patch(dict(projection_line_color=dict(op='clear'))) == _set(projection_line_color=None)
        checks.append('seven groups, exact clears, read-only enabled, bounds, RGB and resource validation')

        assert [x['id'] for x in service.resources('weight')] == list(range(1, 17))
        assert -3000010 in [x['id'] for x in service.resources('line')]
        assert [x['id'] for x in service.resources('fill')] == [301]
        reads = doc.reads, doc.collectors
        service.resources('line')
        service.resources('fill')
        assert reads == (doc.reads, doc.collectors)
        _reject(lambda: service.resources('fill', cancel=lambda: True), fg.GraphicsCancelled)
        uncached = fg.GraphicService(native)
        calls = [0]
        def cancel_resources():
            calls[0] += 1
            return calls[0] >= 3
        _reject(lambda: uncached.resources('fill', cancel=cancel_resources), fg.GraphicsCancelled)
        assert 'fill' not in uncached._resources
        checks.append('lazy cached line/drafting-fill/weight catalogues, Solid not Clear')

        source = doc.elements[1]
        source.seed(102)
        source.seed(101, enabled=False, visibility=False, projection_line_weight=6)
        doc.elements[3].seed(101, enabled=True, visibility=False, projection_line_weight=6)
        source.attachments[101]['ogs'].values['DetailLevel'] = 'Fine'
        full = service.snapshot(1, 101)
        assert not full['values']['enabled'] and full['values']['detail_level'] == 'Fine'
        reads = doc.reads
        visibility = service.snapshot(1, 101, ('visibility',))
        assert visibility['values'] == {'visibility': False}
        assert visibility['coverage'] == ('visibility',)
        assert reads == doc.reads
        full['values']['projection_line_weight'] = 999
        full['template']['controls'] = 'edited by caller'
        isolated = service.snapshot(1, 101)
        assert isolated['values']['projection_line_weight'] == 6
        assert isolated['template']['controls'] is False
        service.snapshot(3, 101, ('visibility',))
        assert doc.ogs_reads == 1
        missing = service.snapshot(2, 101)
        assert not missing['attached'] and missing['values'] == {}
        checks.append('flat coverage, zero cached-repeat reads, visibility-only zero OGS, missing != default')

        variants = service.source_variants(101, [1, 3])
        assert variants['complete'] and len(variants['groups']) == 1
        doc.elements[3].attachments[101]['visibility'] = True
        service.invalidate()
        variants = service.source_variants(101, [1, 3], include_visibility=False)
        assert variants['complete'] and len(variants['groups']) == 1
        variants = service.source_variants(101, [1, 3])
        assert len(variants['groups']) == 2
        assert not service.source_variants(102, [1, 3])['complete']
        conflict = service.plan(_request(origins=[1, 3]))
        assert conflict['rows'][0]['action'] == 'Invalid'
        resolved = service.plan(_request(origins=[1, 3], source_choices={101: 1}))
        assert resolved['rows'][0]['action'] == 'Add'
        assert resolved['rows'][0]['after']['enabled']
        assert resolved['rows'][0]['after']['visibility'] is False
        explicit = service.plan(_request(origins=[1], include_visibility=False,
                                         source_mode='explicit'))
        assert explicit['rows'][0]['requested'] == {'projection_line_weight': 6}
        _reject(lambda: service.plan(_request(source_mode='guess')))
        checks.append('selected-channel variants ignore enabled; incomplete/conflicting origins never choose first')

        events = []
        batch = service.read_batch([(1, 101), (3, 101), (2, 101), (1, 102),
                                    (2, 102), (3, 102)], progress=events.append)
        assert not batch['cancelled'] and not batch['remaining']
        assert all(e['slice_pairs'] <= 5 for e in events) and len(events) >= 2
        calls = [0]
        def cancel():
            calls[0] += 1
            return calls[0] >= 3
        cancelled = service.read_batch([(1, 101), (3, 101), (2, 101)], cancel=cancel)
        assert cancelled['cancelled'] and cancelled['remaining']
        _reject(lambda: service.project_targets(cancel=lambda: True), fg.GraphicsCancelled)
        _reject(lambda: service.plan(_request(), cancel=lambda: True), fg.GraphicsCancelled)
        _reject(lambda: service.read_batch([(1, 101)], max_pairs=6))
        checks.append('<=5 pair slices, main-thread progress, cancellation explicit for batch/catalogue/plan')

        # All Project blank drafts add native defaults; preserve disabled existing.
        doc.elements[2].seed(102, enabled=False, projection_line_weight=9)
        service.invalidate()
        before = service.snapshot(2, 102)
        draft = service.plan(_request(filters=[101, 102]))
        assert [r['action'] for r in draft['rows']] == ['Add', 'Unchanged']
        result = service.apply(draft)
        assert result['counts']['added'] == 1 and result['counts']['unchanged'] == 1
        assert service.snapshot(2, 102)['values'] == before['values']
        assert not any(w == ('enabled', 2, 102) for w in doc.writes)
        again = service.plan(_request(filters=[101, 102]), completed=result['receipts'])
        assert all(r['action'] == 'Completed' for r in again['rows'])
        assert service.apply(again)['counts']['completed'] == 2
        checks.append('blank Add native defaults, existing disabled untouched, completed checks do not requeue')

        # Adds proceed while pre-existing updates await exact approval.
        service.invalidate()
        request = _request(filters=[101, 103], patches={101: _set(halftone=True)})
        mixed = service.plan(request)
        assert [r['action'] for r in mixed['rows']] == ['Update', 'Add']
        result = service.apply(mixed)
        assert result['counts']['added'] == 1 and result['counts']['unapproved'] == 1
        assert not doc.elements[2].attachments[101]['ogs'].values['Halftone']
        retained = service.plan(request, completed=result['receipts'])
        assert [r['action'] for r in retained['rows']] == ['Update', 'Completed']
        approved = service.approve_updates(retained)
        assert not service.clear_approvals(approved)['rows'][0]['approved']
        result = service.apply(approved)
        assert result['counts']['updated'] == 1
        assert doc.elements[2].attachments[101]['ogs'].values['Halftone']
        assert doc.events[-2:] == ['tx-commit', 'group-assimilate']
        checks.append('ready Adds proceed, Updates pending, exact approval/clear and retained receipts')

        # Turning an existing True override Off is an explicit Update, not Unset.
        service.invalidate()
        request = _request(patches={101: _set(halftone=False)})
        pending_off = service.plan(request)
        assert pending_off['rows'][0]['action'] == 'Update'
        writes_before = list(doc.writes)
        result = service.apply(pending_off)
        assert result['counts']['unapproved'] == 1 and result['counts']['updated'] == 0
        assert doc.writes == writes_before
        assert doc.elements[2].attachments[101]['ogs'].values['Halftone']
        approved_off = service.approve_updates(
            service.plan(request, completed=result['receipts']))
        result = service.apply(approved_off)
        assert result['counts']['updated'] == 1
        assert not doc.elements[2].attachments[101]['ogs'].values['Halftone']
        checks.append('explicit Halftone True-to-False update remains pending without a write, then commits after approval')

        # Native cloning preserves protected DetailLevel and unrequested values.
        doc.elements[2].attachments[101]['ogs'].values['DetailLevel'] = 'Fine'
        doc.elements[2].attachments[101]['enabled'] = False
        service.invalidate()
        copied = service.plan(_request(origins=[1], include_visibility=False,
                                       patches={101: _set(projection_line_weight=7)}))
        copied = service.approve_updates(copied)
        result = service.apply(copied)
        values = result['snapshots'][(2, 101)]['values']
        assert values['projection_line_weight'] == 7
        assert values['detail_level'] == 'Fine' and not values['enabled']
        assert values['visibility'] is True
        checks.append('source+custom overlay; unselected visibility, DetailLevel and disabled preserved')

        # Blocked selected rows require explicit exclusion, no silent skip.
        blocked = service.plan(_request(targets=[1, 5], origins=[1]))
        assert blocked['counts']['Blocked'] == 1
        _reject(lambda: service.apply(blocked))
        result = service.apply(service.exclude_rows(blocked, [(1, 101)]))
        assert result['counts']['excluded'] == 1 and result['counts']['added'] == 1
        checks.append('visible source-as-target blocking and explicit counted exclusion')

        # Template dedup and full consumers, direct views never redirected.
        template, dependent = doc.elements[4], doc.elements[6]
        template.controls = True
        template.seed(101)
        dependent.ViewTemplateId = _FakeId(4)
        service.invalidate()
        assert service.effective_sources([4, 6]) == [4]
        assert service.source_filters([6]) == {101: [4]}
        controlled = service.plan(_request(targets=[6]))
        assert controlled['counts']['Blocked'] == 1
        templated = service.plan(_request(targets=[4], patches={101: _set(halftone=True)}))
        assert [i['id'] for i in templated['rows'][0]['impact']] == [6]
        approved = service.approve_updates(templated)
        doc.elements[5].ViewTemplateId = _FakeId(4)
        _reject(lambda: service.apply(approved))
        checks.append('controlling templates explicit, deduplicated sources, full impact change blocks')

        # Fresh source/target/order/resource/identity validation and tamper guard.
        mutations = [
            lambda d: d.elements[1].attachments[101].update(visibility=True),
            lambda d: d.elements[2].attachments[101].update(visibility=False),
            lambda d: d.elements[2].order.reverse(),
            lambda d: setattr(d.elements[101], 'VersionGuid', 'v2'),
            lambda d: setattr(d.elements[201], 'VersionGuid', 'v2')]
        for mutate in mutations:
            d = _FakeDoc()
            d.elements[1].seed(101, visibility=False, projection_line_pattern_id=201)
            d.elements[2].seed(102)
            d.elements[2].seed(101)
            g = fg.GraphicService(_FakeService(d))
            p = g.approve_updates(g.plan(_request(origins=[1])))
            mutate(d)
            _reject(lambda: g.apply(p))
            assert not d.writes
        d = _FakeDoc()
        d.elements[2].seed(101)
        g = fg.GraphicService(_FakeService(d))
        p = g.approve_updates(g.plan(_request(patches={101: _set(halftone=True)})))
        p['rows'][0]['after']['halftone'] = False
        _reject(lambda: g.apply(p))
        p = g.plan(_request(filters=[101, 102]))
        p['rows'].reverse()
        _reject(lambda: g.apply(p))
        checks.append('external source/target/order/identity/resource changes and tampered approval rejected')

        # Commit verification failure rolls group back before assimilation.
        d = _FakeDoc()
        d.elements[2].seed(101)
        n = _FakeService(d)
        g = fg.GraphicService(n)
        p = g.approve_updates(g.plan(_request(patches={101: _set(halftone=True)})))
        n.fail_verify = True
        _reject(lambda: g.apply(p))
        assert d.events == ['tx-start', 'tx-commit', 'group-rollback']
        assert not d.elements[2].attachments[101]['ogs'].values['Halftone']
        assert d.elements[2].attachments[101]['visibility']
        checks.append('post-commit verification failure rolls back atomic group, no success receipt')

        # Explicit source order; dict/set ids are accepted and deterministic.
        d = _FakeDoc()
        d.elements[1].seed(102)
        d.elements[1].seed(101)
        g = fg.GraphicService(_FakeService(d))
        p = g.plan(_request(filters=[101, 102], origins=[1]))
        assert [r['key'][1] for r in p['rows']] == [102, 101]
        g.apply(p)
        assert d.elements[2].order == [102, 101]
        g.invalidate()
        p = g.plan(dict(filter_ids={103, 101}, target_ids={3: True}))
        assert [r['key'][1] for r in p['rows']] == [101, 103]
        assert g.plan(_request(filters=[], targets=[]))['rows'] == []
        assert g.apply(g.plan(_request(filters=[], targets=[])))['counts']['added'] == 0
        checks.append('append source order, numeric mappings/sets, empty input and empty Apply')
        d = _FakeDoc()
        d.elements[1].seed(101, enabled=False, projection_line_weight=6)
        d.elements[1].seed(102)
        g = fg.GraphicService(_FakeService(d))
        normal_missing = g.plan(_request(filters=[101, 103], origins=[1]))
        assert normal_missing['counts']['Invalid'] == 1
        pinned_request = _request(filters=[101, 103], origins=[1],
                                  source_exempt_ids={103, 999})
        pinned = g.plan(pinned_request)
        assert pinned['counts']['Add'] == 2
        assert pinned['rows'][0]['requested']['projection_line_weight'] == 6
        assert pinned['rows'][1]['requested'] == {} and pinned['rows'][1]['source_exempt']
        pinned_result = g.apply(pinned)
        expanded = g.plan(_request(filters=[101, 102, 103], origins=[1],
                                   source_exempt_ids=[103]), completed=pinned_result['receipts'])
        assert expanded['counts']['Completed'] == 2 and expanded['counts']['Add'] == 1
        assert g.plan(_request(filters=[103], targets=[1], origins=[1],
                               source_exempt_ids=[103]))['counts']['Add'] == 1
        mixed_source_target = g.plan(_request(filters=[101, 103], targets=[1], origins=[1],
                                              source_exempt_ids=[103]))
        assert mixed_source_target['counts']['Blocked'] == 2
        checks.append('explicit new-definition source exemptions preserve originals; new checks do not requeue receipts')
        d = _FakeDoc()
        d.elements[1].ViewTemplateId = _FakeId(4)
        d.elements[2].ViewTemplateId = _FakeId(4)
        d.elements[1].seed(101, visibility=False)
        g = fg.GraphicService(_FakeService(d))
        p = g.plan(_request(origins=[1], targets=[2, 4]))
        assert p['counts']['Add'] == 2
        applied = g.apply(p)
        assert applied['counts']['added'] == 2
        assert not g.snapshot(2, 101)['values']['visibility']
        assert not g.snapshot(4, 101)['values']['visibility']
        assert g.plan(_request(origins=[1], targets=[2, 4]),
                      completed=applied['receipts'])['counts']['Completed'] == 2
        checks.append('noncontrolling assigned template and direct view remain independent eligible targets')
        # Original selected view provenance must not collapse to old template
        # attachment snapshots. Mutations below leave old T1 values unchanged.
        def candidate_fixture():
            fixture = _FakeDoc()
            fixture.elements[4].controls = True
            fixture.elements[4].seed(101, visibility=False)
            fixture.elements[5].IsTemplate = True
            fixture.elements[5].controls = True
            fixture.elements[5].seed(101, visibility=False)
            fixture.elements[6].ViewTemplateId = _FakeId(4)
            fixture.elements[2].seed(101)
            return fixture
        mutations = [
            lambda d: setattr(d.elements[6], 'ViewTemplateId', _FakeId(5)),
            lambda d: setattr(d.elements[6], 'ViewTemplateId', _FakeId(-1)),
            lambda d: setattr(d.elements[4], 'controls', False),
            lambda d: setattr(d.elements[6], 'UniqueId', 'replacement-view'),
            lambda d: d.elements.pop(6)]
        for mutate in mutations:
            d = candidate_fixture()
            g = fg.GraphicService(_FakeService(d))
            candidate_request = _request(origins=[4], source_candidate_ids=[6])
            p = g.approve_updates(g.plan(candidate_request))
            row = p['rows'][0]
            assert row['source_candidates'][0]['candidate_id'] == 6
            assert row['source_candidates'][0]['effective_id'] == 4
            assert row['source_id'] == 4 and row['action'] == 'Update'
            mutate(d)
            _reject(lambda: g.apply(p))
            assert not d.writes and not d.events
            assert d.elements[2].attachments[101]['visibility'] is True
        d = candidate_fixture()
        g = fg.GraphicService(_FakeService(d))
        p = g.approve_updates(g.plan(_request(origins=[6])))
        assert p['request']['source_candidate_ids'] == [6]
        d.elements[6].ViewTemplateId = _FakeId(5)
        _reject(lambda: g.apply(p))
        assert not d.writes and not d.events
        d = candidate_fixture()
        d.elements[5].IsTemplate = False
        d.elements[5].ViewTemplateId = _FakeId(4)
        g = fg.GraphicService(_FakeService(d))
        p = g.approve_updates(g.plan(_request(
            origins=[4], source_candidate_ids=[6, 5])))
        assert [c['candidate_id'] for c in p['rows'][0]['source_candidates']] == [6, 5]
        assert [s['target_id'] for s in p['rows'][0]['sources']] == [4]
        assert g.apply(p)['counts']['updated'] == 1
        blocked = g.plan(_request(origins=[4], targets=[6], source_candidate_ids=[6]))
        assert blocked['counts']['Blocked'] == 1
        assert blocked['rows'][0]['source_candidates'][0]['candidate_id'] == 6
        d = candidate_fixture()
        g = fg.GraphicService(_FakeService(d))
        # Capture UI's old effective resolution before assignment changes;
        # plan's fresh original-candidate snapshot must reject the mismatch.
        assert g.effective_sources([6]) == [4]
        d.elements[6].ViewTemplateId = _FakeId(5)
        p = g.plan(_request(origins=[4], source_candidate_ids=[6]))
        assert p['counts']['Invalid'] == 1
        assert 'assignment' in p['rows'][0]['reason'].lower()
        assert not d.writes and not d.events
        d = candidate_fixture()
        g = fg.GraphicService(_FakeService(d))
        request = _request(origins=[4], source_candidate_ids=[6])
        applied = g.apply(g.approve_updates(g.plan(request)))
        old_meaning = applied['receipts'][0]['meaning_token']
        d.elements[6].ViewTemplateId = _FakeId(5)
        g.invalidate()
        reassigned = g.plan(_request(origins=[5], source_candidate_ids=[6]),
                            completed=applied['receipts'])
        assert reassigned['counts']['Completed'] == 0
        assert reassigned['rows'][0]['meaning_token'] != old_meaning
        disabled = g.plan(_request(
            origins=[4], source_candidate_ids=[6],
            include_graphics=False, include_visibility=False,
            pair_patches={(2, 101): _set(halftone=True)}))
        assert not disabled['rows'][0]['source_candidates']
        assert disabled['rows'][0]['action'] == 'Update'
        checks.append('original source candidate reassignment/removal/control/identity changes reject before transaction; stale effective plan and receipts invalidated')
        d = _FakeDoc()
        g = fg.GraphicService(_FakeService(d))
        pair = {(2, 101): _set(projection_line_color=(1, 2, 3))}
        pair_plan = g.plan(_request(targets=[2, 3], pair_patches=pair))
        assert pair_plan['rows'][0]['after']['projection_line_color'] == (1, 2, 3)
        assert pair_plan['rows'][1]['after']['projection_line_color'] is None
        applied = g.apply(pair_plan)
        assert len(applied['receipts']) == 2
        expanded = g.plan(_request(targets=[2, 3, 5], pair_patches=pair),
                          completed=applied['receipts'])
        assert expanded['counts']['Completed'] == 2 and expanded['counts']['Add'] == 1
        assert expanded['rows'][-1]['after']['projection_line_color'] is None
        overlaid = g.plan(_request(
            targets=[2, 3], patches={101: _set(projection_line_weight=4)},
            pair_patches={(2, 101): _set(projection_line_weight=8)}))
        assert [r['after']['projection_line_weight'] for r in overlaid['rows']] == [8, 4]
        assert g.patch_draft(pair[(2, 101)], {
            'projection_line_color': {'op': 'keep'}}) == {}
        checks.append('optional pair patches preserve target-specific history and overlay independent per-filter/source drafts')
        d = _FakeDoc()
        d.elements[1].seed(101, enabled=False, visibility=False, halftone=True,
                           transparency=37)
        d.elements[2].seed(101, projection_line_color=(80, 90, 100))
        g = fg.GraphicService(_FakeService(d))
        plain = _request(targets=[2], origins=[1],
                         include_graphics=False, include_visibility=False)
        assert g.plan(plain)['rows'][0]['action'] == 'Unchanged'
        loaded = g.load_source_draft(101, [1])
        assert loaded['values']['projection_line_color'] is None
        assert 'enabled' not in loaded['values'] and 'detail_level' not in loaded['values']
        source_entry = dict(token=loaded['token'], fields=list(loaded['values']))
        request = _request(targets=[2, 3], include_graphics=False,
                           include_visibility=False, pair_sources={(2, 101): source_entry})
        plan = g.plan(request)
        assert plan['rows'][0]['after']['projection_line_color'] is None
        assert plan['rows'][0]['after']['transparency'] == 37
        assert plan['rows'][1]['after']['transparency'] == 0
        assert not plan['rows'][1]['sources']
        reverted = dict(source_entry, fields=[key for key in source_entry['fields']
                                              if key != 'projection_line_color'])
        request['pair_sources'][(2, 101)] = reverted
        plan = g.plan(request)
        assert plan['rows'][0]['after']['projection_line_color'] == (80, 90, 100)
        assert 'projection_line_color' not in plan['rows'][0]['requested']
        request['pair_patches'] = {(2, 101): _set(transparency=60)}
        plan = g.plan(request)
        assert plan['rows'][0]['after']['transparency'] == 60
        g.apply(g.approve_updates(plan))
        assert not any(w[1] == 1 for w in d.writes)
        assert not g.plan(request, completed=g.apply(g.plan(request))['receipts'])['counts']['Add']
        _reject(lambda: g.load_source_draft(101, [1], include_graphics=False,
                                            include_visibility=False))
        bad = _request(pair_sources={(2, 101): dict(token='not minted', fields=['halftone'])})
        assert g.plan(bad)['rows'][0]['action'] == 'Invalid'
        request = _request(targets=[2], include_graphics=False, include_visibility=False,
                           pair_sources={(2, 101): source_entry})
        plan = g.approve_updates(g.plan(request))
        d.elements[1].attachments[101]['visibility'] = True
        before_writes = list(d.writes)
        _reject(lambda: g.apply(plan))
        assert before_writes == d.writes
        checks.append('explicit immutable source loads scoped per pair; genuine unsets copied, revert retains target, custom overlay, stale source rejects before writes')
        d = _FakeDoc()
        d.elements[1].seed(101, visibility=False, halftone=True, transparency=37)
        d.elements[3].seed(101, visibility=True, halftone=False, transparency=62)
        d.elements[2].seed(101)
        g = fg.GraphicService(_FakeService(d))
        visibility = g.load_source_draft(101, [1], include_graphics=False)
        graphics = g.load_source_draft(101, [3], include_visibility=False)
        contributions = [dict(token=load['token'], fields=list(load['values']))
                         for load in (visibility, graphics)]
        request = _request(targets=[2], include_graphics=False, include_visibility=False,
                           pair_sources={(2, 101): contributions})
        plan = g.approve_updates(g.plan(request))
        assert not plan['rows'][0]['after']['visibility']
        assert plan['rows'][0]['after']['transparency'] == 62
        assert set(s['target_id'] for s in plan['rows'][0]['sources']) == set((1, 3))
        g.apply(plan)
        assert not any(w[1] in (1, 3) for w in d.writes)
        overlapped = dict(request)
        overlapped['pair_sources'] = {(2, 101): contributions + [contributions[0]]}
        assert g.plan(overlapped)['rows'][0]['action'] == 'Invalid'
        cross_scope = dict(request, target_ids=[2, 3])
        cross_plan = g.plan(cross_scope)
        assert cross_plan['rows'][1]['action'] == 'Blocked'
        stale = g.approve_updates(g.plan(request))
        d.elements[1].attachments[101]['visibility'] = True
        before_writes = list(d.writes)
        _reject(lambda: g.apply(stale))
        assert before_writes == d.writes
        checks.append('partial source-load lists retain independent channel provenance; overlaps rejected, every source destination blocked, earlier token stale guard preserved')
        abandoned = g.load_source_draft(101, [3])
        retained = set((visibility['token'], graphics['token']))
        g.prune_source_drafts(retained)
        assert set(g._source_loads) == retained
        assert g._loaded_sources(101, contributions)['values']['transparency'] == 62
        _reject(lambda: g._loaded_source(101, dict(
            token=abandoned['token'], fields=list(abandoned['values']))))
        g.prune_source_drafts([])
        assert not g._source_loads
        checks.append('unreferenced source snapshots released; retained inactive/partial-channel tokens remain usable')
        assert len(messages) >= 7
    finally:
        fg.DB, fg.element_id, fg.id_value, fg.name_of, fg.supports_filters = original
        fg._log.removeHandler(handler)
        fg._log.propagate = old_propagate
    return checks


def run_detached():
    """Native detached OGS + fake planner checks; no Revit model reads/writes."""
    checks = []
    original = DB.OverrideGraphicSettings()
    original.SetDetailLevel(DB.ViewDetailLevel.Fine)
    try:
        for field in fg.FIELDS:
            if not field['can_clear']:
                continue
            value = (10, 20, 30) if field['kind'] == 'color' else (
                5 if field['kind'] == 'weight' else
                fm.id_value(DB.LinePatternElement.GetSolidPatternId()) if field['resource_kind'] == 'line' else
                42)  # Detached OGS has no document; eligibility is tested separately.
            first = fg._patch_ogs(original, {field['key']: value})
            try:
                assert fg._flat(first, [field['key']])[field['key']] == value
                clear = None if field['kind'] == 'color' else -1
                reset = fg._patch_ogs(first, {field['key']: clear})
                try:
                    assert fg._flat(reset, [field['key']])[field['key']] == clear
                    assert reset.DetailLevel == DB.ViewDetailLevel.Fine
                    assert original.DetailLevel == DB.ViewDetailLevel.Fine
                finally:
                    reset.Dispose()
            finally:
                first.Dispose()
        checks.append('native detached OGS copy/reset and protected DetailLevel for 14 clearable fields')
    finally:
        original.Dispose()
    return checks + _fake_checks()


class _ReadService(object):
    def __init__(self, doc):
        self.doc = doc
        self._native = fm.FilterService.__new__(fm.FilterService)
        self._native.doc = doc

    def template_controls(self, template):
        return self._native.template_controls(template)

    def atomic(self, title, action, verify=None):
        raise AssertionError('Read-only test attempted a model transaction.')


def run(doc, uidoc=None):
    """Read-only acceptance entry: detached suite + at most FIVE native pairs.

    No full-project graphics benchmark, WPF, selection changes or transactions.
    Returns check labels plus focused/cached/source-load timing diagnostics.
    Existing sample projects can have IsModified already True; preserve it.
    """
    modified = doc.IsModified
    selected = tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) if uidoc else None
    checks = run_detached()
    service = fg.GraphicService(_ReadService(doc))
    assert not service._cache and service._catalogue is None
    pairs = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if fm.supports_filters(view):
            for fid in service.membership(fm.id_value(view.Id)):
                if isinstance(doc.GetElement(fm.element_id(fid)), DB.ParameterFilterElement):
                    pairs.append((fm.id_value(view.Id), fid))
                    break
        if len(pairs) == 5:
            break
    timings = {}
    if pairs:
        start = time.time()
        first = service.snapshot(*pairs[0])
        timings['focused_ms'] = (time.time() - start) * 1000.0
        start = time.time()
        repeat = service.snapshot(*pairs[0])
        timings['cached_ms'] = (time.time() - start) * 1000.0
        assert first == repeat and first['attached'] and set(first['coverage']) == set(fg.FULL)
        events = []
        loaded = service.read_batch(pairs, progress=events.append)
        assert not loaded['errors'] and not loaded['cancelled'] and not loaded['remaining']
        assert all(e['slice_pairs'] <= 5 for e in events)
        for tid, fid in pairs:
            direct = doc.GetElement(fm.element_id(tid))
            ogs = direct.GetFilterOverrides(fm.element_id(fid))
            try:
                expected = fg._flat(ogs, fg.GRAPHICS + ('detail_level',))
            finally:
                ogs.Dispose()
            expected.update(visibility=bool(direct.GetFilterVisibility(fm.element_id(fid))),
                            enabled=bool(direct.GetIsFilterEnabled(fm.element_id(fid))))
            assert loaded['snapshots'][(tid, fid)]['values'] == expected
        checks.append('five-or-fewer real flat snapshots exactly match native getters; bounded progress/cache')
    else:
        checks.append('sample has no eligible attachment pairs; native snapshot check NOT RUN')
    assert doc.IsModified == modified
    if uidoc:
        assert selected == tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds())
    return dict(checks=checks, count=len(checks), pair_count=len(pairs), timings=timings,
                model_writes=False, modified_unchanged=True)


def model_fixture(doc, fixture, uidoc=None):
    """MUTATING fixture ONLY for parent-approved disposable model/dry-run.

    Never called by run(). Caller must provide fixture:
      {authorized:True, expected_title:doc.Title, source_id:sid,
       target_id:tid, existing_filter_id:fid, new_filter_id:fid2}.
    Both rule definitions must already exist and be attached to source, source
    visibility=False; existing target attachment must be disabled and fid2
    missing. Target must be direct/uncontrolled and not source. Parent owns
    fixture creation and rollback/Undo; this function invokes real atomic Apply.
    Return exact per-pair readback/count/receipt evidence, not UI acceptance.
    """
    if fixture.get('authorized') is not True or fixture.get('expected_title') != doc.Title:
        raise ValueError('Explicit disposable-document fixture authorization is required.')
    service = fg.GraphicService(_ReadService(doc))
    # Replace the read-only adapter ONLY after explicit guard above.
    service.filter_service = fm.FilterService.__new__(fm.FilterService)
    service.filter_service.doc = doc
    source, target = fixture['source_id'], fixture['target_id']
    existing, new = fixture['existing_filter_id'], fixture['new_filter_id']
    assert source != target
    first, second = service.snapshot(source, existing), service.snapshot(source, new)
    assert first['attached'] and second['attached']
    assert not first['values']['visibility'] and not second['values']['visibility']
    before = service.snapshot(target, existing)
    assert before['attached'] and not before['values']['enabled']
    assert not service.snapshot(target, new)['attached']
    request = _request(filters=[existing, new], targets=[target], origins=[source])
    proposal = service.plan(request)
    assert proposal['counts']['Add'] == 1
    result = service.apply(proposal)
    actual_new = result['snapshots'][(target, new)]
    assert actual_new['values']['enabled'] and not actual_new['values']['visibility']
    assert service.snapshot(target, existing)['values'] == before['values']
    retained = service.plan(request, completed=result['receipts'])
    result2 = service.apply(service.approve_updates(retained))
    actual_existing = service.snapshot(target, existing)
    assert not actual_existing['values']['enabled']
    assert not actual_existing['values']['visibility']
    assert actual_existing['values']['detail_level'] == before['values']['detail_level']
    assert service.membership(target) == before['order'] + (new,)
    return dict(first=result['counts'], second=result2['counts'],
                receipts=result['receipts'] + result2['receipts'],
                enabled_preserved=True, new_enabled=True, source_visibility_copied=True)


def run_mutating(doc, uidoc=None):
    """MUTATING: parent-approved dry_run fixture entry; NEVER called by run().

    Creates exactly 3 category-only filter definitions, 5 plan views and 1 view
    template. Existing levels, a FloorPlan ViewFamilyType and drafting fill/line
    resources are READ ONLY dependencies; never edits a pre-existing view,
    definition or graphics setting. Cleans up all nine fixture elements in
    finally, with post-commit deletion readback. Parent must use an explicitly
    approved disposable/sample document and run_modify(dry_run=True) first.

    Covers exact 20 graphics+visibility, disabled policy, partial Adds/pending
    Updates then approval/receipts, blank All Project, selected source variants/
    channels/custom Keep, native reset vs Solid, stale approvals, source order,
    template impact and forced AFTER-commit verification failure/group rollback.
    No save/reload/selection/WPF; this is NOT an Undo or committed UI test.
    """
    if doc.IsFamilyDocument or doc.IsReadOnly or doc.IsModifiable:
        raise ValueError('Fixture requires an idle writable project; authorize its dry-run explicitly.')
    if uidoc is not None and uidoc.Document != doc:
        raise ValueError('The fixture document is not the active document.')
    native = fm.FilterService.__new__(fm.FilterService)
    native.doc = doc
    service = fg.GraphicService(native)
    view_type = next((v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                      if v.ViewFamily == DB.ViewFamily.FloorPlan), None)
    level = next(iter(DB.FilteredElementCollector(doc).OfClass(DB.Level)), None)
    categories = sorted(fm.id_value(i) for i in
                        DB.ParameterFilterUtilities.GetAllFilterableCategories())
    fills = service.resources('fill')
    fill = next((r['id'] for r in fills if r['solid']), None)
    if view_type is None or level is None or not categories or fill is None:
        raise ValueError('Fixture needs an existing level, FloorPlan type, filterable category and drafting solid fill.')
    solid = fm.id_value(DB.LinePatternElement.GetSolidPatternId())
    selected_before = tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) if uidoc else None
    prefix = 'FM graphics fixture ' + uuid.uuid4().hex[:12]
    created, checks, fixture_ids, cleanup_ids = [], [], {}, []
    values = {}
    for index, field in enumerate(fg.FIELDS):
        if not field['setter']:
            continue
        kind = field['kind']
        values[field['key']] = (
            (10 + index, 40 + index, 80 + index) if kind == 'color' else
            solid if field['resource_kind'] == 'line' else
            fill if field['resource_kind'] == 'fill' else
            7 if kind == 'weight' else
            37 if kind == 'int' else
            field['key'] == 'halftone')
    assert set(values) == set(fg.GRAPHICS)

    def create():
        filters = [DB.ParameterFilterElement.Create(
            doc, prefix + ' F' + str(i), fm.ids(categories[:1])) for i in range(3)]
        created.extend(fm.id_value(e.Id) for e in filters)
        views = []
        for i in range(5):
            view = DB.ViewPlan.Create(doc, view_type.Id, level.Id)
            created.append(fm.id_value(view.Id))
            view.Name = prefix + ' V' + str(i)
            # A type's automatic template must not turn a new fixture view into
            # a destination controlled by a PRE-EXISTING template.
            view.ViewTemplateId = fm.element_id(-1)
            views.append(view)
        source, alternate, target, blank, consumer = views
        first, new, unrelated = filters
        for definition in (new, first):
            source.AddFilter(definition.Id)
            settings = DB.OverrideGraphicSettings()
            patched = None
            try:
                patched = fg._patch_ogs(settings, values)
                source.SetFilterOverrides(definition.Id, patched)
            finally:
                if patched is not None:
                    patched.Dispose()
                settings.Dispose()
            source.SetFilterVisibility(definition.Id, False)
            source.SetIsFilterEnabled(definition.Id, False)
        alternate.AddFilter(first.Id)
        alternate.SetFilterVisibility(first.Id, True)
        target.AddFilter(unrelated.Id)
        target.AddFilter(first.Id)
        target.SetIsFilterEnabled(first.Id, False)
        protected = DB.OverrideGraphicSettings()
        try:
            protected.SetDetailLevel(DB.ViewDetailLevel.Fine)
            protected.SetProjectionLineWeight(11)
            target.SetFilterOverrides(first.Id, protected)
        finally:
            protected.Dispose()
        blank.AddFilter(first.Id)
        blank.SetIsFilterEnabled(first.Id, False)
        template = alternate.CreateViewTemplate()
        created.append(fm.id_value(template.Id))
        template.Name = prefix + ' Template'
        consumer.ViewTemplateId = template.Id
        fixture_ids.update(
            source=fm.id_value(source.Id), alternate=fm.id_value(alternate.Id),
            target=fm.id_value(target.Id), blank=fm.id_value(blank.Id),
            consumer=fm.id_value(consumer.Id), template=fm.id_value(template.Id),
            first=fm.id_value(first.Id), new=fm.id_value(new.Id),
            unrelated=fm.id_value(unrelated.Id))

    try:
        native.atomic('Create graphics test fixture', create)
        source, target, first, new = (fixture_ids[key] for key in
                                      ('source', 'target', 'first', 'new'))
        alternate, blank, template, consumer = (fixture_ids[key] for key in
                                                ('alternate', 'blank', 'template', 'consumer'))
        service.invalidate()
        before = service.snapshot(target, first)
        unrelated = service.snapshot(target, fixture_ids['unrelated'])
        loaded = dict((fid, service.load_source_draft(fid, [source]))
                      for fid in (first, new))
        request = _request(
            filters=[first, new], targets=[target],
            include_graphics=False, include_visibility=False,
            pair_sources=dict(((target, fid), [dict(
                token=draft['token'], fields=list(draft['values']))])
                for fid, draft in loaded.items()))
        proposal = service.plan(request)
        assert [r['action'] for r in proposal['rows']] == ['Add', 'Update']
        assert [r['key'][1] for r in proposal['rows']] == [new, first]
        result = service.apply(proposal)
        assert result['counts']['added'] == 1 and result['counts']['unapproved'] == 1
        actual_new = result['snapshots'][(target, new)]
        assert actual_new['values']['enabled'] is True
        assert actual_new['values']['visibility'] is False
        assert dict((k, actual_new['values'][k]) for k in fg.GRAPHICS) == values
        assert service.snapshot(target, first)['values'] == before['values']
        assert service.snapshot(target, fixture_ids['unrelated'])['values'] == unrelated['values']
        assert service.membership(target) == before['order'] + (new,)
        checks.append('explicit scoped Load then Add exact20+visibility from disabled source ends enabled; existing update pending; source-order append')

        pending = service.plan(request, completed=result['receipts'])
        assert pending['counts']['Completed'] == 1 and pending['counts']['Update'] == 1
        result2 = service.apply(service.approve_updates(pending))
        actual = result2['snapshots'][(target, first)]
        assert dict((k, actual['values'][k]) for k in fg.GRAPHICS) == values
        assert actual['values']['visibility'] is False and actual['values']['enabled'] is False
        assert actual['values']['detail_level'] == before['values']['detail_level']
        receipts = result['receipts'] + result2['receipts']
        assert service.plan(request, completed=receipts)['counts']['Completed'] == 2
        checks.append('approved retained Update copies exact20+visibility, preserves disabled/DetailLevel; receipts finish both')

        # All Project's checked source-channel defaults do not find a source.
        blank_before = service.snapshot(blank, first)
        all_project = service.plan(_request(filters=[first, new], targets=[blank]))
        assert all_project['counts']['Unchanged'] == 1 and all_project['counts']['Add'] == 1
        all_result = service.apply(all_project)
        assert all_result['counts']['added'] == 1
        assert service.snapshot(blank, first)['values'] == blank_before['values']
        assert service.snapshot(blank, new)['values']['enabled']
        checks.append('All Project blank graphics preserve existing disabled settings and add native defaults')

        # Multiple different origins require an explicit origin id.
        service.invalidate()
        variants = service.source_variants(first, [source, alternate])
        assert variants['complete'] and len(variants['groups']) == 2
        unresolved = service.plan(_request(targets=[blank], origins=[source, alternate], filters=[first]))
        assert unresolved['counts']['Invalid'] == 1
        chosen = service.plan(_request(
            targets=[blank], origins=[source, alternate], filters=[first],
            source_choices={first: source}, include_graphics=False))
        assert set(chosen['rows'][0]['requested']) == {'visibility'}
        toggled = service.plan(_request(
            targets=[blank], origins=[source], filters=[first],
            include_graphics=False, include_visibility=False,
            patches={first: _set(projection_line_weight=4)}))
        assert toggled['rows'][0]['requested'] == {'projection_line_weight': 4}
        kept = service.patch_draft(_set(projection_line_weight=4),
                                  {'projection_line_weight': {'op': 'keep'}})
        assert kept == {}
        checks.append('different variants unresolved until explicit origin; channel toggles preserve independent custom patches')

        # Clear all 14 native-reset fields, not bool/zero-transparency defaults.
        resets = dict((f['key'], {'op': 'clear'}) for f in fg.FIELDS if f['can_clear'])
        clear_plan = service.plan(_request(targets=[target], filters=[first], patches={first: resets}))
        clear_result = service.apply(service.approve_updates(clear_plan))
        cleared = clear_result['snapshots'][(target, first)]['values']
        for field in fg.FIELDS:
            if field['can_clear']:
                assert cleared[field['key']] == (None if field['kind'] == 'color' else -1)
        assert cleared['halftone'] is True and cleared['transparency'] == 37
        assert solid != -1 and actual['values']['projection_line_pattern_id'] == solid
        assert actual['values']['surface_foreground_pattern_id'] == fill
        checks.append('14 clears read back verified sentinels, Solid line/fill distinct; bool/transparency untouched')

        # Stale approval fails before writes, retaining the actual new state.
        stale = service.approve_updates(service.plan(_request(
            targets=[target], filters=[first], patches={first: _set(transparency=42)})))
        def external_fixture_edit():
            view = doc.GetElement(fm.element_id(target))
            view.SetFilterVisibility(fm.element_id(first), True)
        native.atomic('Change only fixture to test stale approval', external_fixture_edit)
        _reject(lambda: service.apply(stale))
        current = service.snapshot(target, first)
        assert current['values']['transparency'] == 37 and current['values']['visibility']
        checks.append('fresh native target read rejects stale approval; no proposal write')

        # Force failure AFTER real transaction commit, BEFORE assimilation.
        class FailAfterReadback(fg.GraphicService):
            def _verify(self, rows):
                readback = fg.GraphicService._verify(self, rows)
                self.observed_after_commit = not self.doc.IsModifiable
                assert readback[(target, first)]['values']['transparency'] == 42
                raise ValueError('Expected graphics fixture post-commit verification failure.')
        failing = FailAfterReadback(native)
        failure_plan = failing.approve_updates(failing.plan(_request(
            targets=[target], filters=[first], patches={first: _set(transparency=42)})))
        _reject(lambda: failing.apply(failure_plan))
        assert failing.observed_after_commit
        service.invalidate()
        restored = service.snapshot(target, first)
        assert restored['values'] == current['values'] and restored['order'] == current['order']
        checks.append('native tx committed and readback saw42, forced verify failure group-rollback restored37')

        assert native.template_controls(doc.GetElement(fm.element_id(template)))
        assert service.effective_sources([consumer, template]) == [template]
        controlled = service.plan(_request(targets=[consumer], filters=[first]))
        assert controlled['counts']['Blocked'] == 1
        shared = service.plan(_request(
            targets=[template], filters=[first], patches={first: _set(halftone=True)}))
        assert [v['id'] for v in shared['rows'][0]['impact']] == [consumer]
        template_result = service.apply(service.approve_updates(shared))
        assert template_result['counts']['updated'] == 1
        assert service.snapshot(template, first)['values']['halftone']
        checks.append('new template explicit target, new controlled view blocked, full consumer snapshot and postcommit readback')
    finally:
        remaining = [numeric for numeric in created
                     if doc.GetElement(fm.element_id(numeric)) is not None]
        if remaining:
            def delete_fixture():
                cleanup_ids.extend(fm.id_value(i) for i in doc.Delete(fm.ids(remaining)))
            def verify_cleanup(unused):
                assert all(doc.GetElement(fm.element_id(i)) is None for i in created)
            native.atomic('Remove only graphics test fixtures', delete_fixture, verify=verify_cleanup)
    if uidoc:
        assert selected_before == tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds())
    return dict(checks=checks, count=len(checks), fixture_ids=fixture_ids,
                cleanup_ids=cleanup_ids, cleaned=True, commits_require_outer_rollback=True,
                existing_model_settings_untouched=True)


def run_persistence_smoke(doc, uidoc=None):
    """MUTATING keeper: parent must preview, then obtain explicit commit approval.

    Intentionally KEEPS exactly one NEW category-only filter and two NEW plan
    views. No existing settings/definitions/resources are written. One Undo
    group covers creation plus GraphicService Apply; on any failure it rolls
    back. No cleanup on success: parent fresh-reads returned ids/unique_ids and
    settings, obtains one genuine user Undo, then verifies all three are gone.
    Never called by run()/run_mutating(). Does not save, change active view,
    selection or attempt Undo. The returned receipt is audit evidence for this
    service session, not a portable plan for another GraphicService instance.
    """
    if doc.IsFamilyDocument or doc.IsReadOnly or doc.IsModifiable:
        raise ValueError('Persistence smoke requires an authorized idle writable project.')
    if uidoc is not None and uidoc.Document != doc:
        raise ValueError('Persistence smoke document must be the active project.')
    native = fm.FilterService.__new__(fm.FilterService)
    native.doc = doc
    view_type = next((v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                      if v.ViewFamily == DB.ViewFamily.FloorPlan), None)
    level = next(iter(DB.FilteredElementCollector(doc).OfClass(DB.Level)), None)
    categories = sorted(fm.id_value(i) for i in
                        DB.ParameterFilterUtilities.GetAllFilterableCategories())
    if view_type is None or level is None or not categories:
        raise ValueError('Persistence smoke needs an existing FloorPlan type, level and filterable category.')
    selected = tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) if uidoc else None
    prefix = 'FM graphics keeper ' + uuid.uuid4().hex[:12]
    objects = {}
    group = DB.TransactionGroup(doc, 'Filter Manager: graphics persistence smoke')
    try:
        if group.Start() != DB.TransactionStatus.Started:
            raise ValueError('Could not start the persistence smoke Undo group.')

        def create():
            definition = DB.ParameterFilterElement.Create(doc, prefix, fm.ids(categories[:1]))
            source = DB.ViewPlan.Create(doc, view_type.Id, level.Id)
            destination = DB.ViewPlan.Create(doc, view_type.Id, level.Id)
            source.Name, destination.Name = prefix + ' source', prefix + ' destination'
            source.ViewTemplateId = fm.element_id(-1)
            destination.ViewTemplateId = fm.element_id(-1)
            source.AddFilter(definition.Id)
            settings = DB.OverrideGraphicSettings()
            try:
                settings.SetHalftone(True)
                settings.SetSurfaceTransparency(37)
                source.SetFilterOverrides(definition.Id, settings)
            finally:
                settings.Dispose()
            source.SetFilterVisibility(definition.Id, False)
            source.SetIsFilterEnabled(definition.Id, False)
            objects.update(filter=definition, source=source, destination=destination)

        native.atomic('Create three private persistence fixtures', create)
        ids = dict((key, fm.id_value(element.Id)) for key, element in objects.items())
        service = fg.GraphicService(native)
        source_before = service.snapshot(ids['source'], ids['filter'])
        assert source_before['values']['enabled'] is False
        assert source_before['values']['visibility'] is False
        assert source_before['values']['transparency'] == 37
        assert source_before['values']['halftone'] is True
        assert not service.snapshot(ids['destination'], ids['filter'])['attached']
        request = _request(filters=[ids['filter']], targets=[ids['destination']],
                           origins=[ids['source']])
        proposal = service.plan(request)
        assert proposal['counts']['Add'] == 1
        applied = service.apply(proposal)
        assert applied['counts']['added'] == 1 and applied['counts']['updated'] == 0
        destination = applied['snapshots'][(ids['destination'], ids['filter'])]
        expected = dict(source_before['values'])
        expected['enabled'] = True
        # DetailLevel is deliberately NOT copied.
        expected['detail_level'] = destination['values']['detail_level']
        assert destination['values'] == expected
        source_after = service.snapshot(ids['source'], ids['filter'], refresh=True)
        assert source_after['values'] == source_before['values']
        assert source_after['order'] == source_before['order']
        if uidoc:
            assert selected == tuple(fm.id_value(i) for i in uidoc.Selection.GetElementIds())
        result = dict(
            fixture_ids=ids,
            unique_ids=dict((key, element.UniqueId) for key, element in objects.items()),
            names=dict((key, fm.name_of(element)) for key, element in objects.items()),
            settings=dict(source=source_after['values'], destination=destination['values']),
            orders=dict(source=source_after['order'], destination=destination['order']),
            counts=applied['counts'], receipts=applied['receipts'],
            kept=True, fixture_element_count=3, existing_model_settings_untouched=True,
            undo_group='Filter Manager: graphics persistence smoke')
        if group.Assimilate() != DB.TransactionStatus.Committed:
            raise ValueError('Persistence fixture did not finish its Undo group.')
        return result
    except Exception:
        if group.GetStatus() == DB.TransactionStatus.Started:
            group.RollBack()
        fg._log.exception('Persistence smoke failed; no keeper fixtures were accepted.')
        raise
    finally:
        group.Dispose()
