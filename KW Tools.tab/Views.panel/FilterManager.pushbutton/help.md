# Filter Manager - BETA

**KW Tools > Views > Filter Manager** requires an open project in Revit 2023 or newer. The dialogs are modal, movable and resizable; this is not a modeless/live-preview editor.

## Working with filters

- Search names, categories and rule parameters. Filter by category or direct application to the current view. Click a filter's name or row to focus its rule tree and project-wide usage without changing the checked set. **Ctrl-click** adds/removes highlighted rows; **Shift-click** selects a contiguous range; **Ctrl+Shift-click** adds a range to the highlights.
- Click a checkbox in the highlighted group to check or uncheck the whole highlighted group, following the clicked box's new state. Clicking an unhighlighted checkbox affects only that filter. Highlighting is separate from checking: Apply/Rename/Delete still act only on checked filters. The manager shows both counts.
- **New Filter / Edit Filter:** choose categories first, then typed rules and nested AND/OR groups. Only parameters eligible for the entire category selection are offered for new rules. Presence conditions hide the operand control.
- **Equals / Not Equals:** recognised text, integer and numeric parameters offer editable autofill/dropdown suggestions from values assigned to instances and types in the selected categories. Suggestions are collected lazily and cached until refresh, use exact parameter IDs, and retain distinct stored values. Choose one or enter any custom value; suggestions do not constrain valid rules. Numeric labels use project units, but selecting a suggestion retains the exact stored number. Reference and Yes/No parameters keep their existing typed pickers.
- Saving creates/updates the native definition and returns directly to the manager. Applied definitions keep their identity and graphics; edits affect every consumer. Drafts never change the drawing.
- Identical definitions alone open **Confirm Duplicate Definition**. Explicitly acknowledge intentional duplicates, return to the draft, or **Use Existing** to discard the draft and focus a match without applying/merging it.
- **Review & Apply** adds selected filters to exactly one current view or template. Choose an eligible template in the searchable, single-selection picker. Template-controlled/unsupported current-view targets are blocked. Existing attachments, order, visibility, enable state and overrides are preserved.
- Selecting **One selected view template** opens the **Select View Template** dialog, not a template dropdown. Search names, optionally filter by view type, inspect the compatible template list and dependent-view impact, then **Use This Template**. The chosen name appears in the manager; **Choose Template...** reopens the picker. Cancel preserves the previously chosen template and never assigns a template to a view.
- Successful application (including already-applied skips) returns directly to the refreshed manager with an inline added/skipped summary, without an Application Results dialog. The application review remains; errors still display an explicit reason and roll back the batch.
- Configure graphics in Revit afterward. There is no multi-view application or graphics-copy operation.

## Management and selection

