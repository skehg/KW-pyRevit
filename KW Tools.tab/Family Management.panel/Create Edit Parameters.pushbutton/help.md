# Parameter Editor

Parameter Editor lets you create, edit, sort, reorder, batch edit, and import family parameters in the Family Editor.

## Main areas

- Left panel: searchable parameter grid with collapsible groups, optional formula search, and group filtering.
  - Groups follow the names in `lib/RevitGroupOrder.txt` in all supported Revit versions, not alphabetical or internal ID order. Only groups present in the family appear; unlisted groups follow the known sequence alphabetically. Reopen the tool after changing that file.
  - The group filter uses the same sequence. Parameter order within each grid group is preserved.
- Tabs on right:
  - Edit Existing Parameter / Batch Edit (leftmost, depending on selection)
  - Create New Parameter
  - Import Parameters

The Edit Existing Parameter tab is shown for a single selection (or no selection).
Selecting multiple parameters hides it and shows Batch Edit instead. If either
edit tab is active, the editor switches to the other as the selection changes;
other active tabs stay open.

## Edit Existing Parameter

- Rename parameters.
- Change group.
- Toggle Instance/Type for non-shared parameters.
- Edit current value for the current type.
  - In the grid, double-click a Value cell or press F2. Enter, Tab, or leaving the cell commits the edit; Escape cancels it.
  - In the Edit pane, change Current Value and click Apply Value.
  - Family-type parameters offer Revit's allowed nested-family choices as `Family Name : Type Name`.
  - Yes/No parameters use checkboxes; other values use text entry, including document units for numbers.
  - Formula-driven and read-only values stay locked. Each successful value edit is an Undo-able transaction.
  - Only the current family type is changed; values and dependent results refresh after saving. Invalid edits show an error without saving.
- Edit formula with syntax highlighting and autocomplete.

## Create New Parameter

- Create family or shared parameters.
- Choose discipline, type, group, and instance/type mode.
- Optional formula entry with autocomplete.

## Sort Parameters

- Right-click a grid group header to sort that group by name A-Z or Z-A.
- Type then Instance options keep type parameters first, sorting names within each scope in the chosen direction.
- Sorting applies to the entire group, including parameters hidden by search or filtering. Other groups keep their order.
- Right-click sorting is a grid-only preview; it does not change Revit yet. Left-click still collapses or expands the group.
- **Apply Sorting** at the bottom saves all pending sorting and manual reordering in one Undo-able transaction.
- **Reset Sorting** discards all pending sorting and manual reordering and returns to the current saved Revit order. It does not undo ordering that has already been applied.
- Closing with pending sorting prompts to apply, discard, or cancel closing.
- Other edits still save immediately. Pending sort choices are reapplied to the current parameters after those edits; deleted or unchanged groups no longer need applying.

## Reorder Parameters

- Select rows in the grid and use **Top**, **Up**, **Down**, or **Bottom** beneath the grid.
- Multiple selections move within each group independently; parameters never move between groups. Up/Down moves each selected block one position, preserving selection order.
- Reordering is a preview, saved or discarded with the same **Apply Sorting** and **Reset Sorting** buttons.
- Preview moves update an observable collection in place, keeping the grid view and loaded rows without a full view reset, parameter-value reload, or editor rebuild for each selected row.
- Search disables the arrows to avoid moving past hidden parameters; hover over a disabled arrow for the reason. Group filtering still permits reordering.
- A manual move replaces a pending alphabetical sort for that group; a subsequent right-click sort replaces its manual order.
- Renames preserve manual ordering by parameter ID. Deleted or moved-out parameters are removed from the preview; new or moved-in parameters follow existing manually ordered members.
- Status messages appear on a separate row beneath the footer buttons.

## Batch Edit

- Toggle scope for multiple parameters when valid.
- Move groups in bulk.
- Find/replace plus prefix/suffix rename.
- Duplicate or delete selected parameters.

## Import Parameters

- Import parameters, nested families, and object styles from a source family.
- Filter import lists and choose transfer options.

## Tips

- Formula suggestions come from existing family parameter names.
- Keep formulas balanced; bracket feedback highlights issues while typing.
- Some operations are restricted by Revit API/version rules and shared parameter constraints.
