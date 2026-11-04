# Filter Manager — Tool Scope (BETA)

## Full-workflow revision (2026-11-05)

**Design scope, not implemented functionality.** This revision makes Filter Manager an end-to-end workspace for definitions, attachments and graphics across multiple views/templates. It supersedes the 2026-10-31 single-target/separate-copy-tool boundary. Runtime scripts, bundle behaviour and existing tests are unchanged by this design update; [help.md](help.md) continues to describe the shipped BETA.

Deliverables:
- This scope: requirements, interaction rules, safeguards, implementation sequence and acceptance criteria.
- [WORKFLOW.md](WORKFLOW.md): Mermaid user-task graph, thirteen task paths, Clear Selection and interaction-efficiency targets.
- A single **Current UI** page in the existing Penpot **Filter Manager** file. At the user's request, superseded pages/boards were removed after saving **Before cleanup · preserve superseded designs · 2026-11-05**; history is recoverable through saved versions, not additional pages. The [design handoff](WORKFLOW.md#penpot-handoff) records current identifiers and verification limits.

The design retains the selected **IronPython 2.7 / WPF** architecture and Revit **2023 minimum**. It does not expand engine/version support or certify new API behaviour. New graphics/batch/browser-selection behaviour requires release-specific verification before implementation is accepted.

Approved product decisions:
- One persistent, resizable dialogue; **not a wizard**. Switch tasks without losing valid selections, searches or attachment drafts.
- Centre tabs are **Graphics / Edit Rules / Rename**. Copy is an explicit **Include source graphic overrides** option, not a separate tab. Graphics and Edit Rules share checked-filter navigation; Rename uses a grid without arrows or approval checkboxes.
- Rename proposals start from current names. Keep direct editing, optional rule-based generation and the ReValue draft handoff. **Rename** processes valid changed rows; successful/unchanged rows leave the grid and only unresolved rows remain for correction and retry, with exact inline counts.
- Apply/configure selected filters on multiple explicitly selected views and templates.
- Browse filters from one/many source views/templates; copy one resolved attachment setting per filter to multiple explicit targets within the same project. Never merge differing source graphics automatically.
- All Project Filters starts with empty graphic drafts: adding with no overrides uses native defaults; existing target overrides stay unchanged unless explicitly edited or cleared.
- Show **Include source graphic overrides** and **Include source visibility** as adjacent independent checkboxes, both checked by default for valid attachment sources; no source Options menu or enabled-state choice. All Project Filters has neither source channel available. Every new attachment is enabled, even if its source is disabled. Existing attachments retain their enabled state, including disabled ones.
- **Duplicate Filter** starts an independent new-definition draft from one focused filter, for editing before creation. It is separate from **Analyse Duplicates** and attachment-graphics Copy.
- Replace the old **Select Unused** management action with **Purge Unused**: review project-wide unused definitions inline, then explicitly delete the approved unused set. Keep Project-unused as a non-destructive library scope for finding filters to apply.
- Provide one-click **Clear Selection** across all selection/approval checkboxes, including hidden rows, plus local **Clear filters** / **Clear targets** controls. Do not treat graphics values or copy-channel choices as selection checkboxes.
- Preserve existing target settings by default. Existing-setting changes require individual approval or **Approve All Updates** for the current reviewed proposal.
- Apply ready new attachments directly without requiring review or approval first. Retain proposed changes to pre-existing attachments for approval, like Rename retains correction rows; those pending updates do not hold up ready additions. Existing attachments with no requested difference are unchanged and need no approval.
- Flag template-controlled views and offer their controlling templates as **explicit selectable targets**. Never silently redirect, assign templates or expand the write set.
- Search filters, views, templates and copy sources. Accept multiple views selected in Revit's Project Browser before launch.
- Use inline review, validation and impact details rather than repetitive confirmation/success dialogues. Reserve explicit acknowledgement for meaningful destructive/shared-impact decisions.

## Status
**Implemented BETA: Filter Manager, Revit 2023 minimum, IronPython 2.7.**

The command now lives in `FilterManager.pushbutton` on the Views panel. The implementation uses the reviewed Penpot palette and flat button states in modal, resizable WPF dialogs. New/Edit saves return directly to the manager; only identical definitions open the duplicate confirmation. It currently applies attachments to one target and does not edit/copy attachment graphics. The sections below distinguish that baseline from the proposed full workflow.

Implementation validation (2026-11-01), using the Revit 2023 and 2026 MCP connections:
- Each version passed 15 native-operation acceptance checks, 7 WPF/controller checks and 4 real ReValue-window/callback checks. The native tests cover typed rules, category-only/nested definitions, duplicates, in-place edits, attachment preservation, renaming, matching, used deletion and atomic failure rollback.
- WPF dialogs were instantiated in both IronPython 2.7 runtimes and measured at their minima. The manager keeps its list usable by collapsing management/target sections at compact sizes; editors wrap rule controls and scroll long drafts. Operator/tolerance-only edits preserve exact double operands instead of reparsing rounded display values.
- Committed create/edit/rename/application smoke tests were read back in fresh runs. The user then performed one genuine Revit Undo in each version; MCP confirmed removal of the test definition/attachment and restoration of the original filter counts.
- The existing ReValue regression suite passed all 168 tests. Its new name-only entry preserves ordinary settings and Revit selection.
- Reloaded pyRevit in both versions and verified the visible, enabled **Filter Manager** ribbon button on **KW Tools > Views**, with its BETA tooltip and the new bundle's registered script path.
- Test changes were rolled back or undone; no test definitions remain. Revit 2024/2025 have not been execution-tested. Intermediate/future compatibility relies on the shared 2023+ API surface, not a claim of certification.
- Exact native dropdown parity for every parameter, complex/category-specific definition editing, saved-file reopen and manual visual checks across monitor/DPI configurations remain BETA acceptance work. Unsupported native structures are inspection-only; unresolved operand metadata is never guessed.

### Performance follow-up (2026-11-02)

- Manager browsing and rename previews no longer build every eligible parameter or sample every selected category. Resolve metadata only for actual double rules, preserving project-unit formatting; cache representative numeric specimens, parameter labels and editor eligibility until refresh.
- Search uses cached rule text and reuses row controls while preserving independent checks/highlights. Build inherited usage through a per-template index instead of a filter-by-view nested scan.
- Cancel from New/Edit/Rename does not refresh definitions or usage. Successful results still refresh; rename previews use a name snapshot while commits revalidate live names.
- Revit 2023 / IronPython 2.7 validation used 165 filters and 171 views. Representative measured search changed from approximately 452 ms to 57 ms and summary rendering from 199 ms to 3 ms. Timings are diagnostic measurements, not guaranteed limits.
- Seven new read-only performance checks, six existing selection/template checks and nine rename/settings checks passed. The 15 native-operation, seven WPF/controller and seven suggestion/application checks also passed in a dry run with every model fixture rolled back. No 2025/2026 MCP connection was used for this follow-up.

### Search-scope follow-up (2026-11-02)

- Add a dropdown beside manager Search: Name (default), Category, Rule and All. Rule includes readable parameter names, operators and operands. Match case-insensitively against cached field text, without additional Revit collection.
- Changing scope retains the query and checked filters; category/current-view constraints remain independent. Preserve scope in the manager state used for the ReValue handoff; newly opened sessions default to Name.
- Nine performance/search checks and six selection/template checks passed read-only in Revit 2023 / IronPython 2.7, including all scopes, state restoration, cached row reuse and search-control widths at the manager's minimum size.

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

## Purpose and task coverage

Complete the following work without leaving the main Filter Manager dialogue:

