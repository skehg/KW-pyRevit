# -*- coding: utf-8 -*-
"""Lazy attachment graphics backend. IronPython 2.7, Revit 2023+.

All methods run synchronously in a valid Revit API context. No WPF objects,
threads, model-event subscriptions, launch preload or implicit source discovery.
The host must call invalidate() after DocumentChanged/Undo, definition edits or
Refresh. Apply additionally re-reads every dependency, independent of the cache.
Cancelled/incomplete reads are never defaults. See GraphicService.plan for the
UI request contract; snapshots, plans and receipts contain only Python values.
"""
import hashlib
import logging
import time
import uuid
from collections import OrderedDict

from System import Byte
from pyrevit import DB
from filter_model import element_id, id_value, name_of, supports_filters

try:
    _integers = (int, long)
except NameError:
    _integers = (int,)


class GraphicsCancelled(Exception):
    """Explicit cancellation: discard the incomplete operation, not its draft."""


def _field(key, label, group, kind, getter=None, setter=None, clear=False,
           resource=None, bounds=None, editable=True):
    return dict(key=key, label=label, group=group, kind=kind, getter=getter,
                setter=setter, editable=editable, can_clear=clear,
                clear_capability=clear, resource_kind=resource, bounds=bounds,
                explicit_detection=clear)


_fields = [
    _field('visibility', 'Visible', 'Element visibility', 'bool'),
    _field('enabled', 'Enabled (preserved)', 'Filter enabled (read-only policy)',
           'bool', editable=False),
    _field('halftone', 'Halftone', 'Halftone', 'bool', 'Halftone', 'SetHalftone')]
for _prefix, _group, _native in (
        ('projection', 'Projection lines', 'Projection'),
        ('cut', 'Cut lines', 'Cut')):
    _fields.extend([
        _field(_prefix + '_line_weight', 'Line weight', _group, 'weight',
               _native + 'LineWeight', 'Set' + _native + 'LineWeight',
               True, 'weight', (1, 16)),
        _field(_prefix + '_line_color', 'Colour', _group, 'color',
               _native + 'LineColor', 'Set' + _native + 'LineColor', True,
               bounds=(0, 255)),
        _field(_prefix + '_line_pattern_id', 'Line pattern', _group, 'resource',
               _native + 'LinePatternId', 'Set' + _native + 'LinePatternId',
               True, 'line')])
for _prefix, _group, _native in (
        ('surface', 'Projection/surface patterns', 'Surface'),
        ('cut', 'Cut patterns', 'Cut')):
    for _layer in ('foreground', 'background'):
        _stem = _prefix + '_' + _layer + '_pattern_'
        _n = _native + _layer.title() + 'Pattern'
        _fields.extend([
            _field(_stem + 'id', _layer.title() + ' pattern', _group,
                   'resource', _n + 'Id', 'Set' + _n + 'Id', True, 'fill'),
            _field(_stem + 'color', _layer.title() + ' colour', _group,
                   'color', _n + 'Color', 'Set' + _n + 'Color', True,
                   bounds=(0, 255)),
            _field(_stem + 'visible', _layer.title() + ' visible', _group,
                   'bool', 'Is' + _n + 'Visible', 'Set' + _n + 'Visible')])
_fields.append(_field('transparency', 'Transparency (%)', 'Transparency', 'int',
                      'Transparency', 'SetSurfaceTransparency', bounds=(0, 100)))
# Descriptor order follows the seven UI groups, not setter order.
_groups = ('Element visibility', 'Halftone', 'Projection lines',
           'Projection/surface patterns', 'Transparency', 'Cut lines',
           'Cut patterns', 'Filter enabled (read-only policy)')
FIELDS = tuple(sorted(_fields, key=lambda f: _groups.index(f['group'])))
BY_KEY = dict((f['key'], f) for f in FIELDS)
GRAPHICS = tuple(f['key'] for f in FIELDS if f['setter'])
READABLE = tuple(f['key'] for f in FIELDS) + ('detail_level',)
FULL = READABLE
_log = logging.getLogger('FilterManager.graphics')


def _number(value):
    if isinstance(value, bool) or not isinstance(value, _integers):
        raise ValueError('Expected a stable numeric element id, not a UI object.')
    return int(value)


def _ordered(values):
    """Lists/tuples preserve order; mappings/sets use numeric sorted order."""
    if isinstance(values, dict):
        values = sorted(values)
    elif isinstance(values, (set, frozenset)):
        values = sorted(values)
    result = []
    for value in values:
        value = _number(value)
        if value not in result:
            result.append(value)
    return result


def _freeze(value):
    if isinstance(value, dict):
        return tuple((k, _freeze(v)) for k, v in
                     sorted(value.items(), key=lambda item: repr(item[0])))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(v) for v in value), key=repr))
    return value


def _digest(value):
    return hashlib.sha256(repr(_freeze(value)).encode('utf-8')).hexdigest()


