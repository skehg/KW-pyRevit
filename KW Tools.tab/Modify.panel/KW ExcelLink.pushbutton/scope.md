You are assisting in building a pyRevit7 extension called “Parameter Grid”.
This tool extracts Revit element parameters into an Excel‑like datagrid using WebView2 + Tabulator,
supports formulas, batch apply, type renaming, mixed‑use parameter handling, and multi‑sheet workbooks.

Follow these architectural requirements exactly:

============================================================

## OVERALL TOOL PURPOSE

A pyRevit7 tool that:

- Extracts parameters from selected elements, current view, or entire model
- Displays them in a WebView2 datagrid using Tabulator
- Allows Excel‑like formulas (HyperFormula or Formula.js)
- Supports batch apply of parameter changes back to Revit
- Supports type renaming
- Handles mixed‑use parameters (sometimes type, sometimes instance)
- Builds either separate category sheets or one combined multi-category sheet
- Allows custom parameter column selection and ordering
- Supports two parameter modes: Types Mode and Instances Mode
- Uses a wizard flow before opening the datagrid

============================================================

## WIZARD FLOW (MANDATORY)

Steps 2-4 have **Back** and **Cancel**, retaining scope, categories, mode and
ordered field selections while navigating. Separate mode retains an ordered
field list per category; combined mode retains one shared field list. The
category step offers **Separate category sheets** and **Combined grid**. In
separate mode, Back in Step 4 revisits the previous category; Back from the
first category, or from the combined picker, returns to Step 3. Step 1 has
Cancel (there is no preceding step).

Wizard forward buttons (Next, Next category and Open Grid) show the Back arrow
rotated 180 degrees, positioned after the label.
Navigation buttons are grouped at the bottom right in Cancel, Back, Next order
(with Open Grid replacing Next on the final step). Step 1 hides Back.

The grid's **Back** button returns to Step 4 for the active sheet, with its
current fields preselected. Finish the wizard to rebuild the workbook from
current Revit values with the revised fields. Existing column widths, sorting,
filters and column-formula templates are retained by category/title. There is
a confirmation when unapplied edits would be replaced. Canceling the wizard
leaves the original grid and all its unapplied edits intact. Preset/import
workbooks support the same return path; canceling a file/preset picker returns
to Step 1. Wizard operations never apply pending edits to Revit.

Copilot must generate code following this exact sequence:

### Step 1 — Selection Mode

User chooses:

- Selected Elements
- Current View
- Entire Model
- Entire Project File (all non-type elements and all element types, including unused
  types)

A horizontal rule separates the scope choices from **Import XLSX...** (see
"Importing edited XLSX"; skips Steps 2–4). A second rule separates import from
**Load Preset...** and **Manage presets...**. When configured, **Open default
preset: <name>** appears at the end of the preset group. Rules cannot be selected.

Entire Model includes non-type elements found in the project and only their
referenced element types. Unused types are excluded, so categories represented
only by unused types (such as unused tag types or ducts with no instances) do
not appear in the category picker.

When **Current View** is a schedule, Step 4 preselects its supported parameter
fields in displayed schedule order. Hidden fields needed by schedule filters
or sorting are appended as visible, editable grid columns. Schedule filters
load as editable AND rules in the grid's advanced filter controls; schedule
sorting is also carried across. Numeric operands use project display units
(the same units as grid cells), and element references use display names.
These are initial defaults only: Back navigation and returning from the grid
preserve the user's ordered fields and layout instead of reloading defaults.
The existing Types/Instances Mode column rules still apply.

Calculated, combined and other non-element parameter fields cannot be
reproduced. Missing/removed fields and unsupported filters (including parameter
existence and global-parameter association rules) are explicitly reported when
opening the grid and are not included in saved presets. Current View still
uses Revit's schedule-scoped element collector. Linked-file, embedded-schedule,
filter-by-sheet, grouping and total settings are not portable grid filters.

### Step 2 — Category Selection