1. Review filters in the current view and its assigned template, distinguishing their source.
2. Select project-unused definitions and attach them to the current view or its explicitly selected template.
3. Add selected definitions to many views/templates, with optional graphics.
4. Create new rule-based definitions and retain the current target context.
5. Edit existing definitions in place, showing their project-wide impact.
6. Rename one/many definitions manually, by naming pattern, or through the existing optional ReValue handoff.
7. Delete explicitly approved definitions, unused or used, with full impact.
8. Analyse duplicates, inspect differences in usage/graphics and explicitly keep, reuse, rename or delete selected definitions.
9. Review attachment graphics across views/templates, including inherited and mixed values.
10. Apply chosen graphic overrides and visibility to selected attachments; enable every new attachment and preserve existing enabled states.
11. Copy selected attachment settings from one resolved source per filter to multiple targets, resolving multi-source variants inline.
12. Duplicate an existing filter as the starting point for a new definition, then edit its name, categories and rules before creating it.
13. Purge explicitly approved definitions that are unused in every view and template in the active project.

Definition operations affect the shared project filter. Graphics, visibility and enabled state belong to each **view/template attachment**. The UI must keep these scopes visibly separate. Duplicate definitions may intentionally have different graphics; copying settings never creates a duplicate definition.

## Integrated workflow

1. Open in the middle-panel **Graphics** tab with the current view/template source context. Capture eligible Project Browser view selections before displaying the modal window, retaining the snapshot for independent source/target choices. Review definition/usage details alongside the focused filter without a separate Filters tab.
2. Choose the left source: **Current View / Template**, **Browser View / Template**, **Selected Views / Templates**, or **All Project Filters**. Search/check its combined filter list and the independent target list; focus inspects and checks determine batch scope. Selected sources use an on-demand searchable multi-picker.
3. Inspect/configure attachments in **Graphics**, edit definitions in **Edit Rules**, or edit current-name proposals in the **Rename** grid. Use **+ New / Duplicate Filter** for an independent new-definition draft.
4. To reuse attachment settings, explicitly check **Include source graphic overrides** and/or **Include source visibility** in the persistent attachment strip. Load only the requested source channels; Graphics resolves differing variants per filter or through a bulk preferred source. Identical settings need no conflict choice. Custom edits can refine the source-based proposal; enabled state is never copied.
5. Expand the persistent **Changes** drawer when needed. Additions are ready; modifications to existing settings default to unapproved. Approve individually or use **Approve All Updates**.
6. The contextual attachment action validates and atomically commits ready additions and approved updates: **Add Filters / Apply Graphic Changes / Apply Filters + Graphics**, or **Apply Filters + Visibility / Apply Visibility Changes** for visibility-only proposals. Adjacent counts disclose unapproved updates left unchanged. Stay in the workspace with refreshed attachment state; no normal confirmation/results modal.
7. Continue another task using the same searches, context and surviving checks. Close only when finished.

Changing workspace sections is navigation, not a series of steps. Ordinary definition Save, Rename and Delete are independent explicit commits with their own Undo actions, not secretly queued into attachment Apply. The footer and action labels must make this boundary unambiguous.

## Out of scope for this revision
- Cross-document copying, loading linked-project filter definitions or creating missing pattern resources
- Modeless/live Project Browser synchronisation and live drawing previews of unsaved drafts
- Saved graphics presets, filter-order editing, automatic priority reconciliation and multi-source conflict merging
- Automatically replacing all target attachments, removing unrelated target filters or reassigning templates
- Detaching filters from particular views/templates while retaining their project definitions; explicit definition deletion below is separate and affects every attachment
- Automatically merging duplicates, replacing their view attachments, or deleting duplicate definitions without explicit selection and confirmation
- Creating/editing selection-based filters (`SelectionFilterElement`); if surfaced in the browser, identify them separately as read-only
- ExcelLink-only conditions such as regular expressions and arbitrary wildcards
- Unrelated changes to ReValue or ExcelLink; the explicit ReValue integration described below is in scope

## Workspace design and navigation

### One shell, not a wizard

Use the existing resizable modal WPF shell, flat blue buttons, white cards and warning styling. Routine work stays inside it:

- **Left: filter source and library.** A source dropdown precedes the single search/options box; full source names/descriptions appear in the menu, with a compact current label in the closed control. Search options retain Name/Category/Rule/All, category and non-destructive Project-unused narrowing without duplicating source selection. + New / Actions manage definitions; Clear Selected Filters unticks visible/hidden library checks. Keep independent focus and action checkboxes, Ctrl/Shift ranges and explicit counts.
- **Centre: task surface.** **Graphics / Edit Rules / Rename** are tabs across the top of this panel, not workspace-wide navigation above the side panes. Graphics distinguishes source review from destination drafts and resolves source variants inline. Edit Rules shows categories, typed conditions and shared usage; Rename shows all checked definitions in a current/proposed-name grid. New/Duplicate Filter, Analyse Duplicates, Delete and Purge Unused use inline panels with a clear return control; Edit/Rename actions focus their corresponding tabs. Both side panes stay visible.
- **Duplicate Filter** acts on exactly one focused definition, not the checked batch; display the source name and preserve batch checks. Keep it visibly distinct from the project-wide **Analyse Duplicates** action. Include the same explicit-source action in the focused row's context menu.
- **Right: searchable target list.** One search box with an embedded options dropdown for Views / Templates / Both and view types. A heading-level source dropdown displays its current state as **View**, **Template**, **Browser** or **Project**, replacing the generic Actions label and separate shortcut buttons. The open menu retains full names: **Current View**, **Current View's Template**, **Browser Selected**, **Project Search**, **Clear Targets**. Each has a short description underneath; the active source has a checkmark. Keep selected/hidden counts and template impact. Focusing a target inspects it; checking it changes the proposed destination set. Neither writes to Revit.
- **Bottom: optional Changes drawer and sticky action strip.** Keep both include-source checkboxes, source provenance and attachment summary outside the central tabs. Display pending counts, unapproved updates, blocked rows and inherited-view impact. **Changes** optionally expands searchable per-target/per-filter before/after details and update approvals; opening it is never a prerequisite for applying ready additions. Remove the redundant **Review graphics** shortcut: the Graphics tab already opens that editor. Definition Save/Rename/Delete buttons remain in their task panel and are visibly distinct from the persistent attachment Apply.
- **Clear Selection** stays visible in the workspace header. It clears selection checkboxes across panes in one action, not just the visible search results; local Clear filters / Clear targets support narrower changes without resetting the other pane.
- Reuse a target's current graphics without copying by focusing its attachment. For multiple attachments show mixed values, not the first row's settings as if they were common.
- Source, review context and destination set are separate labelled states. Selecting a source does not replace targets; focusing a target does not silently select it. Template-origin graphics are inspectable even when the view is blocked for direct writes.

### Search and selection contract

- Every filter, view, template and source list supports case-insensitive search; no extra Search/OK click. The source mode is single-choice; Selected Views / Templates supports multiple checked sources with view/template, type and eligibility filters. Target choices are independent multi-selection.
- Search results update from cached metadata, not repeated model-wide evaluation. Preserve checks hidden by search; display total selected and hidden-selected counts with **Show selected**, local **Clear filters** / **Clear targets** and global **Clear Selection**.
- **Select visible** affects only the current result set. Do not overload it as an invisible whole-project Select All. Approve All Updates has a separate, explicitly counted approval scope.
- Record selections by document/element identity, not display name; duplicate view names and names shared between views/templates must remain distinguishable.
- Selected-target scopes filter the library only; changing a list/search does not erase graphics draft entries. Hidden checked rows remain part of the counted proposal. Explicitly unchecking a filter/target removes its pairs from the active write plan; retain their edited values only as inactive drafts, never as hidden writes.
- Reopening a management panel, resizing, changing focus or switching Graphics/Edit Rules/Rename preserves valid per-filter rule, name and attachment drafts, queries, checks and scroll/focus context. Navigation never saves or applies. One active attachment proposal at a time; incompatible source/mode changes offer explicit replace/discard/stay instead of merging silently.

