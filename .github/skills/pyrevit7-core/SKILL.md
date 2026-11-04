---
name: pyrevit7-core
description: Use when structuring, extending, or debugging pyRevit 7 extensions, bundles, ribbon commands, and configuration.
---

# pyRevit 7 Core

Inspect the current extension and pyRevit 7 configuration before applying generic examples. Confirm bundle naming, entry-point files, pushbutton/panel/tab layout, icons, configuration, and selected engine from the project itself.

Load [workspace-tooling](../workspace-tooling/SKILL.md) for installed extension capabilities, MCP discovery, and the verification contract. The pyRevit VS Code extension provides authoring help, not live Revit execution.

## Workflow
1. Find repository instructions and nearby working examples.
2. Classify the work as a new tool, feature, failure/behavior bug, UI refinement, or mixed change; load `debugging` for defects.
3. For a new tool, choose an appropriate bundle location and command identity; check for overlapping commands and match extension conventions.
4. For a feature, trace the existing bundle, settings, entry points, and user behavior before editing. Keep the change localized and preserve compatibility and defaults unless the request says otherwise.
5. Identify extension bundle type, script entry point, engine, dependencies, and Revit targets. Resolve missing/conflicting declarations with the user; neither the editor interpreter nor the MCP script engine establishes the button engine.
6. Follow existing pyRevit conventions and keep changes localized.
7. Verify packaging, imports, and command discovery using confirmed commands. Use the MCP server's `extension-authoring` guidance when applicable, but adapt its standalone-agent examples to this authorized repository scope. Do not register another extension, change search paths, or reload a running session without authorization. A successful reload is not proof that the changed button ran correctly.

Do not assume a command name, bundle capability, or engine setting. Treat pyRevit 7 behavior as environment-specific until confirmed against installed documentation or a working project example.