Extract only category names (cheap operation).
User selects categories to include.
On a new launch, selected Revit elements preselect **Selected Elements** in
Step 1 and their categories in Step 2 (limited to the chosen scope).
Choosing **Current View** on a schedule preselects all categories found in
that schedule's scoped elements instead. These are initial defaults only:
Back navigation retains the user's category choices for each scope, and
returning from the grid retains its existing scope and categories.
User chooses **Separate category sheets** (one sheet and parameter picker per
category) or **Combined grid** (one sheet and one shared parameter picker for
all selected categories). A multicategory schedule scoped to Current View
defaults to Combined grid; the user can change the layout.

### Step 3 — Parameter Mode

User chooses:

- Types Mode
- Instances Mode

### Step 4 — Parameter Selection

The category coverage dropdown is visible only for **Combined grid** selected
in Step 2, including when returning from the grid. Separate category sheets
hide this dropdown.

For each selected category, or once across all selected categories for a
combined grid:

- Build a parameter usage map:
  - isType
  - isInstance
  - mixed‑use
- User selects parameters to include by moving them from an available-parameters
  list into a selected-datagrid-columns list
- The picker supports name search and availability filters for type, instance
  and mixed-use parameters; rows identify their availability and show counts
  for visible available parameters and selected columns. Combined rows also
  show category coverage.
- Both lists show the parameter name separately from a smaller, right-aligned
  availability badge: blue Type, grey Instance, or purple Type + Instance.
  Friendly data type and project unit appear as metadata above the parameter
  name; long names are trimmed with the full name available in a tooltip.
- In Types Mode the picker hides instance-only parameters and excludes them
  from restored selections. Mixed-use parameters remain available for their
  type values. Existing imported/preset workbook column rules are unchanged.
- User can remove selected columns and reorder the selected list with up/down
  controls
- Add, Remove, Up and Down use solid vector arrows in 18-DIP icon boxes, with
  3-DIP shafts and 10-DIP-wide, 7-DIP-deep heads. Icons inherit button foreground;
  existing labels, button sizes and the Back icon are retained.
- Mixed‑use parameters:
  - Types Mode → show only type column; instance-only blank/disabled
  - Instances Mode → show two columns: “ParamName (Type)” and “ParamName (Instance)”

### Step 5 — Datagrid Opens

#### Optional API fields and reversible false-positive filtering

Compatible parameter definitions now share one picker listing and grid column
per scope: grouping uses the exact displayed name, semantic Forge spec (ignoring
minor/patch version differences), and storage type. For example, multiple
family-specific Length definitions of `Grille Height Validation` become one
listing. Actual identities/GUIDs/spec versions remain in each cell's metadata
and are used for writing, refresh and XLSX import; the grouped label is never
used as the parameter setter identity.

Different quantities/storage types remain separate. When multiple compatible
definitions coexist on one element in the same scope, they stay separate too,
because merging them would discard a value. An older saved grouped selection
that becomes ambiguous is read-only with an explanation rather than silently
choosing a parameter. Existing identity-specific preset/XLSX selections remain
supported. The grouping does not depend on the false-positive-filter checkbox:
that checkbox controls known placeholder suppression, not catalog presentation.
Multiple compatible spec-version representations of the same built-in/shared
identity are aliases, not conflicting definitions. They collapse even when
other genuinely distinct same-name definitions must remain separate. Each
cell still carries its actual spec version for write-back.
When reopening Parameters or loading a preset, previous identity-specific and
grouped selections now resolve to a single current picker entry. This avoids
restoring a second Height listing/instance column alongside its group. Explicit
XLSX reconstruction remains identity-preserving to match the file's schema.

Step 4 has three controls:

- **Offer coordinates (read-only)** is off by default. Enable it, then select
  individual fields from the parameter list: internal-origin X/Y/Z,
  project-base-point X/Y/Z, or shared Easting/Northing/Elevation.
- **Offer useful API fields (read-only)** is off by default. It offers resolved
  category/family names, host element ID, pinned state, point-location rotation,
  and facing/hand unit-vector components. These supplement ordinary parameters;
  existing Level, dimensions, quantities, phases and IFC parameters stay in the
  normal parameter list.
- **Hide redundant or empty system parameters** is on for new wizard sessions. Uncheck it
  to restore raw parameter availability. Filtering targets exact built-in
  Category identities and empty, read-only built-in Family Name/Type Name
  records per scope. It never hides arbitrary blank editable or custom
  parameters with those names. Shared/built-in identity handling from the
  existing parameter catalog is retained.

