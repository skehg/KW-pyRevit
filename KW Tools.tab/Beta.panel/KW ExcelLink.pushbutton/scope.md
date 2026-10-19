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
- Builds one sheet per category
- Allows custom parameter column selection and ordering
- Supports two parameter modes: Types Mode and Instances Mode
- Uses a wizard flow before opening the datagrid

============================================================

## WIZARD FLOW (MANDATORY)

Steps 2-4 have **Back** and **Cancel**, retaining scope, categories, mode and
each category's ordered field list while navigating. For multiple categories,
Back in Step 4 revisits the previous category; Back from the first category
returns to Step 3. Step 1 has Cancel (there is no preceding step).

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
- Import edited XLSX... (see "Importing edited XLSX"; skips Steps 2–4)

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
Each category becomes its own sheet.

### Step 3 — Parameter Mode

User chooses:

- Types Mode
- Instances Mode

### Step 4 — Parameter Selection

For each selected category:

- Build a parameter usage map:
  - isType
  - isInstance
  - mixed‑use
- User selects parameters to include by moving them from an available-parameters
  list into a selected-datagrid-columns list
- User can remove selected columns and reorder the selected list with up/down
  controls
- Mixed‑use parameters:
  - Types Mode → show only type column; instance-only blank/disabled
  - Instances Mode → show two columns: “ParamName (Type)” and “ParamName (Instance)”

### Step 5 — Datagrid Opens

Build sheets, columns, rows, highlighting, disabled cells, formula engine, change tracking.

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
- Highlight type parameters
- Disable invalid cells
- Dual columns for mixed‑use parameters
- Formula engine integration
- Change tracking array

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
- XLSX layout: one worksheet per category, frozen bold header row with
  filters, highlighted type columns, greyed read-only cells. Element ID,
  Unique ID and Type Element ID are kept as hidden columns, and a very-hidden
  `_ExcelLink` sheet maps each column to its parameter/target for re-import.
- Values are saved (not grid formulas).

### Units

- All Double values are shown, edited, exported and imported in the
  project's display units (Manage > Project Units), never Revit internal
  feet/radians (`core/units.py`).
- Values are rounded to the project unit accuracy for display; column headers
  show the unit symbol, e.g. `Width (Type) [mm]`.
- On apply, edited values are converted back with
  `UnitUtils.ConvertToInternalUnits` using the same project unit.

### Importing edited XLSX

- Step 1 option **Import edited XLSX...** opens a file picker for a workbook
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
  categories, ordered parameters and per-sheet layout (user-resized column
  widths and sorting, keyed by column title) as JSON. No element data is
  stored, so presets work in any project or view (`core/presets.py`,
  `ui/preset_dialogs.py`).
- Personal presets live in `%APPDATA%\KW\ExcelLink\presets`; settings
  (default preset, shared folder) in `%APPDATA%\KW\ExcelLink\settings.json`.
  An optional shared/team folder is also listed (marked `[shared]`); a
  personal preset hides a shared one of the same name. Saving asks which
  folder to use when a shared folder is set.
- Step 1 lists **Open default preset: <name>** (when a default is set),
  **Load preset...** and **Manage presets...** (set/clear default, delete,
  set/clear shared folder, open folder). Loading either a named or default
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

Column headers wrap to at most two text lines (with the filter row below),
keeping formula letter badges and
column-menu buttons visible. The sort/filter dropdown button sits at the
right-hand end of each column's filter input.

- The formula bar offers eligible instance parameter columns, an expression,
  and **Visible rows** (default) / **All rows** scope. Type parameters and
  ElementId references remain manual-only; read-only rows are skipped.
- Write the expression for original row `#1`, e.g. `=B1*C1` or
  `=SUM(B1:C1)`. Applying it fills the column, adjusting relative row
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
  calculated values, not formulas. Range selection and drag-fill are not
  part of the column-formula workflow; **Set value...** fills literal values.

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
