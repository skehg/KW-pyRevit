# -*- coding: utf-8 -*-
"""Native view-filter definitions, identities and atomic operations."""
import io
import json
import math
import os
import re
import uuid

import clr
from System import Enum, Int32, Int64, Double, String
from System.Collections.Generic import List, HashSet
from pyrevit import DB


COMPARISONS = [
    ('Equals', 'equals'), ('NotEquals', 'does not equal'),
    ('Greater', 'is greater than'), ('GreaterOrEqual', 'is greater than or equal to'),
    ('Less', 'is less than'), ('LessOrEqual', 'is less than or equal to')]
TEXT_OPERATORS = COMPARISONS + [
    ('Contains', 'contains'), ('NotContains', 'does not contain'),
    ('BeginsWith', 'begins with'), ('NotBeginsWith', 'does not begin with'),
    ('EndsWith', 'ends with'), ('NotEndsWith', 'does not end with')]
PRESENCE = [('HasValue', 'has a value'), ('HasNoValue', 'has no value')]
LEVEL_OPERATORS = COMPARISONS[:2] + [
    ('Greater', 'is above'), ('GreaterOrEqual', 'is at or above'),
    ('Less', 'is below'), ('LessOrEqual', 'is at or below')]
EVALUATORS = {
    'FilterStringEquals': 'Equals', 'FilterStringGreater': 'Greater',
    'FilterStringGreaterOrEqual': 'GreaterOrEqual', 'FilterStringLess': 'Less',
    'FilterStringLessOrEqual': 'LessOrEqual', 'FilterStringContains': 'Contains',
    'FilterStringBeginsWith': 'BeginsWith', 'FilterStringEndsWith': 'EndsWith',
    'FilterNumericEquals': 'Equals', 'FilterNumericGreater': 'Greater',
    'FilterNumericGreaterOrEqual': 'GreaterOrEqual', 'FilterNumericLess': 'Less',
    'FilterNumericLessOrEqual': 'LessOrEqual'}
INVERSES = {
    'Equals': 'NotEquals', 'Contains': 'NotContains',
    'BeginsWith': 'NotBeginsWith', 'EndsWith': 'NotEndsWith',
    'HasValue': 'HasNoValue', 'HasNoValue': 'HasValue'}
NAMING_SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'naming_settings.json')
NAMING_OPERATOR_KEYS = [key for key, label in TEXT_OPERATORS + PRESENCE]


def load_naming_symbols(path=None):
    """Read optional operator labels used only by the {rules} naming token.

    A missing file means the readable summary wording is used. A present file must be
    fully valid; nothing is skipped or guessed.
    """
    path = path or NAMING_SETTINGS
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, 'r', encoding='utf-8-sig') as stream:
            data = json.load(stream)
    except ValueError as error:
        raise ValueError(u'Naming settings file is not valid JSON: {}\n{}'.format(path, error))
    if not isinstance(data, dict):
        raise ValueError(u'Naming settings file must contain a JSON object: {}'.format(path))
    problems = [u'Unknown setting "{}".'.format(key) for key in sorted(data)
                if key != 'operator_symbols' and not key.startswith('_')]
    symbols = data.get('operator_symbols', {})
    if not isinstance(symbols, dict):
        problems.append(u'"operator_symbols" must be an object of operator key to name text.')
        symbols = {}
    for key in sorted(symbols):
        value = symbols[key]
        if key not in NAMING_OPERATOR_KEYS:
            problems.append(u'Unknown operator key "{}". Valid keys: {}.'.format(
                key, ', '.join(NAMING_OPERATOR_KEYS)))
        elif not isinstance(value, basestring) or not value.strip():
            problems.append(u'"{}" must be nonempty text.'.format(key))
        elif value != value.strip():
            problems.append(u'"{}" has leading/trailing spaces.'.format(key))
        elif not DB.NamingUtils.IsValidName(value):
            invalid = sorted(c for c in set(value) if not DB.NamingUtils.IsValidName(c))
            problems.append(u'"{}" value "{}" contains characters Revit rejects in names: {}.'.format(
                key, value, ', '.join(repr(c) for c in invalid) or 'unknown'))
    if problems:
        raise ValueError(u'Naming settings file is invalid: {}\n- {}'.format(path, u'\n- '.join(problems)))
    return dict(symbols)


