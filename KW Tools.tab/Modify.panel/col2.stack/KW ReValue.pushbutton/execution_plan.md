# KW ReValue: Replace the Pattern DSL with Structured Token Rules

## Handoff goal

Refactor KW ReValue so its ordered token-chip collection is the single source of
truth for output composition, preview, persistence, and execution. Remove the
`{val1}`, `{param1}`, `{count}`, `~upper`, and related pattern language from the
normal implementation.

Do not build a migration from old pattern strings. A user session using the old
`pattern` setting may be reset to the default chip composition after this update.

This task changes the **output-composition language** only. Do not replace or
remove the separate parameter-filter tree and `filter_expression.py`.

## Working state to preserve

The worktree already contains unrelated, user-owned changes in:

- `script.py`: plan-view and level instance renames use the direct `Name`
  property.
- `help.md`: documents that renaming plan views does not rename associated
  levels.

Preserve and integrate those changes. Do not revert them when editing these
files.

## Before implementation

1. Read the repository instructions in `copilot-instructions.md`.
2. Confirm the command's actual pyRevit engine before writing engine-specific
   code. KW ReValue does not currently declare a command-level `bundle.yaml`.
   Keep new code IronPython 2.7-compatible unless the deployment configuration
   proves otherwise.
3. Run the existing focused offline tests as a baseline:
   - `tests\test_token_pattern.py`
   - `tests\test_preview.py`
   - `tests\test_range_separator.py`
   - the WPF check in `tests\check_token_editor_runtime.py`, if the required
     runtime is available
4. Record baseline failures before editing. Do not fix unrelated failures.

## Current architecture to remove

The current flow is:

```text
Token chips
    -> serialize_pattern()
    -> txt_pattern.Text
    -> apply_pattern()
    -> NewName
```

The relevant coupling is:

- `token_pattern.py`
  - `parse_pattern()`
  - `serialize_pattern()`
  - `expression()`
  - pattern-specific raw-string preservation
- `token_editor.py`
  - reads and writes `host.txt_pattern`
  - converts token settings into DSL fragments
  - switches between Tokens and Advanced Pattern
- `script.py`
  - `_parse_val_expression()`
  - `_resolve_window()`
  - `_parse_progression_expression()`
  - `_sequence_source_refs()`
  - `apply_pattern()`
  - `PreviewItem.format_value()`
  - `_pattern_uses_counter()`
  - session setting named `pattern`
  - `OnUseOriginal()`'s temporary `{orig}` pattern
- `ReValueUI.xaml`
  - `combo_editor_mode`
  - `txt_pattern`
  - the Pattern/Source toggle currently stores a DSL string

## Target architecture

Make the output composition a structured, versioned list of operations:

```python
{
    'version': 1,
    'operations': [
        {'kind': 'source', 'start': {'direction': 'start', 'index': 1},
         'end': None, 'separator': '', 'case': 'unchanged',
         'progression': None},
        {'kind': 'text', 'text': '-'},
        {'kind': 'parameter', 'slot': 2, 'case': 'unchanged',
         'progression': None}
    ]
}
```

Use ordinary dictionaries and lists so the model remains compatible with
IronPython 2.7 and can be persisted with `json`.

### Supported operation kinds

Preserve all current user-visible behavior with these operation kinds:

1. `source`
   - A start position counted from Start or End.
   - Optional end position.
   - Optional Following-count endpoint.
   - Explicit join separator as a literal string.
   - Per-operation case conversion.
   - Optional `inc` or `seq` progression for a single absolute token position.
2. `parameter`
   - Shared slot 1-5.
   - Per-operation case conversion.
   - Optional `inc` or `seq` progression.
3. `original`
   - The complete, untokenized source.
   - Per-operation case conversion.
4. `counter`
   - The shared row counter.
   - Per-operation case conversion.
5. `text`
   - Arbitrary literal text, including spaces and braces.
   - No case conversion.

### Position representation

Do not store `valN`, `end-N`, or `+N` strings in the canonical model.

