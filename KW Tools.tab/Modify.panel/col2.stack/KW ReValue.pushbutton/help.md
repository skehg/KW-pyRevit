# KW ReValue

KW ReValue renames element types or instances by combining source tokens and parameter values.

## Pattern syntax

A pattern combines literal text with placeholders. Token expressions read source text split by the configured token delimiters; token positions start at 1.

- Single tokens: `{val1}` (first token), `{end}` (last token), `{end-1}` (second-to-last token).
- Ranges: `{val1:4}` (tokens 1 through 4), `{val2:end}` (token 2 through last), `{val1:end-1}` (all but the last token), `{end-2:end}` (last 3 tokens), and `{end-3:end-1}` (from the fourth-to-last through the second-to-last token).
- Relative ranges: `{val3:+2}` (token 3 and the next 2 tokens) or `{end-3:+1}` (the fourth-to-last token and the next token).
- Add `|delimiter` to any token expression to join its selected tokens with a different delimiter: `{val1:end|space}`, `{val1:4|-}`, `{end-2:end|underscore}`, or `{val2:end|/}`. Without it, selected tokens are joined with `-`.
- Named delimiters are `space`, `hyphen`, and `underscore`. Literal delimiters such as `-`, `/`, and `.` are also supported. Quote custom separators in Advanced Pattern to preserve surrounding spaces: `{val1:3|" - "}`. Quoted separators use JSON escapes: `\"` for a double quote and `\\` for a backslash. For example, `{val1:3|" \" "}` joins with space-quote-space, and `{val1:3|"\\"}` joins with a backslash. Apostrophes need no escaping. `""` joins without a separator, while `"space"` inserts the literal word rather than the named space delimiter. Case conversion follows the closing quote, for example `{val1:3|" - "~upper}`. Invalid quoted syntax shows a preview error, not a silently altered separator. Use `\u007b` / `\u007d` for braces inside a quoted separator so they do not terminate the placeholder.
- Append `~upper`, `~lower`, `~title`, or `~sentence` to a placeholder to convert its value: `{val1:3|space~upper}`, `{val1~lower}`, `{param1~title}`, or `{orig~sentence}`. Token ranges are selected and joined before conversion.
- `{param1}` through `{param5}` substitute the five selected parameters.
- `{param6}` and `{count}` use the configured counter.
- `{orig}` inserts the complete, un-tokenized source (good for find/replace).
- `{inc:val3:1}` increments token 3 independently for each row; `{inc:param1:-1}` decrements parameter slot 1.
- `{seq:val3:1}` starts with token 3 from the first unfiltered preview row and advances by row position.
- Increment and sequence expressions accept a single `{valN}` or `{param1}` through `{param5}` source and a signed integer step, not a token range. Zero is allowed; `{seq:val3:-1}` counts backward from the first row's token 3. Numeric values keep their digit width (`009` plus 1 becomes `010`), alphabetic values roll over (`Z` to `AA`), and prefixed numeric values keep their prefix (`RM09` plus 1 becomes `RM10`). Negative numeric and prefixed results preserve their width (`RM01` minus 2 becomes `RM-01`). Alphabetic values cannot decrement below `A`; blank or unsupported values remain unchanged and show a preview warning.

The counter is used only when the pattern contains `{count}` or `{param6}`. Its configured increment must be nonnegative.
The **Final Case** dropdown converts the complete generated value, including literal text, after Find/Replace. Options are None, upper, lower, title, and sentence. It is separate from per-placeholder modifiers.

## Workflow

1. Optionally select elements in Revit.
2. Open KW ReValue.
3. Choose mode:
   - Type mode: works on element types.
   - Instance mode: works directly on selected instances.
4. Expand **More Settings** to adjust token delimiters if required.
5. Choose a source parameter, or keep the bracketed **Default** option to use the element/type name.
6. In **More Settings**, pick up to 5 parameters for substitution.
7. Build a pattern in **Tokens**, or choose **Advanced Pattern** to enter syntax directly. The sliding switch beside the pattern is labelled with the action it will perform: click **Source** to use `{orig}` (the complete source value), then click **Pattern** to restore your previous pattern (kept while the dialog is open, including after applying changes). The switch is grey with its thumb on the left when off, and green with its thumb on the right while Source is enabled. Editing the pattern while Source is enabled turns the switch off, changes its label back to **Source**, and keeps your edit; the next switch remembers that new pattern.
8. Optionally set the counter in **More Settings** and final find/replace in the main controls.
9. Review Current Value and New Value in the preview. Rows with different values are highlighted pale yellow.
10. Optionally type into the Current Value and New Value header filters, then click Apply Re-Value. Only rows remaining in the filtered preview are eligible to be changed, including rows below the scroll area.
11. After the result message, the dialog stays open and reloads current values from the model. Find and Replace are cleared, and Final rows are unfrozen so the next preview is recalculated. Pattern, mode, parameter choices, counter settings, case options and filters are preserved. Filters are re-evaluated against the updated values, so changed rows may no longer be visible.
12. Repeat as needed, then click **Close**. Closing does not apply pending changes or undo earlier applies.

