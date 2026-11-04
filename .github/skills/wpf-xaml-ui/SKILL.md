---
name: wpf-xaml-ui
description: Use for standard pyRevit dialogs, forms, settings, data grids, selection tools, progress windows, and modeless utilities; WPF/XAML is the default UI.
---

# WPF / XAML UI

Choose WPF/XAML by default for conventional Revit interfaces because it fits native Windows controls and .NET integration. Confirm the project's UI loading pattern and supported runtime before selecting syntax or libraries.

- Define a compact workflow with clear primary actions, cancel behavior, validation, and empty/error states.
- For a new tool, establish the full task flow and window/dialog structure. For a feature, preserve established controls, bindings, defaults, and keyboard behavior while adding the smallest coherent interaction.
- For a UI refinement, make the requested layout/presentation change without altering the control's command or data behavior. Treat broken interaction or a mismatch against an agreed design as a bug and verify the corrected state.
- Keep UI event handlers small; isolate model logic and respect Revit API context/thread constraints.
- Use data binding or established project patterns for lists and grids; avoid blocking the UI during long work.
- Support keyboard use, readable labels, sensible tab order, and adequate contrast.
- Handle window ownership/lifetime and modeless behavior using verified pyRevit patterns.
- Validate XAML and code against the target engine; syntax accepted by one runtime may not work in another.
- For modeless UI, marshal model work through a verified Revit API-context mechanism; a WPF dispatcher alone does not grant API context. Keep reads/writes out of worker threads.
- Test bindings/events, Enter/Escape and cancellation, tab/focus order, resizing/high DPI, empty/error states, and progress on affected paths. XML parsing cannot validate WPF resources, runtime bindings, or actual layout.
- Use [workspace-tooling](../workspace-tooling/SKILL.md) and `pyrevit-mcp-testing` for available evidence; use `penpot-design` when an approved design exists. Record actual hosted screenshots/interactions and label unavailable runtime checks.
