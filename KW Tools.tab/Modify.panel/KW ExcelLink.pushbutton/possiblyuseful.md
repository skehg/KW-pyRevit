# Potentially useful ExcelLink fields outside the current parameter picker

## Implementation update (2026-10-23)

Step 4 now offers opt-in, read-only derived fields: all three coordinate frames,
resolved category/family, host ID, pinned state, point rotation and facing/hand
vectors. These are instance-only fields, selected individually in the picker.
Curve midpoint/endpoints, solid centroids, and coordinate movement are not
implemented. See [coordinate definitions and rollback controls](scope.md#optional-api-fields-and-reversible-false-positive-filtering).

The investigation below records the earlier baseline and rationale.

Reviewed 2026-10-22 against the ExcelLink source and the active Revit 2024
document (`Project1`). The Revit check read one placed door and its API
parameters; it did not modify the model. The active Revit context had no
selection, so the sample was collected from the document's Doors category,
not from a user selection or a specific 3D view.

## Main finding: XYZ is not a Revit parameter

ExcelLink discovers parameters by iterating `element.Parameters` in
`core/parameter_map.py`, then extracts the selected parameter values in
`core/extract.py`. It does not currently add a row's location or geometry to
the picker.

The Revit API exposes element position separately:

- `Element.Location` returns a `Location`; it is not a parameter.
- For a point-based location, `LocationPoint.Point` is an `XYZ`.
- For curve-based elements, `LocationCurve.Curve` provides a curve rather
  than one universal insertion point.
- `FamilyInstance.FacingOrientation` and `FamilyInstance.HandOrientation`
  expose orientation vectors for family instances; these also are not
  parameters.

These members were confirmed in the Revit 2024 API. In the sample door,
`LocationPoint.Point` returned approximately `(-48.344, 49.203, 0.0)` in
Revit internal length units (feet). The displayed `Level` parameter was
separate and did not provide X/Y.

**Recommendation:** if spatial data is desired, add separate derived,
read-only columns such as `Location X`, `Location Y`, `Location Z` (and
optionally rotation/facing), rather than pretending these are selectable
parameters. A location reader must handle point locations, curve locations,
and elements with no supported location. Document which coordinate system is
used: raw Revit coordinates are internal coordinates; shared/project
coordinates require an explicit transform. Keep these derived fields out of
parameter write-back unless a deliberate, separately validated location-edit
workflow is designed.

## Other useful candidates found in the door sample

ExcelLink's current scan includes the names below because they are present in
`Element.Parameters`. Some are not in the same set returned by Revit's
`GetOrderedParameters()` for this sample.

| Candidate | Why it may help | Caution |
|---|---|---|
| `Host Id` | Helps identify the wall/host associated with a hosted door. | It is a read-only `ElementId`; show a readable host label or ID, not a raw unresolved reference. |
| `Level` | Useful for sorting/filtering by level. | The door exposed two same-named Level parameters: one read-only and one editable. Identity matters; do not merge blindly by name. |
| `Sill Height`, `Head Height` | Useful placement/opening checks. | Height semantics vary by family/category; values are unit-aware doubles. |
| `Rough Width`, `Rough Height` | Useful for opening coordination. | Read-only in the sample; distinguish from type Width/Height and family-defined dimensions. |
| `Area`, `Volume` | Useful for takeoffs or analysis where meaningful. | Read-only calculated values; not applicable or stable for all categories/elements. |
| `Design Option` | Useful when comparing alternatives. | Often unset; resolve the referenced option to a name rather than showing a sentinel ElementId. |
| `Phase Created`, `Phase Demolished` | Useful for phasing and lifecycle filters. | ElementId values need display-name resolution; demolished phase may be unset. |
| `Family`, `Type`, `Family and Type` | Convenient readable family/type information and type switching context. | These overlap with the dedicated Type Name column and may be read-only/display-only depending on which parameter is chosen. |
| `IfcGUID`, `IFC Predefined Type`, `Export to IFC As` | Useful for IFC coordination/export checks. | Several are empty or unset until configured; these are optional workflows, not generally useful default columns. |
| `Mark`, `Comments` | Common scheduling and coordination fields. | Comments may be blank; blank editable fields should remain available. |
| `Swing Angle` | Potentially useful for checking door leaf configuration. | It is family/category-specific and should be labeled/formatted as an angle, not treated as a length. |

Values above are a category/model sample, not a proposal to add all candidates
to every sheet. A useful default depends on element category and task.

## What the live API comparison showed

For one placed door, `Element.Parameters` returned 44 parameter entries, while
`Element.GetOrderedParameters()` returned 31. The additional entries included
two `Category` parameters, `Design Option`, `Area`, `Volume`, `Host Id`, a
second `Level`, `Family and Type`, `Family`, `Type`, `Family Name`, `Type
Name`, and `Type Id`.

ExcelLink currently scans `Element.Parameters`, not
`GetOrderedParameters()`. Therefore entries outside that ordered list are not
necessarily missing from ExcelLink; many are already eligible for the
parameter picker. The number above is for one door in one model and should not
be generalized to every category or Revit version.

This comparison is useful for identifying additional exposed fields, but it
does not establish that each entry is hidden in every Revit UI context.
`InternalDefinition.Visible` is not used by ExcelLink today, and Revit's
definition visibility flag should not be treated as a universal
Properties-palette visibility test without validating its semantics for the
parameter type in question.

## Current limitations relevant to discovery

1. **No derived geometry discovery.** The picker only sees parameters; it
   cannot offer location XYZ or orientation simply by scanning
   `element.Parameters`.
2. **Name-only aggregation.** `_parameter_names` returns a set of names.
   Different parameters with the same label are collapsed, including
   built-ins, shared parameters, and duplicate presentations.
3. **Unnamed definitions are skipped.** Entries with no `Definition` or an
   empty `Definition.Name` are ignored.
4. **No visibility or usefulness filter.** The picker inventory does not
   examine whether a value is blank, read-only, a calculated quantity, or a
   duplicate of a standard ExcelLink column. Later extraction may disable
   values, but that happens after discovery.
5. **Category-specific semantics matter.** The same field name or storage
   type can mean different things across categories and families.

Relevant source: `core/parameter_map.py`, `core/extract.py`,
`core/column_builder.py`, `core/units.py`, and `core/element_refs.py`.

## Suggested implementation direction

- Keep ordinary Revit parameters in a parameter catalog keyed by stable
  identity (built-in id or shared GUID when available), with display name,
  scope, storage/data type, read-only status, and category applicability.
- Add derived values such as location and orientation through a separate
  metadata/derived-column catalog. This keeps them read-only and avoids
  confusing them with editable parameter setters.
- Make derived columns opt-in and category-aware. Read location/orientation
  only for elements actually being extracted; do not perform extra
  document-wide collectors or geometry calculations during the parameter
  picker step.
- Prefer cheap supported properties (`Location`, `LocationPoint.Point`,
  `LocationCurve.Curve`, family-instance orientation) before considering
  bounding-box or solid-geometry calculations. Geometry-derived centroids
  can be ambiguous and more expensive.
- Normalize units and coordinates explicitly. Revit parameter doubles are
  converted by the existing unit converter, but new XYZ columns need their
  own clear length-unit and coordinate-system contract.
- Add tests for point, curve, missing-location, and unsupported-location
  cases; for different coordinate origins; and for duplicate parameter names
  such as the door's two `Level` entries.

The small read cost of reading `Location` for output rows is likely
reasonable; a robust feature should still avoid assuming every element has a
point location or computing full geometry unless requested.
