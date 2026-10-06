# Koala ReValue - Syntax and Examples

This window reads from `help_examples.md` in the same folder as the tool.
Edit this file to add your own office-specific patterns and notes.

## Core Concepts

- `Original Parameter` (top dropdown):
  - Used as tokenization source when selected.
  - Also becomes the write-back target when Apply runs.
  - Leave empty to use element/type Name as source and target.

- `Pattern` field supports both token and parameter placeholders:
  - Token placeholders: `{val...}` / `{end...}`
  - Parameter placeholders: `{param1}` to `{param5}`

## Token Syntax

- Single token:
  - `{val1}` = first token
  - `{end}` = last token
  - `{end-1}` = second to last token

- Ranges:
  - `{val1:3}` = tokens 1 to 3
  - `{val2:end}` = token 2 to last
  - `{val1:end-1}` = all except last token
  - `{end-2:end}` = last 3 tokens

- Relative count from start token:
  - `{val3:+2}` = tokens 3 to 5
  - `{end-3:+1}` = token (end-3) plus next 1 token

- Per-expression output delimiter:
  - `{val1:3|-}` = join with `-`
  - `{end-2:end|space}` = join with spaces
  - `{val2:end|underscore}` = join with `_`

## Named Delimiters

- `space` => ` `
- `underscore` => `_`
- `hyphen` => `-`

You can also use literal delimiters such as `/` or `.`.

## Parameter Syntax

- `{param1}` through `{param5}` map to the 5 parameter dropdowns.
- You can use parameter placeholders only (no token placeholders required).

## Increment and Sequence Syntax

- `{inc:val3:1}` increments token 3 by 1 for each row using that row's own value.
- `{inc:param1:-1}` decrements parameter slot 1 by 1 for each row.
- `{seq:val3:1}` starts with token 3 from the first displayed row, then advances by 1 for each following row.
- The step is a signed integer; zero is allowed. `{seq:val3:-1}` counts backward from the first displayed row's value.
- Numeric values keep their digit width (`009` plus 1 becomes `010`); alphabetic values roll over (`Z` plus 1 becomes `AA`); prefixed values keep their prefix (`RM09` plus 1 becomes `RM10`). Negative numeric/prefixed values keep their width (`RM01` minus 2 becomes `RM-01`).
- Alphabetic values cannot decrement below `A`. Blank or unsupported values remain unchanged in the pattern output and show a preview warning.
- Increment/sequence operands accept a single `{valN}` or `{param1}` through `{param5}`, not token ranges. `{count}` and `{param6}` retain their existing counter settings and nonnegative increment behavior.

## Examples

### Example A - Build combined value and push into selected Original Parameter

- Pattern:
  - `{param1} - {param2} - {param3}`
- Behavior:
  - Writes this composed string into the selected `Original Parameter`.

### Example B - Last three tokens from source parameter with spaces

- Pattern:
  - `{end-2:end|space}`
- Source:
  - Selected `Original Parameter`
- Result:
  - Last 3 tokens, space-separated.

### Example C - All except last token, then append code

- Pattern:
  - `{val1:end-1}-{param1}`

### Example D - No Original Parameter selected (Name mode)

- Pattern:
  - `{val1}-{param1}`
- Behavior:
  - Uses Name as source and writes back to Name.

## Notes

- Delimiters collapse during tokenization (e.g. `A--B` behaves like `A-B`).
- In Type mode, parameter selectors are type-only.
- In Instance mode, selectors can include instance and type parameters.
