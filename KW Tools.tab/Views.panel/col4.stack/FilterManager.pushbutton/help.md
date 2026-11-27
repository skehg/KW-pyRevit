# Filter Manager - BETA

**KW Tools > Views > Filter Manager** requires an open project, Revit 2023 minimum and IronPython 2.7. It is one persistent, movable, resizable modal WPF workspace, not a modeless/live-preview editor.

## Sources and destinations

- **Current View / Template** reads the current view's template only when that template controls Filters. Otherwise it reads the view. The actual origin is shown. Unsupported current views remain explicitly unavailable.
- **Browser View / Template** uses view/template selections captured before the dialog opens. Shared effective template sources are deduplicated.
- **Selected Views / Templates** opens a searchable multi-picker. **All Project Filters** lists shared definitions without inventing attachment settings for them.
- Source and target selections are independent. Targets are **View**, **Template**, **Browser** or **Project**. Project loads the full name/type catalogue on demand. Checking a template explicitly changes that template and affects its dependent views; checking a template-controlled view does not silently redirect to its template.
- Search by filter Name, Category, Rule or All, with category/project-unused restrictions. Target search supports names, Views/Templates/Both and view type. Search changes preserve checked rows, including hidden rows.
- Highlighting inspects; checking defines an action's scope. Ctrl/Shift ranges and group checkbox changes keep those concepts separate. Counts include hidden selections.
- **Clear filters** clears filter checks. **Clear targets** clears all destination checks and returns to Project. **Clear Selection** clears action-selection/approval checkboxes across the workspace, not graphics values or copy-channel choices. Reset search clears restrictions, not selections.

## Graphics and application

- The centre tabs are **Graphics / Edit Rules / Rename**. Switching tabs does not apply or discard drafts.
- The compact grid loads the checked targets' current values on demand. Common values display normally; differences show **Mixed**, and genuine missing overrides show **Unset**. Loaded/displayed values alone never request writes.
- Source selection browses filters only. Click **Load from source** to fill the same proposed-value grid with a chosen view/template's settings, including its unsets. **Graphics** and **Visibility** default checked for valid sources and configure the next load only; toggling them does not change existing drafts. All Project Filters disables loading because it has no source attachment.
- Loaded source values and custom edits remain drafts until Apply. Differing source variants require one chosen attachment per filter; there is no automatic first-source choice or field-by-field merge. Loading affects only current checked pairs, not future selections.
- Graphics supports filter visibility, halftone, projection/cut line colour, weight and pattern, surface/cut foreground/background fill patterns, colours and visibility, and transparency. Colours use visual swatches/native Revit colour selection. Line patterns come from document LinePatternElements, not named Line Styles; fills are drafting patterns, including the actual solid fill.
- **Per Filter** uses Previous/Next over the stable checked-filter set, including hidden checks. **Together** applies only fields explicitly edited in that mode to the current checked filter/target pairs; toggling modes or checking new targets does not replay earlier edits. Choose destinations before editing custom values; unchecked pairs retain inactive drafts.
- Leave a cell untouched to retain each target's setting. Change a value to request that value; click its small **×** to remove the override on Apply. The cell immediately displays Unset, without the previous colour/pattern. Crosses appear only where genuine native reset values exist; Off and 0% are explicit values, not Unset.
- There are no Keep buttons. Right-click **Revert this edit** to remove that field's source-loaded/custom contribution and restore the original target value. Changed cells are highlighted and routine edits retain scroll position. Solid line, solid fill and Unset are distinct.
- New attachments are always enabled, even when their source is disabled. Existing attachments retain their enabled state. Source visibility Off is a separate supported choice; enabled state is read-only.
- Applying blank All Project drafts adds missing attachments with Revit defaults and preserves existing settings. Existing filter order is preserved; additions append.
- **Apply** commits ready additions immediately and approved existing-setting changes. It never forces a review visit for additions. An operation scoped only to the current Revit view approves its existing-update rows automatically. Multi-view/template operations require individual approval or **Approve All Updates**; pending updates receive a prominent review action and **Changes** notice instead of a traceback. **Changes** is an optional before/after drawer, not a wizard step.
- **Apply and Close** runs that same attachment/graphics action, then closes only if no unapplied drafts remain. It does not save rules, rename proposals or new definitions; save those explicitly. Invalid, unapproved and inactive drafts keep the workspace open. The dynamic Add/Apply label remains, with fixed-size footer buttons.
- Successful/unchanged work-list entries leave the queue after native readback. Unapproved/unresolved entries remain, with an inline summary. Retained checks do not requeue completed additions without a new requested change.
- A newly added filter can be inspected and its actual graphics edited without closing the workspace. Drafting never changes the drawing.