def id_value(value):
    return int(value.Value if hasattr(value, 'Value') else value.IntegerValue)


def element_id(value):
    if not hasattr(DB.ElementId.InvalidElementId, 'Value'):
        return DB.ElementId(Int32(value))
    return DB.ElementId(Int64(value))


def ids(values):
    return List[DB.ElementId]([v if isinstance(v, DB.ElementId) else element_id(v)
                              for v in values])


def name_of(element):
    return DB.Element.Name.GetValue(element)


def group(children=None, op='AND'):
    return {'kind': 'group', 'op': op, 'children': children or []}


def clone_tree(node):
    # Native rules are immutable operands here; deepcopy tries CLR constructors.
    result = dict(node)
    if node['kind'] == 'group':
        result['children'] = [clone_tree(c) for c in node['children']]
    return result


def supports_filters(view):
    return view is not None and view.IsValidObject and view.AreGraphicsOverridesAllowed() and view.ViewType in (
        DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan, DB.ViewType.EngineeringPlan,
        DB.ViewType.AreaPlan, DB.ViewType.Section, DB.ViewType.Elevation,
        DB.ViewType.ThreeD, DB.ViewType.Detail)


def signature(node):
    """Compare full typed definitions, never descriptions or current matches."""
    if node['kind'] == 'unsupported':
        raise ValueError(node['reason'])
    if node['kind'] == 'group':
        children = []
        for child in node['children']:
            key = signature(child)
            if len(key) == 2 and key[0] == node['op']:
                children.extend(key[1])
            else:
                children.append(key)
        if not children:
            return ('AND', ())
        if len(children) == 1:
            return children[0]
        return (node['op'], tuple(sorted(children, key=repr)))
    return ('rule', node['pid'], node['family'], node['op'],
            node.get('value'), node.get('epsilon'))


def definition_signature(categories, node):
    return (tuple(sorted(categories)), signature(node))


def read_rule(rule):
    inverse = isinstance(rule, DB.FilterInverseRule)
    inner = rule.GetInnerRule() if inverse else rule
    family, value, epsilon = None, None, None
    if isinstance(inner, DB.HasValueFilterRule):
        op, family = 'HasValue', 'presence'
    elif isinstance(inner, DB.HasNoValueFilterRule):
        op, family = 'HasNoValue', 'presence'
    elif isinstance(inner, (DB.FilterStringRule, DB.FilterIntegerRule,
                            DB.FilterDoubleRule, DB.FilterElementIdRule)):
        op = EVALUATORS.get(inner.GetEvaluator().GetType().Name)
        if isinstance(inner, DB.FilterStringRule):
            family, value = 'string', unicode(inner.RuleString)
        elif isinstance(inner, DB.FilterDoubleRule):
            family, value, epsilon = 'double', float(inner.RuleValue), float(inner.Epsilon)
        elif isinstance(inner, DB.FilterIntegerRule):
            family, value = 'integer', int(inner.RuleValue)
        else:
            family, value = 'reference', id_value(inner.RuleValue)
    else:
        op = None
    if op is None:
        return {'kind': 'unsupported', 'reason': 'Unsupported native rule: {}'.format(
            inner.GetType().Name)}
    if inverse:
        op = INVERSES.get(op, 'NOT:' + op)
    return {'kind': 'rule', 'pid': id_value(inner.GetRuleParameter()), 'family': family,
            'op': op, 'value': value, 'epsilon': epsilon, 'native': rule}


def read_tree(native):
    if native is None:
        return group()
    if isinstance(native, (DB.LogicalAndFilter, DB.LogicalOrFilter)):
        if native.Inverted:
            return {'kind': 'unsupported', 'reason': 'Inverted logical group is inspection-only.'}
        return group([read_tree(c) for c in native.GetFilters()],
                     'AND' if isinstance(native, DB.LogicalAndFilter) else 'OR')
    if isinstance(native, DB.ElementParameterFilter):
        if native.Inverted:
            return {'kind': 'unsupported', 'reason': 'Inverted parameter-filter group is inspection-only.'}
        return group([read_rule(r) for r in native.GetRules()])
    return {'kind': 'unsupported', 'reason': 'Category-specific or unsupported filter: {}'.format(
        native.GetType().Name)}


