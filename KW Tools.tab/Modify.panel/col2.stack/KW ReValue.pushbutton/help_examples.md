# KW ReValue - Token Rule Examples

Add chips to the composition bar. Chips concatenate directly in the order shown.
The examples below describe equivalent results using structured chips, not text
syntax.

## Example A - Parameter-based name

Operations:

1. Parameter chip for `Mark`
2. Text: `-`
3. Parameter chip for `Comments`

This produces `Slot1-Slot2` for each preview row.

## Example B - Last three tokens

Operations:

1. Source range from End 3 through End 1
2. Separator: space

For source `A-B-C-D`, this produces `B C D`.

## Example C - First token and last token

Operations:

1. Source Start 1
2. Text: `-`
3. Source End 1

For source `A-B-C`, this produces `A-C`.

## Example D - Original source

One Original operation inserts the complete untokenized source. Use it for direct
Find/Replace workflows.

## Example E - Counter

Operations:

1. Counter
2. Text: `-`
3. Source Start 1

Configure this chip with Start `001` and Increment `1`; the first row produces `001-A` and
the next produces `002-A` (subject to sorting and preview filters).

## Example F - Literal braces

Add a Text operation with `{existing}` or `}` as its literal text. Braces require
no escaping in Token Rules.

## Repeated Counter chips

Repeated Counter operations insert the same row counter value, not separate
independent counters.

## Progression

For a Source chip with Start 1, set Increment or Sequence and a signed step.
For example, Increment `2` turns `009` into `011`, `A` into `C`, and `RM09`
into `RM11`. Alphabetic and prefixed-numeric behavior follows the existing
preview rules.

## Final operations

Find/Replace and the Final Case dropdown remain post-composition operations.
Find/Replace is literal text; Final Case applies to the complete generated value.
