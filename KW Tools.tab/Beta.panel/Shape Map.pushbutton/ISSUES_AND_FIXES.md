# Shape Map Debug Log (2026-07-08)

This note captures the major issues encountered while stabilizing Shape Map corner and boundary behavior, plus the final fixes that made the tool reliable.

## 1) Corner vertices not getting updated

Symptom:
- Boundary corners stayed at base elevation while nearby edge points updated.

Cause:
- Corner points were not always targeted explicitly, and host behavior differed between geometric boundary points and editable slab-shape vertices.

Fix:
- Added explicit corner handling using vertex type detection (`Corner`) and a dedicated corner update pass.
- Corner targets are resolved from mapped XY->Z data first, with nearest mapped fallback.

## 2) Reporting could not explain what was happening

Symptom:
- It was unclear whether corners existed as editable vertices or only as geometric boundary diagnostics.

Cause:
- Report did not include vertex type and did not clearly separate shape vertices vs geometric boundary control points.

Fix:
- Expanded output to include full destination vertex table with `Vertex Type`.
- Kept a separate geometric boundary control point table for diagnostics.

## 3) Retry behavior created near-corner artifacts

Symptom:
- In some runs, retries added points near corners and produced spikes.

Cause:
- Add/retry fallback could create nudged points near boundaries without reliably re-targeting original intended XY.

Fix:
- Added nearest-existing-vertex preference and snap-back logic from nudged retry points to original XY targets.

## 4) Mixed and unstable elevations after corner/crease passes

Symptom:
- Some vertices became extreme or inconsistent after post-write passes.

Cause:
- Post-map face re-sampling (`_sample_height_on_faces`) during write-time correction passes introduced unstable values on some host geometries.

Fix:
- Write-time corrections now use the already-computed mapped XY->Z set as the source of truth.
- Boundary crease re-sample pass was disabled for stability.

## 5) Uniform +base elevation drift on non-corner points

Symptom:
- Corners could be correct while many non-corner vertices were too high by about destination base elevation.

Cause:
- `AddPoint`/`DrawPoint` path on this host interpreted Z as relative offset in `relative_level_offset` mode.

Fix:
- Added dedicated add-Z conversion for add/draw calls in relative mode.
- Existing vertex modifications continue to use absolute-world targeting path.

## 6) Temporary seed point remained in final result

Symptom:
- Extra interior point (seed point) remained in final destination vertex table.

Cause:
- Seed used to enable shape editing was intentionally kept during writes and not cleaned up afterward.

Fix:
- Tracked the seed point used for auto-enable.
- Added end-of-run cleanup to delete the matching temporary interior seed vertex (with API fallback delete signatures).

## Final operating rules now used by Shape Map

- Treat corners explicitly by vertex type.
- Use mapped XY->Z as write source-of-truth.
- Avoid unstable write-time face re-sampling.
- Convert add/draw Z correctly for relative mode.
- Remove temporary seed point after successful mapping.

## Practical verification checks

After a run, verify:
- Corner rows show expected Z values.
- Non-corner rows are not shifted by base elevation.
- No extra seed interior point remains.
- Warnings include seed auto-enable and optional seed removal note when applicable.
