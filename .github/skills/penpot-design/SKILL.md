---
name: penpot-design
description: Use when planning, creating, or visually reviewing pyRevit UI designs in the connected Penpot workspace.
---

# Penpot Design and Review

Use Penpot to clarify hierarchy, layout, component states, and visual consistency before or during UI implementation.

- Confirm which Penpot project/file and available connected operations are in scope.
- Discover the chosen server's high-level overview and read it before API/code tools. Inspect required members through its API-info tool; do not guess plugin properties from browser/DOM conventions.
- Confirm the connected file/page/frame read-only before edits. If duplicate registrations exist, use one verified connection. Limit writes/exports to the approved scope and never overwrite a reference design without authorization.
- Start from the user's task flow and target UI technology; annotate interaction states and responsive/layout constraints as relevant.
- For a new tool, map the complete primary workflow and key states before polishing screens; check fit with the extension's existing visual language.
- For a feature, inspect existing screens/components and extend their patterns. Mark any broader redesign as a separate proposal so feature scope remains clear.
- For a UI refinement, capture the specific requested adjustment (such as position, spacing, hierarchy, or wording) and review that change in context. If the current UI contradicts an approved design or impairs use, record it as a defect with an observable expected state.
- Capture tokens for colors, spacing, typography, and control sizing when present.
- Give engineering a concise handoff: frame/page identifiers, component behavior, assets, dimensions, and unresolved questions.
- Compare implementation screenshots to the approved design when available and record concrete discrepancies.
- Do not assume the Penpot MCP can create, export, inspect, or edit a particular artifact; verify tool capabilities and actual results first.
- If the plugin/file is disconnected, report the exact blocker. Proceed with labeled local design work only where it does not depend on missing evidence; do not invent frame identifiers or call a mockup "Penpot reviewed."
- A browser-frozen plugin tab requires the user to focus/wake the connected tab. Retry only after that action; if still blocked, preserve the error and do not claim design inspection succeeded.
- Follow [workspace-tooling](../workspace-tooling/SKILL.md) for capability/evidence rules. Return design identifiers, observed/exported evidence, discrepancies, and unresolved checks; actual WPF/WebView2 interaction checks remain separate.