- **Analyse Duplicates** scans the entire project and groups identical categories, parameter identities, typed operands and complete supported logic. Names/graphics/current element matches do not determine duplicates. Unsupported definitions are reported separately.
- **Rename Selected** previews a naming pattern and permits manual corrections/row approval. Tokens are `{categories}` and `{rules}`; unknown/malformed tokens and colliding/invalid names block saving. The saved default is `{categories} - {rules}`: the illustrative `|` separator is not a valid Revit name character. BETA names have a conservative 255-character limit; shorten lengthy proposals explicitly.
- Generated rule names omit redundant outer/single-rule/same-operator parentheses, retaining brackets needed to distinguish mixed AND/OR groups and any parentheses in literal values. Category-only naming uses `Category-only - no additional conditions` rather than introducing Revit's invalid `:` character.
- Validation is specific to each approved row: valid proposals remain **Ready** even when another row fails. Invalid-character warnings identify the character; overlong proposals show their actual length and the 255-character limit. Both participants in a proposed-name collision are flagged. Correct or unapprove offending rows to enable **Rename Approved**; nothing is automatically truncated or renamed.
- Operator text in the `{rules}` naming token comes from the bundle-local, hidden settings file `naming_settings.json` (see [Naming settings](#naming-settings-advanced)). By default, generated names use `Comments = Alpha` and `Comments ≠ Alpha`, while the manager summary and search still show `Comments equals Alpha`.
- **Select Unused** replaces the manager checks with definitions attached to no view or template, including templates assigned to zero views. It reveals those results but never deletes them.
- **Unselect All** clears every manager check, including hidden rows, without changing search, focus, row highlights, target or Revit selection.
- **Delete Selected** requires approved rows and used-filter impact acknowledgement. Deleting a used definition removes its attachments/graphics everywhere, not matching model elements. Any unexpected dependent deletion rolls back the entire batch.
- Right-click a checked row to act on the checked set. Right-click an unchecked row to explicitly make that row the sole context-action selection.
  - **Rename Filters with ReValue** closes the manager, opens a restricted filter-own-Name preview, then returns with the manager state preserved. Ordinary ReValue type/parameter settings and Revit selection are unchanged.
  - **Select Matching Elements in Revit** supports current view/project and ANY/ALL selected definitions. Refresh the native match count, then confirm selection replacement. Confirmation closes the manager; no matches/cancel/errors preserve selection. Use ReValue normally afterward if desired.

## BETA boundaries

- Text, numeric/integer, Yes/No and recognised level/phase/material operands have typed controls. Numbers use project display units and native parsing; double tolerances are explicitly in internal units. Untouched native operands/tolerances retain full precision.
- Built-in parameter metadata can be unavailable in projects without representative elements/types. Enumeration mappings and unfamiliar reference kinds are not guessed. Existing supported native rules are retained; new unknown operands are blocked. Applicable presence-only rules still require native validation.
- Category-specific/unfamiliar/inverted filter groups are inspection-only and excluded from complete duplicate comparisons. They may still be applied, renamed, deleted or used for native matching; their definitions are never approximated.
- Work writes are atomic and Undo-grouped. Read-only projects permit inspection/previews/matching but disable manager writes. Recheck stale definitions, usage and duplicate acknowledgements before committing.
- Tested inside Revit **2023 and 2026**, both on IronPython 2.7. Middle versions are compatibility targets, not executed certifications. Full native-menu parity, saved-file reopening and hands-on visual/DPI testing remain outstanding.

## Naming settings (advanced)

`naming_settings.json` sits beside `script.py` and is not exposed in the UI. Its `operator_symbols` object maps operator keys to the text used **only** in the `{rules}` naming token. Summaries, search, duplicate signatures and native rules are unaffected. Edit the file as UTF-8, then use **Update Preview** or reopen Rename; no pyRevit reload is needed.

| Key | Default | Key | Default |
|---|---|---|---|
| `Equals` | `=` | `NotEquals` | `≠` |
| `Greater` | `＞` (fullwidth) | `GreaterOrEqual` | `≥` |
| `Less` | `＜` (fullwidth) | `LessOrEqual` | `≤` |

The text operators (`Contains`, `NotContains`, `BeginsWith`, `NotBeginsWith`, `EndsWith`, `NotEndsWith`) and presence operators (`HasValue`, `HasNoValue`) are listed with their readable wording, so they can be changed too. Level rules use the same keys. A native inverted rule without a dedicated key renders as `NOT ` plus the base operator's text.

- Remove a key to use the readable wording for that operator. If the file is missing, all naming uses readable wording.
- Top-level keys beginning with `_` are notes. Any other unknown top-level or operator key, empty, padded or non-text value, or character that Revit `NamingUtils.IsValidName` rejects makes the whole file invalid. Nothing is skipped or guessed.
- When the file is invalid, Rename shows one dialog-level error with the file path and problem list, leaves proposals unchanged and disables **Rename Approved** until the file is fixed.
- Revit 2023 and 2026 both reject ASCII `<`, `>`, `<=`, `>=` and `~`. They accept `=`, `≠`, `≥`, `≤` and fullwidth `＞`/`＜`.

## Validation

The MCP acceptance modules in [tests](tests) are for disposable projects only:

```python
# Run with MCP run_modify(dry_run=True), workspace set to this bundle.
import os
import sys
import filter_model
sys.path.insert(0, os.path.join(os.path.dirname(filter_model.__file__), 'tests'))
import revit_checks, ui_checks, revalue_checks
result = {
    'native': revit_checks.run(doc, uidoc),
    'ui': ui_checks.run(doc, uidoc),
    'revalue': revalue_checks.run(doc, uidoc, uiapp),
}
```

Tests create disposable definitions, a wall and a template; keep `dry_run=True`. They exercise 26 grouped assertions per version (15 native, 7 WPF/controller, 4 ReValue). Committed persistence and genuine single-step Undo were additionally verified in both versions. No test definitions remain. Ribbon registration, visible title and enabled state were verified after reloading pyRevit in both versions.

The follow-up `improvement_checks.run(doc, uidoc)` suite adds 7 focused checks for independent row/checkbox selection, success-only application flow, assigned-value suggestions, exact numeric operands and cache refresh. It and the 7 existing WPF checks passed in both Revit 2023 and 2026 with all test changes rolled back.

The read-only `selection_template_checks.run(doc, uidoc)` suite checks Ctrl/Shift range highlights, group checkbox toggling, highlighted-state retention, the searchable Penpot page 04 picker, its confirm/cancel target handoff and usable minimum layout. It passed 6 grouped checks in each version without model writes.

The read-only `rename_checks.run(doc)` suite passed 9 grouped checks in Revit 2023 and 2026 for unambiguous bracket rendering, valid category-only tokens, row-specific errors, length/character feedback, collisions/swaps, manual correction of a single failed preview, naming-only operator symbols, settings fallback/rejection and dialog-level settings errors. The write-time validator uses the same per-name checks as the dialog.

See [SCOPE.md](SCOPE.md) for the complete scope and design history.