Represent positions structurally:

```python
{'direction': 'start', 'index': 1}
{'direction': 'end', 'index': 2}
```

For a range endpoint counted after the start:

```python
{'direction': 'following', 'count': 2}
```

Keep user-facing 1-based positions:

- Start 1 is the first token.
- End 1 is the last token.
- Following 0 means the start token only.

### Separator representation

Store the final separator text directly. UI labels such as `space`, `hyphen`,
and `underscore` may remain, but evaluation must not parse named delimiters.
The settings result should contain the actual resulting string, such as `' '`,
`'-'`, or `'_'`.

Literal braces are ordinary text after this refactor; no parser escape syntax is
required.

### Evaluation boundary

Replace `apply_pattern()` with an evaluator similar to:

```python
evaluate_composition(
    input_text,
    composition,
    parameter_values,
    tokenizer_func=None,
    sequence_seeds=None,
    row_index=0,
    warnings=None
)
```

Evaluation must:

1. Tokenize the source once per row.
2. Evaluate operations in list order.
3. Concatenate their text results.
4. Apply operation-level case conversion to each result.
5. Preserve current numeric, alphabetic, and prefixed-numeric progression
   behavior.
6. Report unsupported/blank progression input through the existing preview
   warning mechanism.
7. Leave final Find/Replace and Final Case after composition evaluation.

Do not silently return original DSL fragments for unknown operations. Unknown
operation kinds, invalid positions, invalid slots, and invalid case/progression
settings are validation errors and must be surfaced explicitly.

## File-by-file plan

### 1. Create the structured model module

Create `rule_model.py` beside `script.py`.

Move or rewrite the non-parser parts of `token_pattern.py` there:

- operation creation helpers
- deep-copy/edit helpers
- insertion/reordering helpers
- validation
- structured labels for chip display
- composition serialization for session persistence

Use names that no longer imply a text language. For example:

- `operation(...)`
- `validate_composition(...)`
- `serialize_composition(...)`
- `deserialize_composition(...)`
- `edit_operation(...)`
- `insert_operation(...)`
- `describe_operation(...)`

Keep `token(...)` only temporarily if that substantially reduces the integration
edit, but do not retain parser or DSL string behavior.

### 2. Replace direct pattern evaluation

In `script.py`:

1. Keep tokenization and the useful progression algorithms:
   - `_increment_value()`
   - `_alpha_to_int()`
   - `_int_to_alpha()`
   - counter construction
   - case conversion
2. Remove the DSL parser/evaluator:
   - `VAL_EXPR_REGEX`
   - `_parse_val_expression()`
   - `_parse_progression_expression()`
   - `_split_case_modifier()`
   - `apply_pattern()`
3. Implement structured helpers for:
   - resolving a source-token range
   - evaluating a source/parameter/original/counter/text operation
   - collecting sequence source references from operations
   - checking whether a composition uses a counter
4. Change `PreviewItem.format_value()` to accept the structured composition
   instead of `pattern`.
5. Change `ReValueDialog.update_preview()` to use the dialog's current
   composition for every row.
6. Sequence seeds must still be based on the first numbered/displayed row after
   sorting and Current Value/parameter filters.
7. Repeated counter operations must return the same counter value within a row.

The Revit read/write and transaction paths are out of scope. Do not refactor
them.

### 3. Make `TokenEditor` own the structured operations

In `token_editor.py`:

1. Remove imports from `token_pattern.py` of parsing/DSL functions.
2. Import structured helpers from `rule_model.py`.
3. Keep `self.items` or rename it to `self.operations`; it must contain only
   structured operation dictionaries.
4. Remove these host couplings:
   - `host.txt_pattern.Text`
   - pattern serialization
   - pattern parsing
   - Advanced Pattern fallback
5. Change `refresh()` to compare the structured composition, not a serialized
   pattern.
6. Change settings dialogs to return structured operation values directly.
7. Change `commit()` to update `host.composition`, update any session value, and
   trigger one preview refresh. Do not generate intermediate DSL.