These options apply to the workbook and survive Back/reopening fields, presets,
and XLSX reconstruction (through the existing hidden parameter usage metadata).
Old presets/XLSX files without options retain their saved raw field selections.
The new derived fields are instance-only, explicitly disabled in the grid, and
ignored as write targets during XLSX diffing. Server-side apply also rejects
derived identities. No model transaction or movement is performed to read them.

Coordinate definitions:

- **Internal origin:** `LocationPoint.Point`, internal model axes.
- **Project base point:** the same point minus `BasePoint.Position`. Axes remain
  parallel to internal/project-north axes; this is not a true-north rotation
  or the base point's shared survey values.
- **Shared:** `ActiveProjectLocation.GetProjectPosition(point)`, so translation,
  elevation and rotation use the active shared site. Changing the active site
  changes these values on refresh.

Coordinates use project length units; rotation uses project angle units.
Facing/hand components are dimensionless vectors in internal axes, not distances.
Only point locations provide insertion XYZ. Curve-based and location-less
elements show blank disabled cells with an explanatory tooltip; there is no
implicit centroid, curve midpoint or zero-coordinate fallback. Derived fields
are not offered in Types Mode.

Values are read only for selected fields/output elements. Project-base-point
position and unit formats are cached for an extraction/refresh, with no solid
geometry traversal or extra whole-model collector in discovery.

To roll back the optional behavior in the UI, turn off both API-field offers
and uncheck false-positive filtering, then rebuild the grid. Removing a selected
field through these options is reported. Code changes are uncommitted and
separate from baseline commit `a7e1916`; no model data or parameters are added.

Build sheets, columns, rows, highlighting, disabled cells, formula engine, change tracking.
Parameter column headers show the friendly data type and project unit above the
parameter name. In a combined grid, the Category column is visible.

For category-less generic `ElementType` references (such as Callout Tag),
dropdowns use Revit's `GetSimilarTypes()` plus the current reference, rather than
all generic types in the document. This keeps unrelated arrowheads and other
annotation definitions out of the choices. Type labels prefer the Type Name
parameter and use the API element name when that parameter is missing or empty;
types with neither name still report an explicit error.

Browser initialization starts after the host window loads. ExcelLink creates an
explicit WebView2 environment using the Core assembly referenced by the actual
WPF control, avoiding the default creation-properties path that can mix Revit
2024's WebView2 SDK with a newer SDK loaded by pyRevit or another add-in. Browser
data remains in `%LOCALAPPDATA%\KW\ExcelLink\WebView2`. Initialization failures
are reported in full in pyRevit output before the host closes.

============================================================

## PARAMETER MODE RULES

### Types Mode

- Only type rows
- Only type parameters
- Mixed‑use parameters: instance-only cells blank + disabled
- Type names editable
- Formulas allowed
- No instance parameters shown

### Instances Mode

- Instance rows + duplicated type parameters
- Mixed‑use parameters produce two columns
- Type columns highlighted
- Type columns manual-only (no formulas)
- Instance columns formula-enabled
- Editing a type parameter updates all rows of that type

============================================================

## DATA MODEL REQUIREMENTS

### Row Model

Copilot must generate structures like:
{
ElementId,
UniqueId,
Category,
IsTypeRow,
TypeElementId,
TypeName,
TypeKey,
Parameters: {
ParamName: {
value,
isTypeParam,
isInstanceParam,
isReadOnly,
storageType,
guid,
builtin
}
}
}

### Parameter Usage Map

{
ParamName: {
isType: bool,
isInstance: bool
}
}

============================================================

## UI REQUIREMENTS

### WebView2 Host

- WPF host window
- The modeless command requires a persistent IronPython engine (declared in
  both the command metadata and bundle). Reload pyRevit after changing engine
  metadata so WebView2 and ExternalEvent callbacks remain live after launch.
- The page reports a missing startup workbook, JavaScript errors and rejected
  grid operations visibly. Host delivery/serialization failures show a dialog
  and a full traceback in the pyRevit output instead of leaving a blank grid.
