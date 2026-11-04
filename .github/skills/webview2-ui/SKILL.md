---
name: webview2-ui
description: Use when a pyRevit interface benefits materially from web-native layouts, rich visualization, complex filtering, or advanced interaction; WebView2 may be hosted inside WPF.
---

# WebView2 UI

Use WebView2 when its web capabilities provide clear value over WPF. Keep WPF as the shell when native windowing, dialogs, or Revit integration are useful.

- For a new tool, evaluate WebView2 against WPF using the complete workflow and deployment needs. For an existing tool, do not migrate its UI solely to add a feature; prefer a compatible extension unless the request includes a redesign.
- For a UI refinement in an existing WebView2 interface, adjust the requested layout or presentation while preserving established message-bridge behavior. If a control fails or the UI disagrees with an approved design, treat it as a defect and verify the expected interaction/state.
- Verify pyRevit 7's actual WebView2 hosting API, runtime prerequisites, and message bridge before implementation; do not invent method or MCP names.
- Keep the JavaScript/.NET bridge narrow, validate messages, and never expose arbitrary model mutation through untrusted UI input.
- Separate UI rendering from Revit API operations. Route API work through a verified Revit-supported context mechanism.
- Design loading, initialization failure, offline assets, focus, keyboard, and high-DPI states.
- Avoid remote dependencies unless the project explicitly permits them and the deployment behavior is known.
- Test using the actual embedded WebView2 runtime in a representative Revit environment where possible.
- Validate message type, payload, allowed operation, and document/element ownership on the host side; reject unknown messages explicitly. Navigation and local/remote content must not broaden the bridge's authority.
- Run focused existing JavaScript/UI tests and inspect browser-console failures where applicable, then verify the hosted bridge and UI in Revit. A standalone browser preview cannot establish .NET/Revit integration correctness.
- Use [workspace-tooling](../workspace-tooling/SKILL.md) for discovered browser/diagnostic tools and `pyrevit-mcp-testing` for hosted checks. Record startup/disposal, failure, keyboard/high-DPI, and API-handoff evidence separately.
