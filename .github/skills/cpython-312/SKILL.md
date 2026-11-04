---
name: cpython-312
description: Use when writing or reviewing pyRevit scripts configured for CPython 3.12.
---

# CPython 3.12

Confirm the bundle engine and actual embedded runtime before relying on CPython 3.12-specific behavior. Use [workspace-tooling](../workspace-tooling/SKILL.md) to inspect the Python extension/Pylance-selected environment. An external virtual environment is useful for tooling and isolated checks, but does not establish Revit's runtime or the deployed button engine.

- Use Python 3 syntax only when the bundle's engine is confirmed as CPython.
- Verify package availability in the runtime that executes the extension; external virtual environments do not automatically transfer dependencies into Revit.
- Check .NET interop and Revit API access through verified pyRevit examples/documentation.
- Verify UI-library compatibility explicitly; helpers such as `pyrevit.forms` may rely on IronPython behavior and are not automatically usable through CPython/pythonnet.
- Do not use threads to make arbitrary Revit API calls; use a verified Revit-supported handoff pattern.
- Run focused tests with the confirmed tooling interpreter; record its version separately from the embedded runtime. Verify bridge overloads, .NET collections, and UI loading in the actual embedded runtime where affected.
- State separately what was validated externally, through an MCP script, and through the deployed button in Revit.