- Workbook messages use Unicode JSON (`ensure_ascii=False`), avoiding the
  IronPython ASCII encoder failure on accented parameter values or names.
- WebView2 control
- Toolbar: Apply Changes, Reload, Sheet Selector
- Message bridge: JS ↔ Python

### Tabulator Grid

- Dynamic columns based on wizard output
- Default widths are 180 px from the third displayed column onward. The row
  number column and first visible data column retain their existing sizing;
  saved and manually resized widths take precedence over defaults.
- Highlight type parameters
- Disable invalid cells
- Dual columns for mixed‑use parameters
- Formula engine integration
- Change tracking array
- Undo/redo for staged grid edits, including cell edits, formulas, bulk edits,
  paste/text operations and XLSX imports. Undo/redo never writes to Revit;
  Apply Changes remains the only write path.

### Wizard progress

- Selection, category and parameter steps show the active scope and relevant
  element/category counts. Parameter selection identifies its position in the
  category sequence and the selected Types/Instances mode.

============================================================

## BATCH APPLY PIPELINE

Copilot must generate code that:

- Groups changes by:
  - TypeElementId (type updates)
  - ElementId (instance updates)
  - ParameterName (mixed‑use)
- Applies in a single Revit transaction:
  - Type updates first
  - Instance updates second
- Refreshes sheets after commit

### Element reference parameters (ElementId storage)

- Cells show human-readable names (e.g. Level name, `Family: Type`,
  Phase name) instead of numeric ids; `<None>` means no reference.
- Editable reference columns use a dropdown of valid names; formulas are
  disabled on these columns. Read-only references (e.g. hosted door Level)
  and the display-only `Family` / `Type` halves stay disabled.
- On apply (and for imported values), names are resolved back to ElementIds
  in Python (`core/element_refs.py`): case/whitespace-insensitive, bare type
  names and numeric ids are accepted when unambiguous. `Family and Type`
  changes use `Element.ChangeTypeId` restricted to `GetValidTypes()`.

### Moving elements between levels

- Level columns (Level, Base Constraint, etc.) are editable where Revit
  allows a move: level-based families (furniture, casework, columns...),
  floors and walls. Changing the level moves the element and keeps its
  offset, the same as Revit's Properties palette.
- Elements exposing two parameters with the same name (read-only schedule
  "Level" plus the editable placement "Level") use the editable one, both
  when reading and when applying.
- Doors, windows and other wall-hosted inserts can change Level. They stay
  hosted and keep their sill height, so they move by the level difference.
  After the changes, each moved insert is checked against its wall's height;
  if it would sit outside the wall, the whole batch is rolled back with a
  message (move or extend the wall in the same apply, or adjust Sill Height).
- Nested family instances and instances hosted on faces, floors, roofs or
  ceilings are locked: their level follows the host. Locked cells show the
  reason as a tooltip, and imports report it.
- Changing a wall's Base Constraint also moves the doors/windows hosted on
  it that sat on the wall's old base level, so they keep cutting the wall.
- Top constraints are editable too: wall Top Constraint (including
  `Unconnected`), column/element Top Level and Base Level, stair Top Level.
  Unset level references still list every level.
- Top Offset is only writable in Revit while Top Constraint is a level, and
  Unconnected Height only while it is Unconnected. These cells stay editable
  in the grid; reference changes (constraints) are applied before numeric
  ones, so both can be changed in one apply. Editing one while the
  constraint does not allow it gives a message explaining what to change.
- Revit can still reject a move (e.g. a wall base above its top
  constraint); the whole batch then rolls back with Revit's message.

### Saving workbooks

- **Export XLSX** writes `.xlsx` by default (`core/xlsx_export.py`, no
  external dependencies); `.json` remains available in the save dialog.
- XLSX layout follows the selected grid layout (separate category worksheets
  or one combined worksheet). Row 1 contains parameter data types and units;
  row 2 contains parameter names; element data starts on row 3. Freeze the
  first two rows and apply AutoFilter to row 2. Type columns are highlighted
  and read-only cells greyed. Element ID, Unique ID and Type Element ID are
  kept as hidden columns, and a very-hidden `_ExcelLink` sheet maps each
  column by its stable parameter key and target for re-import.