### Filter sources and graphic variants

- **Current View / Template** resolves to the current view's template only when it controls Filters, otherwise to the view. Show the actual effective origin and whether a template was resolved; assignment alone is not inheritance. This is read-source resolution, never permission to redirect a destination write.
- **Browser View / Template** uses the pre-modal Browser snapshot. Resolve each selected view by the same control rule, retain explicitly selected templates as themselves and deduplicate effective origin ids. Views sharing one controlling template produce one source attachment, not repeated variants.
- **Selected Views / Templates** opens a searchable multi-picker inside/over the same workspace, with Views / Templates / Both, view types, checked/hidden counts and Use Sources / Cancel. Load project name/type metadata only when this picker is explicitly opened; reuse the dialogue cache if already available. Cancel keeps the previous source set, checks and drafts; incomplete loads are explicit and retryable.
- **All Project Filters** lists shared definitions, including unattached and project-unused filters. It has no implicit attachment source, so a fresh graphic draft is empty rather than borrowed from some consumer. Do not retain source-derived values as if they were global defaults after switching here; preserve pending work as a labelled draft or explicitly resolve incompatible proposal replacement.
- View/template source modes show the union of attached definitions once by filter id. Add source-count / graphic-variant badges where needed; expanding a filter reveals each exact variant and its source names/ids. A missing attachment is **Not attached**, never an all-default source variant.
- Graphics review shows common source fields normally and differing fields as **Mixed**, with origin labels. Destination settings and custom patch fields remain separately labelled; changing a field writes only an explicitly scoped destination draft, never the source automatically. Keep other per-source/per-target values untouched.
- Copy compares only the selected channels. Identical values across origins need no conflict decision; retain their provenance. Differing values require one chosen source variant for that filter, never the first attachment or a field-by-field merge. **Use this source for all checked filters** resolves available attachments in bulk; missing filters stay flagged for another source, not defaulted.
- All Project Filters can be applied with every graphics field empty. New attachments receive Revit defaults for untouched graphics/visibility and are always enabled. Existing attachments retain their settings, including enabled state; empty does not request Clear override. Custom values take effect only after explicit Apply; inspection/Cancel does not persist them.
- Copy has no attachment settings to copy while All Project Filters is the source. Keep that state honest: offer choosing a view/template source or Graphics / Apply with the empty/custom draft, without inventing default copy data.
- Source/target selections remain independent. Switching central tabs preserves both and valid drafts; choosing a different source that would replace a loaded proposal follows explicit replace/discard/stay. Revalidate each resolved copy origin and invalidate only affected approvals on changes.

### Graphic data loading: benchmark before implementation

- **Pre-implementation gate:** investigate and benchmark the graphics-loading strategy before implementing the production loader. Compare a complete project attachment-graphics preload against on-demand loading per inspected filter/effective source and bounded batches for checked filters. Select the least complex strategy supported by measurements; full-project preload is permitted only if representative large-project results meet an explicitly agreed startup, responsiveness and memory budget. Until that evidence exists, do not load all graphic overrides for all filters in all views/templates on opening.
- Keep definition metadata, attachment membership/usage ids, project view/template name/type search metadata and attachment graphic values as distinct data needs. Complete usage/purge and template-impact checks remain mandatory, but must not accidentally hydrate all graphic values. Entering project search, typing, filtering lists, checking names or opening a source picker is not by itself a request for project-wide graphics.
- Candidate on-demand triggers: inspect a filter's actual attachment, open Graphics for an explicit edit/review scope, expand source variants, prepare Copy for the checked filters/selected channels, or build destination deltas for the active proposal. Resolve shared controlling-template origins once. Read only the fields needed for the requested comparison, plus any fields required to preserve untouched settings and verify the eventual write; do not omit correctness-critical reads for speed.
- Multi-source membership can show source counts before graphics are loaded. Show **Graphics not loaded** / **Loading** / **Unavailable** distinctly from a known-empty draft, native defaults, Not attached and Mixed. Publish variant counts or identical/mixed claims only after the relevant reads complete; failed/cancelled or partial data cannot become a copy choice, approval or writable default.
- Cache successfully read immutable snapshots by document, effective source/target attachment identity and loaded field coverage for this dialogue. Repeated focus/tab/search changes reuse valid data; deduplicate in-flight requests. Invalidate affected snapshots and approvals after Apply, definition/attachment changes or detected document changes, and revalidate before commit. Applying a default attachment must allow reading/editing its actual target graphics immediately in the same dialogue without rebuilding the entire project cache.
- Large source/target batches need bounded progress and cancellation, preserving selections and recoverable drafts. All Revit reads stay in a verified API context; background-thread API calls are not a responsiveness shortcut. Explicitly report load failures and keep dependent review/Apply blocked until resolved or explicitly excluded.
- Benchmark read-only on representative small and large projects, including many view/filter pairs, shared templates and differing graphic variants, in the intended IronPython/WPF host and supported Revit runtimes. Record model/attachment counts, API-read counts, cache hits, memory cost, cold/warm time to usable dialogue, first Graphics/Copy/variant request and cancellation/UI response. Compare the same requested values/results for fidelity; Python-only timings do not establish hosted UI responsiveness.
- Present the measured eager/lazy/batched trade-offs and agree acceptance budgets before selecting the loader. No fixed speed threshold or performance gain is asserted here. Benchmark scripts and results are a prerequisite to production implementation, not evidence already obtained by this scope update.

### Target source selector and deferred project search

- At launch, resolve only the current-view context, its assigned template and directly captured Browser-selected candidates as needed. Do not build the complete project view/template name/type catalogue for the target picker.
- **View** means the current view; **Template** means that view's assigned template; **Browser** means the pre-modal Browser-selected snapshot; **Project** means all eligible project views/templates. Mark the active source in the menu and show its single-word name on the closed dropdown. Start in Browser when captured views/templates exist, otherwise View; an unavailable/blocked current context is still explicitly shown, not replaced silently.
- View / Template / Browser resolve only their explicit candidates, deduplicate by identity and retain existing destination checks and drafts when switching sources. Checks outside the displayed source count as hidden; a source switch is not an implicit Replace or project-wide Select All. Keep blocked candidates visible with reasons; never redirect a controlled view to its template automatically. Disable unavailable choices with an explanation, including no template or no captured Browser views.
- Browser uses the captured snapshot, not live Browser access. Retain the existing launch import of eligible captured selections without duplicate rows. Any Replace operation must be explicit, never an incidental effect of changing source.
- Search and options narrow the active target source only, with an appropriate placeholder such as **Search current template** or **Search project targets**. Show whether project metadata is loaded. Typing, opening search options, resetting search or choosing View / Template / Browser must not trigger the full project catalogue. Explicitly opening Selected Views / Templates on the left can also load the shared metadata cache, but does not change target scope/checks.
- **Project** explicitly loads eligible project views/templates and their searchable name/type metadata. Entering it does not check every result or discard current checks, queries or drafts. Cache the catalogue for this dialogue; repeated searches/source changes must not rescan it per keystroke. Keep a focused row's identity where available without presenting an out-of-source row as a visible result.
- **Clear** is an action, never a fifth persistent state: untick every target, including hidden checks from other sources, then return to **Project** with zero selections. Load the catalogue on demand if it is not already cached; this is an explicit exception to loading only via the Project menu item. Preserve filter checks, query/restrictions and draft values; deactivate affected target pairs and invalidate their approvals. Do not delete candidates or reset search.
- Show bounded cancellable progress on first project load. Cancellation or failure retains available candidates and recoverable state and explicitly reports incomplete project search with retry/source choices; never present a partial catalogue as complete. If Clear initiated loading, target checks stay cleared even if loading fails/cancels: do not restore them or report a complete project list. Revalidate document context and selected identities before applying changes.
- **Reset search** clears only the query and search restrictions; it neither checks targets nor changes the selected source. Global **Clear All Selections** continues to clear workspace checkboxes without changing source or triggering a project catalogue load; the local dropdown Clear has the additional explicit return-to-Project behaviour.
- Deferred target browsing does not reduce required project-wide usage, purge validation or template-impact checks. Keep those data paths separate from the target-name catalogue and perform complete checks when their tasks need them; an unloaded target catalogue is never evidence that a filter is unused.
- Measure launch time and first catalogue request separately on the same representative model, recording view/template counts and full-catalogue build counts. Require zero complete view/template-name catalogue builds before choosing target Project / Clear or explicitly opening the source picker, and cache reuse afterwards. All Project Filters collects definitions, not view/template names. No startup speed improvement is claimed until measured in the actual WPF command.