## Visual token editor

Palette and composition tokens use compact sky-blue pill buttons with semicircular ends (22 high, radius 11). A soft vertical gradient, fine highlight and small shadow give them a raised appearance. Icons and labels identify token kinds; a dark outline marks the selected token, with lighter hover feedback. Pressed tokens use darker shading without a shadow to appear pushed down.

- **Tokens is the default interface** when ReValue opens. The pattern field shows generated syntax and is read-only in this mode. **Advanced Pattern** makes it editable and hides the palette/bar. Unsupported saved expressions or unmatched braces open in Advanced Pattern with an explanation; the original text is never discarded or simplified. Return to Tokens after correcting the expression.
- The palette and bar labels sample the **selected grid row**. For a selected cell range or multiple rows, they use the **topmost selected row in the displayed order**, regardless of selection direction. With no selection they use the first visible row after filtering; with no visible rows the palette has no sample values. The read-only token display in More Settings follows the same row. Source chips store token positions, not the sample words. Each row uses its own source values. Source, delimiter and mode changes refresh the labels without changing the pattern; `(missing in sample)` does not imply the token is missing in every row. Selection refreshes only sample labels, using the cached source text; it does not recalculate previews, counters or sequence seeds.
- Drag a palette item into the ReValue bar to copy it. Drag a bar chip to reorder it. A blue edge marks the insertion gap, including on wrapped lines. Dropping outside the bar or pressing Esc cancels the drag. The bar scrolls when dragging near its top or bottom.
- Clicking a palette item adds it after the selected chip, or at the end when no chip is selected. **+ Add** provides the same choices, including arbitrary source positions and ranges. Click a bar chip to select it; double-click to edit. Right-click (or Shift+F10) opens its menu, including **Duplicate**, **Move Left**, **Move Right**, and **Remove**. Delete removes a focused chip.
- Separators are explicit **Text** chips: adjacent chips concatenate without automatic punctuation. Palette shortcuts add a space, hyphen or underscore. **Text...** opens an editor for other literal text, preserving leading/trailing spaces. Chip labels quote literal values; tooltips show their character count. Braces are reserved for expressions in Tokens mode; use Advanced Pattern for brace text.
- Source settings use compact **Start / End** direction toggles beside numeric positions; no `val` or `end` typing is required. Positions are 1-based in both directions: End 1 is the last token (`end`), End 2 is second-last (`end-1`). Enable **Include a range** to choose its endpoint and join separator. The endpoint also offers **Following**, meaning additional tokens after the start (0 allowed); Start 3 through Following 2 generates `{val3:+2}`, three tokens total. A live selection hint shows the equivalent syntax. Existing patterns populate these controls automatically; Advanced Pattern syntax is unchanged. Range menus offer hyphen, space, underscore or custom join separators. Enter custom text exactly in the join field, including spaces, quotes or backslashes, without wrapping quotes or manual escaping. The editor generates quoted/escaped syntax automatically when needed. Named choices `space`, `hyphen` and `underscore` retain their existing meanings.
- Non-text chips offer **Text Case**. **Progression** is available for absolute single `valN` chips and parameter chips, not ranges, joins or end-relative positions. **Increment Each Value...** with step `2` generates `{inc:val1:2}` for token 1; **Sequence from First Row...** generates `{seq:val1:2}`. Signed integer steps and existing alphabetic/prefixed numeric behavior are unchanged. The settings dialog validates unsupported combinations.
- Parameter chips show both their slot and parameter name. There are **five shared slots**, matching More Settings. Choosing an already mapped parameter reuses its slot; otherwise an empty slot is selected. When all slots are occupied, explicitly choose a slot to reassign. Reassignment changes every chip using that slot. Unmapped/unavailable slots are reported above the bar; edit the chip or the mappings in More Settings.
- Counter settings are **shared** with More Settings and all Counter chips. Repeated Counter chips insert the same counter value within a row, not independent counters. A new counter starts with the existing configured settings; double-click it to adjust them.
- Settings dialogs edit a draft. **Cancel** or closing the dialog discards text, parameter mapping and counter changes together. Confirmed edits update the preview once; dragging/configuring chips never modifies the model.
- Existing Find/Replace, Final Case, frozen Final rows, preview filters, sequence ordering and Apply behavior remain unchanged. The compact token area scrolls independently; Tokens mode uses a taller minimum window size to preserve preview space.