- The current workbook schema is required; legacy ExcelLink XLSX schemas are
  not supported. Combined worksheets record their category list and stable
  combined sheet identity.
- Values are saved (not grid formulas).

### Units

- All Double values are shown, edited, exported and imported in the
  project's display units (Manage > Project Units), never Revit internal
  feet/radians (`core/units.py`).
- Values are rounded to the project unit accuracy for display; column headers
  show the unit symbol, e.g. `Width (Type) [mm]`.
- On apply, edited values are converted back with
  `UnitUtils.ConvertToInternalUnits` using the same project unit.
- Genuinely unitless numeric parameters remain unchanged. Unresolved data types,
  invalid project units/accuracy and conversion failures are errors, never a
  fallback to internal units. Extraction stops with an error; failures during
  Apply Changes roll back the entire batch and are reported in the grid and
  pyRevit output.
- Unit-symbol lookup failures are logged as warnings and use the unit's Forge
  type ID in headers instead. Numeric conversion remains active.

### Importing edited XLSX

- Step 1 option **Import XLSX...** opens a file picker for a workbook
  previously written by Export XLSX (the `_ExcelLink` sheet is required).
- The parameter mode, categories, parameter order and elements are read from
  the file (`core/xlsx_import.read_import_plan`); elements are found by
  Unique ID, falling back to Element ID. The grid is rebuilt from current
  Revit values (`core/workbook_builder.build_import_workbook`).
- `core/xlsx_import.diff_xlsx` compares each cell with Revit. Differences on
  editable cells become pending changes, highlighted in the grid with the
  Revit value shown on hover; nothing is written until **Apply Changes**.
- Headers are matched by title and unit; a column whose unit changed is
  skipped. Reference values (Level, Family and Type) are matched by name.
  Conflicting values for the same type, invalid values and edits to
  read-only cells are skipped and listed in the pyRevit output window.
- The datagrid also has an **Import XLSX** button for the round trip
  "Export XLSX > edit in Excel > save > Import XLSX" without closing the
  grid. The picker defaults to the last saved/imported file, and the file can
  stay open in Excel. If the file's sheets and parameters fit the current
  grid, the grid is refreshed from Revit and the file's differences are
  highlighted; otherwise the grid is rebuilt from the file. Unapplied grid
  edits are replaced by the import (the user is asked first).

### Presets (reusable grid settings)

- **Save Preset** in the datagrid stores the selection mode, parameter mode,
  grid layout (separate or combined), categories, ordered parameter keys and per-sheet layout (user-resized column
  widths and sorting, keyed by column title) as JSON. No element data is
  stored, so presets work in any project or view (`core/presets.py`,
  `ui/preset_dialogs.py`).
- Personal presets live in `%APPDATA%\KW\ExcelLink\presets`; settings
  (default preset, shared folder) in `%APPDATA%\KW\ExcelLink\settings.json`.
  An optional shared/team folder is also listed (marked `[shared]`); a
  personal preset hides a shared one of the same name. Saving asks which
  folder to use when a shared folder is set.
- Step 1 lists **Open default preset: <name>** (when a default is set),
  **Load Preset...** and **Manage presets...** (set/clear default, delete one
  or more presets in a single operation, set/clear shared folder, open folder).
  Loading either a named or default
  preset first asks for a fresh selection mode, then skips Steps 2–4 and
  opens the grid (`workbook_builder.build_preset_workbook`). Its saved
  columns, order, filters, sorting and formulas apply to the newly collected
  elements; the active schedule's defaults do not overwrite the preset.
- Categories match by `BuiltInCategory` name (e.g. `OST_Doors`), falling back
  to the display name. Missing categories or parameters are skipped and
  listed in the pyRevit output window.
- Each sheet layout also stores its filters (search, Show, column filters,
  value checklists and advanced rules), keyed by column title.

### Column formulas