## Definitions and rules

- **New Filter** and **Duplicate Filter** create inline independent drafts. Duplicate copies one focused definition's categories/rules, not its attachments/graphics, and never edits the original. Cancel creates nothing.
- **Edit Rules** retains independent category/rule drafts per checked filter. Previous/Next shares Graphics' checked-filter navigator. **Save Rule Changes** saves only the displayed definition, affecting every project-wide consumer; it is independent of attachment Apply.
- Categories determine the eligible parameter intersection. Supported text, numeric/integer, Yes/No, level/phase/material operands have typed controls. Nested AND/OR groups and untouched native operands/tolerances are preserved.
- Equals/Not Equals offers lazily collected assigned-value suggestions. Choose one or enter custom text; suggestions are not a validity restriction. Numeric labels use project units while selected suggestions retain exact stored values. Double tolerances are in internal units.
- Identical definitions require explicit inline acknowledgement or **Use Existing**. Unsupported native structures remain inspection-only rather than being approximated.
- **Analyse Duplicates** compares complete supported categories/parameter identities/typed operands/logic across the project. Names, graphics and current matching elements do not define duplicates. It never merges or deletes automatically.

## Rename and ReValue

- Rename is a grid. Proposed Name starts exactly at the current name; edit directly or optionally generate `{categories}` / `{rules}` names.
- **Rename** processes valid changed rows atomically. Successful and unchanged rows leave the grid. Clashes/invalid proposals remain for correction and retry, without an approval checkbox. An unresolved row cannot falsely vacate its current name for another proposal. Swaps are supported when the final namespace is valid.
- Unexpected stale/ownership/write/readback failures roll back the attempted subset and retain proposals. Each successful retry has its own Undo operation.
- **Edit in ReValue** starts from the remaining grid's proposed text. Find/replace, tokens, rearrangement, prefixes/suffixes and case return proposals only. **Use Proposals** does not rename the model; cancel leaves the grid unchanged. Ordinary ReValue settings and Revit selection are preserved.
- Unknown/malformed naming tokens, invalid characters and names over the conservative 255-character BETA limit are explicit errors. Nothing is silently truncated.

## Deletion, purge and selection

- **Delete Selected** reviews exact definitions and project-wide usage inline. Deleting a used definition removes all its attachments/graphics, not matching model elements; used impact requires acknowledgement.
- **Purge Unused** reviews definitions with zero attachments anywhere, including unassigned templates and hidden/disabled attachments. It rechecks exact identities and usage before deletion. Project-unused browsing is non-destructive.
- Unexpected dependent deletions or failed native readback roll back the whole operation.
- **Select Matching Elements in Revit** explicitly evaluates current-view/project matches using ANY/ALL selected definitions. A successful confirmed handoff closes the workspace and replaces selection. Cancel/no matches/errors leave selection unchanged.
- **Cancel** discards all unapplied drafts and closes without another prompt. Escape does the same from the main workspace; inside a management panel it returns to the workspace. During a read, Cancel/Escape only cancels the read. Discarding never undoes previously applied operations.
- The window's **X** warns only about actual unapplied drafts, including unchecked graphics and rename drafts. Selecting sources/filters/targets or reviewing attachment additions alone does not trigger a discard warning.

## Loading and safety

- Opening, searching or checking names does not preload every project's graphic overrides. Definitions/complete attachment usage, project search metadata, resources and actual graphics have separate caches.
- Project target metadata and line/fill resources load on demand. Graphics loads only for explicit attachment inspection, checked-source comparison or destination planning. Cached repeats reuse immutable snapshots; source/target identities and approvals are revalidated before writing.
- Multi-attachment reads use cancellable slices of at most five pairs with progress for longer loads. All API access stays on Revit's valid UI/API thread.
- Read-only projects allow inspection/previews but not writes. Every definition operation and each eligible attachment batch has an independent transaction/Undo boundary; native post-commit readback occurs before the transaction group is assimilated.
- Built-in metadata without representative project elements is not guessed. Unfamiliar/category-specific/inverted filter structures are inspection-only and excluded from complete duplicate comparisons.