def build_tree(node):
    if node['kind'] == 'unsupported':
        raise ValueError(node['reason'])
    if node['kind'] == 'group':
        if not node['children']:
            return None
        children = [build_tree(c) for c in node['children']]
        if any(c is None for c in children):
            raise ValueError('An empty nested group cannot be saved.')
        if len(children) == 1:
            return children[0]
        constructor = DB.LogicalAndFilter if node['op'] == 'AND' else DB.LogicalOrFilter
        return constructor(List[DB.ElementFilter](children))
    if node.get('native') is not None:
        return DB.ElementParameterFilter(node['native'])
    op, family = node['op'], node['family']
    pid = element_id(node['pid'])
    factory = DB.ParameterFilterRuleFactory
    if op in ('HasValue', 'HasNoValue'):
        method = factory.CreateHasValueParameterRule if op == 'HasValue' else factory.CreateHasNoValueParameterRule
        rule = method(pid)
    else:
        method = getattr(factory, 'Create' + op + 'Rule')
        value = node['value']
        if family == 'string':
            rule = method(pid, String(value))
        elif family == 'integer':
            rule = method(pid, Int32(value))
        elif family == 'double':
            rule = method(pid, Double(value), Double(node['epsilon']))
        elif family == 'reference':
            rule = method(pid, element_id(value))
        else:
            raise ValueError('Unknown operand type: ' + family)
    return DB.ElementParameterFilter(rule)


class ParameterInfo(object):
    def __init__(self, pid, name, storage, spec=None):
        self.id = pid
        self.name = name
        self.storage = storage
        self.spec = spec
        self.profile = None
        self.problem = ''

    def __str__(self):
        return self.name


class RollbackFailures(DB.IFailuresPreprocessor):
    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        failures = accessor.GetFailureMessages()
        self.messages = [f.GetDescriptionText() for f in failures]
        if self.messages:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


class FilterRecord(object):
    def __init__(self, service, element):
        self.id = id_value(element.Id)
        self.name = name_of(element)
        self.unique_id = element.UniqueId
        self.version = str(element.VersionGuid)
        self.categories = sorted(id_value(c) for c in element.GetCategories())
        self.tree = read_tree(element.GetElementFilter())
        self.category_names = [service.category_name(c) for c in self.categories]
        self.rules = service.describe(self.tree)
        self.usage = []
        self.inherited = []
        self.problem = ''
        try:
            self.signature = definition_signature(self.categories, self.tree)
        except ValueError as error:
            self.signature = None
            self.problem = unicode(error)

    @property
    def token(self):
        return (self.unique_id, self.version, self.name, tuple(self.categories))

    @property
    def usage_text(self):
        views = sum(1 for v in self.usage if not v.IsTemplate)
        templates = len(self.usage) - views
        return '{} views / {} templates / {} inherited views'.format(
            views, templates, len(self.inherited))