8. Preserve all current interactions:
   - palette add
   - drag/drop copy and reorder
   - double-click edit
   - right-click menu
   - duplicate/remove/move
   - Source/End/Following controls
   - shared parameter-slot reassignment
   - shared counter settings
   - per-operation case
   - increment/sequence settings
   - sample labels and missing-token display
9. Keep operation settings draft-only. Cancel must not mutate the composition,
   parameter mappings, or counter settings.

### 4. Refactor the Pattern/Source toggle

Keep the useful user behavior of the main toggle, but remove text-pattern
state:

- Off: use the user's current ordered composition.
- On: use a composition containing one Original operation.
- Clicking On saves the previous structured composition in memory.
- Clicking Off restores that saved composition.
- Editing the composition while On turns the toggle Off and updates the
  in-memory composition.

Rename `_pattern_before_original` to a composition-oriented name. Do not store
`'{orig}'` anywhere.

### 5. Change session persistence

In `script.py`:

1. Replace `_SESSION_SETTING_DEFAULTS['pattern']` with a structured setting,
   for example `composition`.
2. Store the versioned composition as JSON in the pyRevit session environment.
3. Load with `deserialize_composition()`.
4. If no new structured setting exists, start with the default:
   - one source operation for Start token 1
5. Do not read, parse, or convert the old `pattern` environment variable.
6. For malformed structured JSON, do not silently produce a misleading preview.
   Reset to the default composition and show a clear status/validation message.
7. Preserve all unrelated session settings: mode, delimiters, source parameter,
   five parameter slots, counter, final case, Find/Replace, sort, and match
   options.
8. Filter-name contexts continue to start fresh with one Original operation and
   must neither read nor overwrite ordinary ReValue settings.

### 6. Simplify the XAML

In `ReValueUI.xaml`:

1. Remove `combo_editor_mode` and its Advanced Pattern option.
2. Remove `txt_pattern`.
3. Retain the token palette and composition bar as the default and only
   composition editor.
4. Keep the Pattern/Source toggle only if its labels and tooltip are updated to
   refer to Token Rules/Source rather than pattern syntax.
5. Keep Final Case alongside the token controls.
6. Update group headers/tooltips so they no longer mention placeholders or DSL.
7. Preserve dimensions, scrolling, accessibility names, and existing styles.
8. Keep the parameter-filter UI and filter editor unchanged.

### 7. Remove obsolete DSL helpers and tests

After all imports have been converted:

1. Delete `token_pattern.py` if nothing uses it.
2. Determine whether `range_separator.py` remains used:
   - If only DSL parsing/serialization uses it, delete it.
   - If retained, narrow it to reusable literal settings with no expression
     syntax.
3. Remove pattern-language-only test coverage.
4. Update test file names/references as needed.

Do not remove `filter_expression.py`; it implements the independent parameter
filter rules.

## Test plan

### Unit tests

Replace `test_token_pattern.py` with structured model tests covering:

- default source operation
- source from Start and End
- ranges and Following endpoints
- custom separators, including spaces, braces, quotes, and backslashes
- Original, Parameter, Counter, and literal Text operations
- all per-operation case modes
- increment and sequence operations
- validation failures for bad operation kind, position, slot, separator,
  progression, and case
- edit, duplicate, insertion, move, and deep-copy independence
- JSON serialize/deserialize of structured compositions
- version rejection for unsupported composition schemas

Replace DSL-specific preview tests with direct structured evaluation tests
covering:

- numeric, alphabetic, and prefixed progression
- negative progression steps
- digit-width preservation
- sequence seed and displayed row order
- repeated counters in one row
- missing token behavior
- blank/unsupported progression warnings
- Find/Replace and Final Case remaining post-composition operations
- empty composition validation

### Existing behavior regressions

Update `tests\test_preview.py`, `tests\test_filter_names.py`, and
`tests\check_token_editor_runtime.py` so they:

- use structured compositions instead of strings
- verify Source/Rule toggling with no DSL
- preserve filter-name draft behavior
- preserve parameter mappings and shared counter settings
- verify saved settings load without consulting the old `pattern` key
- verify preview refreshes once per confirmed token edit
- verify no preview/model changes occur during drag configuration or Cancel
- verify the XAML no longer requires `combo_editor_mode` or `txt_pattern`

If no replacement is needed, remove `tests\test_range_separator.py` and all
references to DSL separator encoding/decoding.

### Static checks

- Search the command folder for:
  - `apply_pattern`
  - `parse_pattern`
  - `serialize_pattern`
  - `txt_pattern`
  - `combo_editor_mode`
  - `{val`
  - `{param`
  - `{orig`
  - `{count`
  - `~upper`, `~lower`, `~title`, `~sentence`
- Remaining hits are allowed only in the removal notes, tests proving old syntax
  is ignored, or unrelated historical text outside the command.
- Search for unused imports and obsolete `range_separator` references.
- Run Python 2 syntax-compatible checks if the available tooling supports them.
  CPython-only success does not prove hosted IronPython compatibility.

### WPF/live checks

When the connected Revit runtime is available:

1. Load the actual KW ReValue window through its intended pyRevit engine.
2. Verify all current chip interactions.
3. Verify the Source/Rules toggle.
4. Verify a row with missing tokens and a row with progression warnings.
5. Verify session close/reopen persistence for a structured composition.
6. Verify Filter Manager's draft handoff.
7. Exercise preview only unless a disposable model and explicit approval are
   supplied for Apply.

Report live WPF/Revit checks separately from offline tests.

## Documentation updates

Rewrite:

- `help.md`
- `help_examples.md`

Remove the pattern syntax section and all placeholder examples. Explain:

- ordered chips concatenate directly
- literal Text chips provide separators
- parameter mappings remain shared slots
- token ranges use Start/End/Following settings
- case and progression settings belong to individual chips
- how the Source toggle differs from an Original chip
- literal braces require no escaping
- the old pattern DSL is no longer supported and old sessions are not migrated

Do not remove the existing plan-view rename note.

## Acceptance criteria

The task is complete only when all of the following are true:

- No production path parses or produces `{val1}`-style strings.
- The structured operation list is the sole source of truth for output
  composition.
- Preview and Apply evaluate that same structured list.
- Every current output capability is available through chips.
- The Advanced Pattern control and editable pattern field are gone.
- Counter and sequence behavior is equivalent to the existing implementation.
- Original/Source behavior remains available without DSL placeholders.
- Parameter-filter rules still use `filter_expression.py` and still work.
- Filter Manager draft mode still uses a fresh Original composition.
- Session persistence stores structured JSON and never migrates old DSL text.
- Settings validation produces explicit errors instead of returning unresolved
  syntax.
- Focused offline tests pass.
- Any unavailable or blocked IronPython/WPF/Revit checks are reported as such.

## Suggested implementation order

1. Baseline tests and exact engine confirmation.
2. Add `rule_model.py` and focused model tests.
3. Implement structured evaluation in `script.py`, initially alongside unused
   legacy code to keep the change testable.
4. Switch `PreviewItem` and `ReValueDialog` to the structured evaluator.
5. Switch session persistence to structured JSON.
6. Refactor `token_editor.py` to edit structured operations directly.
7. Refactor `OnUseOriginal()` and the XAML controls.
8. Remove obsolete DSL code and parser modules only after no-import searches are
   clean.
9. Update Filter Manager and preview tests.
10. Update help text.
11. Run focused tests, static searches, WPF checks, and final review.

## Scope boundaries

Do not:

- broaden supported Revit releases without evidence
- change the command's Revit write strategy or transaction boundaries
- redesign the preview grid
- add conditional rule branching unless separately requested
- replace the parameter-filter expression editor
- add compatibility handling for historical pattern strings
- overwrite the existing plan-view rename changes

