# Filter Manager — Tool Scope (BETA)

## Status
**Implemented BETA: Filter Manager, Revit 2023 minimum, IronPython 2.7.**

The command now lives in `FilterManager.pushbutton` on the Views panel. The implementation uses the reviewed Penpot palette and flat button states in modal, resizable WPF dialogs. New/Edit saves return directly to the manager; only identical definitions open the duplicate confirmation. See [help.md](help.md) for operation details and BETA restrictions.

Implementation validation (2026-11-01), using the Revit 2023 and 2026 MCP connections:
- Each version passed 15 native-operation acceptance checks, 7 WPF/controller checks and 4 real ReValue-window/callback checks. The native tests cover typed rules, category-only/nested definitions, duplicates, in-place edits, attachment preservation, renaming, matching, used deletion and atomic failure rollback.
- WPF dialogs were instantiated in both IronPython 2.7 runtimes and measured at their minima. The manager keeps its list usable by collapsing management/target sections at compact sizes; editors wrap rule controls and scroll long drafts. Operator/tolerance-only edits preserve exact double operands instead of reparsing rounded display values.
- Committed create/edit/rename/application smoke tests were read back in fresh runs. The user then performed one genuine Revit Undo in each version; MCP confirmed removal of the test definition/attachment and restoration of the original filter counts.
- The existing ReValue regression suite passed all 168 tests. Its new name-only entry preserves ordinary settings and Revit selection.
- Reloaded pyRevit in both versions and verified the visible, enabled **Filter Manager** ribbon button on **KW Tools > Views**, with its BETA tooltip and the new bundle's registered script path.
- Test changes were rolled back or undone; no test definitions remain. Revit 2024/2025 have not been execution-tested. Intermediate/future compatibility relies on the shared 2023+ API surface, not a claim of certification.
- Exact native dropdown parity for every parameter, complex/category-specific definition editing, saved-file reopen and manual visual checks across monitor/DPI configurations remain BETA acceptance work. Unsupported native structures are inspection-only; unresolved operand metadata is never guessed.

### Historical feasibility evidence

Investigation used the Revit 2023 MCP connection (build 23.1.80.30, IronPython 2.7.12) on 2026-10-30:
- Reading existing categories/rules was live-tested.
- Adding filters to a view and a view template was tested in a rolled-back transaction.
- Creation, category changes, rule replacement, parameter eligibility, and rule-factory signatures were verified through API reflection. At that stage, creating/editing definitions had not been execution-tested.
- The existing ReValue WPF editor and ExcelLink web editor were inspected for reusable UI patterns.

Follow-up validation on 2026-10-31 used the Revit 2023 sample project:
- 208 correctly typed single-rule filter definitions were created and their rules evaluated across 23 representative parameters; all creation/evaluation calls completed without errors.
- Every test was rolled back. The original filter element-id set was verified unchanged.
- At that stage, in-place definition editing, committed persistence, Undo, and exact parity with the native operator dropdown remained to be tested.
- Deliberately mismatched string rules were also accepted by Revit's validation and creation APIs. API acceptance is therefore not an operator-discovery mechanism; see the operator-resolution section below.

The historical evidence above is retained as context; current implementation/testing status is listed first.

### Usability follow-up (2026-11-01)

- Successful single-target application, including already-attached skips, returns directly to the refreshed manager with an inline added/skipped summary. Retain the application review and explicit rollback/error feedback; omit the normal Application Results dialog.
- Clicking a filter name/row focuses its definition summary without toggling the checked set. The checkbox has a separate hit area for inclusion/exclusion. Right-click selection semantics remain unchanged.
- Equals/Not Equals on recognised text/integer/numeric parameters offer editable suggestions from values assigned to instances and types in the chosen categories. Collect lazily by native parameter identity, deduplicate exact values without case-folding or trimming, and invalidate cached suggestions on refresh. Display numeric values in project units while preserving exact selected operands. Manual values remain permitted; typed reference/Yes/No pickers remain unchanged.
- Seven focused checks for these changes and seven existing WPF/controller checks passed in both Revit 2023 and 2026; all test model changes were rolled back.

### Multi-selection and template-picker follow-up (2026-11-01)

- Filter names support Ctrl-click to add/remove highlights, Shift-click for an anchored contiguous range and Ctrl+Shift-click to add a range. Plain-click highlights one row and updates its summary without checking it.
- Clicking a highlighted checkbox checks/unchecks all highlighted rows to the clicked box's new state. Clicking an unhighlighted checkbox changes only that row. Apply/Rename/Delete still consume the checked set, not the highlights; show both counts. Unselect All clears checks but retains highlights.
- Replace the inline template dropdown with the **04 · Select View Template** searchable dialog, verified against the live Penpot MCP page. Selecting the template target mode opens the picker; a Choose Template button can reopen it. Include name search, a view-type filter, aligned name/type/dependent-view/status columns, single-selection count and dependency-impact feedback. Confirm with **Use This Template**, display the chosen name in the manager and preserve it on Cancel. Never assign a template to a view.
- Six grouped read-only acceptance checks passed in Revit 2023 and 2026, covering routed modifier clicks, group check toggling, preserved state, searchable template confirm/cancel behaviour and usable minimum layout.

### Rename-validation follow-up (2026-11-01)

- Remove redundant outer/unary/same-operator brackets from generated rule descriptions/names; retain grouping that distinguishes mixed AND/OR conditions and literal parentheses. This changes presentation only, not native rules or duplicate signatures.
- Category-only naming uses `Category-only - no additional conditions` so the tool does not introduce an invalid colon into a generated name. Other invalid characters and overlong proposals still require explicit correction.
- Validate each approved proposed name independently while checking collisions across the entire approved set and existing definitions. Show each error only on its offending row, mark both proposed-name collision participants, and leave unrelated valid rows Ready. Distinguish invalid characters, blank/padded names and actual lengths over 255. Use the same validation for atomic writes, including valid name swaps. Manual edits/approval changes refresh validation; no automatic truncation, suffixing or model writes.
- Six grouped read-only checks passed in Revit 2023 and 2026 for these rendering and validation changes.

### Naming-settings follow-up (2026-11-01)