def _clone(value):
    """Copy the plain-container contract without generic deepcopy dispatch."""
    if isinstance(value, dict):
        return dict((key, _clone(item)) for key, item in value.items())
    if isinstance(value, list):
        return [_clone(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return type(value)(_clone(item) for item in value)
    return value


def _plain(value):
    if value is None or isinstance(value, _integers + (bool, float, str, type(u''))):
        return True
    if isinstance(value, dict):
        return all(_plain(key) and _plain(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(_plain(item) for item in value)
    return False


def _check_cancel(cancel):
    if cancel is not None and cancel():
        raise GraphicsCancelled('Graphics loading cancelled; draft preserved.')


def _progress(callback, start, done, total, phase, **extra):
    if callback is not None:
        data = dict(done=done, total=total,
                    elapsed_ms=(time.time() - start) * 1000.0, phase=phase)
        data.update(extra)
        callback(data)


def _operation_progress(callback):
    """Keep elapsed time cumulative when a loader has nested subphases."""
    if callback is None:
        return None
    start = time.time()
    def report(data):
        data = dict(data)
        data['elapsed_ms'] = (time.time() - start) * 1000.0
        callback(data)
    return report


def _identity(element):
    return (element.UniqueId, str(element.VersionGuid))


def _flat(ogs, fields):
    values = {}
    for key in fields:
        if key == 'detail_level':
            values[key] = str(ogs.DetailLevel)
            continue
        field = BY_KEY[key]
        if not field['getter']:
            continue
        value = getattr(ogs, field['getter'])
        if field['kind'] == 'color':
            value = (int(value.Red), int(value.Green), int(value.Blue)) if value.IsValid else None
        elif field['kind'] == 'resource':
            value = id_value(value)
        elif field['kind'] in ('weight', 'int'):
            value = int(value)
        else:
            value = bool(value)
        values[key] = value
    return values


def _covered(snapshot, fields):
    """Return only requested channels, even when internal cache covers more."""
    result = dict(snapshot)
    result['coverage'] = tuple(sorted(fields))
    result['values'] = dict((k, v) for k, v in result['values'].items() if k in fields)
    result['template'] = dict(snapshot['template'])
    return result


def _native_value(field, value):
    if field['kind'] == 'color':
        return (DB.Color.InvalidColorValue if value is None else
                DB.Color(Byte(value[0]), Byte(value[1]), Byte(value[2])))
    if field['kind'] == 'resource':
        return element_id(value)
    return value


def _patch_ogs(original, values):
    """Copy the native object; preserve DetailLevel and every unrequested field."""
    clone = DB.OverrideGraphicSettings(original)
    for key, value in values.items():
        field = BY_KEY[key]
        if field['setter']:
            getattr(clone, field['setter'])(_native_value(field, value))
    return clone


def _row_token(row):
    return _digest(dict((k, v) for k, v in row.items()
                        if k not in ('approved', 'excluded', 'approval_token')))


def _plan_token(plan):
    return _digest((plan['document'], plan['epoch'], plan['request'],
                    [(row['key'], row['approval_token']) for row in plan['rows']]))


def _template_after(before, after, written_views):
    """A template we intentionally write gets a new version, not a new identity."""
    expected = dict(before)
    if expected['identity'] and expected['template_id'] in written_views:
        identity = after['identity']
        if identity is None or identity[0] != expected['identity'][0]:
            return False
        expected['identity'] = identity
    return expected == after


def _counts(rows):
    result = dict((key, 0) for key in
                  ('Add', 'Update', 'Unchanged', 'Blocked', 'Invalid', 'Completed'))
    for row in rows:
        result[row['action']] += 1
    return result


class GraphicService(object):
    """GraphicService(filter_service): no graphics or catalogue reads at init.

    filter_service must expose .doc, .template_controls(template), and
    .atomic(title, action, verify=None). verify(result) MUST execute after the
    native transaction commits, BEFORE the transaction group assimilates.
    """
    FIELDS = FIELDS
    cache_limit = 256 * 1024  # Serialized-value budget, NOT managed heap size.

    def __init__(self, filter_service):
        self.filter_service = filter_service
        self.doc = filter_service.doc
        self.document_token = uuid.uuid4().hex
        self._epoch = 0
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._members = {}
        self._contexts = {}
        self._definitions = {}
        self._info = {}
        self._resources = {}
        self._catalogue = None
        self._impact_cache = {}
        self._source_loads = {}

    def invalidate(self, keys=None):
        """Invalidate on external edits/Undo/Refresh or after mutation.

        keys=None drops all coverage, catalogues, resource/impact metadata and
        invalidates outstanding plans. keys may identify affected (target_id,fid)
        pairs; currently this conservatively drops the entire cache too because
        view versions, order and template dependencies cross pair boundaries.
        No native reads. UI must reload/review; approvals cannot survive this.
        """
        self._epoch += 1
        if keys is None:
            self._cache.clear()
            self._cache_bytes = 0
        else:
            for key in keys:
                cached = self._cache.pop(tuple(key), None)
                if cached:
                    self._cache_bytes -= cached[1]
        self._members.clear()
        self._contexts.clear()
        self._definitions.clear()
        self._info.clear()
        self._resources.clear()
        self._impact_cache.clear()
        self._catalogue = None
        # A partial invalidation must not retain old metadata in other pairs.
        for key in list(self._cache):
            cached = self._cache.pop(key)
            self._cache_bytes -= cached[1]

    def _element(self, numeric, expected):
        element = self.doc.GetElement(element_id(_number(numeric)))
        if (element is None or not isinstance(element, expected) or
                not element.IsValidObject or element.Document != self.doc):
            raise ValueError('Element {} is missing or no longer a valid {}.'.format(
                numeric, expected.__name__))
        return element

    def target_info(self, target_id):
        """Return lazy named target metadata, never OGS or a native object.

        Keys: id,name,view_type,is_template,template_id,controlled,
        controlling_template_id,supported,unique_id. Controlled direct views
        remain inspectable; selecting their template is a separate UI action.
        """
        tid = _number(target_id)
        if tid not in self._info:
            view = self._element(tid, DB.View)
            template_id = -1 if view.IsTemplate else id_value(view.ViewTemplateId)
            template = self.doc.GetElement(element_id(template_id)) if template_id != -1 else None
            controlled = not view.IsTemplate and self.filter_service.template_controls(template)
            self._info[tid] = dict(
                id=tid, name=name_of(view), view_type=str(view.ViewType),
                is_template=bool(view.IsTemplate), template_id=template_id,
                controlled=bool(controlled),
                controlling_template_id=template_id if controlled else None,
                supported=bool(supports_filters(view)), unique_id=view.UniqueId)
        return dict(self._info[tid])

    def targets(self, candidate_ids, cancel=None, progress=None):
        """Resolve only explicit numeric candidates; cancellation raises.

        progress(data) is invoked on this API thread at most five items apart
        and on completion (including cache hits). It may pump WPF's dispatcher;
        it must not start a model operation or re-enter this service.
        """
        result, start = [], time.time()
        candidates = _ordered(candidate_ids)
        for index, tid in enumerate(candidates):
            _check_cancel(cancel)
            result.append(self.target_info(tid))
            if (index + 1) % 5 == 0:
                _progress(progress, start, index + 1, len(candidates), 'targets')
        _check_cancel(cancel)
        _progress(progress, start, len(result), len(candidates), 'targets', complete=True)
        return result

    def project_targets(self, cancel=None, progress=None):
        """Lazily collect supported project views/templates, with no OGS reads.

        Returns list of target_info dicts; only a complete result is cached.
        Raises GraphicsCancelled, never an empty/default catalogue on cancel.
        """
        progress = _operation_progress(progress)
        _check_cancel(cancel)
        if self._catalogue is not None:
            return _clone(self._catalogue)
        # Collection is intentionally deferred until explicit Project request.
        candidates = [id_value(v.Id) for v in
                      DB.FilteredElementCollector(self.doc).OfClass(DB.View)]
        result = [info for info in self.targets(candidates, cancel, progress)
                  if info['supported']]
        result.sort(key=lambda info: (info['name'].lower(), info['id']))
        self._catalogue = result
        return _clone(result)

    def membership(self, target_id, refresh=False):
        """Ordered attached filter ids, cached independently of graphics."""
        tid = _number(target_id)
        if refresh or tid not in self._members:
            view = self._element(tid, DB.View)
            if not supports_filters(view):
                raise ValueError('Target {} does not support view filters.'.format(tid))
            self._members[tid] = tuple(id_value(fid) for fid in view.GetOrderedFilters())
        return self._members[tid]

    def effective_sources(self, origin_ids, cancel=None, progress=None):
        """Deduplicated effective numeric origins; only controlling templates inherit.

        Empty input is All Project Filters and returns []; it never discovers
        implicit consumers. Unsupported explicit sources raise ValueError.
        """
        result, start = [], time.time()
        origins = _ordered(origin_ids)
        for index, oid in enumerate(origins):
            _check_cancel(cancel)
            info = self.target_info(oid)
            if not info['supported']:
                raise ValueError('Source {} does not support view filters.'.format(oid))
            effective = info['controlling_template_id'] if info['controlled'] else oid
            if effective not in result:
                result.append(effective)
            if (index + 1) % 5 == 0:
                _progress(progress, start, index + 1, len(origins), 'sources')
        _check_cancel(cancel)
        _progress(progress, start, len(origins), len(origins), 'sources', complete=True)
        return result

    def source_filters(self, origin_ids, cancel=None, progress=None):
        """{fid:[effective_origin_ids]} in effective attachment order; zero OGS."""
        progress = _operation_progress(progress)
        result, start = OrderedDict(), time.time()
        origins = self.effective_sources(origin_ids, cancel, progress)
        for index, oid in enumerate(origins):
            _check_cancel(cancel)
            for fid in self.membership(oid):
                result.setdefault(fid, []).append(oid)
            _check_cancel(cancel)
            if (index + 1) % 5 == 0:
                _progress(progress, start, index + 1, len(origins), 'source-membership')
        _progress(progress, start, len(origins), len(origins), 'source-membership', complete=True)
        return result

    def _template_state(self, view):
        if view.IsTemplate:
            return dict(template_id=-1, controls=bool(self.filter_service.template_controls(view)),
                        identity=None)
        tid = id_value(view.ViewTemplateId)
        template = self.doc.GetElement(element_id(tid)) if tid != -1 else None
        return dict(template_id=tid,
                    controls=bool(self.filter_service.template_controls(template)),
                    identity=_identity(template) if template is not None else None)

    def _source_candidate(self, candidate_id):
        """Fresh original selection provenance; never use effective-id caches."""
        view = self._element(candidate_id, DB.View)
        if not supports_filters(view):
            raise ValueError('Selected source {} no longer supports view filters.'.format(candidate_id))
        template = self._template_state(view)
        effective = (template['template_id'] if not view.IsTemplate and
                     template['controls'] else candidate_id)
        return dict(candidate_id=candidate_id, identity=_identity(view),
                    template=template, effective_id=effective)

    def _source_candidates(self, candidate_ids, cancel=None, progress=None):
        result, start = [], time.time()
        for index, candidate_id in enumerate(candidate_ids):
            _check_cancel(cancel)
            result.append(self._source_candidate(candidate_id))
            if (index + 1) % 5 == 0:
                _progress(progress, start, index + 1, len(candidate_ids), 'source-provenance')
        _check_cancel(cancel)
        _progress(progress, start, len(result), len(candidate_ids), 'source-provenance', complete=True)
        return result

    def _check_source_candidates(self, expected, cache, written_views=()):
        for candidate in expected:
            candidate_id = candidate['candidate_id']
            if candidate_id not in cache:
                cache[candidate_id] = self._source_candidate(candidate_id)
            fresh = cache[candidate_id]
            if not _template_after(candidate['template'], fresh['template'], written_views):
                raise ValueError('Selected source template assignment/control changed; reload and review.')
            adjusted = dict(candidate)
            adjusted['template'] = fresh['template']
            if _freeze(adjusted) != _freeze(fresh):
                raise ValueError('Selected source identity/effective origin changed; reload and review.')

    def _impact(self, template_id, refresh=False, cancel=None, progress=None):
        if not refresh and template_id in self._impact_cache:
            return _clone(self._impact_cache[template_id])
        template = self._element(template_id, DB.View)
        result, start = [], time.time()
        if self.filter_service.template_controls(template):
            views = list(DB.FilteredElementCollector(self.doc).OfClass(DB.View))
            for index, view in enumerate(views):
                _check_cancel(cancel)
                if not view.IsTemplate and id_value(view.ViewTemplateId) == template_id:
                    result.append(dict(id=id_value(view.Id), unique_id=view.UniqueId,
                                       name=name_of(view), view_type=str(view.ViewType)))
                if (index + 1) % 5 == 0:
                    _progress(progress, start, index + 1, len(views), 'template-impact')
            _progress(progress, start, len(views), len(views), 'template-impact', complete=True)
        result.sort(key=lambda info: info['id'])
        self._impact_cache[template_id] = result
        return _clone(result)

    def _read(self, tid, fid, fields, refresh=False):
        if refresh or tid not in self._contexts:
            view = self._element(tid, DB.View)
            self._contexts[tid] = (view, dict(
                target_identity=_identity(view),
                order=self.membership(tid, refresh=refresh),
                template=self._template_state(view),
                is_template=bool(view.IsTemplate)))
        view, context = self._contexts[tid]
        if refresh or fid not in self._definitions:
            self._definitions[fid] = _identity(self._element(fid, DB.ParameterFilterElement))
        order = context['order']
        attached = fid in order
        values = {}
        if attached:
            native_fields = [key for key in fields if key not in ('visibility', 'enabled')]
            if native_fields:
                ogs = view.GetFilterOverrides(element_id(fid))
                try:
                    values.update(_flat(ogs, native_fields))
                finally:
                    ogs.Dispose()
            if 'visibility' in fields:
                values['visibility'] = bool(view.GetFilterVisibility(element_id(fid)))
            if 'enabled' in fields:
                values['enabled'] = bool(view.GetIsFilterEnabled(element_id(fid)))
        return dict(document=self.document_token, target_id=tid, filter_id=fid,
                    attached=attached, values=values, coverage=tuple(sorted(fields)),
                    target_identity=context['target_identity'],
                    filter_identity=self._definitions[fid],
                    order=order, template=dict(context['template']),
                    is_template=context['is_template'])

    def _store(self, key, snapshot):
        old = self._cache.pop(key, None)
        if old:
            self._cache_bytes -= old[1]
        # Plain Python-value serialization. Avoid IronPython's pure-Python JSON
        # encoder on every native pair; this is a payload cap, not a heap claim.
        size = len(repr(snapshot).encode('utf-8'))
        if size <= self.cache_limit:
            self._cache[key] = (_covered(snapshot, set(snapshot['coverage'])), size)
            self._cache_bytes += size
        while self._cache_bytes > self.cache_limit and self._cache:
            _unused, cached = self._cache.popitem(last=False)
            self._cache_bytes -= cached[1]

    def snapshot(self, target_id, filter_id, fields=None, refresh=False):
        """Return one flat snapshot, no native reads on valid covered repeats.

        fields=None loads FULL (20 graphics + visibility + enabled + protected
        detail_level). Partial coverage is explicit. attached=False has empty
        values, NEVER native defaults. refresh=True re-reads membership/identity
        and requested fields; caches need host invalidation on external edits.
        Returned dictionaries can safely be edited by callers.
        """
        tid, fid = _number(target_id), _number(filter_id)
        fields = set(FULL if fields is None else fields)
        requested = set(fields)
        if fields - set(READABLE):
            raise ValueError('Unknown snapshot field(s): {}'.format(sorted(fields - set(READABLE))))
        key = (tid, fid)
        cached = self._cache.get(key)
        if cached and not refresh:
            old = cached[0]
            if fields <= set(old['coverage']):
                self._cache.pop(key)
                self._cache[key] = cached
                return _covered(old, requested)
            fields.update(old['coverage'])
        snapshot = self._read(tid, fid, fields, refresh=refresh)
        self._store(key, snapshot)
        return _covered(snapshot, requested)

    def read_slices(self, keys, fields=None, max_pairs=5, max_ms=100,
                    cancel=None, progress=None, refresh=False):
        """Yield read_batch-shaped cumulative results on the API thread.

        A slice has <=5 pairs and an elapsed-time target (not a guarantee for
        one native call). Check cancel before AND after each pair. A caller
        can pump its UI between yields; progress is called each slice, even
        below 1s. Cancel returns one explicit partial result then stops.
        Errors are per-pair strings, never synthetic default snapshots.
        """
        return self._read_slices(keys, fields, max_pairs, max_ms, cancel,
                                 progress, refresh, True)

    def _read_slices(self, keys, fields, max_pairs, max_ms, cancel, progress,
                     refresh, copy_results):
        if (isinstance(max_pairs, bool) or not isinstance(max_pairs, _integers) or
                max_pairs < 1 or max_pairs > 5 or max_ms <= 0):
            raise ValueError('Read slices require 1..5 pairs and positive max_ms.')
        if isinstance(keys, (dict, set, frozenset)):
            keys = sorted(keys)
        keys = list(OrderedDict(((_number(t), _number(f)), None) for t, f in keys))
        done, errors, start, index = {}, {}, time.time(), 0
        while index < len(keys):
            slice_start, count, cancelled = time.time(), 0, False
            while index < len(keys) and count < max_pairs:
                key = keys[index]
                try:
                    _check_cancel(cancel)
                    done[key] = self.snapshot(key[0], key[1], fields, refresh)
                    index += 1
                    count += 1
                    _check_cancel(cancel)
                except GraphicsCancelled:
                    cancelled = True
                    break
                except ValueError as error:
                    errors[key] = str(error)
                    index += 1
                    count += 1
                if (time.time() - slice_start) * 1000.0 >= max_ms:
                    break
            _progress(progress, start, index, len(keys), 'attachments',
                      cancelled=cancelled, complete=index == len(keys), slice_pairs=count)
            yield dict(snapshots=_clone(done) if copy_results else done, errors=dict(errors),
                       remaining=keys[index:], cancelled=cancelled)
            if cancelled:
                return
        if not keys:
            _check_cancel(cancel)
            _progress(progress, start, 0, 0, 'attachments', complete=True, slice_pairs=0)
            yield dict(snapshots={}, errors={}, remaining=[], cancelled=False)

    def read_batch(self, keys, fields=None, max_pairs=5, max_ms=100,
                   cancel=None, progress=None, refresh=False):
        """Drain read_slices; return {snapshots,errors,remaining,cancelled}.

        Synchronous/main-thread, bounded pumping via progress callback. Inspect
        all four result members; cancelled/errors must block dependent planning.
        """
        result = None
        # Intermediate cumulative results are not exposed by this draining
        # method. Each snapshot is already isolated from its internal cache;
        # do not clone the entire growing prefix at every slice (quadratic).
        for result in self._read_slices(keys, fields, max_pairs, max_ms,
                                        cancel, progress, refresh, False):
            pass
        return result

    def source_variants(self, filter_id, origin_ids, include_graphics=True,
                        include_visibility=True, cancel=None, progress=None,
                        source_mode='exact'):
        """Group identical SELECTED channels; enabled never participates.

        Returns {groups:[{origin_ids,values,token}],complete,missing,cancelled,
        errors,snapshots}. Missing/unloaded/error sources aren't default variants.
        One group may resolve automatically; multiple groups need an explicit
        per-filter effective origin id. No source requests => no native reads.
        source_mode='explicit' copies only reliably detectable non-unset graphics
        (14 clearable fields), NEVER guesses booleans/zero transparency. The
        independent visibility channel still copies its explicit On/Off choice.
        """
        progress = _operation_progress(progress)
        if source_mode not in ('exact', 'explicit'):
            raise ValueError('Source mode must be exact or explicit.')
        fid = _number(filter_id)
        origins = self.effective_sources(origin_ids, cancel, progress)
        fields = [key for key in GRAPHICS if source_mode == 'exact' or
                  BY_KEY[key]['explicit_detection']] if include_graphics else []
        if include_visibility:
            fields.append('visibility')
        if not origins or not fields:
            return dict(groups=[], complete=True, missing=[], cancelled=False,
                        errors={}, snapshots={})
        loaded = self.read_batch([(oid, fid) for oid in origins], fields,
                                 cancel=cancel, progress=progress)
        groups, missing = OrderedDict(), []
        for oid in origins:
            snap = loaded['snapshots'].get((oid, fid))
            if snap is None:
                continue
            if not snap['attached']:
                missing.append(oid)
                continue
            values = dict((key, snap['values'][key]) for key in fields)
            if source_mode == 'explicit':
                values = dict((key, value) for key, value in values.items()
                              if key == 'visibility' or value not in (None, -1))
            token = _digest(values)
            group = groups.setdefault(token, dict(origin_ids=[], values=values, token=token))
            group['origin_ids'].append(oid)
        return dict(groups=list(groups.values()), missing=missing,
                    complete=not (missing or loaded['remaining'] or loaded['errors'] or loaded['cancelled']),
                    cancelled=loaded['cancelled'], errors=loaded['errors'],
                    snapshots=loaded['snapshots'])

    def resources(self, kind, cancel=None, progress=None):
        """Lazy list of {id,name,...}, kind='line'/'fill'/'weight'.

        Line includes the native Solid sentinel, NEVER named line styles.
        Fill includes only actual drafting FillPatternElements (including solid).
        Clear is an operation, not a fabricated resource. No implicit creations.
        cancel()/progress(data) run on the API thread every <=5 inspected
        patterns. Cancellation raises GraphicsCancelled; partial catalogues are
        not cached. Cached repeats have zero native reads.
        """
        if kind not in ('line', 'fill', 'weight'):
            raise ValueError('Unknown graphics resource kind: {}'.format(kind))
        start = time.time()
        inspected_total = None
        _check_cancel(cancel)
        if kind not in self._resources:
            if kind == 'weight':
                result = [dict(id=i, name=str(i)) for i in range(1, 17)]
            else:
                expected = DB.LinePatternElement if kind == 'line' else DB.FillPatternElement
                elements = DB.FilteredElementCollector(self.doc).OfClass(expected)
                total = elements.GetElementCount()
                inspected_total = total
                result = ([dict(id=id_value(DB.LinePatternElement.GetSolidPatternId()),
                                name='Solid', solid=True)] if kind == 'line' else [])
                for index, element in enumerate(elements):
                    _check_cancel(cancel)
                    if kind == 'line':
                        result.append(dict(id=id_value(element.Id), name=name_of(element), solid=False))
                    else:
                        pattern = element.GetFillPattern()
                        try:
                            if pattern.Target == DB.FillPatternTarget.Drafting:
                                result.append(dict(id=id_value(element.Id), name=name_of(element),
                                                   solid=bool(pattern.IsSolidFill)))
                        finally:
                            pattern.Dispose()
                    _check_cancel(cancel)
                    if (index + 1) % 5 == 0:
                        _progress(progress, start, index + 1, total, 'resources-' + kind)
                _progress(progress, start, total, total, 'resources-' + kind)
            if kind != 'weight':
                result.sort(key=lambda item: (not item.get('solid', False), item['name'].lower(), item['id']))
            _check_cancel(cancel)
            self._resources[kind] = result
        total = len(self._resources[kind]) if inspected_total is None else inspected_total
        _progress(progress, start, total, total, 'resources-' + kind, complete=True,
                  resource_count=len(self._resources[kind]))
        _check_cancel(cancel)
        return _clone(self._resources[kind])

    def _resource_token(self, kind, numeric):
        if numeric == -1:
            return None
        if kind == 'line' and numeric == id_value(DB.LinePatternElement.GetSolidPatternId()):
            return ('solid-line', numeric)
        expected = DB.LinePatternElement if kind == 'line' else DB.FillPatternElement
        element = self._element(numeric, expected)
        if kind == 'fill':
            pattern = element.GetFillPattern()
            try:
                if pattern.Target != DB.FillPatternTarget.Drafting:
                    raise ValueError('Fill {} is a model pattern, not a drafting fill.'.format(numeric))
            finally:
                pattern.Dispose()
        return _identity(element)

    def _value(self, field, value):
        kind = field['kind']
        if kind == 'bool':
            if not isinstance(value, bool):
                raise ValueError('{} requires On/Off, not Clear.'.format(field['label']))
        elif kind == 'color':
            if value is not None:
                if not isinstance(value, (tuple, list)) or len(value) != 3:
                    raise ValueError('Colour must be an RGB tuple or None to clear.')
                if any(isinstance(v, bool) or not isinstance(v, _integers) or
                       v < 0 or v > 255 for v in value):
                    raise ValueError('RGB components must be integers 0..255.')
                value = tuple(int(v) for v in value)
        else:
            value = _number(value)
            if kind == 'resource':
                self._resource_token(field['resource_kind'], value)
            elif kind == 'weight':
                if value != -1 and not 1 <= value <= 16:
                    raise ValueError('Line weight must be 1..16 or -1 to clear.')
            elif field['bounds'] and not field['bounds'][0] <= value <= field['bounds'][1]:
                raise ValueError('{} must be {}..{}.'.format(
                    field['label'], field['bounds'][0], field['bounds'][1]))
        return value

    def validate_patch(self, patch):
        """Normalize {key:{op:'set',value:v}|{op:'clear'}|{op:'keep'}}.

        Raises ValueError for unknown/read-only fields or invalid operations.
        Keep entries are removed. clear => set(None) for colours, set(-1) for
        weights/resource ids. No Boolean/transparency clear. No WPF values.
        """
        if not isinstance(patch, dict) or not _plain(patch):
            raise ValueError('A graphics patch must contain only plain Python field/operation values, not UI objects.')
        result = {}
        for key, operation in patch.items():
            field = BY_KEY.get(key)
            if field is None or not field['editable']:
                raise ValueError('Unknown or read-only graphics field: {}'.format(key))
            if not isinstance(operation, dict) or operation.get('op') not in ('set', 'clear', 'keep'):
                raise ValueError('{} requires an explicit Keep/Set/Clear operation.'.format(key))
            op = operation['op']
            if op == 'keep':
                continue
            if op == 'clear':
                if not field['can_clear']:
                    raise ValueError('{} has no distinct native Clear representation.'.format(key))
                value = None if field['kind'] == 'color' else -1
            else:
                if 'value' not in operation:
                    raise ValueError('{} Set has no value.'.format(key))
                value = self._value(field, operation['value'])
            result[key] = dict(op='set', value=value)
        return result

    def patch_draft(self, existing, changes):
        """Return independent validated patch; Keep removes only custom entry.

        Apply this separately to each affected filter for Together. No earlier
        Together operation is replayed onto subsequently checked filters.
        """
        result = self.validate_patch(existing)
        normalized = self.validate_patch(changes)
        for key in changes:
            result.pop(key, None)
        result.update(normalized)
        return result

    def load_source_draft(self, filter_id, origin_ids, source_candidate_ids=None,
                          source_choice=None, include_graphics=True,
                          include_visibility=True, cancel=None, progress=None):
        """Explicitly load exact source values without requesting any writes.

        Return {token,values,source_id,origin_ids}. Use token and a subset of
        values' field keys in request.pair_sources. The immutable dependency
        snapshots stay service-owned, so editing/reverting a grid field cannot
        replace the source identity or evade fresh Apply checks.
        """
        if not isinstance(include_graphics, bool) or not isinstance(include_visibility, bool):
            raise ValueError('Source load channels require Boolean values.')
        if not include_graphics and not include_visibility:
            raise ValueError('Choose graphics or visibility to load.')
        fid = _number(filter_id)
        origins = _ordered(origin_ids)
        candidates = self._source_candidates(
            origins if source_candidate_ids is None else source_candidate_ids, cancel, progress)
        effective = self.effective_sources(origins, cancel, progress)
        if not effective or set(c['effective_id'] for c in candidates) != set(effective):
            raise ValueError('Selected source assignment changed or is unavailable; choose sources again.')
        request = self._request(dict(
            origin_ids=origins, include_graphics=include_graphics,
            include_visibility=include_visibility, source_choices=(
                {} if source_choice is None else {fid: source_choice})))
        source_map = self.source_filters(origins, cancel, progress)
        values, provenance, source_id, sources, _ = self._source_proposal(
            fid, request, effective, source_map, cancel, progress)
        _check_cancel(cancel)
        token = uuid.uuid4().hex
        self._source_loads[token] = dict(
            filter_id=fid, values=_clone(values), provenance=provenance,
            source_id=source_id, sources=_clone(sources),
            source_candidates=_clone(candidates), origin_ids=origins)
        return dict(token=token, values=_clone(values), source_id=source_id,
                    origin_ids=list(origins))

    def prune_source_drafts(self, active_tokens):
        """Release unreferenced loads, retaining inactive-pair/ReValue drafts."""
        active = set(active_tokens)
        for token in list(self._source_loads):
            if token not in active:
                del self._source_loads[token]

    def grid_values(self, snapshot):
        """Known original values for an attached pair, or native new defaults.

        Missing attachments remain labelled Not attached by the caller. These
        display values never turn into a write request until explicitly edited.
        """
        if snapshot['attached']:
            if not set(FULL).issubset(snapshot['coverage']):
                raise ValueError('Current target values are incomplete; reload this attachment.')
            return dict(snapshot['values'])
        defaults = DB.OverrideGraphicSettings()
        try:
            values = _flat(defaults, GRAPHICS + ('detail_level',))
        finally:
            defaults.Dispose()
        values.update(visibility=True, enabled=True)
        return values

    def _loaded_source(self, fid, entry):
        if not isinstance(entry, dict) or set(entry) != set(('token', 'fields')):
            raise ValueError('Loaded source requests require a token and explicit field subset.')
        if not isinstance(entry['token'], (str, type(u''))):
            raise ValueError('Loaded source token must be text.')
        loaded = self._source_loads.get(entry['token'])
        if loaded is None or loaded['filter_id'] != fid:
            raise ValueError('Loaded source draft belongs to another session/filter; load it again.')
        fields = entry['fields']
        if (not isinstance(fields, (list, tuple)) or
                not all(isinstance(key, (str, type(u''))) for key in fields) or
                not set(fields).issubset(loaded['values'])):
            raise ValueError('Loaded source fields must be a subset of the actual loaded values.')
        result = _clone(loaded)
        result['values'] = dict((key, loaded['values'][key]) for key in fields)
        return result

    def _loaded_sources(self, fid, entries):
        entries = entries if isinstance(entries, list) else [entries]
        result = dict(values={}, sources=[], source_candidates=[], origin_ids=[],
                      source_id=None)
        source_ids = set()
        for entry in entries:
            loaded = self._loaded_source(fid, entry)
            if not loaded['values']:
                continue
            if set(result['values']).intersection(loaded['values']):
                raise ValueError('Loaded source contributions overlap; reload the affected fields.')
            result['values'].update(loaded['values'])
            result['sources'].extend(loaded['sources'])
            result['source_candidates'].extend(loaded['source_candidates'])
            result['origin_ids'] = _ordered(result['origin_ids'] + loaded['origin_ids'])
            source_ids.add(loaded['source_id'])
        if len(source_ids) == 1:
            result['source_id'] = next(iter(source_ids))
        return result

    def _request(self, request):
        if not isinstance(request, dict) or not _plain(request):
            raise ValueError('A graphics request must contain only plain Python dictionaries/ids/values, not UI objects.')
        unknown = set(request) - set(('filter_ids', 'target_ids', 'origin_ids',
                                      'source_candidate_ids',
                                      'include_graphics', 'include_visibility',
                                      'source_choices', 'source_mode',
                                      'source_exempt_ids', 'patches', 'pair_patches',
                                      'pair_sources'))
        if unknown:
            raise ValueError('Unknown request options: {}'.format(sorted(unknown)))
        result = dict(filter_ids=_ordered(request.get('filter_ids', [])),
                      target_ids=_ordered(request.get('target_ids', [])),
                      origin_ids=_ordered(request.get('origin_ids', [])))
        result['source_candidate_ids'] = _ordered(request.get(
            'source_candidate_ids', result['origin_ids']))
        for channel in ('include_graphics', 'include_visibility'):
            value = request.get(channel, True)
            if not isinstance(value, bool):
                raise ValueError('{} requires a Boolean.'.format(channel))
            result[channel] = value
        result['source_choices'] = dict((_number(fid), _number(oid)) for fid, oid in
                                        request.get('source_choices', {}).items())
        result['source_mode'] = request.get('source_mode', 'exact')
        if result['source_mode'] not in ('exact', 'explicit'):
            raise ValueError('Source mode must be exact or explicit.')
        result['source_exempt_ids'] = _ordered(request.get('source_exempt_ids', []))
        # Validate per filter inside plan, so invalid selected rows stay visible.
        result['patches'] = _clone(request.get('patches', {}))
        for fid in result['patches']:
            _number(fid)
        result['pair_patches'] = {}
        for key, patch in request.get('pair_patches', {}).items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError('Pair patches require (target_id, filter_id) tuple keys.')
            result['pair_patches'][(_number(key[0]), _number(key[1]))] = _clone(patch)
        result['pair_sources'] = {}
        for key, source in request.get('pair_sources', {}).items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError('Loaded sources require (target_id, filter_id) tuple keys.')
            result['pair_sources'][(_number(key[0]), _number(key[1]))] = _clone(source)
        return result

    def _source_proposal(self, fid, request, effective, source_map, cancel, progress):
        values, provenance, source_id, snapshots = {}, {}, None, []
        active = (effective and fid not in request['source_exempt_ids'] and
                  (request['include_graphics'] or request['include_visibility']))
        if active:
            origins = source_map.get(fid, [])
            if not origins:
                raise ValueError('Filter is not attached to any selected source; choose another source.')
            variants = self.source_variants(fid, origins, request['include_graphics'],
                                             request['include_visibility'], cancel, progress,
                                             source_mode=request['source_mode'])
            if variants['cancelled']:
                raise GraphicsCancelled('Source load cancelled; no proposal created.')
            if not variants['complete']:
                raise ValueError('Source attachment data is missing/incomplete; reload it explicitly.')
            groups = variants['groups']
            choice = request['source_choices'].get(fid)
            if choice is not None:
                chosen = [g for g in groups if choice in g['origin_ids']]
                if not chosen:
                    raise ValueError('The selected source variant no longer contains this filter.')
                source_id, values = choice, dict(chosen[0]['values'])
            elif len(groups) == 1:
                # Only identical selected-channel values can resolve automatically.
                source_id, values = groups[0]['origin_ids'][0], dict(groups[0]['values'])
            else:
                raise ValueError('Different source variants: explicitly choose an origin for this filter.')
            provenance.update((key, 'source') for key in values)
            snapshots = [variants['snapshots'][(oid, fid)] for oid in origins]
        patch = self.validate_patch(request['patches'].get(fid, {}))
        for key, operation in patch.items():
            values[key] = operation['value']
            provenance[key] = 'custom'
        return values, provenance, source_id, snapshots, patch

    def plan(self, request, completed=(), cancel=None, progress=None):
        """Build a reviewable proposal, never write.

        request = {filter_ids:[fid], target_ids:[tid], origin_ids:[oid],
          include_graphics:True, include_visibility:True,
          source_choices:{fid:effective_oid}, patches:{fid:{key:operation}},
          source_mode:'exact'}. Optional 'explicit' mode copies only reliably
        detectable non-unset graphics; no boolean/transparency unset guessing.
          source_candidate_ids:[original_selected_view_or_template_id] preserves
          original selection provenance when the UI supplies effective template
          ids in origin_ids. Defaults to origin_ids for direct callers. A fresh
          candidate identity/assignment/control/effective-origin snapshot must
          agree with the requested effective source set at plan time and remain
          exact at Apply, BEFORE opening a transaction. Replacing selected view's
          controlling template is stale even if old template graphics did not
          change. Original candidates never become implicit destination writes.
        Optional source_exempt_ids:[fid] explicitly declares newly created,
        unattached definitions as filters-only/custom while keeping other
        filters' source requests. UI MUST label that exception; ordinary missing
        source attachments are NEVER exempted implicitly. Rows expose
        source_exempt=True for this deliberately requested native-default case.
        During a mixed Copy batch all source views remain read-only, including
        exempt rows targeting those views. An exempt-only filters-only scope
        has no active source request and can add to an explicit source target.
        Optional pair_patches:{(tid,fid):patch} overlays the per-filter patch and
        source for that pair only. Keep removes that pair's custom contribution,
        exposing any per-filter/source value underneath. The caller records
        current checked pairs at edit time to preserve target-specific history;
        this service never replays pair patches onto newly selected targets.
        Inactive per-filter and per-pair drafts may remain in request.
        Optional pair_sources:{(tid,fid):[{token,fields:[key]},...]} requests only
        explicitly loaded source fields for that pair. Tokens come from
        load_source_draft; original source values/identities remain immutable.
        Reverting a loaded field removes it from fields, preserving that target's
        before value. New checked pairs receive no old source requests.
        List order is explicit append order; mappings/sets sort numerically.
        A single effective source uses its attachment order; multiple origins
        use filter_ids order. Empty origins means All Project: both source
        channels inactive regardless of checked defaults. Custom patches overlay
        source values independently. Neither source mode copies enabled.

        Result {rows,counts,request,document,epoch,proposal_token}; the latter is
        an opaque selection/order integrity token. Row keys include key=(tid,fid),
        action=Add/Update/Unchanged/Blocked/Invalid/Completed, reason, before
        snapshot, after flat values, requested, delta={key:{before,after}},
        source_id, sources, provenance, impact=[all inherited consumers],
        approval_token, approved=False, excluded=False, meaning_token.
        Missing/incomplete/conflicting sources produce explicit Invalid rows.
        Controlled views and source-as-target produce explicit Blocked rows.
        Pass accumulated apply receipts in completed to avoid immediate requeue.
        Cancellation raises GraphicsCancelled, preserving the caller's old plan.
        """
        progress = _operation_progress(progress)
        request = self._request(request)
        _check_cancel(cancel)
        effective = self.effective_sources(request['origin_ids'], cancel, progress)
        copying = bool(effective and
                       any(fid not in request['source_exempt_ids'] for fid in request['filter_ids']) and
                       (request['include_graphics'] or request['include_visibility']))
        candidates, candidate_error = [], None
        if copying:
            try:
                candidates = self._source_candidates(request['source_candidate_ids'], cancel, progress)
                if set(candidate['effective_id'] for candidate in candidates) != set(effective):
                    raise ValueError('Selected source assignment no longer matches requested origins; reload and review.')
            except ValueError as error:
                candidate_error = str(error)
        source_map = (self.source_filters(request['origin_ids'], cancel, progress)
                      if copying and not candidate_error else {})
        filter_ids = list(request['filter_ids'])
        if copying and len(effective) == 1:
            native_order = self.membership(effective[0])
            filter_ids = [fid for fid in native_order if fid in filter_ids] + [
                fid for fid in filter_ids if fid not in native_order]
        loaded_readonly_ids = set()
        if request['pair_sources']:
            loaded_origins, loaded_orders = set(), {}
            for (tid, fid), entry in request['pair_sources'].items():
                if tid not in request['target_ids'] or fid not in filter_ids:
                    continue
                try:
                    loaded = self._loaded_sources(fid, entry)
                    if loaded['values']:
                        loaded_origins.update(c['effective_id'] for c in loaded['source_candidates'])
                        loaded_orders.update((s['target_id'], s['order']) for s in loaded['sources'])
                        loaded_readonly_ids.update(loaded['origin_ids'])
                        loaded_readonly_ids.update(c['candidate_id'] for c in loaded['source_candidates'])
                        loaded_readonly_ids.update(c['effective_id'] for c in loaded['source_candidates'])
                except ValueError:
                    # Keep invalid source entries visible as their own rows.
                    continue
            if not copying and len(loaded_origins) == 1:
                native_order = loaded_orders[next(iter(loaded_origins))]
                filter_ids = [fid for fid in native_order if fid in filter_ids] + [
                    fid for fid in filter_ids if fid not in native_order]
        proposals, errors, rows, start = {}, {}, [], time.time()
        for fid in filter_ids:
            _check_cancel(cancel)
            try:
                if candidate_error and fid not in request['source_exempt_ids']:
                    raise ValueError(candidate_error)
                proposals[fid] = self._source_proposal(
                    fid, request, effective, source_map, cancel, progress)
            except ValueError as error:
                errors[fid] = str(error)
        total = len(filter_ids) * len(request['target_ids'])
        for tid in request['target_ids']:
            for fid in filter_ids:
                _check_cancel(cancel)
                row = dict(key=(tid, fid), action='Invalid', reason='', before=None,
                           after={}, requested={}, delta={}, source_id=None, sources=[],
                           provenance={}, impact=[], approved=False, excluded=False,
                           meaning_token=None, origin_ids=request['origin_ids'])
                row['source_exempt'] = fid in request['source_exempt_ids']
                row_copying = copying and not row['source_exempt']
                row['source_candidates'] = _clone(candidates) if row_copying else []
                if not row_copying:
                    row['origin_ids'] = []
                try:
                    info = self.target_info(tid)
                    if not info['supported']:
                        row.update(action='Blocked', reason='Target does not support view filters.')
                    elif info['controlled']:
                        row.update(action='Blocked', reason=(
                            'Filters are template-controlled. Select template {} explicitly.'.format(
                                info['controlling_template_id'])))
                    elif (tid in loaded_readonly_ids or (copying and tid in set(
                            effective + request['origin_ids'] + request['source_candidate_ids']))):
                        row.update(action='Blocked', reason=(
                            'Source-as-target excluded: source views stay read-only during a Copy batch. '
                            'Explicitly exclude this row or use a filters-only scope.'))
                    elif fid in errors:
                        row['reason'] = errors[fid]
                    else:
                        requested, provenance, source_id, sources, patch = proposals[fid]
                        requested, provenance = dict(requested), dict(provenance)
                        pair_source = request['pair_sources'].get((tid, fid))
                        if pair_source is not None:
                            loaded = self._loaded_sources(fid, pair_source)
                            if loaded['values']:
                                candidates_for_pair = loaded['source_candidates']
                                source_ids = loaded['origin_ids'] + [
                                    c['candidate_id'] for c in candidates_for_pair] + [
                                    c['effective_id'] for c in candidates_for_pair]
                                if tid in source_ids:
                                    row.update(action='Blocked', reason=(
                                        'Loaded source is also a destination; sources stay read-only. '
                                        'Revert its copied fields or exclude this pair.'))
                                    row['approval_token'] = _row_token(row)
                                    rows.append(row)
                                    continue
                                self._check_source_candidates(candidates_for_pair, {})
                                requested.update(loaded['values'])
                                provenance.update((key, 'source') for key in loaded['values'])
                                for key, operation in patch.items():
                                    requested[key] = operation['value']
                                    provenance[key] = 'custom'
                                source_id = loaded['source_id']
                                sources = list(sources) + loaded['sources']
                                row_copying = True
                                row['source_candidates'].extend(candidates_for_pair)
                                row['origin_ids'] = _ordered(row['origin_ids'] + loaded['origin_ids'])
                        pair_patch = self.validate_patch(request['pair_patches'].get((tid, fid), {}))
                        for key, operation in pair_patch.items():
                            requested[key] = operation['value']
                            provenance[key] = 'custom'
                        before = self.snapshot(tid, fid)
                        impact = self._impact(tid, cancel=cancel, progress=progress) if info['is_template'] else []
                        after = self.grid_values(before)
                        after.update(requested)
                        # Enabled is neither editable nor copied, ever.
                        after['enabled'] = before['values']['enabled'] if before['attached'] else True
                        delta = dict((key, dict(before=before['values'].get(key), after=value))
                                     for key, value in requested.items()
                                     if not before['attached'] or before['values'][key] != value)
                        resources = dict((key, self._resource_token(BY_KEY[key]['resource_kind'], value))
                                         for key, value in requested.items()
                                         if BY_KEY[key]['kind'] == 'resource')
                        meaning = _digest(dict(
                            document=self.document_token, pair=(tid, fid),
                            origins=row['origin_ids'] if row_copying else [],
                            source_exempt=row['source_exempt'],
                            channels=(bool(row_copying and request['include_graphics']),
                                      bool(row_copying and request['include_visibility'])),
                            source_id=source_id, requested=requested, patch=patch,
                            pair_patch=pair_patch,
                            source_mode=request['source_mode'] if row_copying else None,
                            source_candidates=[dict(
                                candidate_id=c['candidate_id'],
                                unique_id=c['identity'][0],
                                template_id=c['template']['template_id'],
                                controls=c['template']['controls'],
                                template_unique_id=(c['template']['identity'][0]
                                                    if c['template']['identity'] else None),
                                effective_id=c['effective_id'])
                                for c in row['source_candidates']],
                            source_values=[(s['target_id'], s['target_identity'][0], s['filter_identity'],
                                            s['values']) for s in sources]))
                        row.update(action=('Add' if not before['attached'] else
                                           'Update' if delta else 'Unchanged'),
                                   before=before, after=after, requested=dict(requested),
                                   delta=delta, source_id=source_id, sources=sources,
                                   provenance=dict(provenance), impact=impact,
                                   resources=resources, meaning_token=meaning)
                        row['pair_patch'] = pair_patch
                        for receipt in completed:
                            if (receipt.get('document') == self.document_token and
                                    tuple(receipt.get('key', ())) == (tid, fid) and
                                    receipt.get('meaning_token') == meaning and
                                    receipt.get('post_token') == self._completion_token(before)):
                                row.update(action='Completed', reason='Already completed for this request.')
                                break
                except ValueError as error:
                    row.update(action='Invalid', reason=str(error))
                row['approval_token'] = _row_token(row)
                rows.append(row)
                if len(rows) % 5 == 0:
                    _progress(progress, start, len(rows), total, 'plan')
        _check_cancel(cancel)
        _progress(progress, start, len(rows), total, 'plan', complete=True)
        result = dict(rows=rows, counts=_counts(rows), request=request,
                      document=self.document_token, epoch=self._epoch)
        result['proposal_token'] = _plan_token(result)
        return result

    def _validate_plan(self, plan):
        if plan['document'] != self.document_token or plan['epoch'] != self._epoch:
            raise ValueError('Proposal invalidated. Reload and review before applying.')
        if plan.get('proposal_token') != _plan_token(plan):
            raise ValueError('Proposal selection/order changed; build a new plan.')
        for row in plan['rows']:
            if row['approval_token'] != _row_token(row):
                raise ValueError('Proposal contents changed; build a new plan before approval/apply.')

    def approve_updates(self, plan, row_keys=None):
        """Return copied plan with exact-token Update approvals; None means all.

        Add/Unchanged/Blocked/Invalid never receive approval. Hidden Update rows
        are included by None. Inspecting/changing tabs does not change tokens.
        """
        self._validate_plan(plan)
        result = _clone(plan)
        selected = None if row_keys is None else set(tuple(k) for k in row_keys)
        for row in result['rows']:
            if row['action'] == 'Update' and not row['excluded'] and (
                    selected is None or row['key'] in selected):
                row['approved'] = row['approval_token']
        return result

    def clear_approvals(self, plan):
        """Return copied plan with all Update approvals cleared."""
        self._validate_plan(plan)
        result = _clone(plan)
        for row in result['rows']:
            row['approved'] = False
        return result

    def exclude_rows(self, plan, row_keys):
        """Explicit counted exclusion; use to resolve selected Blocked/Invalid rows.

        Return copied plan. Excluded rows never write and are reported, not
        silently skipped. Rebuild the plan to include them again.
        """
        self._validate_plan(plan)
        result, selected = _clone(plan), set(tuple(k) for k in row_keys)
        available = set(row['key'] for row in result['rows'])
        if selected - available:
            raise ValueError('Cannot exclude a row outside this proposal.')
        for row in result['rows']:
            if row['key'] in selected:
                row['excluded'] = True
                row['approved'] = False
        return result

    def _completion_token(self, snapshot):
        # Other attachments/order may change while this completed pair stays done.
        return _digest((snapshot['attached'], snapshot['target_identity'][0],
                        snapshot['filter_identity'], snapshot['values']))

    def _fresh_snapshot(self, snapshot, cache):
        key = (snapshot['target_id'], snapshot['filter_id'], tuple(snapshot['coverage']))
        if key not in cache:
            cache[key] = self._read(key[0], key[1], set(key[2]), refresh=True)
        return cache[key]

    def _preflight(self, rows):
        cache, impacts, candidates = {}, {}, {}
        for row in rows:
            if row['sources']:
                if not row.get('source_candidates'):
                    raise ValueError('Source selection provenance is missing; rebuild and review the proposal.')
                self._check_source_candidates(row['source_candidates'], candidates)
            before = row['before']
            fresh = self._fresh_snapshot(before, cache)
            if _freeze(fresh) != _freeze(before):
                raise ValueError('Target {} / filter {} changed; reload and review.'.format(*row['key']))
            if before['is_template']:
                tid = row['key'][0]
                if tid not in impacts:
                    impacts[tid] = self._impact(tid, refresh=True)
                if _freeze(impacts[tid]) != _freeze(row['impact']):
                    raise ValueError('Template consumer impact changed; reload and review.')
            # Re-resolve original source assignments too, not just effective ids.
            effective = self.effective_sources(row['origin_ids']) if row['sources'] else []
            for source in row['sources']:
                if source['target_id'] not in effective:
                    raise ValueError('Source template assignment changed; reload and review.')
                if _freeze(self._fresh_snapshot(source, cache)) != _freeze(source):
                    raise ValueError('Source attachment changed; reload and review.')
            for key, token in row.get('resources', {}).items():
                if self._resource_token(BY_KEY[key]['resource_kind'], row['requested'][key]) != token:
                    raise ValueError('Requested graphics resource changed; reload and review.')

    def _write(self, rows):
        for row in rows:
            tid, fid = row['key']
            view = self._element(tid, DB.View)
            native_id = element_id(fid)
            if row['action'] == 'Add':
                view.AddFilter(native_id)
                # Explicit for new attachments only, never touch existing enabled.
                view.SetIsFilterEnabled(native_id, True)
            graphics = dict((k, v) for k, v in row['requested'].items()
                            if BY_KEY[k]['setter'])
            if graphics:
                original = view.GetFilterOverrides(native_id)
                clone = None
                try:
                    clone = _patch_ogs(original, graphics)
                    view.SetFilterOverrides(native_id, clone)
                finally:
                    if clone is not None:
                        clone.Dispose()
                    original.Dispose()
            if 'visibility' in row['requested']:
                view.SetFilterVisibility(native_id, row['requested']['visibility'])
        return rows

    def _verify(self, rows):
        snapshots, expected_orders, sources, candidates = {}, {}, {}, {}
        written_views = set(row['key'][0] for row in rows if row.get(
            '_will_write', row['action'] in ('Add', 'Update')))
        for row in rows:
            tid, fid = row['key']
            if tid not in expected_orders:
                expected_orders[tid] = list(row['before']['order'])
            if row['action'] == 'Add':
                expected_orders[tid].append(fid)
        for row in rows:
            tid, fid = row['key']
            self._check_source_candidates(row.get('source_candidates', []),
                                          candidates, written_views)
            actual = self._read(tid, fid, set(FULL), refresh=True)
            if (not actual['attached'] or actual['values'] != row['after'] or
                    actual['order'] != tuple(expected_orders[tid]) or
                    actual['filter_identity'] != row['before']['filter_identity'] or
                    actual['target_identity'][0] != row['before']['target_identity'][0] or
                    not _template_after(row['before']['template'], actual['template'], written_views)):
                raise ValueError('Post-commit graphics/identity/order/template verification failed for {}.'.format(row['key']))
            if actual['is_template'] and self._impact(tid, refresh=True) != row['impact']:
                raise ValueError('Post-commit template consumer impact changed.')
            for source in row['sources']:
                fresh = self._fresh_snapshot(source, sources)
                expected = dict(source)
                # Assigned-but-noncontrolling templates can be independent
                # explicit destinations in this same batch. Their identity and
                # control state must survive; their planned version bump must
                # not masquerade as an external source change.
                if not _template_after(source['template'], fresh['template'], written_views):
                    raise ValueError('Source template context changed during Apply; rolling back.')
                expected['template'] = fresh['template']
                if _freeze(fresh) != _freeze(expected):
                    raise ValueError('Source changed during Apply; rolling back.')
            snapshots[row['key']] = actual
        return snapshots

    def apply(self, plan):
        """Apply ready Adds + exact-approved Updates in one atomic Undo group.

        Unapproved Updates remain counted/pending. Any selected Blocked/Invalid
        row aborts until explicitly excluded. Fresh preflight checks identities,
        all before/source values, order, template controls/impact and resources.
        Verify full postconditions AFTER transaction commit BEFORE assimilation.
        Native failures/verification exceptions are logged, rolled back and
        raised, NEVER success receipts. No cancellation/UI pumping while writing.

        Return {counts:{added,updated,unchanged,unapproved,excluded,completed},
          receipts:[{document,key,meaning_token,post_token}], retained:[Update],
          snapshots:{(tid,fid):confirmed_snapshot}}.
        Receipts are per pair/request meaning; pass them to subsequent plan().
        Calling apply on pending-only/empty plans opens no transaction.
        """
        self._validate_plan(plan)
        unresolved = [r for r in plan['rows'] if not r['excluded'] and
                      r['action'] in ('Blocked', 'Invalid')]
        if unresolved:
            raise ValueError('{} blocked/invalid selected rows require resolution or explicit exclusion.'.format(len(unresolved)))
        active = [r for r in plan['rows'] if not r['excluded'] and
                  r['action'] not in ('Blocked', 'Invalid', 'Completed')]
        eligible = [r for r in active if r['action'] == 'Add' or (
            r['action'] == 'Update' and r['approved'] == r['approval_token'])]
        retained = [r for r in active if r['action'] == 'Update' and
                    r['approved'] != r['approval_token']]
        counts = dict(added=sum(r['action'] == 'Add' for r in eligible),
                      updated=sum(r['action'] == 'Update' for r in eligible),
                      unchanged=sum(r['action'] == 'Unchanged' for r in active),
                      unapproved=len(retained),
                      excluded=sum(bool(r['excluded']) for r in plan['rows']),
                      completed=sum(r['action'] == 'Completed' and not r['excluded']
                                    for r in plan['rows']))
        confirmed = {}
        try:
            # Do not let metadata caches mask template reassignment/catalogue edits.
            self._info.clear()
            self._impact_cache.clear()
            self._preflight(active)
            if eligible:
                if self.doc.IsReadOnly or self.doc.IsModifiable:
                    raise ValueError('Document is read-only or another transaction is open.')

                def verify(_unused):
                    verification = _clone(active)
                    eligible_keys = set(row['key'] for row in eligible)
                    for row in verification:
                        row['_will_write'] = row['key'] in eligible_keys
                        if row['key'] not in eligible_keys:
                            row['after'] = dict(row['before']['values'])
                    # Verify retained/unchanged pairs also stayed untouched, and
                    # refresh their view version after additions to that view.
                    confirmed.update(self._verify(verification))
                self.filter_service.atomic('Apply filter graphics',
                                           lambda: self._write(eligible), verify=verify)
            for row in active:
                if row['action'] == 'Unchanged' and row['key'] not in confirmed:
                    confirmed[row['key']] = row['before']
            finished_keys = set(row['key'] for row in eligible)
            finished_keys.update(row['key'] for row in active if row['action'] == 'Unchanged')
            receipts = [
                dict(document=self.document_token, key=row['key'],
                     meaning_token=row['meaning_token'],
                     post_token=self._completion_token(confirmed[row['key']]))
                for row in active if row['key'] in finished_keys]
        except Exception:
            self.invalidate()
            _log.exception('Filter Manager graphics Apply failed; no batch changes were accepted.')
            raise
        if eligible:
            self.invalidate()
            for key, snapshot in confirmed.items():
                self._store(key, snapshot)
        return dict(counts=counts, receipts=receipts,
                    retained=_clone(retained), snapshots=_clone(confirmed))