## Choosing elements

- Existing preselection opens ReValue directly, unchanged.
- With nothing selected, choose **Select on Screen** or **Select Categories**. Close the choice window, cancel the category picker, or press Esc during screen selection to exit without changing the model.
- **Select Categories** opens a separate picker with **Current View** selected by default. Toggle to **Entire Project** to collect from the active document instead. Current View uses Revit's view collection, not the zoomed screen area; elements inside linked documents are excluded. If the active view cannot collect elements, Current View is disabled and the picker explains that Entire Project is selected.
- Check one or more categories. Highlight a category to load its families; **All families** is the default. For a subset, choose **Selected families only** and check the desired families. Each category has its own family choices. System families are grouped using their type's family name; categories without family grouping (including views and sheets) can be included as a whole.
- Search boxes only narrow the lists shown in the picker; they do not clear checked choices. The summary and matching-element count describe the complete selection.
- On the first scope change, available choices carry across. Unavailable categories/families are reported, and a family restriction with no matches stays restricted rather than becoming All families. Returning to a previously visited scope restores its own choices. **Use Selection** is disabled until every checked, restricted category has at least one matching family.
- Category counts are cached per scope. Families load only when a category is highlighted or an existing family restriction needs checking in a new scope, with names resolved once per distinct type. Only the final matching element IDs are resolved into the ReValue selection when clicking **Use Selection**. The first collection in a large project or view can still take time.
- The category picker module is loaded only when requested; preselection and screen selection do not load it.
- **Type mode changes are project-wide for the affected types:** instances outside the selection or chosen scope can also be affected. Use Instance mode for instance parameters, views, and sheets. The preview and its filters still control which element/type rows Apply can modify.

## Layout

- Mode, Source Parameter, the editor selector/generated pattern and Find/Replace stay visible above the full-width preview. Tokens mode adds the palette and composition bar.
- **More Settings** starts collapsed and contains shared parameter mappings, token delimiters, the shared counter and the original read-only token display. Collapsing it does not reset any values.
- When expanded, drag the horizontal divider to adjust the balance between More Settings and Preview. The settings area scrolls independently when space is limited.
- Collapsing More Settings returns the available space to the preview; reopening it restores the default settings/preview split.
- **Help** is at the bottom left, on the same row as **Apply Re-Value** and **Close** at the bottom right.

## Default source

- The first Source Parameter option shows the system default instead of a blank entry: `<Default: Type Name>` in Type mode, or `<Default: Sheet Name>` for sheets and `<Default: View Name>` for other views in Instance mode.
- Instance mode also shows `<Default: Type Name>` for instances whose default name matches their type name, as well as element types themselves. Instances with their own distinct name show `<Default: Name>`. Mixed selections with different name sources show `<Default: Name (varies by element)>`.
- The label updates when switching modes. It is a system option, not a parameter: choosing it preserves the existing name-based preview and Apply behavior.
- Actual parameters remain separate choices, even if their names contain brackets. The default is still stored as an empty source setting internally, so existing session settings remain compatible.

## Find/Replace

- Find/Replace runs on the final generated value and treats both Find and Replace as literal text (not regular expressions).
- **Match Case** requires matching uppercase/lowercase letters. It starts checked to preserve the existing behavior; uncheck it to ignore case.
- **Match Whole Word** prevents matches inside longer words. Letters, digits and underscores count as word characters; spaces and hyphens separate words. For example, finding `Door` matches `Door-A` but not `Doorway` or `Door_A`.
- Both options can be combined and are remembered for the current Revit session. Changing either option updates the preview immediately, except for frozen Final rows.
- Find and Replace text is cleared after each completed apply (including an apply with individual failed rows); the matching options are preserved. If there are no changes, editing is incomplete, or the operation errors out, the text is kept for correction or retry.

## Preview filters

