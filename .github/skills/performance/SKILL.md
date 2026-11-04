---
name: performance
description: Use when pyRevit commands process many elements, perform repeated API access, or risk blocking Revit's UI.
---

# Performance

Measure the user-visible bottleneck before optimizing. Revit API access and UI responsiveness matter more than speculative micro-optimizations.

- For a new tool, establish a baseline on a representative model and define acceptable response/progress behavior. For a feature, compare the affected workflow before and after, including impact on existing paths.
- Narrow element collection early with verified filters; avoid repeated full-document scans.
- Cache values within a command when document validity and change behavior make that safe.
- Batch reads and writes thoughtfully while keeping transaction scope understandable and safe.
- Avoid repeated geometry extraction, parameter lookup, regeneration, and expensive formatting inside loops.
- Keep long tasks cancellable and provide progress without unsafe cross-thread API access.
- Compare before/after behavior on a representative model and report model size and measurement method when known.
- Define measurable acceptance criteria for the affected workload (elapsed time, element/API-call counts, or response/cancellation latency). If no threshold is agreed, report the baseline and measured difference without inventing a performance guarantee.
- Use [workspace-tooling](../workspace-tooling/SKILL.md) to discover existing profiling/test tools. Python-only profiles do not establish Revit API or hosted UI performance; separate measured timings from estimates and do not trade correctness or transaction safety for speed.
