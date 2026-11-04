---
name: ironpython-27
description: Use when writing or reviewing pyRevit scripts configured to run under IronPython 2.7.
---

# IronPython 2.7

Confirm the active bundle engine before using this guidance. Use Python 2.7 compatible syntax and libraries supported by the embedded IronPython environment.

Use [workspace-tooling](../workspace-tooling/SKILL.md) for editor/environment discovery and [pyrevit-ironpython27](../pyrevit-ironpython27/SKILL.md) when an end-to-end IronPython implementation workflow is needed.

- Avoid f-strings, annotations, async/await, and Python 3-only standard library APIs.
- Be explicit about Unicode and .NET string conversions at API/UI boundaries.
- Verify .NET overload resolution and collection conversions in the actual runtime when ambiguous.
- Avoid assuming CPython packages or native extensions are importable.
- Keep Revit API calls on the valid Revit thread/context and apply the transaction skill for mutations.
- Clearly mark checks made only under CPython or in editor stubs as not proving IronPython runtime compatibility.
- Use the actual IronPython parser/runtime when available. Pylance's Python 3 diagnostics are advisory for this engine; do not "fix" Python 2 code by introducing annotations, f-strings, or Python 3-only imports.