## Naming settings (advanced)

`naming_settings.json` sits beside `script.py`. Its `operator_symbols` object changes only generated `{rules}` text, not summaries/search/native rules. Reopen or regenerate the preview after editing it as UTF-8.

| Key | Default | Key | Default |
|---|---|---|---|
| `Equals` | `=` | `NotEquals` | `≠` |
| `Greater` | `＞` | `GreaterOrEqual` | `≥` |
| `Less` | `＜` | `LessOrEqual` | `≤` |

Text/presence operators also have readable mappings. Remove a key to use readable wording; a missing file uses readable wording throughout. Unknown keys, empty/padded/non-text values and Revit-invalid name characters produce explicit generation errors, never guessed replacements. Existing proposals are not silently rewritten.

## Validation and BETA limits

`workspace_checks.run_close_actions(doc, uidoc)` is a Revit 2023-only, read-only WPF regression check for selection-only closing, Cancel/Escape, Apply and Close, inactive drafts, read cancellation and fixed footer geometry. Apply writes are replaced with controller receipt stubs; it does not verify native commits or Undo.

Native MCP acceptance modules in [tests](tests) require the intended IronPython engine. Mutation tests are only for explicitly approved sample projects and should be previewed with `run_modify(dry_run=True)`:

```python
import os
import sys
import filter_model
sys.path.insert(0, os.path.join(os.path.dirname(filter_model.__file__), 'tests'))
import definition_workflow_checks
result = definition_workflow_checks.run(doc, uidoc)
```

`run_readonly` checks rename vacancies and duplicate drafts without mutation. The definition preview passed four native groups in Revit 2023 and 2025, including partial swaps/retry, post-commit verification rollback and exact unused purge. All 173 offline ReValue tests passed, including 16 filter-name tests for legacy compatibility and draft-return/cancel/failure behaviour.

Final native read-only checks passed 20 graphics, 19 WPF/controller and three ReValue groups in each of Revit 2023/2025. Eight native graphics mutation-preview groups per version and user-approved commit/fresh-readback checks passed. The user reported no Undo options after the MCP persistence test; Undo is not verified. All temporary fixture elements were removed through separately approved exact cleanup and baseline view/filter counts restored. No files were saved.

In an attended actual-ribbon check, the user confirmed the workspace opens, native colour-picker Cancel returns correctly, and Undo works after a direct UI operation. That does not establish Undo availability for MCP-driven runs. The reported colour Clear feedback and graphics scroll-retention defects were fixed; three focused actual-WPF groups passed in Revit 2025 without model changes. The user deferred further live/full-suite and attended retesting; see [WORKFLOW.md](WORKFLOW.md) for details.

The compact-grid revision supersedes those earlier graphics controls. Revit 2023-only checks passed eight user-approved native rollback groups (`68f54726617c`), including exact scoped loads, native clears, approvals and failure rollback. Follow-up run `c23c0b0b6117` passed 59 read-only groups: three checkbox-event, three token-lifecycle, eleven compact-grid, nineteen preserved workspace and twenty-three graphics backend groups. The initial Per Filter and **Select controlling template** refresh paths were fixed; four selection-event groups then passed (`fe2b4dc738bb`), and the user confirmed immediate editing in the actual ribbon window. Independent targeted review found no remaining high-confidence issues after fixing source-token retention. Full visual, keyboard/DPI and attended picker checks remain not run for this revision. Revit 2025 was not used. Penpot's single Current UI page is updated and validates without errors; image export failed, so rendered-image review is not claimed.

Historical single-target BETA checks ran in Revit 2023/2026; those are not certification of the new workspace. See [WORKFLOW.md](WORKFLOW.md) for detailed evidence and outstanding acceptance checks. Representative large-project timings, full modal handoffs/colour-picker OK/ownership, manual monitor/DPI review and saved-file reopen require separate verification; static design or service tests do not establish them.

See [SCOPE.md](SCOPE.md) for the full requirements and design history.
