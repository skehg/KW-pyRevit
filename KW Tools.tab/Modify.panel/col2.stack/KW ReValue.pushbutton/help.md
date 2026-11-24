# KW ReValue

KW ReValue renames element types or instances by combining ordered Token Rule
operations. Each operation appears as a chip in the composition bar.

## Composing a value

Operations concatenate directly in list order:

- **Token** reads one token from the selected source value. Position 1 from
  **Start** is the first token; position 1 from **End** is the last token.
- **Range** combines a source Start/End position with a second endpoint, or a
  Following count. Following 0 means the start token only.
- Source chips can contain several selections. Combine ranges and single
  positions, for example token 1 through 3 plus the last token.
- **Text** inserts arbitrary literal text, including spaces and braces.
- **Parameter** inserts a named Revit parameter selected directly on that chip.
  Enable **Tokenise parameter value** to split that parameter with its own
  delimiters, then combine single positions and ranges exactly like Source tokens.
- **Original** inserts the complete untokenized source value.
- **Counter** inserts the shared row counter.

Separator text is stored directly for every range and between selections. Use
the separator choices or enter a literal custom separator exactly as it should
appear.

Case conversion belongs to individual Source, Parameter, Original, and Counter
operations. Text operations remain literal. **Final Case** converts the complete
result after Find/Replace.

## Progression

Source operations with a single absolute Start position, Parameter operations,
and Original operations support:

- **Increment**: advance each row from its own value.
- **Sequence**: begin at the first numbered preview row after sorting and
  Current Value/parameter filtering, then advance by row position.

Numeric values preserve digit width, alphabetic values roll over, and prefixed
numeric values preserve their prefix. Unsupported or blank progression values
show a preview warning. Negative progression steps are supported.

The Counter operation stores its own Start and Increment settings. Repeated
Counter operations return the same value within each row; settings stay on the chip.

## Source and Original

The **Source** dropdown chooses a parameter or the default element/type name.
The **Rules / Source** switch temporarily replaces the composition with one
Original operation. Turning it off restores the previous composition kept in
memory. Editing the composition while Source is enabled turns the switch back
off.

## Workflow

1. Optionally select elements in Revit.
2. Open KW ReValue.
3. Choose Type or Instance mode.
4. Choose the source parameter or keep the default Name source.
5. Edit **Delimiters** in the toolbar to control how source text is split.
   The default is `-_/,|`. The composition panel shows the resulting
   `[1] [2] [3] ...` source-token preview.
6. Use **Edit Filters** beside the delimiter field for independent parameter rules.
   The compact filter summary shows the active rule count.
7. Build operations in the composition bar:
   - drag palette chips into the bar;
   - click `+ Add`;
   - double-click or right-click a chip to edit it;
   - duplicate, move, or remove chips from the chip menu.
8. Optionally set Find/Replace and Final Case.
9. Sort and filter the preview as needed.
10. Review and use **Apply Re-Value**.

The preview and Apply use the same ordered composition. The counter and sequence
numbering follow the displayed sort and filtering order.

## Filter Manager

Filter Name Proposals starts with one Original operation and fresh local settings.
It does not read or overwrite ordinary ReValue session settings. Parameter
chips and parameter filters are unavailable in this context. Use Proposals
returns the preview text to Filter Manager without renaming the model.

## Layout


## Legacy syntax

The previous pattern DSL is no longer supported. Old `pattern` sessions are not
read or migrated. An existing old session starts with the default Start 1 source
operation.

Literal braces require no escaping in Token Rules.

## Plan views

In Instance mode, renaming plan views changes only the view names. Associated
levels keep their existing names.
