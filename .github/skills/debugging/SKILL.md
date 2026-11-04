---
name: debugging
description: Use when diagnosing pyRevit startup, import, engine, API, transaction, UI, or runtime failures.
---

# pyRevit Debugging

Reproduce narrowly and gather the complete traceback, Revit/pyRevit version, active engine, bundle path, and relevant document state.

1. Classify the symptom: outright failure (cannot complete), behavior bug (completes but gives an unexpected result/effect), UI bug (broken interaction or deviation from an agreed design), or UI refinement (requested adjustment to a working interface). Also classify bundle discovery, syntax/import, runtime/dependency, API context, transaction, UI/XAML/WebView2, or model-data layer.
2. Record expected versus actual behavior, exact error/output, reproduction steps, affected Revit version, engine, document conditions, and the smallest relevant input.
3. Decide whether the issue affects a new command or a path through an existing command; compare existing paths and identify regressions.
4. Find the first actionable frame in the traceback or trace the successful-but-wrong result back through its inputs and API operations.
5. Change one cause at a time; avoid broad exception swallowing and unrelated refactoring.
6. Check whether the issue is engine- or Revit-version-specific.
7. Reproduce the original symptom after the fix and verify nearby cases in the environment that failed when possible; otherwise state the exact missing verification.

Use [workspace-tooling](../workspace-tooling/SKILL.md) to select available evidence: Pylance definitions/diagnostics for source analysis, Python test/debug tools for isolated logic, and pyRevit MCP context/run records for live failures. External Python cannot reproduce Revit/.NET context by itself. Add focused regression coverage where feasible and report expected versus observed results, not just command exit status.

For `revit_busy`, a modal dialog, missing document, or rejected run, resolve/report the prerequisite rather than retrying indefinitely, closing user windows, or suppressing the error. Preserve the traceback and distinguish a test-environment blocker from a code defect.

Do not invent pyRevit reload/debug commands or MCP operations. Confirm them from installed help or project documentation before use.