- Add a hidden bundle-local `naming_settings.json` file. Its `operator_symbols` object maps operator keys (`Equals`, `NotEquals`, `Greater`, `GreaterOrEqual`, `Less`, `LessOrEqual`, the text and presence operators) to naming text. Defaults: `=`, `≠`, fullwidth `＞`, `≥`, fullwidth `＜`, `≤`; text and presence operators keep their wording. No UI exposure.
- Symbols apply only to the `{rules}` token in Rename Filters. Manager summaries, search, duplicate signatures and native definitions keep readable wording or remain unchanged. Native inverted rules render `NOT ` plus the base text.
- MCP verified `NamingUtils.IsValidName` in 2023 and 2026. Valid: `=`, `≠`, `≥`, `≤`, `≈`, `!=`, fullwidth `＞`/`＜`. Invalid: ASCII `<`, `>`, `<=`, `>=`, `~`.
- Load strictly on every preview, as UTF-8 with an optional BOM.
  - A missing file uses readable wording.
  - `_`-prefixed top-level keys are notes.
  - Reject the whole file for unknown keys, malformed JSON, nonobject shapes, blank/padded/non-text values or Revit-invalid characters. Show one dialog-level error with the file path and problems. Keep proposals unchanged and disable Rename; do not silently fall back.
- `rename_checks` now has 9 grouped checks; it and all earlier suites passed in Revit 2023 and 2026.

## Purpose
A single dialog that lets the user browse all `ParameterFilterElement`s (Rule-based View Filters) in the project, search/filter the list, read a plain-English description of each filter (categories + conditions), then apply one or more selected filters to **exactly one target per operation**:

1. Current view
2. Current view's view template
3. One selected view template (picked from a single-selection list)

The same tool should also create new rule-based view filters, edit existing categories and conditions, analyse duplicate definitions, rename one or several selected filters manually or with configurable rule-based naming patterns, select unused definitions, and delete explicitly approved selected definitions. These are native Revit filter definitions, not temporary filters on the manager's list.

## Revised Workflow (2026-10-31)

1. Browse, create or edit filter definitions in Filter Manager.
2. Apply selected filters to one current view or one view template using the target modes above.
3. Configure their graphics overrides on that target using Revit's native view/template settings. Overrides belong to each view/template attachment, not to the shared filter definition.
4. Use a **separate copy tool** to distribute the configured filters to other views and/or view templates.

Filter Manager establishes one configuration target; it no longer provides multi-view or multi-template application. Selecting a template does not assign that template to the current view. Applying to a template may still affect all views that inherit its Filters settings, so show that impact explicitly before applying.

The separate tool should copy selected filter attachments and their configured graphical overrides from an explicitly chosen source view/template, rather than merely add the same definition ids. Its handling of existing target filters, visibility/enable state, ordering, template-controlled targets, and conflict policy needs its own scope and validation. Do not implement it as part of Filter Manager or silently assume replacement behaviour.

## Out of Scope
- Applying to multiple views or multiple templates in one operation
- Copying configured filters/graphics between views/templates (separate tool)
- Setting graphic overrides for applied filters (line/pattern/colour/halftone/transparency)
- Toggling filter visibility / enable state on views where the filter already exists
- Detaching filters from particular views/templates while retaining their project definitions; explicit definition deletion below is separate and affects every attachment
- Automatically merging duplicates, replacing their view attachments, or deleting duplicate definitions without explicit selection and confirmation
- Creating/editing selection-based filters (`SelectionFilterElement`); if surfaced in the browser, identify them separately as read-only
- ExcelLink-only conditions such as regular expressions and arbitrary wildcards
- Unrelated changes to ReValue or ExcelLink; the explicit ReValue integration described below is in scope

## Creating and Editing Filters

### Existing UI to reuse

