# Filter Manager — Tool Scope

## Status
**Viability: CONFIRMED for browsing/applying; creation/editing is API-supported.**

Investigation used the Revit 2023 MCP connection (build 23.1.80.30, IronPython 2.7.12) on 2026-10-30:
- Reading existing categories/rules was live-tested.
- Adding filters to a view and a view template was tested in a rolled-back transaction.
- Creation, category changes, rule replacement, parameter eligibility, and rule-factory signatures were verified through API reflection. Creating/editing definitions has not yet been execution-tested.
- The existing ReValue WPF editor and ExcelLink web editor were inspected for reusable UI patterns.

This folder contains the scope only; no runnable tool has been implemented. Other Revit releases are not yet certified.

## Purpose
A single dialog that lets the user browse all `ParameterFilterElement`s (Rule-based View Filters) in the project, search/filter the list, read a plain-English description of each filter (categories + conditions), then apply selected filters to one or more targets:

1. Current view
2. Selected views (picked from a list)
3. Current view's view template
4. Selected view templates (picked from a list)

The same tool should also create new rule-based view filters and edit existing filter names, categories, and conditions. These are native Revit filter definitions, not temporary filters on the manager's list.

## Out of Scope
- Setting graphic overrides for applied filters (line/pattern/colour/halftone/transparency)
- Toggling filter visibility / enable state on views where the filter already exists
- Removing filters from views
- Deleting filters
- Creating/editing selection-based filters (`SelectionFilterElement`); if surfaced in the browser, identify them separately as read-only
- ExcelLink-only conditions such as regular expressions and arbitrary wildcards
- Changing ReValue or ExcelLink behaviour as part of this tool

## Creating and Editing Filters

### Existing UI to reuse