### Project Browser multi-view selection

- Capture the Revit selection **before** the modal workspace opens. Import directly selected eligible views/templates, deduplicate ids and display an imported-count summary. Do not substitute the active view for a genuine multi-view selection.
- Preselect writable imported targets; retain blocked/unsupported selections as visible candidates with reasons. If selection contains views but none is writable, show that fact rather than silently falling back to the current view.
- Ignore non-view selections with an inline count/reason; do not expand sheets into placed views or infer unrelated views from browser hierarchy.
- If no views/templates were selected, initialise the current-view context; make its controlling template a one-click explicit choice when necessary. Do not select the template automatically.
- **Browser** in the target source dropdown reuses the captured snapshot and retains prior target checks outside that source; Replace, if offered, is explicit. It does not imply live browser access behind a modal dialogue. Changing the live browser selection requires closing/reopening; pending work must first be applied/discarded explicitly.
- Verify actual multi-view Project Browser selection retrieval and per-view-type eligibility in each supported Revit runtime. This is an acceptance requirement, not behaviour demonstrated by the static design.

## Attachment graphics and multi-target application

### Fields

| Group | Proposed controls |
|---|---|
| Element visibility | On / Off; Off hides matching elements |
| Filter enabled (read-only policy) | New attachments: always On. Existing attachments: preserve On/Off. No enabled-state editor or source-copy option; disabled means no filter effect, not hidden matching elements |
| Halftone | On / Off |
| Projection lines | Line weight, colour, line pattern |
| Projection/surface patterns | Foreground and background pattern, colour and visibility |
| Transparency | Percentage with release-verified bounds; validate before committing |
| Cut lines | Line weight, colour, line pattern |
| Cut patterns | Foreground and background pattern, colour and visibility |

- Each editable field supports **Keep existing** / **Set value**; expose **Clear override** only where the native field has a verified reset representation. Boolean Off, zero transparency and "no override" are not interchangeable.
- Review current values before editing. Mixed values remain unchanged until explicitly edited; never pick an arbitrary representative value for writes.
- Apply changed fields to one selected attachment/filter or an explicitly labelled checked set. Keep per-filter drafts, including proposals for missing attachments.
- Read existing attachment settings and patch only requested fields. Existing enabled state, untouched graphics/visibility and order survive. New attachments receive native defaults for untouched graphics/visibility and must be enabled regardless of the source enabled state. Inspecting disabled sources remains allowed; their enabled state never participates in copy variants or requested writes. Display the policy read-only, not as an empty/editable enabled draft.
- Show line/fill/colour swatches as aids, not a rendered drawing preview. Use document pattern resources; validate fill-pattern type/eligibility, solid/none sentinels, colours, weights and reset semantics before offering values. Do not create patterns implicitly.
- Graphics review shows the actual attachment origin. A template's Filters settings must control the view before describing those values as inherited; assigned-but-noncontrolling templates remain separate consumers.
- Review the active source set as deduplicated filter definitions with source-labelled attachments. Current View / Template resolves one effective origin; Browser/Selected sources can expose more than one attachment per filter. Include visibility/enabled state and Mixed fields, not just definition presence. The older current-view-plus-template union is not the latest source-mode contract.

### Graphics edit mode: Per Filter / Together

- Place a two-position **Per Filter / Together (N)** control above the graphics editor; default to **Per Filter** on first opening. N counts every checked filter, including ones hidden by search. This controls destination-draft editing, not source selection or the model selection.
- **Per Filter** shows **Previous / i of N · Filter name / Next** plus an explicit scope such as **This filter -> 3 selected targets**. Edit only that filter's requested fields across the checked destinations. Differences between those destinations remain Mixed until edited; other filters retain their independent drafts.
- Arrows traverse the checked-filter set in stable library order, including hidden checked rows, without ticking/unchecking anything or changing the search. Clicking a checked filter in Per Filter jumps to it. Disable arrows at either end rather than wrapping; expose the full long name accessibly and support keyboard activation. Navigation retains focus/draft state without committing.
- **Together** labels its scope **All N checked filters -> M selected targets**. Show common draft/effective values normally and differing values or requested operations as **Mixed**; Keep, Set and Clear are distinct operations even if their rendered colours/numbers match. Only a field explicitly changed in this mode sets that field/operation across the current checked filter/target set. Untouched differences survive; no averaging or first-row representative writes.
- Switching modes alone must not copy the current filter's settings to the group, flatten independent drafts, grant approvals or write to Revit. Return to the last focused checked filter in Per Filter. Edits made Together become explicit field patches in each affected per-filter draft, which can then be individually refined; changing that same field Together later deliberately replaces it for the currently labelled group, not other fields.
- Preserve per-filter/per-target drafts while moving with arrows, changing mode or switching central tabs. Invalid field input stays visible and blocks navigation that would discard it until corrected/cancelled, using inline feedback rather than a normal modal warning.
- Selection changes update the counted scope without replaying earlier Together edits onto newly checked filters/targets. Retain unchecked items' values as inactive drafts and remove their active pairs/approvals. If the current filter is unchecked, move to the next remaining checked item (otherwise the preceding one); no checked filters disables the editor/arrows and shows an explicit empty-selection state. A single checked filter remains editable with both arrows disabled.
- One final Apply can commit differently configured filters through the existing atomic batch/approval mechanism. Invalidate affected approvals when fields or selection change; merely inspecting or switching edit mode does not invalidate an unchanged proposal. After Apply, refresh affected attachments so their actual graphics can be edited again without closing the dialogue.
- Colour controls use visible swatches and Revit's native colour picker rather than an RGB-value list. Choosing OK changes only the scoped draft; Cancel leaves it untouched. Host ownership, keyboard return and supported-release behaviour remain required runtime tests; a swatch sketch is not a tested native-picker invocation.

### Batch proposal and approval

