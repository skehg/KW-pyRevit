# Koala ReValue - Syntax and Examples

This window reads from `help_examples.md` in the same folder as the tool.
Edit this file to add your own office-specific patterns and notes.

## Pattern Syntax

A pattern combines literal text with placeholders. Token expressions read the source text after it is split by the configured token delimiters. Token numbers start at 1.

- Single tokens:
  - `{val1}` = first token
  - `{end}` = last token
  - `{end-1}` = second-to-last token
- Ranges:
  - `{val1:4}` = tokens 1 through 4
  - `{val2:end}` = token 2 through the last token
  - `{val1:end-1}` = first token through the second-to-last token
  - `{end-2:end}` = last 3 tokens
  - `{end-3:end-1}` = token four from the end through the second-to-last token
- Relative count from the start token:
  - `{val3:+2}` = token 3 and the next 2 tokens
  - `{end-3:+1}` = token four from the end and the next token
- Per-expression output delimiter:
  - `{val1:end|space}` = all tokens joined with spaces
  - `{val1:4|-}` = tokens 1 through 4 joined with `-`
  - `{end-2:end|underscore}` = last 3 tokens joined with `_`
  - `{val2:end|/}` = token 2 through the last token joined with `/`
  - `{val1:3|space~upper}` = tokens 1 through 3, space-separated and uppercased
  - `{val1~lower}` = first token lowercased
  - `{param1~title}` = parameter 1 in title case
  - `{orig~sentence}` = source text in sentence case

The default join delimiter is `-`. An optional `|delimiter` can be added to a token expression to override it, including a single-token expression. Named delimiters are `space`, `hyphen`, and `underscore`; literal delimiters such as `-`, `/`, and `.` are also supported. Use `space` rather than a literal space.
Append `~upper`, `~lower`, `~title`, or `~sentence` to a placeholder to convert its value after token selection and joining. `sentence` uppercases the first character and lowercases the remaining characters.

Other placeholders:

- `{param1}` through `{param5}` = values from the five parameter dropdowns.
- `{param6}` or `{count}` = generated counter value.
- `{orig}` = the complete, un-tokenized source text.
- `{inc:val3:1}` = increment token 3 by 1 independently for each row.
- `{inc:param1:-1}` = decrement parameter slot 1 by 1 independently for each row.
- `{seq:val3:1}` = start with token 3 from the first unfiltered preview row, then advance by 1 per row.

`{inc:...}` and `{seq:...}` accept one `{valN}` or `{param1}` through `{param5}` source and a signed integer step; ranges are not supported. A zero step is allowed. For example, `{seq:val3:-1}` counts backward from the first row's token 3. Numeric values preserve digit width (`009` plus 1 becomes `010`), alphabetic values roll over (`Z` plus 1 becomes `AA`), and prefixed numeric values preserve their prefix (`RM09` plus 1 becomes `RM10`). Negative numeric and prefixed results preserve their width (`RM01` minus 2 becomes `RM-01`). Alphabetic values cannot decrement below `A`. Blank or unsupported values remain unchanged and show a preview warning. The counter uses its configured start and nonnegative increment only when the pattern contains `{count}` or `{param6}`.
The **Final Case** dropdown applies `None`, `upper`, `lower`, `title`, or `sentence` to the complete generated value after Find/Replace. This is independent of per-placeholder modifiers.

## Core Concepts

- `Original Parameter` (top dropdown):
  - Used as tokenization source when selected.
  - Also becomes the write-back target when Apply runs.
  - Leave empty to use element/type Name as source and target.

- `Pattern` field supports both token and parameter placeholders:
  - Token placeholders: `{val...}` / `{end...}`; see Pattern Syntax above for single tokens, ranges, relative ranges, and delimiters.
  - Parameter placeholders: `{param1}` to `{param5}`.

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