- Expand **More Settings** and click **Edit Filters...** under **Filter by Parameter**. The main dialog only shows a compact summary; the rules are edited in a separate window.
- **+ Add Condition** adds a Parameter / Condition / Value row. **+ Add Group** adds a nested group. Choose **All conditions (AND)** or **Any conditions (OR)** for each group; check **Exclude this group (NOT)** to reverse it. Use Remove or Remove Group to delete individual entries. New groups default to AND.
- **Use Filters** validates and applies the draft to the preview. **Cancel** or closing the editor discards draft changes without affecting active filters. **Clear All** clears the draft; confirm with Use Filters. The main dialog's **Clear** button removes the active parameter filters immediately.
- **Advanced expression (optional)** shows the equivalent editable expression. Valid edits update the visual rules; invalid edits show a location-specific syntax error and disable Use Filters and visual edits until corrected or cleared. Invalid drafts never replace active filters.
- Syntax uses Revit-style logical functions, not native Revit formulas: `AND(condition, ...)`, `OR(condition, ...)`, `NOT(condition)`. Parameters use `[Name]`; a literal `]` within a name is escaped as `]]`. Text uses double quotes with JSON escapes (for example `\"` and `\\`). Functions ignore case, and parentheses can also wrap a condition or group. AND/OR need at least one condition; NOT needs exactly one.
- Examples: `AND([Width] >= 900, [Width] <= 1200)`, `OR(CONTAINS([Comments], "External"), STARTSWITH([Mark], "A"))`, and `NOT(ISBLANK([Comments]))`.
- Text conditions are **Equals**, **Does not equal**, **Contains**, **Starts with**, **Ends with**, **Is blank**, and **Is not blank**. Text matching ignores case; blank conditions ignore the Value input. Missing parameters count as blank.
- Numeric conditions are **Greater than**, **Less than**, **Greater than or equal to**, **Less than or equal to**, **Equals (numeric)** and **Does not equal (numeric)**. Numeric text values are supported as well as numeric parameters. In expressions, unquoted numbers mean numeric comparison (`[Width] = 900`); quoted values mean text comparison (`[Mark] = "900"`).
- Numeric comparisons use the displayed number, including its display rounding, in project units. For a Width displayed as `900 mm`, enter `900`, not Revit's internal feet value. Filter inputs always use a decimal point without thousands separators or unit suffixes, such as `1200.5`. Parameter displays are interpreted using current regional separators. Decimal unit suffixes on parameter values are ignored; no unit conversion is performed.
- Compound or fractional measurements (such as feet-and-inches) are not parsed as a single decimal number. Blank, non-numeric and unsupported numeric displays produce an unknown numeric result, which NOT does not turn into a match. OR can still match another valid condition; AND can still fail another condition. Rows whose final result remains unknown are excluded with a warning count beside Preview. Use decimal project display units for these comparisons.
- The active rule count and displayed row count remain visible beside Preview even when More Settings is collapsed. Hover over the main filter summary to see the expression.
- The parameter filter uses type parameters in Type mode, and instance parameters with type fallback in Instance mode. If switching modes makes a parameter unavailable, the active rules are preserved but all rows are hidden and Apply is disabled; edit or clear the filter to proceed. This prevents silently broadening the selection. Filters start clear on each tool launch.
- Element-reference parameters are available for filters and `{param1}` through `{param5}` tokens, including wall **Base Constraint** / **Top Constraint**, floor and ceiling **Level**, and roof **Base Level**. Use **Instance mode** for these instance constraints. Labels come from Revit, so localized parameter names are preserved.
- Reference values use Revit's display text when available, otherwise the referenced element's name (for example `Level 1`), with the ID as a fallback for unnamed/unresolved positive references. Special values such as an unconnected wall top retain Revit's display text when supplied; otherwise an unset/special negative reference is blank. Text filters match these names, not level elevations. References can be read for tokens and filters but cannot be reassigned by Apply Re-Value; choose a supported text/numeric target parameter or the default name instead.
- Header filters match text anywhere in the value, ignoring case. When both filters contain text, a row must match both.
- The parameter expression and both header filters are combined with AND. Apply uses only the rows remaining after all filters. The filtering parameter is never modified just because it is used in a filter.
- Clear the parameter filters and both header filter boxes to show all rows again.
- Filtering does not recalculate counters or sequences; values remain exactly as previewed.
- Unchanged rows and blank new values are not applied. The Final checkbox still freezes a row's preview value; it does not exclude that row from Apply.
- Pale yellow highlights differences between Current Value and New Value. The existing green New Value cell highlight still indicates a Final (frozen) row.

## Notes

- The default `-` token delimiter still splits negative-looking source names; remove `-` from the delimiter list if a `{valN}` source must retain a leading minus sign.
- In Instance mode, if a selected parameter is missing on instance, type fallback is attempted.
- Preview shows final values before commit.

## Examples

Pattern:

```text
{val1}-{param1}-{count}
```

Result:

```text
Door-Width-A
Door-Width-B
Door-Width-C
```