class FilterService(object):
    def __init__(self, doc):
        self.doc = doc
        self.records = []
        self.views = []
        self.parameters = {}
        self.category_names = {}
        self.refresh()

    def category_name(self, value):
        if value not in self.category_names:
            cat = DB.Category.GetCategory(self.doc, element_id(value))
            self.category_names[value] = cat.Name if cat else unicode(
                Enum.ToObject(DB.BuiltInCategory, Int32(value)))
        return self.category_names[value]

    def all_categories(self):
        return sorted([(id_value(c), self.category_name(id_value(c)))
                       for c in DB.ParameterFilterUtilities.GetAllFilterableCategories()],
                      key=lambda p: p[1].lower())

    def parameter_name(self, pid):
        if pid < 0:
            return DB.LabelUtils.GetLabelFor(Enum.ToObject(DB.BuiltInParameter, Int32(pid)))
        element = self.doc.GetElement(element_id(pid))
        if not isinstance(element, DB.ParameterElement):
            raise ValueError('Parameter {} no longer exists.'.format(pid))
        return element.GetDefinition().Name

    def eligible_parameters(self, categories):
        if not categories:
            return []
        eligible = DB.ParameterFilterUtilities.GetFilterableParametersInCommon(
            self.doc, ids(categories))
        specimens = []
        for cat in categories:
            first = DB.FilteredElementCollector(self.doc).OfCategoryId(
                element_id(cat)).WhereElementIsNotElementType().FirstElement()
            if first is not None:
                specimens.append(first)
                type_element = self.doc.GetElement(first.GetTypeId())
                if type_element is not None:
                    specimens.append(type_element)
            type_element = DB.FilteredElementCollector(self.doc).OfCategoryId(
                element_id(cat)).WhereElementIsElementType().FirstElement()
            if type_element is not None:
                specimens.append(type_element)
        sampled = {}
        for specimen in specimens:
            for param in specimen.Parameters:
                sampled[id_value(param.Id)] = param
        result = []
        for native_id in eligible:
            pid = id_value(native_id)
            spec = None
            if pid < 0:
                bip = Enum.ToObject(DB.BuiltInParameter, Int32(pid))
                storage = str(self.doc.GetTypeOfStorage(DB.ParameterUtils.GetParameterTypeId(bip)))
            else:
                definition = self.doc.GetElement(native_id).GetDefinition()
                spec = definition.GetDataType()
                storage = self.storage_from_spec(spec)
            if pid in sampled:
                param = sampled[pid]
                spec = param.Definition.GetDataType()
                storage = str(param.StorageType)
            info = ParameterInfo(pid, self.parameter_name(pid), storage, spec)
            if storage == 'String':
                info.profile = 'text'
            elif storage == 'Double' and spec is not None:
                info.profile = 'number'
            elif storage == 'Integer' and spec is not None:
                info.profile = 'yesno' if spec == DB.SpecTypeId.Boolean.YesNo else (
                    'integer' if spec == DB.SpecTypeId.Int.Integer else 'enum')
            elif storage == 'ElementId':
                if DB.FilterElementIdRule.UsesLevelFiltering(self.doc, native_id):
                    info.profile = 'level'
                elif pid in [id_value(DB.ElementId(DB.BuiltInParameter.PHASE_CREATED)),
                             id_value(DB.ElementId(DB.BuiltInParameter.PHASE_DEMOLISHED))]:
                    info.profile = 'phase'
                elif spec == DB.SpecTypeId.Reference.Material:
                    info.profile = 'material'
            if info.profile is None:
                info.problem = 'No verified authoring metadata for this parameter. Existing rules are preserved; new operands cannot be guessed.'
            if info.profile == 'enum':
                info.problem = 'Enumeration value mapping is not exposed by Revit. Use an existing rule or choose another parameter.'
            self.parameters[pid] = info
            result.append(info)
        return sorted(result, key=lambda p: (p.name.lower(), p.id))

    @staticmethod
    def storage_from_spec(spec):
        if spec == DB.SpecTypeId.String.Text or spec == DB.SpecTypeId.String.MultilineText:
            return 'String'
        if spec == DB.SpecTypeId.Boolean.YesNo or spec == DB.SpecTypeId.Int.Integer:
            return 'Integer'
        if DB.UnitUtils.IsMeasurableSpec(spec):
            return 'Double'
        if spec == DB.SpecTypeId.Reference.Material:
            return 'ElementId'
        return 'None'

    def operators(self, info):
        if info.profile == 'text':
            return TEXT_OPERATORS + PRESENCE
        if info.profile == 'level':
            return LEVEL_OPERATORS + PRESENCE
        if info.profile in ('number', 'integer', 'phase'):
            return COMPARISONS + PRESENCE
        if info.profile in ('yesno', 'material'):
            return COMPARISONS[:2] + PRESENCE
        return list(PRESENCE)

    def references(self, info):
        cls = {'level': DB.Level, 'phase': DB.Phase, 'material': DB.Material}.get(info.profile)
        if cls is None:
            raise ValueError(info.problem or 'Reference values cannot be resolved for this parameter.')
        return sorted([(id_value(e.Id), name_of(e)) for e in
                       DB.FilteredElementCollector(self.doc).OfClass(cls)], key=lambda p: p[1].lower())

    def assigned_values(self, categories, info):
        """Read exact parameter identities on category-filtered instances and types."""
        if info.profile not in ('text', 'number', 'integer') or not categories:
            raise ValueError('Assigned-value suggestions require recognised text or numeric metadata and categories.')
        key = (tuple(sorted(categories)), info.id, info.storage,
               info.spec.TypeId if info.spec else None)
        if key not in self.value_suggestions:
            identifier = (Enum.ToObject(DB.BuiltInParameter, Int32(info.id)) if info.id < 0
                          else self.doc.GetElement(element_id(info.id)).GetDefinition())
            reader = {'String': 'AsString', 'Double': 'AsDouble', 'Integer': 'AsInteger'}[info.storage]
            values = set()
            collector = DB.FilteredElementCollector(self.doc).WherePasses(
                DB.ElementMulticategoryFilter(ids(categories)))
            for element in collector:
                param = element.get_Parameter(identifier)
                if param is None or not param.HasValue or str(param.StorageType) != info.storage:
                    continue
                value = getattr(param, reader)()
                if value is None:
                    continue
                if info.storage == 'Double' and (math.isnan(value) or math.isinf(value)):
                    raise ValueError('Nonfinite assigned value for "{}" on element {}.'.format(
                        info.name, id_value(element.Id)))
                values.add(value)
            family = {'String': 'string', 'Double': 'double', 'Integer': 'integer'}[info.storage]
            options = []
            ordered = sorted(values, key=lambda v: (v.lower(), v)) if family == 'string' else sorted(values)
            for value in ordered:
                text = self.format_operand({'pid': info.id, 'op': 'Equals',
                                            'family': family, 'value': value}, info)
                options.append((value, text if text else '(empty string)'))
            counts = {}
            for value, text in options:
                counts[text] = counts.get(text, 0) + 1
            self.value_suggestions[key] = [
                (value, '{} [stored: {}]'.format(text, repr(value)) if counts[text] > 1 else text)
                for value, text in options]
        return self.value_suggestions[key]

    def format_operand(self, node, info=None):
        if node['op'] in ('HasValue', 'HasNoValue'):
            return ''
        value = node['value']
        if node['family'] == 'reference':
            e = self.doc.GetElement(element_id(value))
            return name_of(e) if e is not None else '<id {}>'.format(value)
        info = info or self.parameters.get(node['pid'])
        if node['family'] == 'double' and info is not None and info.spec is not None:
            if DB.UnitUtils.IsMeasurableSpec(info.spec):
                return DB.UnitFormatUtils.Format(self.doc.GetUnits(), info.spec, value, False)
        return unicode(value)

    def describe(self, node, parent_op=None, symbols=None):
        if node['kind'] == 'unsupported':
            return '[Inspection only: {}]'.format(node['reason'])
        if node['kind'] == 'group':
            if not node['children']:
                return 'Category-only: no additional conditions'
            if len(node['children']) == 1:
                return self.describe(node['children'][0], parent_op, symbols)
            text = (' {} '.format(node['op'])).join(
                self.describe(c, node['op'], symbols) for c in node['children'])
            return '(' + text + ')' if parent_op is not None and parent_op != node['op'] else text
        pid = node['pid']
        info = self.parameters.get(pid)
        if info is None and node['family'] == 'reference' and DB.FilterElementIdRule.UsesLevelFiltering(
                self.doc, element_id(pid)):
            info = ParameterInfo(pid, self.parameter_name(pid), 'ElementId')
            info.profile = 'level'
        options = dict(TEXT_OPERATORS + PRESENCE)
        if info:
            options.update(self.operators(info))
        inverted = node['op'].startswith('NOT:')
        base = node['op'][4:] if inverted else node['op']
        if symbols and base in symbols:
            op = symbols[base]
        else:
            op = base if inverted else options.get(base, base)
        if inverted:
            op = 'NOT ' + op
        return '{} {} {}'.format(self.parameter_name(pid), op,
                                 self.format_operand(node)).rstrip()

    def refresh(self):
        self.parameters = {}
        self.value_suggestions = {}
        self.views = list(DB.FilteredElementCollector(self.doc).OfClass(DB.View))
        self.records = [FilterRecord(self, e) for e in
                        DB.FilteredElementCollector(self.doc).OfClass(DB.ParameterFilterElement)]
        by_id = dict((r.id, r) for r in self.records)
        for view in self.views:
            if not view.AreGraphicsOverridesAllowed():
                continue
            for fid in view.GetFilters():
                record = by_id.get(id_value(fid))
                if record:
                    record.usage.append(view)
        for record in self.records:
            template_ids = set(id_value(v.Id) for v in record.usage if v.IsTemplate)
            record.inherited = [v for v in self.views if not v.IsTemplate and
                                id_value(v.ViewTemplateId) in template_ids and self.template_controls(
                                    self.doc.GetElement(v.ViewTemplateId))]
        self.records.sort(key=lambda r: r.name.lower())

    def get_record(self, fid):
        for r in self.records:
            if r.id == fid:
                return r
        raise ValueError('Filter {} was deleted. Refresh and select again.'.format(fid))

    def usage_token(self, record):
        return (tuple(sorted(id_value(v.Id) for v in record.usage)),
                tuple(sorted(id_value(v.Id) for v in record.inherited)))

    def assert_current(self, record):
        e = self.doc.GetElement(element_id(record.id))
        if not isinstance(e, DB.ParameterFilterElement) or not e.IsValidObject:
            raise ValueError('Filter "{}" no longer exists.'.format(record.name))
        current = FilterRecord(self, e)
        if current.token != record.token:
            raise ValueError('Filter "{}" changed. Reopen it before writing.'.format(record.name))
        return e

    def matches(self, categories, tree, exclude=None):
        key = definition_signature(categories, tree)
        return [r for r in self.records if r.id != exclude and r.signature == key]

    def duplicate_groups(self):
        groups = {}
        for r in self.records:
            if r.signature is not None:
                groups.setdefault(r.signature, []).append(r)
        duplicates = sorted([v for v in groups.values() if len(v) > 1],
                            key=lambda members: members[0].name.lower())
        return duplicates, [r for r in self.records if r.problem]

    def name_errors(self, names):
        all_names = dict((name_of(e).lower(), id_value(e.Id)) for e in
                         DB.FilteredElementCollector(self.doc).OfClass(DB.FilterElement))
        proposed = {}
        for fid, name in names.items():
            proposed.setdefault(name.lower() if name else '', []).append(fid)
        errors = {}
        for fid, name in names.items():
            reasons = []
            if not name or not name.strip():
                reasons.append('Name must not be blank.')
            elif name != name.strip():
                reasons.append('Remove leading/trailing spaces.')
            if name and len(name) > 255:
                reasons.append('Name is {} characters; maximum is 255. Shorten this proposal.'.format(len(name)))
            if name and not DB.NamingUtils.IsValidName(name):
                invalid = sorted(c for c in set(name) if not DB.NamingUtils.IsValidName(c))
                reasons.append('Invalid Revit name character(s): {}.'.format(
                    ', '.join(repr(c) for c in invalid)) if invalid else 'Revit rejects this name.')
            if len(proposed[name.lower() if name else '']) > 1:
                reasons.append('Two or more approved proposed names collide.')
            owner = all_names.get(name.lower()) if name else None
            if owner is not None and owner != fid and owner not in names:
                reasons.append('Filter name already exists: "{}".'.format(name))
            if reasons:
                errors[fid] = ' '.join(reasons)
        return errors

    def validate_names(self, names):
        errors = self.name_errors(names)
        if errors:
            raise ValueError('\n'.join('"{}": {}'.format(names[fid], errors[fid])
                                       for fid in names if fid in errors))
        return True

    def validate_definition(self, name, categories, tree, existing=None):
        self.validate_names({existing.id if existing else None: name})
        if not categories:
            raise ValueError('Choose at least one category.')
        allowed = set(id_value(c) for c in DB.ParameterFilterUtilities.GetAllFilterableCategories())
        if not set(categories).issubset(allowed):
            raise ValueError('One or more categories are not filterable.')
        native = build_tree(tree)
        if native is not None:
            if not DB.ParameterFilterElement.AllRuleParametersApplicable(self.doc, ids(categories), native):
                raise ValueError('A rule parameter is not applicable to the selected categories.')
            if not DB.ParameterFilterElement.ElementFilterIsAcceptableForParameterFilterElement(
                    self.doc, HashSet[DB.ElementId](ids(categories)), native):
                raise ValueError('This rule structure is not accepted by Revit.')
        return native

    def atomic(self, title, action):
        if self.doc.IsReadOnly or self.doc.IsModifiable:
            raise ValueError('The document is read-only or another transaction is open.')
        tg = DB.TransactionGroup(self.doc, 'Filter Manager: ' + title)
        tx = DB.Transaction(self.doc, title)
        tg.Start()
        try:
            tx.Start()
            failure_handler = RollbackFailures()
            options = tx.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(failure_handler)
            options.SetClearAfterRollback(True)
            tx.SetFailureHandlingOptions(options)
            result = action()
            if tx.Commit() != DB.TransactionStatus.Committed:
                raise ValueError('Revit did not commit the operation. ' + '\n'.join(failure_handler.messages))
            if tg.Assimilate() != DB.TransactionStatus.Committed:
                raise ValueError('Revit did not finish the Undo group.')
            return result
        except Exception:
            if tx.GetStatus() == DB.TransactionStatus.Started:
                tx.RollBack()
            if tg.GetStatus() == DB.TransactionStatus.Started:
                tg.RollBack()
            raise
        finally:
            tx.Dispose()
            tg.Dispose()

    def save(self, name, categories, tree, existing=None, acknowledged=()):
        if existing:
            self.assert_current(existing)
        self.refresh()
        if existing and self.usage_token(self.get_record(existing.id)) != self.usage_token(existing):
            raise ValueError('Shared usage changed. Reopen the editor to review the current impact.')
        native = self.validate_definition(name, categories, tree, existing)
        duplicates = self.matches(categories, tree, existing.id if existing else None)
        if set(r.id for r in duplicates) != set(acknowledged):
            if duplicates or acknowledged:
                raise ValueError('Duplicate matches changed. Review and acknowledge the current matches.')

        def write():
            if existing:
                e = self.assert_current(existing)
                e.ClearRules()
                e.SetCategories(ids(categories))
                if native is not None and not e.SetElementFilter(native):
                    raise ValueError('Revit rejected the replacement rules.')
                e.Name = name
            else:
                e = DB.ParameterFilterElement.Create(self.doc, name, ids(categories))
                if native is not None and not e.SetElementFilter(native):
                    raise ValueError('Revit rejected the new rules.')
            return id_value(e.Id)
        return self.atomic('Save filter definition', write)

    def rename(self, records, names):
        if not names or set(names) != set(r.id for r in records):
            raise ValueError('Approved names must correspond exactly to the selected filters.')
        for record in records:
            self.assert_current(record)
        self.validate_names(names)

        def write():
            elements = dict((r.id, self.assert_current(r)) for r in records if r.id in names)
            for e in elements.values():
                e.Name = 'FM temporary ' + str(uuid.uuid4())
            for fid, e in elements.items():
                e.Name = names[fid]
        self.atomic('Rename filters', write)

    def delete(self, records, approved_usage):
        if not records or not set(r.id for r in records).issubset(approved_usage):
            raise ValueError('Choose filters and review their current usage before deletion.')
        for record in records:
            self.assert_current(record)
        self.refresh()
        for record in records:
            if self.usage_token(self.get_record(record.id)) != approved_usage[record.id]:
                raise ValueError('Filter usage changed. Review deletion impact again.')
        wanted = set(r.id for r in records)

        def write():
            removed = set(id_value(i) for i in self.doc.Delete(ids(wanted)))
            if removed != wanted:
                raise ValueError('Revit attempted unexpected dependent deletions; the entire operation was rolled back.')
            return removed
        return self.atomic('Delete selected filters', write)

    def template_controls(self, template):
        if template is None or not template.IsTemplate:
            return False
        param = id_value(DB.ElementId(DB.BuiltInParameter.VIS_GRAPHICS_FILTERS))
        return param in set(id_value(i) for i in template.GetTemplateParameterIds()) and param not in set(
            id_value(i) for i in template.GetNonControlledTemplateParameterIds())

    def dependents(self, template):
        return [v for v in self.views if not v.IsTemplate and
                v.ViewTemplateId == template.Id and self.template_controls(template)]

    def apply(self, records, target):
        if not records:
            raise ValueError('Choose at least one filter to apply.')
        if not supports_filters(target):
            raise ValueError('This target does not support view filters.')
        if target.Document != self.doc:
            raise ValueError('The target belongs to another document. Reopen Filter Manager.')
        if not target.IsTemplate and self.template_controls(self.doc.GetElement(target.ViewTemplateId)):
            raise ValueError('The current view template controls Filters. Choose an explicit template target.')
        for record in records:
            self.assert_current(record)
        present = set(id_value(i) for i in target.GetFilters())
        added, skipped = [], []

        def write():
            for record in records:
                if record.id in present:
                    skipped.append(record.name)
                else:
                    try:
                        target.AddFilter(element_id(record.id))
                    except Exception as error:
                        raise ValueError('Could not apply "{}" to "{}". The whole application was rolled back: {}'.format(
                            record.name, name_of(target), error))
                    added.append(record.name)
            return {'added': added, 'skipped': skipped, 'failed': []}
        return self.atomic('Apply filters to ' + name_of(target), write)

    def collect_matches(self, records, view=None, all_filters=False):
        if not records:
            raise ValueError('Choose at least one filter.')
        if view is not None and view.Document != self.doc:
            raise ValueError('The current view belongs to another document. Reopen Filter Manager.')
        if view is not None and not DB.FilteredElementCollector.IsViewValidForElementIteration(
                self.doc, view.Id):
            raise ValueError('The current view does not support element iteration.')
        definitions = []
        for record in records:
            e = self.assert_current(record)
            cat = DB.ElementMulticategoryFilter(e.GetCategories())
            native = e.GetElementFilter()
            definitions.append(DB.LogicalAndFilter(cat, native) if native is not None else cat)
        if len(definitions) == 1:
            combined = definitions[0]
        else:
            constructor = DB.LogicalAndFilter if all_filters else DB.LogicalOrFilter
            combined = constructor(List[DB.ElementFilter](definitions))
        collector = DB.FilteredElementCollector(self.doc, view.Id) if view is not None else DB.FilteredElementCollector(self.doc)
        return list(collector.WhereElementIsNotElementType().WherePasses(combined).ToElementIds())

    def pattern_name(self, record, pattern, symbols=None):
        """Render a proposed name. symbols, from load_naming_symbols, affect only {rules}."""
        if record.tree['kind'] == 'group' and not record.tree['children']:
            rules = 'Category-only - no additional conditions'
        else:
            rules = self.describe(record.tree, symbols=symbols) if symbols else record.rules
        tokens = {'categories': ', '.join(sorted(record.category_names)),
                  'rules': rules}
        if record.problem:
            raise ValueError(record.problem)
        if len(pattern) > 1024:
            raise ValueError('Naming pattern is too long.')
        def expand(match):
            key = match.group(1)
            if key not in tokens:
                raise ValueError('Unknown naming token: {' + key + '}')
            return tokens[key]
        if '{' in re.sub(r'\{([^{}]+)\}', '', pattern) or '}' in re.sub(r'\{([^{}]+)\}', '', pattern):
            raise ValueError('Malformed naming token.')
        return re.sub(r'\{([^{}]+)\}', expand, pattern)