The toolbar groups import/export/preset actions under **File**, text and bulk
edits under **Edit**, and visible-row selection/isolation actions under
**Revit**. Sheet, Back, Apply Changes, Reload and Close remain immediately available.
**Close** exits the tool, asking for confirmation before discarding unapplied
changes. Closing is blocked while a grid edit or Revit operation is in progress.
Reload resolves the workbook's saved source element ids against the active
document before rebuilding sheets. Elements deleted since the grid opened are
omitted and reported in the grid status instead of using stale Revit objects.
The **Formulas** toggle opens/closes the formula bar (collapsed on launch)
without discarding its draft expression or saved templates. Search and filter
controls stay in a separate compact row. Menus close on outside click/Escape.

Column headers wrap to at most two text lines (with the filter row below),
keeping formula letter badges and
column-menu buttons visible. The sort/filter dropdown button sits at the
right-hand end of each column's filter input.

- The formula bar offers eligible type parameter columns in Types Mode and
  instance parameter columns in Instances Mode, an expression, and **Visible
  rows** (default) / **All rows** scope. Type parameters remain manual-only in
  Instances Mode. Type Name is also formula-enabled in Types Mode only.
  ElementId references are excluded; read-only
  rows are skipped.
- In Types Mode the formula panel includes an inline reminder that type
  changes affect all instances, including those outside the workbook.
  Applying a type formula requires no additional confirmation dialog.
- Type Name formulas produce trimmed, nonblank text, for example
  `="Panel "&B1&" x "&C1`. Referencing the destination Type Name cell itself
  (e.g. `="Prefix "&A1` in column A) is circular, not a reference to its old name.
  Use Find/Replace for prefixing existing names instead.
- Proposed duplicate type names stay staged for correction. Conflicting Type
  Name cells turn red (ahead of normal yellow pending highlighting), with
  tooltips identifying the other type and its ID. An inline conflict summary
  blocks Apply Changes without opening a confirmation dialog. Names are checked
  within their family/system-type scope, including document types outside the
  workbook. This covers manual edits, formulas, paste/fill/text tools, undo/redo,
  and imported XLSX values in both parameter modes.
- Apply revalidates names against the current document before any writes.
  Valid rename swaps/chains use temporary names inside the existing atomic
  transaction; failures roll everything back. Filtered Apply cannot omit a
  rename needed to free a name: clear the filters and apply the complete batch.
- Write the expression for original row `#1`, e.g. `=B1*C1` or
  `=SUM(B1:C1)`. The leading `=` is optional in the formula bar: `B1*C1`
  and `SUM(B1:C1)` work too. Saved templates retain the standard `=` prefix.
  Direct cell entry still requires `=` to distinguish formulas from text.
  Applying it fills the column, adjusting relative row
  references for each original row number, regardless of sorting/filtering.
  `$B$1` / `B$1` keep the referenced row fixed; quoted strings are unchanged.
- **Apply formula** validates results before staging changes; circular
  references, Formula.js errors, non-scalar results and invalid numeric
  values abort the formula batch. Results are highlighted pending changes.
  **Apply Changes** is still required to write them to Revit.
- Active formulas recalculate when their source cells are edited. A manual
  edit or Set value replaces the formula in that cell; reapplying the
  column formula fills it again. **Remove formula** stops that column's
  recalculation and removes its template, keeping current values/changes.
- **Save Preset** stores each sheet's column templates, scope and referenced
  column titles (not element IDs or results). Loading a preset restores the
  formula bar without generating edits; choose the column and click
  **Apply formula** to review results. References are remapped by title if
  the column order changes; missing references report an error.
- Expressions use project display units. XLSX export continues to write
  calculated values, not formulas. Range clipboard operations also transfer
  values only; drag-fill is disabled. **Set value...** fills literal values.

### Range selection and Excel clipboard

- Status messages reserve a fixed two-line area above the grid, including when
  empty, so appearing/clearing messages do not move or resize the grid. Longer
  messages scroll within that area, which supports keyboard focus.
