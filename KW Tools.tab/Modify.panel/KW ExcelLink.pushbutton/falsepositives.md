# ExcelLink parameter false-positive review

## Implementation update (2026-10-23)

The committed identity-aware catalog now distinguishes built-in ids, shared
GUIDs and compatible data/storage types, rather than grouping solely by label.
The subsequent optional-fields implementation adds a Step 4 opt-out for
known-false-positive filtering, fixes Category display when raw Category
parameters are retained, and suppresses empty read-only built-in Family
Name/Type Name records per scope. It deliberately does not remove every blank
or read-only parameter. See [the current feature rules](scope.md#optional-api-fields-and-reversible-false-positive-filtering).

The findings below describe the earlier review baseline, not all current code.

Reviewed 2026-10-22. This is a code-path review of parameter discovery,
extraction, projection, and write-back. It does not change ExcelLink behavior.

## Summary

ExcelLink currently uses a parameter's displayed name as its main identity.
That is convenient for the picker, but it can combine parameters that are not
the same Revit parameter, and it classifies availability by existence rather
than by whether a parameter can provide a useful value. The same approach
causes the built-in `Category` parameter to appear in the picker even though
the sheet's category is already known separately.

The safest low-cost direction is to collect a compact parameter inventory
during the existing parameter iteration: keep a user-facing name, a stable
identity where available (built-in id or shared-parameter GUID), scope, storage
type, read-only status, and whether a usable value/display can be resolved.
Cache that inventory for each type as the current code already does for type
parameter names. Do not add a model-wide collector or a separate pass that
reads every parameter value.

## Findings

### 1. Built-in Category is treated as a selectable mixed-use parameter

**Impact: High confidence; moderate UX/data correctness.**

`build_parameter_usage_map` puts all instance and type parameters into a map
keyed only by `Definition.Name`. A parameter called `Category` on an element
and its type therefore creates an `isType` + `isInstance` entry, like any
other mixed-use parameter. The picker shows that badge and Instances Mode
creates both `Category (Type)` and `Category (Instance)` columns.

This is distinct from ExcelLink's own row `Category` metadata. That metadata is
populated from `element.Category.Name` and is stored in the `Category` row
field; its base grid column is hidden. The picker entry named `Category` is a
Revit parameter, not that metadata field.

For the built-in Category parameter, the extracted value is an `ElementId`.
`ReferenceCatalog.describe` only resolves positive element ids or a small
list of specially handled negative ids. Revit category ids are negative, so
they fall through to the generic `<None>` display rather than resolving to a
category name. The parameter is read-only, so its grid cells are disabled
anyway. That makes the selectable field redundant and misleading.

**Recommendation:** exclude the exact built-in Category parameter identities
from the editable parameter picker, while retaining the existing category
metadata. If users need the parameter as a visible read-only field, resolve its
category id explicitly and present the category name instead of `<None>`.
Do not suppress every parameter named `Category`: a custom/shared parameter
with that display name may be meaningful and must be distinguished by identity.

Relevant code: `core/parameter_map.py`, `core/extract.py`,
`core/column_builder.py`, and `core/element_refs.py`.

### 2. Family Name can be advertised as instance-available when it is empty

**Impact: High confidence; low-to-moderate UX impact.**

The usage map records a parameter as instance-available whenever its name
appears on an instance; it does not consider its built-in id, value,
read-only state, or whether the corresponding type provides the useful value.
In the inspected door example, the instance-side built-in `Family Name`
parameter exists but is null, while the type-side `Family Name` contains the
family name. The picker consequently offers both scopes, although the
instance-side option has no useful value.

**Recommendation:** filter only this known false-positive case using the
parameter's exact built-in identity and element scope (for example, the
built-in Family Name parameter on a family instance when it has no value).
Keep genuinely blank editable parameters: an empty editable parameter may be
intentionally available for the user to populate. Avoid a general “ignore all
null-valued parameters” rule.

Relevant code: `core/parameter_map.py` classifies by name and scope;
`core/extract.py` reads values separately.

### 3. Same-name parameters with different identities can be merged

**Impact: High confidence; moderate correctness risk, potentially affecting
edits.**

The usage map and extracted parameter records are dictionaries keyed by
`Definition.Name`. Two distinct parameters with the same displayed name can
therefore look like one parameter. This can happen across bindings or families
in one category, and is especially important for shared parameters with
different GUIDs or parameters with different storage types/units.

