# Koala ReValue

Koala ReValue renames element types or instances by combining source tokens and parameter values.

## Workflow

1. Select elements in Revit.
2. Open Koala ReValue.
3. Choose mode:
   - Type mode: works on element types.
   - Instance mode: works directly on selected instances.
4. Set token delimiters.
5. Pick source parameter (optional). If empty, source is the element/type name.
6. Pick up to 5 parameters for substitution.
7. Enter a pattern.
8. Optionally set counter and final find/replace.
9. Review preview and click Apply.

## Pattern tokens

- `{val1}`, `{val2}`, ... : token positions from tokenized source text.
- `{param1}`, `{param2}`, ... `{param5}` : selected parameter values.
- `{param6}` or `{count}` : generated counter value.
- `{original}` : full un-tokenized source string.

## Notes

- Counter is only used if pattern contains `{count}` or `{param6}`.
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