- The attachment action explicitly proposes the checked filters for the checked target set. Checking alone never mutates the model. Working in Edit Rules/Rename/Delete does not itself queue additions; the persistent attachment action must make any prepared attachment writes explicit.
- Represent each proposal by **document + target id + filter id**, with source, before-values, requested fields, after-values, action, approval and impact.
- Row states: **Add**, **Update**, **Unchanged**, **Blocked**, **Invalid/Stale**. Missing attachments may be added with configured fields; existing attachments with no requested difference are unchanged.
- Add rows are ready for the explicit final Apply. Update rows preserve current settings until approved individually or via **Approve All Updates (N rows / M targets)**. Approval controls review only; they never commit.
- Preflight/build the plan even when Changes is collapsed. Apply must process ready additions and already-approved updates without first opening Graphics, Changes or a review window. Pre-existing unchanged attachments are no-ops; only requested changes to existing attachments require approval. If there are no ready additions or approved updates, explain **N existing attachments await approval** rather than requiring approval for new attachments or presenting a successful empty write.
- Approve All Updates covers all currently eligible update rows in this proposal, including rows hidden by a review search; its label shows that scope. It excludes blocked/invalid/stale rows and destructive definition actions. Provide **Clear approvals**.
- Approval is bound to the exact target/filter/field/source/before/after proposal and template impact. Changing any reviewed meaning invalidates affected approvals, not unrelated approvals. A changed target/source snapshot requires refreshed review; no silent overwrite after external changes.
- Additions are not labelled as graphics replacements. Exact copy clears are visible changes, not mistaken for Keep existing. Display what remains untouched as well as requested changes.
- The contextual attachment action commits ready additions and approved updates only; use the graphics/visibility-specific labels above to reflect all active drafts, not merely the open tab or one source checkbox. Display counts of unapproved updates left unchanged before the click and afterwards; retaining those drafts does not imply the whole proposal succeeded.
- Blocked/invalid selected rows cannot disappear from the batch. Resolve or explicitly exclude them before enabling Apply; bulk exclusion is available with counted reasons. Exclusion is a deliberate user action, not silent "best effort".
- Successful application stays in the same workspace with added/updated/unchanged/unapproved/excluded counts and Undo guidance. Keep unrelated pending work; clear only committed proposal entries after confirmed readback.
- After successful readback, remove committed and unchanged entries from the active Changes work list; keep unapproved existing updates and unresolved rows for approval/correction and re-processing. For example, **8 added · 3 existing attachments await approval**. Preserve library/target checks and unrelated drafts, but do not immediately requeue completed additions as updates merely because their now-existing attachments are discovered. Revalidate each retained row before its later commit; each successful Apply has its own Undo boundary.
- No extra normal review/confirmation/success dialogue is required. The visible Changes summary plus the explicit Apply action is the commit boundary.

### Template and order behaviour

- Template-controlled views remain inspectable but blocked direct destinations. Offer their controlling templates as explicit choices, deduplicating the same template selected through several views.
- Selecting a template warns inline about the full inherited consumer set, including views not selected by the user. Do not add a separate acknowledgement to routine graphics Apply; bind displayed impact to the approval/commit snapshot.
- Do not auto-assign/remove templates, change what parameters they control, or write dependent views individually. Assigned templates that do not control Filters do not block genuine direct-view changes.
- Preserve existing filter order. Ordinary additions append in visible checked-filter order; single-origin copy additions append in source attachment order. Multi-origin copy additions use the explicitly shown checked-filter order, with no automatic priority reconciliation. Deduplicate pairs and never reorder unrelated filters.
- Exclude source-as-target in Copy with a visible explanation. A source change must not silently alter an approved destination write set.

## Copy graphics between views/templates

- Copy has no tab. Persistent **Include source graphic overrides** and **Include source visibility** checkboxes sit alongside each other outside the central tabs; both are checked by default and remain visible in Graphics, Edit Rules and Rename. They are independent: visibility-only reuse does not require graphic overrides. Preserve explicit user choices through filter/target selection and tab navigation; do not recheck an option the user deliberately turned off.
- Enable both for valid view/template attachment sources without pre-scanning for nondefault graphics. Default-on does not authorise project-wide preload: load only checked-filter/requested-channel data as needed for inspection or planning, with the benchmark gate unchanged. All Project Filters disables both, treats both as inactive and shows **Choose a view/template source to include graphics or visibility**; default checks must never invent source data or block default additions there. Distinguish loading/error/unresolved variants from known defaults, block dependent Apply until resolved and never borrow arbitrary consumer settings.
- With both off and no custom edits, show **Filters only · existing target graphics preserved**, with **Add Filters**. With graphics on, show **Source graphics included** (and visibility if checked), actual source/variant provenance, filter/target counts, changed-existing-attachment count and **Apply Filters + Graphics**. Visibility-only requests show **Source visibility included**, with **Apply Filters + Visibility** when adding attachments or **Apply Visibility Changes** for updates only. Use the existing **Graphics** tab for optional inspection/editing; no separate Review graphics button or required visit. Labels reflect all custom requests too, never claim Filters only when visibility changes remain.
- Remove the source **Options** dropdown and **Include enabled state** entirely. Enabled is neither copied nor editable in this revision: new attachments are always enabled; existing attachments keep their current state, even if disabled. Copying visibility Off is still permitted and means hidden matching elements, not a disabled filter. Show this distinction/policy inline.
- Only checked source channels participate in variant comparison; graphics-identical sources differing only in enabled state need no conflict choice. Graphics fields show **From source / Custom / Mixed** provenance, with **Source graphics + custom edits** when applicable.
- Unchecking either checkbox removes only that channel's source-derived request, not the other channel or independent custom patches. Restore each destination's actual values beneath those patches, recompute deltas and invalidate affected approvals. Never leave source-derived writes hidden. The footer reflects the remaining graphics/visibility/custom requests and additions.
- Browse one/many same-document origins through the left source selector and choose attached rule-based filters. Resolve one settings variant per filter before applying; reuse those definitions at the targets, never clone rules or import other documents.
- If a source view inherits Filters, resolve its controlling template and show the actual effective origin. Deduplicate shared templates; assigned-but-noncontrolling templates do not override the source view. Destinations still require explicit controlling-template selection.
- Group identical source settings for selected channels; resolve only differing variants inline. A bulk preferred source chooses its attachment for each available filter and flags missing ones. Store per-filter origin identity/provenance and snapshots; no silent first-source choice or multi-source field merging.
- Copy precisely the explicitly checked graphics/visibility channels. Neither a source's disabled state nor an unchecked visibility option can disable a new attachment or change an existing attachment's enabled state.
- Default mode: **Exact selected channels**. Copy all selected graphics fields including native unset/reset values; this can clear existing target overrides and therefore requires approval for update rows. Unselected channels remain untouched.
- Alternative: **Only explicit source overrides**, leaving other target fields unchanged. Enable only for fields whose overridden/unset state can be determined reliably; unresolved boolean/reset semantics must not be inferred from displayed values.
- After loading source settings, allow optional editing in Graphics without another source-picker or wizard. Preserve the source snapshot and label adjusted fields as custom rather than an exact copy. Exact source unset values can clear destination overrides: show those clears in review and require existing-update approval.
- Existing target attachments follow the same preserve/review/Approve All contract as Apply. Missing attachments are added; unrelated attachments remain intact.
- Copy does not automatically transfer filter priority, detach target filters, rename definitions, change categories/rules or duplicate definitions.
- Revalidate source settings and target snapshots before commit. If the source changed after loading, retain the draft, flag stale rows and require explicit reload/review; never silently copy a different version.

## Creating and Editing Filters

### Existing UI to reuse