The column has a single set of metadata such as storage type, parameter GUID,
built-in id, unit, and reference options, despite values being gathered from
multiple rows. Reference kind and unit are selected from the first usable
record, and column parameter metadata can be populated while projecting rows.
If different rows represent different parameter definitions, the column can
show inconsistent values or use inappropriate formatting, options, or
write-back identity.

**Recommendation:** keep parameter identity separate from its display label.
Aggregate by built-in id or shared GUID where available; use a documented
fallback for non-shared parameters. Before building one column, verify that
its members have compatible identity, storage type, and reference/unit
metadata. Split incompatible definitions or clearly flag/disable the
ambiguous column rather than silently selecting one definition.

Relevant code: `core/parameter_map.py`, `core/extract.py`,
`core/column_builder.py`, and `core/apply_changes.py`.

### 4. “Type + Instance” can mean matching names, not the same parameter

**Impact: High confidence; moderate UX impact.**

`is_mixed_use` is simply the conjunction of name-level `isType` and
`isInstance`. It does not establish that the type-side and instance-side
parameters share the same definition. A same-named but unrelated type
parameter and instance parameter can therefore receive the mixed-use badge
and produce paired columns that imply a relationship that may not exist.

**Recommendation:** calculate mixed use from compatible parameter identities,
not name alone. If the definitions differ, show separate clearly qualified
entries or mark the name ambiguous instead of presenting it as one
Type + Instance parameter.

Relevant code: `core/parameter_map.py` and `ui/wizard.py`.

### 5. Parameter presence is not the same as editability or value usefulness

**Impact: High confidence; low-to-moderate UX impact.**

The inventory includes parameters regardless of whether they are read-only,
null, or unsupported for editing. Projection later disables read-only or
unresolvable cells, so the picker may invite users to select fields that
become entirely disabled or display no useful value. Blank values alone are
not sufficient evidence of a false positive, but known display-only built-ins
and unsupported ElementId references can be identified cheaply while the
parameters are already being inspected.

**Recommendation:** distinguish “exists”, “has a readable value”, and
“editable” in the inventory/picker. Hide or clearly mark fields that are
known to be display-only or unsupported; do not discard empty but editable
fields. For `Category`, show it as metadata/read-only rather than as an
editable parameter.

Relevant code: `core/parameter_map.py`, `core/extract.py`,
`core/column_builder.py`, and `ui/wizard.py`.

### 6. Duplicate same-name parameters on one element are collapsed

**Impact: Medium confidence; context-dependent correctness risk.**

`_parameter_values` intentionally handles elements exposing duplicate names
by preferring an editable parameter, then a parameter with a more specific
lock reason. That is useful for cases such as the documented Level example,
but it still reduces multiple parameters to one name-keyed record. If two
same-name parameters are both relevant, or differ by definition/storage type,
one is silently omitted from extraction and the selection model cannot
represent the distinction.

**Recommendation:** retain the existing editable-preference behavior for
known duplicate presentations, but keep the identity with each candidate and
detect incompatible duplicates. Report or separate ambiguous candidates
rather than silently choosing one.

Relevant code: `core/extract.py` (`_parameter_values`) and
`core/apply_changes.py` (`_find_parameter`).

## Low-overhead implementation outline

1. Replace name-only inventory entries with records keyed by parameter
   identity, keeping the original name for labels. Cache per-type records by
   type id as the current usage-map code already does.
2. During the existing `element.Parameters` loops, capture only cheap
   metadata: identity, scope, storage type, read-only status, and whether a
   string value is null/empty where the known false-positive rule needs it.
   Avoid resolving every ElementId candidate merely to decide picker
   availability.
3. Add narrow rules for known built-ins:
   - omit or qualify built-in Category, since the category is already present
     as row/sheet metadata and its read-only ElementId needs explicit category
     resolution to display usefully;
   - suppress the empty instance-side built-in Family Name case without
     suppressing unrelated blank parameters.
4. Build mixed-use badges only for compatible identities. Detect and surface
   heterogeneous definitions before constructing a shared column.
5. Preserve the identity metadata through projection and write-back, and add
   focused tests for Category, the Family Name scope mismatch, same-name
   distinct GUIDs/storage types, and genuinely blank editable parameters.

This approach reuses the parameter enumeration already required for the
picker and extraction. It avoids extra collectors, repeated model-wide scans,
and eager resolution of every ElementId parameter.

## Validation gaps

Existing picker tests verify badge rendering and selection behavior using
hand-authored usage maps. They do not exercise `build_parameter_usage_map`
against parameters with built-in ids, null values, duplicate display names,
different shared-parameter GUIDs, or incompatible storage types. Add focused
unit tests around inventory construction and projection before changing the
classification rules.
