---
name: revit-api
description: Use when researching or implementing Autodesk Revit API behavior from pyRevit, including document, element, parameter, selection, and UI APIs.
---

# Revit API

Before using an API symbol, identify the target Revit release(s). Load [workspace-tooling](../workspace-tooling/SKILL.md) to discover actual lookup tools and documentation capabilities. Confirm the symbol, overload, types, ownership, and valid API context through the connected API lookup required by project instructions; use release-specific RVTDocs/Autodesk documentation and reference assemblies as supporting evidence. Stubs are navigation/static-analysis aids, not API or runtime proof.

## Safe API workflow
- Use `Autodesk.Revit.DB` and `Autodesk.Revit.UI` concepts only in valid Revit API context.
- Distinguish `Document`, `UIDocument`, and UI selection state; handle missing/closed documents and user cancellation.
- Prefer filtered collection patterns and narrow element classes/categories before retrieving large sets.
- Check element validity, document modifiability, and parameter storage/type before reading or writing.
- Never infer API availability across versions from a single version's stubs.
- Verify exact lookup tools and documentation sources available in the environment; do not invent RVTDocs or MCP tool names.
- Search maintained pyRevit helpers through `lookup_pyrevit_api` before adding raw API logic; verify the helper's signature and availability in the deployed runtime.
- Record symbol, overload, release, source, and relevant context for changed calls. If a required lookup is unavailable or sources conflict, mark it UNRESOLVED, block dependent implementation, and ask for resolution; do not substitute a plausible snippet.
