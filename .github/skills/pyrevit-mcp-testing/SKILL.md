---
name: pyrevit-mcp-testing
description: Use when verifying pyRevit behavior through the connected pyRevit 7 MCP integration or a live Revit session.
---

# pyRevit MCP Testing

Use [workspace-tooling](../workspace-tooling/SKILL.md) for capability discovery. The user's connection establishes availability in principle, not particular commands, accessible documents, or successful tests.

- Verify tool names, argument schemas, active Revit session/document, and read/write effects before use.
- Discover `list_revit_instances`, then `get_context`; disambiguate by process when necessary. Record Revit/pyRevit versions, document identity/type, policy, and script engine. Read the server's `revit-scripting` guidance before queries/dry runs/writes, and `pyrevit-library` before selecting raw API operations.
- Prefer read-only checks for discovery; request a safe test model for any mutation.
- Use side-effect-free `run_query` scripts for reads. For authorized writes, use `run_modify` with `dry_run=true` first and inspect the change set; obtain commit approval and verify the resulting model state and Undo separately. A rollback preview does not prove the commit path.
- MCP rollback is not a filesystem/network/process sandbox. Guarded runs may block save/export; do not bypass the guard or move the operation outside it to make a test pass.
- For a new tool, exercise its primary end-to-end path plus cancellation, empty input, invalid input, and failure handling. For a feature, verify the new behavior and the existing workflows most likely to be affected.
- For an outright failure fix, repeat the original failing steps and confirm completion. For a behavior bug, assert the expected result/model effect rather than treating a successful MCP call as proof of correctness. For a UI refinement, inspect the requested layout and confirm affected controls still behave correctly.
- Use small representative cases and include cancellation, empty selection, invalid input, and failure paths when applicable.
- Capture observable evidence such as returned values, UI behavior, or model state; distinguish tool success from feature correctness.
- Never claim a live test was run unless the tool call succeeded and its result supports that claim.
- Record unavailable MCP operations as environment-specific checks, not assumed capabilities.
- If `revit_busy` or a modal dialog blocks a request, stop dependent checks and ask the user to resolve it when needed; never dismiss their dialogs. Read `get_run` for persisted/truncated results when applicable, and distinguish errors, rejection, rollback, and pending results from success.
- Record criterion, inputs, expected/observed result, tool/run identifier, engine/release, and status (passed/failed/blocked/not run). A script executed in Revit is not evidence that the actual ribbon button, imports, event handlers, or UI ran.