- [ReValue's editor](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_editor.py>) and [XAML](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/FilterEditor.xaml>) already provide parameter/condition/value rows, nested AND/OR groups, group exclusion (NOT), add/remove controls, validation feedback, and a draft that is only accepted on confirmation.
- [ReValue's expression model](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_expression.py>) represents groups and rules independently of the controls, but identifies parameters by name and evaluates conditions in Python.
- [ExcelLink's advanced-filter UI](<../../Modify.panel/KW ExcelLink.pushbutton/web/app.js>) provides similar AND/OR groups and rule rows in a web dialog. Its [operator/evaluation module](<../../Modify.panel/KW ExcelLink.pushbutton/web/filters.js>) also includes between, wildcard, and regex conditions.

**Reuse the interaction pattern, not the existing evaluators unchanged.** ReValue is the closest implementation starting point for an IronPython/WPF tool. ExcelLink uses JavaScript/DOM controls, so its UI is a design reference rather than a drop-in WPF component. Extract shared presentation/model helpers only where genuinely reusable; keep native Revit filter translation separate and preserve both existing tools.

### Editor layout and workflow

- **New Filter** opens an empty draft: name, searchable category checklist, and rule builder.
- **Edit Filter** loads one selected filter into the same editor. Show its current usage in views/templates before saving.
- A valid new/edited draft shows matching existing definitions: **Filter 'X' has the same categories and rules**. List every match, not just the first. Exclude the definition currently being edited, and refresh the check when categories/conditions change.
- Each rule has **Parameter | Operator | Value | Remove**. Groups have **All (AND) / Any (OR)**, **Add Condition**, **Add Group**, and **Remove Group**.
- Parameter operators and value controls depend on the parameter's native type. Use text input, numeric input with unit context, Yes/No, or an element-reference picker as appropriate.
- Equals/Not Equals on recognised text/integer/numeric parameters offer editable assigned-value suggestions scoped to the chosen categories, including both instances and types. Exact stored operands, rather than rounded labels, are used when a suggestion is selected. Other operators retain manual input without autofill suggestions; presence conditions still hide operands.
- **Create Filter** (new) / **Save Changes** (edit) validates and writes the definition, closes the editor and returns to the refreshed manager. Only duplicate definitions require a separate confirmation. Applying to the single chosen target remains a separate explicit action.
- When identical definitions exist, require explicit confirmation before saving but allow intentional duplicates. Offer an explicit action to inspect/use an existing filter instead, without silently applying it, discarding the draft, or changing that existing definition.
- **Cancel** discards the draft without a transaction or document changes.
- Keep any advanced expression text optional; expose it only when it can round-trip typed parameter identities, values, and supported logic without loss.

### Create Filter flow

1. **01 · Filter Manager** opens **02 · New Filter**. **Create Filter** validates the name, categories, typed rules and current duplicate matches; invalid input remains in the editor with actionable feedback and no writes.
2. If no duplicate exists, create the definition atomically and return directly to the refreshed **01 · Filter Manager**. Do not show a separate review, confirmation or success dialog.
3. Only if the draft matches an existing definition, open the new-filter variant of **11 · Confirm Duplicate Definition**. Show all matches and complete rules; require intentional-duplicate acknowledgement before **Create Duplicate**. Recheck matches and name validity immediately before committing; changed context requires updated confirmation.
4. Successful duplicate creation also returns directly to **01 · Filter Manager**. **Back to Editor** or closing the duplicate dialog preserves the draft. **Use Existing** explicitly discards the draft and focuses the chosen match without creating, applying, merging or changing any definition.
5. Write failures roll back, preserve the draft and show the reason. Creation never automatically attaches a filter to a view/template or opens application review/results.

Normal path: **01 → 02 → 01**. Duplicate path: **01 → 02 → 11 → 01**.

### Parameter-specific operator resolution

The operator dropdown must be resolved per rule, not populated from ReValue/ExcelLink's global operator lists.

1. Resolve the filterable parameter for the chosen categories and retain its native identity.
2. Obtain storage type, specification, and semantic parameter role. None of these alone is sufficient: a tested built-in enumeration had integer storage with a string specification, while several reference parameters had an empty specification.
3. Select a version-verified capability profile using that metadata and any necessary parameter-specific handling. Explicitly distinguish text, integer counts/enumerations, Yes/No, unitless and measurable doubles, and phase/level/material/other references.
4. Populate operators in native-dialog order and use the corresponding typed value editor. Text ordering comparisons must remain available where supported; comparisons on references must not be implemented by comparing displayed names.
5. Hide the operand editor for "has a value" / "has no value"; these are not synonyms for trimmed blank text.
6. On parameter/category changes, retain an operator and operand only if both remain valid. Otherwise display a specific validation message and require correction; never silently substitute an operator or coerce a reference to text.
7. Unknown capabilities must be surfaced explicitly. Do not present guessed operators as native-compatible, and do not silently overwrite an existing rule that cannot be represented.

The user's native-dialog examples establish the intended profiles for ordinary text (14 operators, including ordering and six substring/prefix/suffix operations), Phase Created (six comparisons plus two value-presence operations), and level references (the eight operators below). Native-dialog profiles for other families, especially Yes/No, integer enumerations, and non-phase/non-level references, still need comparison with Revit's UI. The inspected `ParameterFilterUtilities` API exposes parameter/category applicability, not a per-parameter list of native-dialog operators.

For level-reference parameters, use this exact dropdown order:

1. equals
2. does not equal
3. is above
4. is at or above
5. is below
6. is at or below
7. has a value
8. has no value

Use a project-level picker for comparison operands. The four directional labels correspond to the native greater/greater-or-equal/less/less-or-equal rule factories with level-specific handling; do not implement them with string comparisons or raw element-id ordering. Select this profile using native parameter identity and verified level-filtering metadata, not a name containing "Level".

### Full category and parameter eligibility inventory

A read-only Revit 2023 MCP inventory on 2026-10-31 queried **every** category returned by `ParameterFilterUtilities.GetAllFilterableCategories()`. For each category, a singleton category list was passed to `GetFilterableParametersInCommon(doc, categories)` to obtain its full filterable parameter-id set, without requiring any placed elements.

In the open sample document this returned:

- **201 filterable categories**, including **172 with no placed instances**.
- **907 distinct filterable parameters** and **5,698 category-parameter pairs**.
- **764 other document categories/subcategories** absent from the filterable-category set.
- All parameter names resolved. Nine filterable categories had no document `Category` object, so the inventory identifies them by built-in enum name and records this limitation explicitly.

CSV reports for category eligibility, category/parameter pairs, and the selected wall's instance/type parameters, plus a complete JSON inventory, were generated as session deliverables. Counts, per-category totals, and unique category/parameter pairs were cross-checked after export.

**Wall example:** selected wall `1480376` had **60 filterable parameter ids**. Its instance and type exposed 77 parameter entries; these are not the same set. `WALL_TOP_IS_ATTACHED` (`-1001117`, "Top is Attached") exists as an integer/Yes-No instance parameter but is **not** in the filterable set for Walls. It must not appear in the filter editor's parameter dropdown.

Implementation requirements:

- Populate eligible categories and parameters from these native APIs in the **current document**, not from all element properties, a trial rule that happens to be accepted, or a hard-coded snapshot.
- For several selected categories, call `GetFilterableParametersInCommon` with the complete selected category-id list. Do not combine per-category parameter lists by union.
- Cache eligibility for the current document/category selection and invalidate it when relevant bindings/categories change. Project/shared parameter ids and availability are document-dependent.
- Preserve categories with no elements: empty categories can still have valid filter parameters.
- Keep eligibility separate from metadata discovery and operator capability resolution. A full parameter-id inventory does not provide storage metadata for every unsampled built-in, nor does it certify native operator menus.
- The wall's excluded-property list is an instance/type example only; the complete eligibility map is the native per-category result. Do not infer every unavailable property for every possible family from one sampled element.

#### Revit 2023 execution evidence

| Representative family | Parameters tested | Typed operators exercised per parameter |
|---|---:|---:|
| Text / URL, including instance, type, project and shared parameters | 4 | 14 |
| Double: length, area, volume, angle, unitless number, shared number, currency | 7 | 8 |
| Integer: ordinary integer, enumeration, two Yes/No parameters, integer with string specification | 5 | 8 |
| ElementId: two phase parameters, two level parameters, two material references, rebar-cover reference | 7 | 8 |
| **Total** | **23** | **208 checks** |

The 14 tested string operations were six comparisons, contains/not-contains, begins/not-begins, ends/not-ends, and has/no-value. The eight operations on other storage types were six comparisons and has/no-value. These counts describe API tests, **not certified dropdown contents**: even Yes/No ordering rules were accepted, which does not prove the native dialog offers them or that the tool should.

Negative controls used a string "contains" rule on Length, Structural (Yes/No), Phase Created, and the integer-backed enumeration. All four passed structure/applicability validation and filter creation; none matched the sampled element. Consequently, trying factory methods or temporary filter creation and keeping whichever succeeds would expose invalid/misleading choices.

The tested Base Constraint and Reference Level parameters also reported native level-specific filtering through `FilterElementIdRule.UsesLevelFiltering`. Level ordering must preserve Revit's native rule handling rather than assume raw element-id or name ordering.

The MCP can validate metadata, factory overloads, definition creation, and execution behaviour. Exact native UI choices require native-dialog evidence (for example screenshots showing the selected parameter and expanded operator list). This is representative coverage, not exhaustive certification of every parameter or category.

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

- Editing a definition changes the filter everywhere it is used, not just on the chosen application target. Show the affected view/template list and shared-use warning in the editor, explaining template-inheriting effects. Do not require a separate shared-definition confirmation dialog.
- Update the existing filter element in place rather than delete/recreate it, preserving its identity and existing view attachments/overrides.
- Validate a nonblank unique name, at least one valid category, parameter applicability, typed operands, and a Revit-acceptable rule tree before committing.
- An intentionally category-only filter must be clearly described as matching the selected categories without additional conditions; incomplete/invalid rules must not silently become a category-only filter.
- Apply name/category/rule changes atomically. If validation or any API write fails, roll back the whole definition edit and show the reason. Account for read-only documents and worksharing ownership failures.

### Save Changes flow

1. **01 · Filter Manager** opens **03 · Edit Filter**. Show the draft's changes and all affected consumers within the editor. Its primary action is **Save Changes**, replacing the earlier Review Changes label.
2. Save validates the draft, current definition/usage and identical existing definitions, excluding the filter being edited. Invalid input or stale context stays in the editor with actionable feedback and a refreshed impact display; preserve the draft rather than overwriting an externally changed definition.
3. If no duplicate exists, update the existing definition atomically, close the editor and return directly to the refreshed **01 · Filter Manager**. There is no intermediate shared-definition confirmation or separate impact acknowledgement.
4. Only if the updated definition duplicates another filter, open the edit-specific variant of **11 · Confirm Duplicate Definition**. Show all matching definitions, complete rules and the shared-edit impact; require explicit intentional-duplicate acknowledgement before **Save Changes**. Recheck immediately before committing; changed matches/context require updated confirmation, not silent continuation.
5. **Back to Editor** or closing the duplicate dialog preserves the unsaved draft. **Use Existing** is an explicit discard-draft alternative: focus the existing match without saving changes, deleting the edited definition or moving any attachments. It does not merge filters.
6. A successful duplicate-confirmed Save also returns directly to **01 · Filter Manager**. Save failures roll back and retain the draft with an actionable error.

Normal path: **01 → 03 → 01**. Duplicate path: **01 → 03 → 11 → 01**. The old **06 · Confirm Definition Edit** is archived, not part of either active workflow.

The editor's readable rule/change preview is a **draft review, not a live drawing preview**. Draft edits do not change the model; **Save Changes** does. Existing attachments and graphics remain in place while all consumers use the saved definition. Resizing/moving the modal editor can expose the drawing, but unsaved rules do not affect it. Close the manager to interact with Revit; redraw and effective display after saving still require implementation verification. A live/modeless preview workflow is not included.

## Duplicate Definition Analysis

### Project-wide analysis

- **Analyse Duplicates** scans every rule-based filter definition in the active project, regardless of the browser's search or checkbox selection.
- Group matching definitions in a results dialog. Show filter names/ids, shared categories and rule description, and each filter's direct/template/inherited usage.
- Report groups, filters in groups, and definitions that could not be compared. An incomplete scan must not report a misleading "no duplicates".
- Selecting a result focuses/inspects that definition in the manager. Analysis itself starts no transaction and changes no model data.
- Reuse the same comparison mechanism for the project-wide scan and new/edit draft warnings. Refresh the index after relevant definition changes and recheck before Save so warnings cannot rely on stale data.

### Meaning of duplicate

Compare a canonical signature consisting of:

- The complete category-id set, independent of category order.
- Native parameter identity, rule kind/operator, typed operand, and any semantic metadata such as numeric tolerance and inversion.
- The complete AND/OR rule structure, including category-specific branches and any filter-level inversion that affects the result.

Filter names, ids of the filter definitions themselves, application targets, graphical overrides, visibility, enable state, and priority are **not** part of the definition signature. Equal definitions may intentionally have different view graphics; detecting them is not permission to merge them.

Canonicalisation must ignore harmless ordering of sibling conditions inside the same AND/OR group and normalise equivalent single-rule versus multiple-rule AND representations where proven safe. Preserve logical distinctions, operand types, native parameter/reference ids, exact text operands, and double values/tolerances. Do not compare rounded/unit-formatted description strings or case-fold values merely because native text comparisons may be case-insensitive.

The BETA also normalises associative nesting of the same AND/OR operator; mixed operators, inversions and unsupported nodes are not rewritten.

This detects identical definitions after conservative structural normalisation, not arbitrary mathematical equivalence. Two different rules that happen to match the same current elements are not duplicates. Do not equate AND with OR, apply speculative boolean rewrites, or ignore unrecognised rule types. If a rule cannot be fully represented, report its comparison as unsupported rather than generating a partial signature.

Category-only filters are comparable when their category sets and lack of conditions are explicitly known. Different numeric tolerances, category sets, inversions, reference ids, or parameter ids must prevent an identical-definition match.

## Renaming and Rule-Based Naming

- Provide **Rename** independently of definition editing. Support manual names for one or several selected rule-based filters without altering their categories, rules, identity, attachments, or graphics.
- Provide configurable token-based naming patterns, initially **`{categories} | {rules}`**. A simple result could be `Doors, Walls | Fire Rating contains Hr`.
- `{categories}` is a deterministically ordered category-name list. `{rules}` renders the complete rule expression with explicit AND/OR grouping, native operator labels (including level-specific labels), value-presence rules without operands, and readable typed values.
- Numeric names use readable project units; references use readable names, but neither is used for duplicate identity comparisons. Clearly label a category-only definition rather than outputting an empty/misleading rule summary.
- Offer a preview table: **Selected | Current Name | Proposed Name | Validation/Conflict**. Allow manual correction of proposed names and explicit selection of rows to rename.
- Validation/conflicts are per row, never the first batch error repeated on unrelated proposals. Flag both sides of approved-name collisions, name invalid characters explicitly and report the actual length for proposals over 255 characters. Remove redundant presentation brackets while preserving mixed logic; use a colon-free category-only naming token.
- Pattern changes only update the preview. Accepting a generated name is explicit; later edits to a filter's rules must not automatically rename it.
- Persist the accepted naming pattern through repository-standard tool settings when implemented. Pattern expansion must be bounded and non-executable; reject unknown/malformed tokens with actionable feedback.
- Reuse the existing Type Renamer's pattern/preview interaction where appropriate, not its family-type-specific value extraction. Keep both existing tools unchanged unless genuinely shared presentation helpers are extracted.
- Validate nonblank names, Revit naming constraints, collisions with existing names, and collisions among proposed names. Duplicate-definition warnings are separate from duplicate-name errors: intentionally equivalent definitions still need valid distinct names.
- If a generated name is too long or invalid, show the proposed name and the problem. Do not silently truncate rules, invent suffixes, or sanitise away meaningful conditions. Require an explicit user correction.
- Preview and Cancel are read-only. Apply only the approved rows atomically in an Undo-friendly rename operation, revalidating current names/ownership immediately before writes. Report failure and roll back on errors, without partial or success-shaped results.
- Manual renaming does not require a fully editable rule tree. Generated rule-based names do require a complete readable representation; unsupported rules produce an explicit per-row error rather than a partial name.

## Selecting Unused, Clearing Selection and Deleting Filters

### Select Unused

- Place **Select Unused** and **Unselect All** alongside **Analyse Duplicates**, **Rename Selected** and **Delete Selected** in the manager's management toolbar.
- Scan all rule-based filter definitions and their attachments across the entire active project, independent of browser search, current view or application target. A filter is unused only when attached to **no view and no view template**.
- Count attachments to templates even when those templates are assigned to no views. Hidden/disabled filter attachments still count as usage. Duplicate definitions and rules matching no model elements are not evidence of being unused.
- Use the existing reverse usage index, refreshed before this action. A failed/incomplete usage scan must not classify uncertain definitions as unused; show the issue and leave the previous selection unchanged.
- After a successful scan, replace the manager's checked-filter set with exactly the unused definitions, clear search/list restrictions to reveal them, and report **N unused filters selected**. This changes neither Revit's element selection nor model data.
- If none are unused, clear the manager's checked set and report **No unused filters found**; Delete Selected is disabled. Do not retain a misleading previously checked set.
- Leave the user free to inspect, uncheck individual filters, select other filters or cancel. Selecting unused definitions never opens deletion automatically or deletes anything.

### Unselect All

- Clear the entire manager checked-filter set, including rows hidden by search/list restrictions. Report **0 filters selected** and disable selected-set actions such as Rename Selected, Delete Selected and Apply to Target.
- Preserve the current search/list restrictions, focused description and application target. Do not confuse the focused row with a checked filter.
- This action is read-only, requires no transaction or confirmation, and does not change Revit's element selection, filter attachments or definitions. It remains available in read-only documents.

### Delete Selected

- Allow deletion of any selected rule-based definitions, including used filters, only through a separate **Delete Selected** action and explicit confirmation. Empty selection and read-only documents disable the action with an explanation.
- Review the exact selected names/ids, categories and usage before deletion. Show direct views, attached templates and template-inheriting views; offer approved-row checkboxes so the user can narrow the operation.
- Clearly distinguish unused rows from used rows. If used filters are approved, warn that deleting the shared definitions removes their filter attachments, graphical overrides and filtering effects everywhere they are used, including affected template-inheriting views. It does not delete the matched model elements.
- Require explicit acknowledgement for approved used filters. If approved rows change, recalculate the impact and confirmation state; do not retain acknowledgement of a different used-filter set.
- Revalidate the definitions, full usage and ownership immediately before writes. A stale selection or changed impact requires a refreshed review and confirmation, not silent continuation.
- Delete only approved definitions in one short Undo-friendly operation. Verify native deletion behaviour in Revit 2023 before implementation is treated as valid, including attachment removal, dependency effects and Undo restoration of definitions, attachments and graphics.
- Do not allow deletion to cascade into unapproved filter definitions or unrelated model elements. Validate the native deletion result before committing; unexpected effects or any write/ownership failure roll back the entire operation with an actionable error, leaving no partial deletion.
- Preview and Cancel perform no model writes. Deletion is never inferred from duplicate analysis or Select Unused, and never runs automatically.
- On success, report deleted definitions and affected usage, then refresh the browser, checked/focused ids, descriptions, usage index, duplicate results and matching previews. Keep surviving checked rows where valid; remove stale/deleted ids. Report failure explicitly rather than displaying a success-shaped result.

## Right-Click ReValue and Revit Selection Actions

Provide two distinct context-menu actions in Filter Manager's filter list:

### Rename Filters with ReValue

- Pass the selected native filter definitions directly to ReValue through an explicit reusable entry point, rather than executing its ribbon script or relying on Revit's current element selection.
- Open in filter-name mode: read and write each filter's own name, never attempt to resolve an element type, and never allow stale saved type/source settings to redirect writes to another target.
- Reuse ReValue's tokenisation, find/replace, case and pattern preview capabilities. Filter-specific `{categories}` / `{rules}` data must be deliberately supplied if those naming tokens are exposed; they are not ordinary native element parameters.
- Preserve the filter-name validation, preview, approved-row selection and atomic rename requirements above. Refresh the manager's names/usage and duplicate results after returning.
- The current ReValue implementation is not ready as a drop-in call: although `ReValueDialog` accepts an element list, its initialisation reloads instance/type mode from session settings, and type mode skips elements with no resolvable type. Add a filter-safe entry point with explicit launch context while preserving normal ribbon behaviour.

### Select Matching Elements in Revit

- Open a matching-scope dialog offering both **Current View / Entire Active Project** and **Match Any Selected Filter (OR) / Match Every Selected Filter (AND)**. Do not assume one choice or conflate this collection scope with Filter Manager's single application target.
- Evaluate each filter's complete native category-plus-condition definition, then union/intersect the resulting matches as selected. Do not translate the rules into ReValue's Python expression evaluator, infer matches from formatted descriptions, or omit category restrictions.
- Collect unique matching non-type model elements, not filter definitions or element types.
- For current-view collection, verify that the view supports element iteration and explain scope limits. Rule matching is not a guarantee of visible pixels: view settings, hiding, phases, templates and graphical overrides are distinct from definition matching.
- If a chosen filter cannot be evaluated or has changed/disappeared, report the issue and require correction rather than silently omitting it.
- Preview the selected filters, scope, ANY/ALL choice and unique matching-element count. The confirmation action is **Select N Elements in Revit**, explicitly replacing the current Revit selection with those matching non-type model elements.
- This action does not launch ReValue, edit elements, apply filters or change graphics. There is no separate **ReValue Matching Elements** shortcut: once selected, the user can launch ReValue normally from Revit.
- Cancel, no matches, invalid view scope, unresolved rules or stale elements leave the existing Revit selection unchanged and show the reason where applicable. Revalidate matches before replacing the selection; do not silently select a partial stale set.
- After confirmation, close the modal manager so the user can interact with the selection in Revit or launch another command. Do not immediately reopen a blocking dialog or restore the previous selection.
- Project-wide matches may be outside the current view or hidden. Explain this distinction; do not automatically change views, unhide elements, isolate them or zoom.
- Matching and selection require no document transaction. Verify the selection handoff in Revit 2023 before treating it as implemented.

### Dialog and Selection Safety

- The initial manager and companion dialogs are **modal**, not modeless. Browsing/editing blocks direct Revit interaction until the dialogs close. A persistent modeless manager is outside this scope and would require a separately designed API-context and document-lifecycle workflow.
- Right-clicking a row already in the selection preserves the selected set; right-clicking an unselected row makes that row the explicit selection. Display the action's filter count so its scope is unambiguous.
- Pending editor drafts must be saved or explicitly discarded before launching filter renaming or selecting matches. Resolve and validate the document/filter/element ids again at handoff.
- Suspend/close the manager's modal dialog before launching **Rename Filters with ReValue** in a valid Revit API context; return to and refresh the manager afterwards, retaining its search, focused item and selection where valid. Do not start a second ribbon command inside an active modal handler or leave a transaction open across either dialog.
- Only **Select Matching Elements in Revit**, after explicit confirmation, replaces Revit's user selection. Do not replace selection just to hand off filter definitions for renaming. Normal ReValue launches must continue to honour their existing selection/mode workflow, including the elements selected by Filter Manager.
- Test module loading, sibling helper imports, document context, cancellation, saved-mode isolation and return/refresh behaviour before calling this integration production-ready. No cross-command execution or matching-scope integration has yet been tested.

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

### Creating/editing definitions (single-rule creation execution-tested; editing signatures verified)
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
- **Filter list** (left, extended-selection ListBox with independent checkboxes) — all `ParameterFilterElement`s sorted by name. Clicking a name/row focuses its summary without checking it. Ctrl-click toggles highlights, Shift-click selects an anchored range, Ctrl+Shift-click adds a range. Clicking a highlighted checkbox applies that box's new state to the highlighted group; an unhighlighted checkbox affects only itself. Batch operations consume checks, not highlights.
- **New Filter / Edit Filter** actions — Edit requires exactly one selected filter; checkboxes used for applying several filters to one target remain separate from the focused filter's description.
- **Analyse Duplicates** action — project-wide read-only scan with grouped results, independent of current selection/search.
- **Rename** action — manual/pattern-based preview for the selected filters, distinct from Apply to Target.
- **Select Unused** action — project-wide usage scan that checks only definitions attached to no view/template; reveals the selected results without deleting.
- **Unselect All** action — clears all manager checks, including hidden rows, while retaining search, focus, highlights and target; does not alter Revit selection.
- **Delete Selected** action — approved-row review and explicit confirmation, with project-wide usage-impact warning for used filters.
- **Right-click menu** — Rename Filters with ReValue / Select Matching Elements in Revit, with explicit selected-filter scope.
- **Description pane** (right, read-only) — updates on selection:
  - Filter name
  - Categories (comma list)
  - Conditions rendered as an indented AND/OR tree, e.g. `Fire Rating contains "Hr"`
  - Views/templates it is already applied to (reverse lookup via `View.GetFilters()` across all views — build this index once at startup)
- **Target selector** (bottom) — radio buttons:
  1. Current view
  2. Current view's view template (disabled + tooltip when active view has no template)
  3. Selected view template… (secondary picker allowing exactly one eligible template)
- Show the resolved target's name/type, selected-filter count, and any template-dependent-view impact.
- **Apply to Target** / **Close** buttons, distinct from saving a filter definition.
- **Review Application** shows the selected filters with add/already-applied status for the one target, not a multi-view matrix.
- Successful application returns directly to the refreshed manager with an inline added/already-applied summary and native-graphics reminder. No normal Application Results dialog; application failures remain explicit and atomic.

The selected-template picker is a dedicated resizable WPF dialog matching Penpot page 04, with name search, view-type filtering, dependency information and exactly one confirmed template. There is no inline template dropdown, arbitrary-view picker or multi-template picker in this tool.

### Resizing and drawing-area visibility

- The actual WPF **manager, New/Edit Filter editors, template picker, duplicate analysis, rename preview, application review and deletion review/results** are resizable. Detailed duplicate confirmation is also resizable to accommodate rules, matches and usage; shared-edit impact stays in the editor rather than a separate change-review dialog.
- Small acknowledgement-only confirmation dialogs remain fixed-size. If a confirmation includes extensive rules or usage data, use a resizable detail dialog rather than forcing the content into a small fixed window.
- Set usable minimum width/height per dialog, not the Penpot board dimensions. Validate these minima against the supported display sizes and DPI scaling; opening windows must fit the available monitor work area.
- Implemented minima are 620 × 680 device-independent units for the manager and searchable template picker, and 620 × 460 for other detailed dialogs, clamped to the monitor work area. Compact manager sizes collapse the management and target sections; their expandable headers retain access to all actions and the target name. Editors wrap parameter/operator/value controls rather than requiring a wide drawing-obscuring window.
- Expanding a window gives space to the lists, rule tree, tables and descriptions rather than scaling text or leaving empty margins. Scroll long content and keep primary actions, validation and impact warnings accessible at the minimum size.
- The filter editor must support a narrower, movable layout so users editing an already-applied filter can leave substantial drawing area visible. Reflow or stack category/rule panes and parameter/operator/value controls as needed; do not require the full-width mockup to edit a rule. Preserve the draft, focus and selected categories when resizing.
- Resizing does not make these dialogs modeless. The exposed drawing is context, not a live preview of unsaved changes; normal Revit interaction resumes after the modal dialogs close.
- Penpot boards remain fixed-size design references. These resizing requirements apply to the implementation and have not yet been demonstrated by the static mockups.

### Penpot Concept v2

The editable **Filter Manager** Penpot file (`9a0c44dc-8874-81e7-8008-ddf0cdc109b5`) now reflects the revised scope. Existing browsing/editor structure and design principles were retained, with obsolete multi-target content replaced and new management workflows added.

Saved baseline version: **Filter Manager · UI concept v2 · expanded scope & blue palette**, 2026-10-31. Follow-ups **v2.1** and **v2.2** simplify the ReValue workflow and add selection/deletion controls; **v2.3** removes intermediate shared-edit confirmation. Latest revision: **Filter Manager · UI concept v2.4 · direct creation & duplicate-only confirmation** also makes new-filter creation return directly to the manager unless duplicate confirmation is required. Named pre-revision checkpoints are retained.

| Page | Design coverage |
|---|---|
| 01 · Filter Manager | Search, descriptions, three single-target modes, Analyse Duplicates / Rename Selected / Select Unused / Unselect All / Delete Selected toolbar; variants show both right-click actions, unused checks and the cleared checked set |
| 02 · New Filter | Category intersection guidance, parameter-aware rules, nested groups, normal/duplicate draft variants; Create Filter returns directly to the manager unless duplicate confirmation is required |
| 03 · Edit Filter | In-place shared-definition editing, inline consumer impact/proposed changes, normal and duplicate draft variants; Save Changes returns directly to the manager unless duplicate confirmation is required |
| 04 · Select View Template | Exactly one template, dependent-view count, no template assignment |
| 05 · Review Application | One resolved target; per-filter add/already-applied actions and preserved-graphics warning |
| 07 · Application Results | Historical concept; the implemented usability follow-up skips this page after success and shows an inline manager summary instead |
| 08 · Duplicate Analysis | Project-wide duplicate groups, definition/usage inspection and explicit uncomparable-definition reporting; no merge/delete |
| 09 · Rename Filters | `{categories} | {rules}` preview, editable proposed names, approved rows and explicit collision correction |
| 10 · Select Matching Elements | Current-view/project scope, ANY/ALL, count preview and selection-replacement warning; closes the modal manager and leaves the elements selected for normal Revit/ReValue use |
| 11 · Confirm Duplicate Definition | Separate new/edit variants, complete matching definition, explicit intentional-duplicate acknowledgement and Use Existing discard-draft alternative; edit Save updates the existing definition, not a new filter |
| 12 · Parameter-aware Rule Controls | User-supplied text, level and phase operator profiles, typed operand examples and no-operand guidance; other families remain subject to native verification |
| 13 · Confirm Filter Deletion | Unused-only and mixed-use approval variants, per-row names/ids/categories/usage, unchecked rows retained and explicit used-filter impact acknowledgement |
| 14 · Deletion Results | Deleted/kept/failed counts, per-filter outcome, Undo guidance and refreshed manager state |

The former Select Views and shared-edit confirmation pages remain as **ARCHIVE · Multi-view Picker (v1)** and **ARCHIVE · Confirm Definition Edit (v2)**, outside the active workflow. There are 13 active pages plus these two archived references; active page numbers are retained.

Palette:
- **`#43789A`**: primary actions, selection and accents.
- **`#172838`**: headings and primary text.
- **`#6E6E71`**: secondary text and neutral labels.
- Derived blue/grey variations include **`#335D78`** for small accent text, **`#EDF3F7`** for pale highlights, **`#E6EDF2`** for chrome, **`#D7E1E7`** for borders and **`#F4F6F8`** for the background; cards remain white.
- Existing warning colours are preserved: **`#FFF5DF`** background, **`#865B14`** warning text and **`#C59339`** accent.

Active boards were visually checked; file validation, board bounds, text-fit checks and footer-button overlap checks passed. All screens remain static concepts with illustrative names/counts, not live Revit data or implemented functionality. Implementation must translate the reviewed native Penpot shapes into WPF/XAML and wire the behaviour; there is no one-click functional import.

## Behaviour & Guardrails
- Read/preview/draft editing runs with **no transaction**. Each definition Save is one short Undo-friendly transaction. Applying selected filters to the single target is a separate short Undo-friendly transaction.
- Resolve and validate exactly one target before applying. Do not auto-expand it into other views/templates, auto-assign a template, or route writes to a template without explicit user choice.
- Skip (and report) rather than fail:
  - filter already on target (`GetFilters()` check)
  - target doesn't allow overrides (`AreGraphicsOverridesAllowed()`)
  - target view's template controls Filters → warn, offer "apply to template instead"
- Document checks: require an active project document. A non-eligible current view disables only that target mode; browsing, creation, and applying to one eligible template remain available.
- Empty states: no filters in project → show an empty state with **New Filter** available; search with no matches → empty list message.
- Disable creation/edit/apply writes in a read-only document, with a clear explanation.
- Disable rename writes in a read-only document; duplicate analysis and rename previews remain read-only.
- Disable deletion writes in a read-only document. Select Unused remains read-only; used-filter deletion requires explicit impact acknowledgement and atomic failure handling.
- Do not overwrite existing filter overrides, visibility, enable state, or priority when applying. Do not copy graphical settings from an arbitrary source view.
- Result summary after Apply: identify the target and show added / skipped / failed filters with reasons. Explain that this step only adds attachments; configure graphics on the target before using the separate copy tool.

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
3. Canonical definition signatures: validate conservative duplicate comparison, then wire the project scan and draft warnings to the same index.
4. Manager dialog: search, filter selection, description, single-target resolution, application, duplicate analysis and rename actions. Translate the reviewed Penpot v2 concept into WPF and wire the revised workflow.
5. Editor dialog: name/categories, typed parameter/operator/value rows, AND/OR groups, draft validation and duplicate warnings, adapting ReValue's proven presentation pattern.
6. Naming-pattern renderer and rename preview: explicit acceptance, full-rule rendering, name/conflict validation and atomic manual/bulk rename.
7. Write adapter: validated model → native Revit rules; implement atomic creation and in-place editing.
8. Execution-test creation/editing/renaming with rollback first, then verify committed persistence and Undo in a disposable test model before release.
9. Regression-check ReValue/ExcelLink/Type Renamer if any common presentation/model logic is extracted.
10. Add the explicit filter-renaming ReValue entry point, native matching collection/scope dialog, confirmed Revit selection action and filter-renaming modal handoff/return flow; regression-test normal ReValue launches.
11. Wire Select Unused to the refreshed full-project usage index and Unselect All to the complete manager checked set, then implement approved-row deletion review, used-filter impact acknowledgement, atomic deletion, result refresh and committed/Undo verification in a disposable Revit 2023 model.

## Acceptance Tests

- Browse, search, describe, and apply to eligible plan/section/3D/drafting views and templates; exclude schedules and other unsupported targets.
- Resize the manager and detailed dialogs from their usable minimum size to a larger window across supported display sizes/DPI settings. Content expands/reflows or scrolls without clipping actions, warnings, names, operands or rule groups; windows open within the available monitor work area.
- Narrow and move the Edit Filter dialog to expose drawing area without losing the draft, categories or focus. Inline changes/usage and detailed duplicate confirmation remain usable with long rules and many consumers; small acknowledgement-only dialogs remain fixed-size.
- Normal edits follow 01 → 03 → 01: Save validates and updates the existing shared definition without page 06 or separate shared-impact acknowledgement. Duplicate edits follow 01 → 03 → 11 → 01 and require intentional-duplicate confirmation; self is excluded and matches/context are rechecked before committing.
- Normal creation follows 01 → 02 → 01, without an intermediate review/confirmation/success dialog. Only duplicate drafts follow 01 → 02 → 11 → 01; creation is atomic, matches/name validity are rechecked and duplicate Back to Editor/close preserves the draft. Neither path automatically applies the filter or opens application review/results.
- Duplicate Back to Editor/close preserves the draft. Use Existing explicitly discards the draft and focuses a match without saving, merging, deleting or transferring attachments. Validation/stale-context/write failures preserve drafts and report the error; successful Save refreshes the manager. Draft previews are not live graphics; verify redraw/effective display after Save and normal Revit interaction after closing the manager.
- Apply one or several selected filters to exactly one target using each of the three modes. Do not expose arbitrary-view selection or multi-template selection.
- Selecting a template does not assign it to the current view. Template application confirms dependent-view impact without explicitly adding filters to those dependent views.
- Application review/results identify the single target, preserve existing overrides, and hand off graphics configuration/copying without changing other targets.
- Duplicate application is skipped and reported; existing overrides/visibility/order remain unchanged.
- Duplicate analysis detects equal category/rule definitions with different names and reordered categories/AND-or-OR siblings, regardless of browser selection/search.
- Different categories, parameters with the same display name but different identities, typed operands, AND versus OR, inversions or double tolerances are not reported as identical.
- Unsupported rules are reported as uncomparable, not ignored. Matching current element sets alone does not establish a duplicate.
- New/edit drafts list every matching existing filter, exclude self, and recheck before Save. Saving an intentional duplicate requires confirmation; reusing a match is an explicit separate choice.
- Duplicate analysis performs no writes and does not merge/delete filters or move attachments.
- Select Unused checks exactly the definitions with no view/template attachments across the full project, clears list restrictions and replaces prior manager checks. Templates assigned to no views and hidden/disabled attachments still count as usage.
- Select Unused does not change Revit selection, write model data or start deletion. Users can inspect and uncheck results before Delete Selected. No unused definitions clears manager checks; incomplete usage scans preserve the prior checks and report the error without guessing.
- Unselect All clears every manager check, including hidden rows, reports zero selected and disables selected-set actions. Search, list restrictions, focused description, application target and Revit selection remain unchanged; read-only documents also support the action.
- Delete Selected previews names/ids and full usage for precisely the approved rows. Used-filter deletion is allowed only with explicit impact acknowledgement; changed usage or approved rows requires renewed review/confirmation.
- Cancel and empty/read-only selection do not delete. Worksharing failures or unexpected dependent deletions roll back all approved deletions, with no unrelated or partial changes.
- Successful deletion removes only approved definitions and their attachments/effects; matching model elements survive. Undo restores definitions, attachment graphics/settings and expected inherited effects. Browser selections, usage, duplicate analysis and matching previews refresh without stale ids.
- Manual and pattern-based renaming work for one or several selected filters. Preview changes, unknown tokens, invalid names, existing-name collisions and intra-preview collisions are surfaced before writes.
- Generated names preserve complete logical grouping, level operator labels, readable units/reference values, and no-value rules. Invalid/overlong/unsupported output cannot silently become a partial name.
- Rename only approved rows and preserve definitions/ids/attachments/overrides. Cancel and pattern edits do not rename; later rule edits do not silently change names. Failed rename operations leave no partial changes, and Undo restores prior names.
- Right-click selection is explicit. ReValue filter renaming works despite previously saved type/parameter settings, never redirects to type/parameter writes, and refreshes the manager on return.
- Filter-renaming ReValue launch/cancel makes no changes or selection substitutions; normal ribbon selection/mode behaviour remains unchanged. Both dialogs have valid API context with no open transaction spanning the handoff.
- Select Matching Elements covers current-view/project and ANY/ALL combinations, includes complete native categories/conditions, deduplicates non-type elements and handles no matches or stale filters explicitly. Only confirmation replaces selection; cancel/no matches/errors preserve it.
- The manager is modal and closes after confirmed selection. Elements remain selected when the user launches ReValue normally; there is no direct matching-elements ReValue shortcut or automatic manager reopening.
- Revit selection contains unique matching non-type elements, not filter definitions/types. No model edits, transactions, automatic view changes, unhiding or reopening a modal manager block subsequent user interaction.
- Template-controlled Filters are detected, template impact is confirmed, and effective display is verified rather than inferred from API success.
- A project with no filters can create its first filter.
- Create string, integer, double-with-units/tolerance, Yes/No, and element-reference rules where applicable, plus nested AND/OR and inverse conditions.
- Verify exact operator labels/order and value controls against native Revit 2023 dialogs for each capability family and parameter-specific exception; factory acceptance alone is not sufficient.
- Verify text ordering, numeric units/tolerance, enumeration and Yes/No restrictions, reference handling, and no-operand presence rules. Switching a parameter must not retain an invalid operator/value.
- Include the mismatched string-rule negative controls so accepted-but-meaningless API rules cannot enter the authoring UI.
- Save, close, reopen, and compare the native definition; a no-change edit must preserve semantics, identity, and attachments.
- Editing an existing filter reports its usage and updates all expected consumers; it does not detach/recreate the filter.
- Invalid names, duplicate names, inapplicable parameters/categories, invalid operands, read-only state, and ownership failures produce actionable errors with no partial changes.
- Category changes flag incompatible existing rules rather than deleting them.
- Existing complex/category-specific rules are either faithfully editable or explicitly inspection-only.
- Blank/no-value conditions, category-only definitions, unsupported operators, and NOT transformations cannot silently broaden the filter.
- Cancel makes no changes. Undo restores the previous definition/application state. Browsing starts no transaction.