- Drag across cells to select one rectangular range (or extend it using
  Shift and the arrow keys). Click a row-number cell to select a whole row.
  Click a cell and start typing to replace its content; F2, Enter or
  double-click edits the existing content. Enter/Shift+Enter commits and
  selects the row below/above; Tab/Shift+Tab commits and selects the next/
  previous column, wrapping to the next/previous displayed row at the edge.
  Navigation stops at the grid boundaries and may select read-only cells,
  which cannot be edited. Escape cancels an open edit. Reference fields keep
  validated dropdowns; numeric input accepts finite project-unit values or
  permitted formulas, never partial/invalid numbers.
  Header sorting uses the sort icon or
  column menu so it does not interfere with selection.
- **Ctrl+C** copies the selected range's current values as tab-separated text,
  without headers, formatting or formula expressions. Quoted tabs, multiline
  text, quotes and Unicode are supported. Literal text that Excel could
  interpret as a formula is prefixed with an apostrophe for safety.
- **Ctrl+V** pastes an Excel block starting at the selected range's top-left
  cell, using the visible columns and currently displayed (sorted/filtered)
  row order. Hidden rows are not paste destinations. No rows or columns are
  added; blocks extending past the grid fail instead of truncating or wrapping.
- **Ctrl+D** or **Fill down** in the range context menu copies each column's
  top selected value to the selected rows below it, in displayed sorted/
  filtered order. Select at least two rows, including the source row.
  Finish or cancel any open cell editor first.
  Formula sources supply calculated values, not relative formula copies.
  Locked destinations are skipped and counted; unchanged cells are not
  staged unless their active formula is being replaced by a literal value.
  Validation, shared-type confirmation/propagation and pending-change
  safeguards are the same as paste. A fill is one grid undo step and never
  writes to Revit until Apply Changes.
- The whole block is validated before staging any edits. Locked cells,
  including the row-number column, are skipped and counted. Editable numeric
  values must be finite, use project display units and have no unit suffix or
  thousands separators; Integer parameters must fit a Revit 32-bit integer.
  ElementId values must exactly match an unambiguous dropdown name. Formula
  expressions are rejected, including when pasted into an open cell editor.
  Excel normally supplies calculated results on its plain-text clipboard.
- Conflicting values for the same shared type parameter reject the entire
  paste. Matching shared values are staged once per type; confirmation warns
  that all instances of that type, including filtered/unselected ones, share
  the change. Corresponding grid rows are updated consistently.
- Pasting replaces affected cell formulas with literal values and recalculates
  dependent grid formulas. Pasted edits use the existing pending-change
  highlighting and **Apply Changes** pipeline; clipboard operations never
  write directly to Revit. Native copy/paste in search/header/formula controls
  is unchanged. Cut, drag-fill and multi-range clipboard operations are not
  enabled.

### Find/Replace and case conversion

- Right-click inside a selected range to preserve it and open **Copy values**,
  **Paste values**, **Fill down**, **Find / Replace...** and **Change case**. Right-clicking
  outside the range targets the clicked cell instead. Clipboard menu actions
  use browser clipboard access; a denied/unavailable permission is reported
  with guidance to use Ctrl+C/Ctrl+V instead.
- **Edit > Find / Replace...** or **Ctrl+H** opens the same dialog. Default
  scope is **Selected range**; **All visible cells (this sheet)** includes
  only visible columns/rows after the current filters, not other sheets.
  Both text tools also offer **Current column(s) (visible rows)**: selecting
  AA6 targets column AA, while AA6:AC6 targets AA, AB and AC, across all rows
  remaining after the current filters. Filtered-out rows are excluded
  (shared-type edits still affect every instance of the type).
  Find/replace defaults to literal text with **Match case** and **Whole cell**
  options. It replaces every occurrence in each matching cell. An empty find
  is invalid; an empty replacement deletes matches. With **Use regular
  expressions (regex)** unchecked, `$` and regex characters are literal.
  When checked, Find accepts JavaScript regex syntax without `/` delimiters;
  replacement supports capture references such as `$1`, `$2`, `$<name>` and
  standard JavaScript replacement tokens (`$&`, `$$`, etc.). Whole cell
  requires the entire value to match; Match case controls case sensitivity.
  Invalid patterns display an error and cannot be staged. Replacement
  results are never evaluated as formulas.