- [ReValue's editor](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_editor.py>) and [XAML](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/FilterEditor.xaml>) already provide parameter/condition/value rows, nested AND/OR groups, group exclusion (NOT), add/remove controls, validation feedback, and a draft that is only accepted on confirmation.
- [ReValue's expression model](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_expression.py>) represents groups and rules independently of the controls, but identifies parameters by name and evaluates conditions in Python.
- [ExcelLink's advanced-filter UI](<../../Modify.panel/KW ExcelLink.pushbutton/web/app.js>) provides similar AND/OR groups and rule rows in a web dialog. Its [operator/evaluation module](<../../Modify.panel/KW ExcelLink.pushbutton/web/filters.js>) also includes between, wildcard, and regex conditions.

**Reuse the interaction pattern, not the existing evaluators unchanged.** ReValue is the closest implementation starting point for an IronPython/WPF tool. ExcelLink uses JavaScript/DOM controls, so its UI is a design reference rather than a drop-in WPF component. Extract shared presentation/model helpers only where genuinely reusable; keep native Revit filter translation separate and preserve both existing tools.

### Editor layout and workflow

- **New Filter** opens an empty draft: name, searchable category checklist, and rule builder.
- **Edit Filter** loads one selected filter into the same editor. Show its current usage in views/templates before saving.
- Each rule has **Parameter | Operator | Value | Remove**. Groups have **All (AND) / Any (OR)**, **Add Condition**, **Add Group**, and **Remove Group**.
- Parameter operators and value controls depend on the parameter's native type. Use text input, numeric input with unit context, Yes/No, or an element-reference picker as appropriate.
- **Save** creates or updates the definition, refreshes the browser/description, and leaves applying to views as a separate explicit action.
- **Cancel** discards the draft without a transaction or document changes.
- Keep any advanced expression text optional; expose it only when it can round-trip typed parameter identities, values, and supported logic without loss.

### Native-rule constraints

1. **Categories first.** Offer only Revit-filterable categories. For the initial authoring surface, offer parameters filterable in common across the selected categories. Recompute and flag invalid rules when categories change; never silently remove them.
2. **Identity, not display name.** Store parameter ids (and suitable persistent identity if drafts are ever persisted), typed values, and parameter metadata. Display names alone are ambiguous.
3. **Typed operators.** Offer string operations only for strings, numeric comparisons for appropriate numeric types, and valid reference comparisons for ElementId values. Never compare formatted numbers as strings.
4. **Units and tolerance.** Display measurable numeric values in project units and convert to/from Revit internal units using the parameter's specification. Preserve existing numeric tolerances and use a deliberate specification-appropriate tolerance for new double rules.
5. **Blank semantics.** Revit's "has value / has no value" rules must not be labelled as equivalent to ExcelLink's whitespace/empty-string handling. Expose distinctions explicitly where supported.
6. **Native logic only.** AND/OR groups are feasible, but the complete tree must pass Revit's acceptability and parameter-applicability checks. Group NOT requires a validated transformation into supported native rules; do not directly carry over ReValue's Python boolean evaluation.
7. **Between** can be expressed as an AND group containing lower/upper comparisons. Regex and arbitrary wildcard matching have no direct rule-factory equivalent and must not be offered as native view-filter operators.
8. **Lossless editing.** Preserve supported existing rule trees, inverse rules, typed values, and tolerances on load/save. Existing category-specific OR branches or unfamiliar rule types must remain intact. If they cannot be faithfully represented, allow inspection but block definition saving with a specific explanation; never flatten, drop, or approximate rules.

### Editing impact and validation

- Editing a definition changes the filter everywhere it is used, not just on the chosen application targets. Confirm with the affected view/template list, and explain that template changes can affect dependent views.
- Update the existing filter element in place rather than delete/recreate it, preserving its identity and existing view attachments/overrides.
- Validate a nonblank unique name, at least one valid category, parameter applicability, typed operands, and a Revit-acceptable rule tree before committing.
- An intentionally category-only filter must be clearly described as matching the selected categories without additional conditions; incomplete/invalid rules must not silently become a category-only filter.
- Apply name/category/rule changes atomically. If validation or any API write fails, roll back the whole definition edit and show the reason. Account for read-only documents and worksharing ownership failures.

## Verified API Surface (Revit 2023)

### Reading filters
| Need | API (verified) |
|---|---|
| Collect filters | `FilteredElementCollector(doc).OfClass(ParameterFilterElement)` |
| Filter categories | `ParameterFilterElement.GetCategories()` → `Category.GetCategory(doc, id).Name` |
| Filter logic tree | `ParameterFilterElement.GetElementFilter()` → may be `None` (filter with no rules) |
| AND/OR nesting | `LogicalAndFilter` / `LogicalOrFilter` (both `ElementLogicalFilter`) → `.GetFilters()` |
| Leaf rules | `ElementParameterFilter.GetRules()` → `IList<FilterRule>` |
| Inverted rules | `FilterInverseRule.GetInnerRule()` ("does not contain", "does not equal", …) |
| Rule parameter | `FilterRule.GetRuleParameter()` → `LabelUtils.GetLabelFor(BuiltInParameter)` when id < 0, else `doc.GetElement(id).Name` (shared/project parameter) |
| Rule operator | `FilterStringRule.GetEvaluator()` / `FilterNumericValueRule.GetEvaluator()` → map evaluator class name to text (see table below); not every `FilterRule` is a value comparison |
| Rule value | `.RuleString` (string rules) / `.RuleValue` (numeric/integer/ElementId rules) |

Live decomposition test output from the test model:

```
Fire Resisting Compartments | Doors, Walls | AND [ Fire Rating contains "Hr" ]
Interior                    | Ramps, Stairs, Floors, Doors, Walls | AND [ Function equals 0 ]
```

### Evaluator → text mapping
`FilterStringContains` → "contains", `FilterStringEquals` → "equals", `FilterStringBeginsWith` → "begins with", `FilterStringEndsWith` → "ends with", `FilterStringGreater(/OrEqual)` / `FilterStringLess(/OrEqual)` → "is greater/less than (or equal to)", `FilterNumericEquals` → "equals", `FilterNumericGreater(/OrEqual)` → "is greater than (or equal)", `FilterNumericLess(/OrEqual)` → "is less than (or equal)". Wrap with "does not …" when the rule came from `FilterInverseRule`. Unknown evaluators fall back to the raw class name.

Note: integer-backed parameters (e.g. Wall `Function`) report raw ints (0 = Interior). Phase 1 shows the raw value; mapping enum ints to labels is a nice-to-have.

### Creating/editing definitions (signatures verified; writes not yet execution-tested)
| Need | Revit 2023 API |
|---|---|
| Filterable categories | `ParameterFilterUtilities.GetAllFilterableCategories()` |
| Common filterable parameters | `ParameterFilterUtilities.GetFilterableParametersInCommon(Document, ICollection<ElementId>)` |
| Create a definition | `ParameterFilterElement.Create(Document, String, ICollection<ElementId>, ElementFilter)`; also an overload without a rule tree |
| Change categories | `ParameterFilterElement.SetCategories(ICollection<ElementId>)` |
| Replace rules | `ParameterFilterElement.SetElementFilter(ElementFilter)` |
| Clear rules intentionally | `ParameterFilterElement.ClearRules()` |
| Rename | Inherited `Element.Name` setter |
| Build typed rules | `ParameterFilterRuleFactory` string, integer, double-with-epsilon, and ElementId overloads; contains/begins/ends, inverse comparisons, and has/no-value factories |
| Wrap/combine rules | `ElementParameterFilter(FilterRule)` / `ElementParameterFilter(IList<FilterRule>)`, `LogicalAndFilter`, `LogicalOrFilter`, `FilterInverseRule` |
| Validate tree structure | `ParameterFilterElement.ElementFilterIsAcceptableForParameterFilterElement(Document, ISet<ElementId>, ElementFilter)` |
| Validate rule parameters | `ParameterFilterElement.AllRuleParametersApplicable(Document, ICollection<ElementId>, ElementFilter)` |

Use the Revit 2023 string rule-factory overloads without `caseSensitive`; overloads accepting that argument are deprecated in this release. Later-release support must be verified separately.

### Applying filters (verified by dry-run transaction)
| Need | API (verified) | Live result |
|---|---|---|
| Add filter to view | `View.AddFilter(filterId)` | OK |
| Add filter to view template | same call on a template view | OK |
| Already-applied check | `View.GetFilters()` before adding | duplicate `AddFilter` **throws** — must guard |
| View supports filters | `View.AreGraphicsOverridesAllowed()` | verified present |
| View has a template | `View.ViewTemplateId != ElementId.InvalidElementId` | verified |
| Template controls V/G Filters? | On the assigned template: check `VIS_GRAPHICS_FILTERS` in `GetTemplateParameterIds()` and not in `GetNonControlledTemplateParameterIds()` | signatures and enum verified present; effective behaviour still needs testing |
| Find templates | `FilteredElementCollector(doc).OfClass(View)` where `v.IsTemplate` | OK (13 found) |

**Important finding:** the earlier dry run accepted `AddFilter` after assigning a template. It did not establish the effective display result, so API success alone must not be treated as proof of a visible change. Detect template-controlled Filters, warn, and offer an explicit template-target action; verify effective display during implementation.

## UI Design

WPF manager dialog with a companion rule editor following ReValue's existing editor pattern.

Layout:
- **Search box** (top) — live substring match on filter name, category names, and parameter names used in rules.
- **Filter list** (left, multi-select ListBox with checkboxes) — all `ParameterFilterElement`s sorted by name.
- **New Filter / Edit Filter** actions — Edit requires exactly one selected filter; checkboxes used for batch application remain separate from the focused filter's description.
- **Description pane** (right, read-only) — updates on selection:
  - Filter name
  - Categories (comma list)
  - Conditions rendered as an indented AND/OR tree, e.g. `Fire Rating contains "Hr"`
  - Views/templates it is already applied to (reverse lookup via `View.GetFilters()` across all views — build this index once at startup)
- **Target selector** (bottom) — radio buttons:
  1. Current view
  2. Selected views… (secondary picker listing non-template views that pass `AreGraphicsOverridesAllowed()`, grouped by ViewType)
  3. Current view's view template (disabled + tooltip when active view has no template)
  4. Selected view templates… (secondary picker listing templates)
- **Apply to Targets** / **Close** buttons, distinct from saving a filter definition.

Secondary pickers can reuse `pyrevit.forms.SelectFromList.show(..., multiselect=True)` to keep Phase 1 simple.

## Behaviour & Guardrails
- Read/preview/draft editing runs with **no transaction**. Each definition Save is one short Undo-friendly transaction. Batch application is a separate Undo-friendly operation; use a transaction group if multiple write transactions are needed.
- Skip (and report) rather than fail:
  - filter already on target (`GetFilters()` check)
  - target doesn't allow overrides (`AreGraphicsOverridesAllowed()`)
  - target view's template controls Filters → warn, offer "apply to template instead"
- Document checks: require an active project document. A non-eligible current view disables only that target mode; browsing, creation, and applying to other eligible targets remain available.
- Empty states: no filters in project → show an empty state with **New Filter** available; search with no matches → empty list message.
- Disable creation/edit/apply writes in a read-only document, with a clear explanation.
- Do not overwrite existing filter overrides, visibility, enable state, or priority when applying. Do not copy graphical settings from an arbitrary source view.
- Result summary after Apply: applied / skipped (with reasons) counts in dialog or pyRevit output window.

## Compatibility Constraints
- IronPython 2.7: no f-strings; use `.format()` / `%`. No Py3-only stdlib.
- Initial verification target is Revit 2023 only. Both reading and writing must be checked against each additional supported release before claiming compatibility.
- Rule creation must use version-appropriate signatures, including the verified Revit 2023 string factory overloads without `caseSensitive`.
- `__revit__` used once: `doc = __revit__.ActiveUIDocument.Document`, `uidoc = __revit__.ActiveUIDocument`.

## Proposed Bundle Layout
When implemented, the tool must live in a `.pushbutton` bundle (pyRevit ignores plain folders). Suggested:

```
Views.panel/
  col3.stack/            (or a new column — panel bundle.yaml layout must list it)
    FilterManager.pushbutton/
      bundle.yaml        (title: "Filter\nManager", tooltip, context: doc-project)
      icon.png
      script.py          (collector, rule adapter, apply logic)
      FilterManager.xaml (main dialog)
      FilterEditor.xaml  (create/edit dialog)
```

## Implementation Steps
1. Read adapter: decompose `ElementFilter` trees into a typed description/editor model without losing native identities or values.
2. Reverse index: filter id → views/templates using it; include template-dependency information for edit impact warnings.
3. Manager dialog: search, selection, description, target resolution, and batch application.
4. Editor dialog: name/categories, typed parameter/operator/value rows, AND/OR groups, and draft validation, adapting ReValue's proven presentation pattern.
5. Write adapter: validated model → native Revit rules; implement atomic creation and in-place editing.
6. Execution-test creation/editing with rollback first, then verify committed persistence and Undo in a disposable test model before release.
7. Regression-check ReValue/ExcelLink if any common presentation/model logic is extracted.

## Acceptance Tests

- Browse, search, describe, and apply to eligible plan/section/3D/drafting views and templates; exclude schedules and other unsupported targets.
- Duplicate application is skipped and reported; existing overrides/visibility/order remain unchanged.
- Template-controlled Filters are detected, template impact is confirmed, and effective display is verified rather than inferred from API success.
- A project with no filters can create its first filter.
- Create string, integer, double-with-units/tolerance, Yes/No, and element-reference rules where applicable, plus nested AND/OR and inverse conditions.
- Save, close, reopen, and compare the native definition; a no-change edit must preserve semantics, identity, and attachments.
- Editing an existing filter reports its usage and updates all expected consumers; it does not detach/recreate the filter.
- Invalid names, duplicate names, inapplicable parameters/categories, invalid operands, read-only state, and ownership failures produce actionable errors with no partial changes.
- Category changes flag incompatible existing rules rather than deleting them.
- Existing complex/category-specific rules are either faithfully editable or explicitly inspection-only.
- Blank/no-value conditions, category-only definitions, unsupported operators, and NOT transformations cannot silently broaden the filter.
- Cancel makes no changes. Undo restores the previous definition/application state. Browsing starts no transaction.
