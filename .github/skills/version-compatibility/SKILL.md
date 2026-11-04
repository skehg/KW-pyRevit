---
name: version-compatibility
description: Use when declaring or maintaining compatibility across Revit releases, pyRevit 7 engines, and installed API references.
---

# Version Compatibility

Create an explicit compatibility matrix before claiming support. Record Revit release, API assembly/reference availability, pyRevit build, Python engine, .NET/runtime assumptions, and verification source.

## Process
1. Read the project's declared target versions and bundle engine settings. If absent or conflicting, list the evidence and ask for confirmation instead of assuming defaults.
2. Check each used API member against the relevant release documentation or reference assembly.
3. Isolate version-specific behavior behind small adapters or capability checks when needed.
4. Keep engine-specific syntax and dependencies separate; do not assume IronPython 2.7 and CPython 3.12 are interchangeable.
5. Separate declared support, API verification, static/unit checks, and live-tested environments. Preserve the existing declared range; report missing verification without expanding or silently dropping support.

Discover available stubs, reference assemblies, and installed Revit sessions through [workspace-tooling](../workspace-tooling/SKILL.md). Record the actual versions found rather than embedding a fixed stub ceiling. An MCP lookup validates its selected Revit release only; the editor Python and MCP query engine do not establish bundle-engine compatibility.