- [ReValue's editor](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_editor.py>) and [XAML](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/FilterEditor.xaml>) already provide parameter/condition/value rows, nested AND/OR groups, group exclusion (NOT), add/remove controls, validation feedback, and a draft that is only accepted on confirmation.
- [ReValue's expression model](<../../Modify.panel/col2.stack/KW ReValue.pushbutton/filter_expression.py>) represents groups and rules independently of the controls, but identifies parameters by name and evaluates conditions in Python.
- [ExcelLink's advanced-filter UI](<../../Modify.panel/KW ExcelLink.pushbutton/web/app.js>) provides similar AND/OR groups and rule rows in a web dialog. Its [operator/evaluation module](<../../Modify.panel/KW ExcelLink.pushbutton/web/filters.js>) also includes between, wildcard, and regex conditions.

**Reuse the interaction pattern, not the existing evaluators unchanged.** ReValue is the closest implementation starting point for an IronPython/WPF tool. ExcelLink uses JavaScript/DOM controls, so its UI is a design reference rather than a drop-in WPF component. Extract shared presentation/model helpers only where genuinely reusable; keep native Revit filter translation separate and preserve both existing tools.

### Editor layout and workflow

- **New Filter** opens an inline definition editor: name, searchable category checklist, and rule builder.
- **Edit Rules** loads one checked definition at a time into the category/rule editor. Reuse **Previous / i of N · Filter name / Next** from Graphics in the same stable checked-filter order, including search-hidden checks; direct checked-row focus jumps and endpoints are disabled without wrapping. Retain the same current filter across the two tabs, restoring the last checked focus when leaving Together. With no checks, show an empty state and disable Save/arrows; Edit from a focused unchecked definition must explicitly select it and disclose the scope change.
- Retain independent unsaved rule/category drafts by document/filter id while navigating; no automatic save or bulk/Together rule replacement. Selection removal makes its draft inactive; it cannot be committed invisibly. Invalid input stays attached to its draft with inline errors, and navigation must not silently discard it. Prompt save/discard/stay only for genuinely incompatible replacement/closing, not harmless arrows/tab navigation.
- Show **Shared filter definition — affects every view/template using it. Selected targets do not limit this change.** Include full usage/template impact before Save. Keep the main workspace and its pending attachment state alive. Rename is handled by its own grid rather than an implicit rule-save name change.
- A valid new/edited draft shows matching existing definitions: **Filter 'X' has the same categories and rules**. List every match, not just the first. Exclude the definition currently being edited, and refresh the check when categories/conditions change.
- Each rule has **Parameter | Operator | Value | Remove**. Groups have **All (AND) / Any (OR)**, **Add Condition**, **Add Group**, and **Remove Group**.
- Parameter operators and value controls depend on the parameter's native type. Use text input, numeric input with unit context, Yes/No, or an element-reference picker as appropriate.
- Equals/Not Equals on recognised text/integer/numeric parameters offer editable assigned-value suggestions scoped to the chosen categories, including both instances and types. Exact stored operands, rather than rounded labels, are used when a suggestion is selected. Other operators retain manual input without autofill suggestions; presence conditions still hide operands.
- **Create Filter** (new) / **Save Rule Changes** (edit) validates and writes its definition and refreshes the workspace; a rule save stays on the same filter/tab. Save only the displayed active rule draft, retaining other drafts. Duplicate creation requires inline intentional-duplicate acknowledgement; normal saves need no second confirmation. Attachment Apply remains separate and can use multiple targets.
- When identical definitions exist, require explicit confirmation before saving but allow intentional duplicates. Offer an explicit action to inspect/use an existing filter instead, without silently applying it, discarding the draft, or changing that existing definition.
- **Cancel** discards the draft without a transaction or document changes.
- Keep any advanced expression text optional; expose it only when it can round-trip typed parameter identities, values, and supported logic without loss.

### Create Filter flow

1. **+ New** opens the inline editor. **Create Filter** validates the name, categories, typed rules and current duplicate matches; invalid input remains with actionable feedback and no writes.
2. If no duplicate exists, create the definition atomically and return to the same workspace. Select/focus the new definition so the next attachment action does not require finding it again; creating alone never attaches it.
3. If matches exist, expand their names, complete rules and usage inline. Require **Create intentional duplicate** acknowledgement; recheck matches/name validity at commit. **Use Existing** explicitly discards this definition draft and focuses a chosen match without applying, merging or altering it.
4. Cancelling leaves the model, attachment draft, searches and targets unchanged. Successful creation keeps those targets and any unrelated pending attachment edits.
5. Write failures roll back and preserve the draft. No extra normal review or success dialogue.

### Duplicate Filter as an editable starting point

1. Focus one rule-based filter and choose **Duplicate Filter**. Require a valid source in the active document; disable with an explanation when none is focused. Do not duplicate every checked filter or create an element immediately.
2. Open the same inline new-definition editor, prefilled from an independent snapshot of the source's categories and complete typed rule tree. Preserve parameter/reference identities, nesting, inversions, exact values and tolerances without sharing mutable draft nodes with the source.
3. Show **Starting from: [source name]** and **New definition; original unchanged**. Suggest an editable, available name based on the source (for example, `Original - Copy`, then a numbered suffix when needed). Revalidate uniqueness at Create; do not overwrite the source or silently alter the user's chosen name on collision.
4. Let the user change the name, categories, rules and grouping before saving. Unsupported structures remain inspection-only with an explicit reason; never drop/flatten nodes just to enable duplication. No extra confirmation is needed to open the draft.
5. **Create Filter** follows the ordinary creation validation and duplicate-definition comparison, including the source among potential matches. If categories/rules still match any existing filter, show the normal intentional-duplicate acknowledgement inline once at commit; a changed definition with no matches needs no acknowledgement. Choosing Duplicate Filter alone does not grant blanket approval for identical definitions.
6. Opening, editing and cancelling the draft make no model changes. Cancel preserves the original, searches, targets and unrelated attachment drafts. A failed Create preserves the new draft and leaves the original unchanged.
7. Successful Create produces one new definition with its own identity in one Undo-friendly operation, then focuses/checks it for the next task. Retain surviving batch checks and target context; reveal the new row even if a current-view/template scope would otherwise hide this unattached filter.
8. Copy **definition only**: no view/template attachments, graphic overrides, visibility, enabled state or priority are inherited. Applying the new definition and configuring/copying graphics remain separate explicit tasks. Existing proposal entries for the original continue to reference the original, never the duplicate.
9. Keep the loaded source snapshot/provenance separate from the new editable draft. If the source changes or is deleted before Create, retain the draft and flag that fact; offer an explicit reload (when available) or continue with the already loaded snapshot after reviewing it. Do not silently refresh/rebase the user's work or mutate the source.

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
- Validate the current definition's identity/name freshness, at least one valid category, parameter applicability, typed operands, and a Revit-acceptable rule tree before committing. Edit Rules preserves its name; Rename validates proposed names separately.
- An intentionally category-only filter must be clearly described as matching the selected categories without additional conditions; incomplete/invalid rules must not silently become a category-only filter.
- Apply category/rule changes atomically. If validation or any API write fails, roll back the whole definition edit and show the reason. Account for read-only documents and worksharing ownership failures.

### Save Changes flow

1. **Edit / Edit Rules** opens the inline definition editor. Show draft changes and all affected consumers; use **Save Rule Changes**, visually distinct from attachment Apply.
2. Save validates the draft, current definition/usage and identical existing definitions, excluding the filter being edited. Invalid input or stale context stays in the editor with actionable feedback and a refreshed impact display; preserve the draft rather than overwriting an externally changed definition.
3. If no duplicate exists, update the definition atomically, staying on the same filter in Edit Rules without another confirmation or success dialogue. Keep its identity, name, attachments and graphics.
4. If the edit duplicates another filter, show all matches and shared impact inline. Require intentional-duplicate acknowledgement before Save Rule Changes, revalidated at commit.
5. **Use Existing** explicitly discards only this definition draft and focuses the match. It does not delete the edited filter or transfer attachments. Cancel returns without changes.
6. Saving keeps unrelated attachment drafts. Recompute affected proposal snapshots/impact after a definition change and invalidate approvals when their reviewed meaning changes. Failed saves retain the draft and explain the error.

The editor's readable rule/change preview is a **draft review, not a live drawing preview**. Draft edits do not change the model; **Save Rule Changes** does. Existing attachments and graphics remain in place while all consumers use the saved definition. Resizing/moving the modal editor can expose the drawing, but unsaved rules do not affect it. Close the manager to interact with Revit; redraw and effective display after saving still require implementation verification. A live/modeless preview workflow is not included.

## Duplicate Definition Analysis

### Project-wide analysis

- **Analyse Duplicates** scans every rule-based filter definition in the active project, regardless of the browser's search or checkbox selection.
- Group matching definitions in the workspace's **Duplicates** management view. Show filter names/ids, shared categories/rules, direct/template/inherited usage and attachment-graphics differences.
- Report groups, filters in groups, and definitions that could not be compared. An incomplete scan must not report a misleading "no duplicates".
- Selecting a result focuses/inspects that definition. Offer explicit Keep, Use Existing, Rename or Delete Selected actions, routing writes through their normal inline safeguards. Analysis alone starts no transaction and does not merge, delete or move attachments.
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
- Use a **Current Name | Proposed Name | Status** grid, not per-filter arrows. Populate all checked filters, including library-search-hidden checks. Proposed Name starts as the exact current name, never automatically as a rule-generated name. Edit directly; no row approval/selection checkboxes or Rename Approved stage. Grid filtering must disclose hidden pending rows; **Rename** processes the whole active grid, not merely visible rows.
- Keep configurable token-based naming patterns as an optional explicit generation action, initially **`{categories} | {rules}`**. A simple result could be `Doors, Walls | Fire Rating contains Hr`.
- `{categories}` is a deterministically ordered category-name list. `{rules}` renders the complete rule expression with explicit AND/OR grouping, native operator labels (including level-specific labels), value-presence rules without operands, and readable typed values.
- Numeric names use readable project units; references use readable names, but neither is used for duplicate identity comparisons. Clearly label a category-only definition rather than outputting an empty/misleading rule summary.
- Validation/conflicts are per row, never the first batch error repeated on unrelated proposals. Flag every side of proposed-name collisions, name invalid characters explicitly and report the actual length for proposals over 255 characters. Remove redundant presentation brackets while preserving mixed logic; use a colon-free category-only naming token.
- Pattern changes only update the preview. Accepting a generated name is explicit; later edits to a filter's rules must not automatically rename it.
- Persist the accepted naming pattern through repository-standard tool settings when implemented. Pattern expansion must be bounded and non-executable; reject unknown/malformed tokens with actionable feedback.
- Reuse the existing Type Renamer's pattern/preview interaction where appropriate, not its family-type-specific value extraction. Keep both existing tools unchanged unless genuinely shared presentation helpers are extracted.
- Validate nonblank names, Revit naming constraints, collisions with existing names, and collisions among proposed names. Duplicate-definition warnings are separate from duplicate-name errors: intentionally equivalent definitions still need valid distinct names.
- If a generated name is too long or invalid, show the proposed name and the problem. Do not silently truncate rules, invent suffixes, or sanitise away meaningful conditions. Require an explicit user correction.
- **Rename** freshly validates the active grid and project names, then processes all changed rows whose final names are valid and unique. Known name clashes/invalid proposals remain in the grid, with their proposals and actionable row errors; they do not prevent unrelated valid rows from renaming. Unchanged rows require no write and leave the processed grid. This explicit preflight eligibility is the intended rename-only partial-result contract, not the attachment planner's approval/blocker contract.
- Check collisions against live names and the whole proposed final namespace, including names retained by blocked rows. If eligibility changes, recheck dependent name vacancies so a proposed rename cannot occupy a name whose owner failed preflight. Conflicting proposals all remain; never choose the first row, silently append suffixes or truncate. Verify safe swaps/cycles and native case/uniqueness semantics in supported runtimes before offering them; unsupported permutations remain explicit correction rows rather than speculative writes.
- Commit the prevalidated eligible subset atomically in one Undo-friendly operation per click. Revalidate identities, current names and ownership immediately before writes. Unexpected write/ownership/stale-context failures roll back every attempted eligible row; retain their proposals and show the actual error, never remove them as successful or silently downgrade write errors to name conflicts.
- After confirmed success/readback, remove only successfully renamed and unchanged rows; keep clashes/other invalid rows for direct correction and **Rename** retry. Show exact inline counts, e.g. **18 renamed · 2 need correction**, with unchanged counts when applicable. When none remain, show an empty-grid completion state. Each successful retry has its own Undo boundary; Undo is not a session-wide rollback.
- Track the grid by document/filter id. Completed rows stay out on harmless tab/search navigation or ReValue return; explicitly new checked filters may join with current-name defaults. Unchecked rows become inactive drafts. Refresh names, usage labels and duplicate displays after writes without losing remaining corrections or unrelated rule/attachment drafts; invalidate only affected snapshots/approvals. Preview, ReValue transformation and Cancel perform no model writes.
- Manual renaming does not require a fully editable rule tree. Generated rule-based names do require a complete readable representation; unsupported rules produce an explicit per-row error rather than a partial name.

## Purging Unused, Clearing Selection and Deleting Filters

### Purge Unused

- Replace **Select Unused** with the explicitly destructive **Purge Unused** action, styled like Delete. It is independent of checked filters, current targets and library search. This changes the proposed workflow, not the current runtime's Select Unused behaviour.
- Scan all rule-based filter definitions and their attachments across the entire active project, independent of browser search, current view or application target. A filter is unused only when attached to **no view and no view template**.
- Count attachments to templates even when those templates are assigned to no views. Hidden/disabled filter attachments still count as usage. Duplicate definitions and rules matching no model elements are not evidence of being unused.
- Refresh the full reverse usage index before building candidates. A failed/incomplete scan blocks purging and preserves prior workspace state; never treat uncertain usage as unused.
- Show an inline searchable candidate review, initially checked, with exact names/ids/categories and zero-usage status. Keep candidate approval separate from library checks. Users can uncheck candidates, cancel, or commit **Purge N Unused Filters**; the count includes approved rows hidden by the candidate search and must be visible.
- The candidate review is the only confirmation. No used-filter acknowledgement, second popup or compulsory results window: the dedicated counted destructive action is explicit consent. Opening/reviewing/cancelling does not delete or change ordinary filter/target selections.
- If no candidates exist, show **No unused filters found**, disable the purge commit and preserve existing selections. Disable purge writes in read-only projects; read-only usage inspection remains available.
- Immediately before committing, revalidate the exact approved definitions, current project-wide usage, document and ownership. If any candidate has become used or the scan fails, perform no deletions, retain the review and explain which candidate changed; refresh the candidate set and require a new counted commit. Do not silently skip it or turn purge into used-filter deletion.
- Delete exactly the approved still-unused definitions using the normal atomic deletion service, with one Undo. Unexpected dependent deletions or any write failure roll back the entire purge; matched model elements and used definitions are never deleted.
- Pending attachment drafts do not count as actual usage. Flag draft references to candidates before the purge click; on success remove references to deleted definitions with a notice and preserve unrelated drafts, selections and queries. A duplicate-as-starting-point snapshot remains available with stale provenance as specified above.
- Report purged/kept counts and Undo guidance inline. Successful purge refreshes usage, library, duplicate results and affected proposal state. It is a standalone definition commit, never part of attachment Apply.
- Retain **Project-unused** as a non-destructive library scope for finding/checking unused definitions to apply. This scope only narrows the list; it never triggers purge or assumes that currently checked filters should be deleted.

### Clear Selection

- Place **Clear Selection** prominently in the workspace header. In one click, clear all filter/source-attachment, view/template target and management/review approval checkboxes, including selections hidden by search or collapsed panes. Clear purging/deletion and attachment-update approvals; Rename has no approval checkboxes and its deselected grid drafts become inactive.
- Do not change graphics On/Off values, halftone, copy-channel options, category choices in a definition draft or other configuration checkboxes. These are values, not action selection. Safety acknowledgements are never granted by clearing; invalidate them when their approved set changes.
- Preserve searches, list scopes, source choice, focused inspection, row highlights and draft values. Remove deselected pairs from the active write plan and retain their edited values only as inactive drafts; do not silently discard work or leave hidden writes active.
- Immediately show zero selection/approval counts and disable selected-set commits with no eligible/approved rows, including Edit Rules Save and Rename for the now-inactive checked set. A valid standalone new/duplicated Create Filter draft is not disabled merely because library selection was cleared. Do not automatically repopulate purge candidates or restore template targets after clearing; choosing rows again is explicit, and old approvals do not return.
- Provide **Clear filters** for the library/source-attachment checked set and **Clear targets** for destination checks. Preserve the other set and invalidate/remove only affected active pairs/approvals. Local controls are scoped; only the header action clears all selection groups.
- Clearing is read-only and requires no confirmation or transaction. It changes neither Revit's user selection nor any definitions, attachments or graphics and remains available in read-only documents.

### Delete Selected

- Allow deletion of selected rule-based definitions only through the dedicated inline **Delete Selected** review and explicit **Delete Approved Definitions** commit. Empty selection and read-only documents disable it with an explanation. It is not part of attachment Apply.
- Review the exact selected names/ids, categories and usage before deletion. Show direct views, attached templates and template-inheriting views; offer approved-row checkboxes so the user can narrow the operation.
- Clearly distinguish unused rows from used rows. If used filters are approved, warn that deleting the shared definitions removes their filter attachments, graphical overrides and filtering effects everywhere they are used, including affected template-inheriting views. It does not delete the matched model elements.
- Require one inline acknowledgement for approved used filters, not a sequence of confirmation popups. If approved rows change, recalculate impact/acknowledgement; unused-only deletion needs no extra acknowledgement beyond the explicit delete action.
- Revalidate the definitions, full usage and ownership immediately before writes. A stale selection or changed impact requires a refreshed review and confirmation, not silent continuation.
- Delete only approved definitions in one short Undo-friendly operation. Verify native deletion behaviour in Revit 2023 before implementation is treated as valid, including attachment removal, dependency effects and Undo restoration of definitions, attachments and graphics.
- Do not allow deletion to cascade into unapproved filter definitions or unrelated model elements. Validate the native deletion result before committing; unexpected effects or any write/ownership failure roll back the entire operation with an actionable error, leaving no partial deletion.
- Preview and Cancel perform no model writes. Ordinary Delete is never inferred from duplicate analysis or the Project-unused list scope. Purge Unused is its own explicit reviewed deletion action; neither runs automatically.
- On success, report deleted definitions and affected usage inline, then refresh lists, checks, descriptions, usage, duplicates and matching previews. Keep surviving checks. Remove draft references to deleted definitions with an explicit notice and recompute affected approvals; never silently lose unrelated work. Failures are explicit, not success-shaped results.

## Right-Click ReValue and Revit Selection Actions

Provide two distinct context-menu actions in Filter Manager's filter list:

### Rename Filters with ReValue

- Pass the selected native filter definitions directly to ReValue through an explicit reusable entry point, rather than executing its ribbon script or relying on Revit's current element selection.
- Open in filter-name mode: read and write each filter's own name, never attempt to resolve an element type, and never allow stale saved type/source settings to redirect writes to another target.
- **Edit in ReValue...** transforms the current grid's proposed names using tokenisation/rearrangement, find/replace, prefixes/suffixes, case and pattern preview. Pass stable filter ids and current proposal text, not stale original names; a retry handoff includes only remaining active rows. Filter-specific `{categories}` / `{rules}` data must be deliberately supplied if exposed; they are not ordinary native element parameters.
- Return confirmed transformations as proposals to the same grid for correction and explicit **Rename**, not immediate model writes. Cancel leaves the grid untouched. Adapt the existing safe callback into draft-return mode for this workspace; preserve standalone ReValue ribbon behaviour. Revalidate names on return/commit and preserve the rename eligibility/atomic-write/error-retention contract above; no approval checkboxes are reintroduced by the handoff.
- Preserve the existing filter-safe name-only entry point and callback validation. Do not replace it with an ordinary ReValue launch that reloads saved instance/type settings or attempts to resolve filter element types. Retain normal ribbon behaviour independently.

### Select Matching Elements in Revit

- Open a matching-scope dialog offering both **Current View / Entire Active Project** and **Match Any Selected Filter (OR) / Match Every Selected Filter (AND)**. Do not assume one choice or conflate this collection scope with Filter Manager's destination set.
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

- The main workspace remains **modal**, not modeless. Inline task panels replace routine companion windows. Capture Project Browser selection before opening; users cannot change the live browser selection behind this window. A modeless redesign requires separate API-context/lifecycle work and is outside this revision.
- Right-clicking a row already in the selection preserves the selected set; right-clicking an unselected row makes that row the explicit selection. Display the action's filter count so its scope is unambiguous.
- Unsaved definition drafts must be saved or explicitly discarded before a conflicting definition action. Preserve valid attachment drafts through ordinary internal task navigation and the ReValue round trip. Selecting matching model elements exits the workspace; resolve pending work with Apply / Discard / Stay first, without silently applying it.
- Suspend/close the manager's modal dialog before launching **Rename Filters with ReValue** in a valid Revit API context; return to and refresh the manager afterwards, retaining its search, focused item and selection where valid. Do not start a second ribbon command inside an active modal handler or leave a transaction open across either dialog.
- Only **Select Matching Elements in Revit**, after explicit confirmation, replaces Revit's user selection. Do not replace selection just to hand off filter definitions for renaming. Normal ReValue launches must continue to honour their existing selection/mode workflow, including the elements selected by Filter Manager.
- Existing handoff validation is recorded in Status. Revalidate it with the expanded workspace state, including cancellation, saved-mode isolation and lossless draft return; do not treat baseline tests as v3 proof.

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

## Historical v2 UI/application reference (superseded)

The page inventory below records historical design evidence only. Those pages were removed from the live Penpot file during the user-requested 2026-11-05 cleanup; use the pre-cleanup saved version for them. The single Current UI page and [current handoff](WORKFLOW.md#penpot-handoff) are authoritative.

**Archive boundary:** everything from this heading to the end of this file records the earlier single-target implementation design and its tests. It is not the v3 requirement set. The current requirements are above; the v3 delivery/acceptance contract is in [WORKFLOW.md](WORKFLOW.md). Keep these references for provenance and baseline regression coverage, not as instructions to retain the separate-copy-tool boundary.

### UI Design (v2)

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

### Behaviour & Guardrails (historical v2)
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

### Compatibility Constraints (historical v2)
- IronPython 2.7: no f-strings; use `.format()` / `%`. No Py3-only stdlib.
- Initial verification target is Revit 2023 only. Both reading and writing must be checked against each additional supported release before claiming compatibility.
- Rule creation must use version-appropriate signatures, including the verified Revit 2023 string factory overloads without `caseSensitive`.
- `__revit__` used once: `doc = __revit__.ActiveUIDocument.Document`, `uidoc = __revit__.ActiveUIDocument`.

### Proposed Bundle Layout (historical v2)
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

### Implementation Steps (historical v2)
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

### Acceptance Tests (historical v2)

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