- **Change case** offers **UPPER**, **lower**, **Title** and **Sentence** for
  the selected range or current column(s) (also accessible from
  **Edit > Change case...**).
  Title case lowercases each word then capitalizes its first letter, retaining
  apostrophes inside words; it does not preserve acronyms. Sentence case
  lowercases the text and capitalizes the first letter and the next letter
  following each `.`, `!` or `?`; it does not infer abbreviations.
- Both dialogs allow **Stage changes** without first using **Preview**.
  Staging validates the current options and grid values; invalid input stays
  in the dialog with an error. **Preview** optionally shows a count and up to
  eight before/after examples. Changing inputs clears the preview. Case
  conversion previews immediately. Cancel/Escape never stages edits.
- Only editable String parameters and editable type names participate.
  Locked, numeric, element-reference and null-valued cells are counted as
  skipped. Unchanged results do not create pending edits. Blank resulting
  type names and conflicting results for a shared type reject the plan.
  Shared changes are deduplicated and require confirmation because every
  instance of that type (including hidden ones) shares the result.
- Staging uses the same pending-change pipeline as range paste. It replaces
  affected cell formulas with literal results, recalculates dependencies,
  and highlights edits; **Apply Changes** is still required to write to Revit.
  Existing pending edits and their original values are retained.

### Filtering

Filters are per sheet (`web/filters.js` holds the matching logic; `app.js`
the UI). The sheet list marks filtered sheets with "(filtered)".

- **Header filter row** under every column. Syntax: text = contains, `=x`
  equals, `=` empty, `!=` not empty, `!x` excludes, `>5 >=5 <5 <=5`,
  `2..8` between, `^start`, `end$`, `* ?` wildcards, `/regex/`, `a|b`
  either. Numbers compare numerically, text ignores case.
- **Column menu** (▾ in each header): sort, a condition editor, and an
  Excel-style checklist of distinct values (counts are for rows passing the
  other filters; `(Blanks)` for empty cells).
- **Search** box (Ctrl+F) matches any visible column.
- **Show**: all rows, rows with/without pending changes, rows with editable
  cells, read-only rows, and type/instance rows when a sheet mixes both.
  **Top-level instances** is available in Instances Mode; it hides instances
  nested inside another family.
- **Advanced filter...**: AND/OR rules with one level of nested groups.
- A summary bar shows "Showing X of Y rows", the pending changes hidden by
  filters, and removable chips for every active filter; **Clear all**.
- A frozen `#` column numbers rows in their original order. Formula
  references such as `B12` use these row numbers, so they stay correct when
  the grid is sorted or filtered.
- **Apply Changes** applies only changes in visible rows. When changes are
  hidden by filters, the user is warned and can go back to the filters; held
  back changes stay pending after the apply.
- **Set value...** writes one value to a column for every visible row
  (shared type values are set once per type; formulas are not allowed).
- **Select in Revit**, **Isolate in view** (temporary isolate, inside a
  transaction so it is one Undo step) and **Reset view** act on the visible
  rows; type rows map to their instances (`core/revit_view.py`).
- **Export XLSX** asks whether to save only the visible rows when filters
  are active.

============================================================

## FILE STRUCTURE (REQUIRED)

YourExtension.extension/
ParamGrid.tab/
Tools.panel/
ParamGrid.pushbutton/
script.py
ui/
host.xaml
host.xaml.cs
web/
index.html
app.js
styles.css
libs/
tabulator.min.js
hyperformula.min.js
core/
selection.py
extract.py
parameter_map.py
column_builder.py
apply_changes.py
types.py
persistence.py

============================================================

## WHAT TO GENERATE

Copilot should generate:

- Python scaffolding for each wizard step
- Parameter extraction logic
- Mixed‑use parameter detection
- Column builder for both modes
- JS Tabulator setup
- JS change tracking
- JS → Python message bridge
- Batch apply transaction logic
- Type renaming logic
- Sheet/workbook persistence

Copilot must NOT generate unrelated code or simplify the architecture.

============================================================

## STYLE

- Use clear, modular functions
- Avoid monolithic scripts
- Prefer pure functions for extraction and mapping
- Keep UI logic separate from Revit logic
- Use comments to explain mixed‑use handling

============================================================

Generate code, scaffolding, and helper functions that strictly follow this architecture.
