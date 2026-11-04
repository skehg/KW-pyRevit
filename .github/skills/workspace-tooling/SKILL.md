---
name: workspace-tooling
description: Use when planning, implementing, or reviewing workspace changes that need VS Code extensions, RVTDocs, Python/Pylance, PowerShell, pyRevit MCP, Penpot MCP, or test evidence.
argument-hint: "Task, files in scope, target runtime, and capabilities or checks needed"
---

# Workspace Tooling and Evidence

Use only the capabilities needed for the task. An installed extension, a registered MCP server, an exposed tool, and a successful operation are different levels of evidence.

## Capability discovery
1. Read project instructions, relevant bundle configuration, and the current diff. Preserve unrelated work.
2. Discover the current host's tools and inspect their descriptions and schemas before invoking them. Tool names can differ between VS Code and CLI hosts; the operation names below are discovery terms, not guaranteed callable identifiers.
3. Use installed extension manifests/help to verify editor commands not exposed as tools. Never run a command-palette ID as a shell command or pretend that installing an extension makes its commands chat-callable.
4. Record the relevant capability, source, target, result, and limitation in the task context. Reuse verified information within the task; refresh it if the session, engine, document, or configuration changes. Do not load every skill or probe every integration for a small fix.
5. If a capability is unavailable, state the blocked check and use a verified alternative for independent work. Ask for user action only when needed to continue. Do not install extensions, change interpreters/configuration, reload pyRevit, or create external artifacts without task authorization.

## Extension routing
These installed extension IDs identify local documentation to inspect; confirm their current contributions rather than assuming a fixed version.

| Extension | Appropriate use | Boundary |
|---|---|---|
| RVTDocs (`learnrevitapi.rvtdocs-com`) | Release-specific Revit API documentation. Verified editor commands include `rvtdocs.search` and `rvtdocs.setVersion`. | Editor/webview commands are not MCP tools. A search result or snippet is not verification of the full overload or release range. |
| PowerShell (`ms-vscode.powershell`) | Windows terminal/task execution and PowerShell script diagnostics/debugging when exposed by the host. | Use the actual terminal/task tools; the extension does not itself expose a general chat execution tool. Use Windows paths and PowerShell syntax, noninteractive commands, and bounded output. |
| Python (`ms-python.python`) | Discover the selected interpreter, execution command, test runner, and dependencies through available environment tools. | Follow each tool's configuration prerequisites. Do not silently switch environments or install packages. The editor interpreter is not Revit's embedded engine. |
| Pylance (`ms-python.vscode-pylance`) | Definitions, references, signatures, imports, and diagnostics through exposed language/MCP tools. | Stubs and Python 3 analysis do not prove Revit-version or IronPython compatibility. Do not add annotations or apply fix-all to IronPython code. |
| pyRevit with VSCode (`baptistelechat.pyrevit-with-vscode`) | Inspect setup, documentation, components, and snippets for authoring help. | Setup changes configuration; snippets are examples, not API proof. This extension is not a Revit execution bridge. Use pyRevit MCP for live operations. |
| Chat Customizations Evaluations (`ms-vscode.vscode-chat-customizations-evaluations`) | Analyze changed agents/skills when a callable editor-command capability exists; otherwise describe the manual check. | `chatCustomizationsEvaluations.analyzePrompt` is an editor command, not a shell command. No Problems diagnostics alone does not prove a fresh evaluation ran. |

For other extensions, inspect their actual contributed commands/tools before relying on them. Prefer existing language services, test discovery, debugger, and tasks over new tooling.

## pyRevit MCP routing
- Load [pyrevit-mcp-testing](../pyrevit-mcp-testing/SKILL.md) before live checks and [revit-api](../revit-api/SKILL.md) for API verification.
- Discover `list_revit_instances` and `get_context`. Select the intended process explicitly if multiple sessions exist; confirm document, version, policy, and engine before scripting. A responding process alone does not prove the document is accessible.
- Read the server's `revit-scripting` guidance before queries, dry runs, or writes, plus `pyrevit-library` before choosing raw API code. Discover `lookup_pyrevit_api` for maintained helpers and `lookup_revit_api` for exact types/members in the selected release.
- Verify API signatures, overloads, types, and context for introduced or changed calls. Keep per-release evidence; one running Revit release does not certify others.
- MCP-injected globals and the query engine are not the deployed button's imports or bundle engine. Test the actual command before claiming end-to-end coverage.
- Treat `run_query` as read-only by intent, not a sandbox. Rollback does not undo filesystem/network/process side effects. Keep scripts bounded and side-effect-free.
- Writes, including `run_modify` dry runs, need an explicitly approved disposable test document and bounded scope. Preview first, then obtain approval for commits; policy `auto` is not user authorization. Verify postconditions, failures, and Undo.
- For `revit_busy` or a modal dialog, report the blocker and let the user resolve it. Do not close windows, retry indefinitely, or switch to a different document to bypass it.
- Read `get_run` for truncated/pending results when documented. Report rejection, timeout, rollback, and errors as such, not success. Do not promise save/export operations that the runtime blocks.

## Penpot MCP routing
- Load [penpot-design](../penpot-design/SKILL.md). Read the chosen server's high-level overview before API/code tools, then inspect the API documentation for the required members.
- Confirm the connected file/page/frame and permission scope using read-only inspection. If duplicate server registrations exist, choose one verified connection and do not write through both.
- Design edits require task scope; never overwrite a reference design or assume asset export/code generation is available. If disconnected, report it and proceed only with clearly labeled local design work that does not depend on unavailable evidence.
- If the browser freezes the plugin tab, ask the user to focus/wake the connected Penpot tab before a bounded retry. If it remains blocked, report the limitation; do not loop or switch registrations to bypass it.
- Penpot checks design intent; screenshots and interaction checks in the actual WPF/embedded WebView2 host establish implementation behavior. Neither substitutes for the other.

## Verification contract
- Run the smallest relevant existing tests and diagnostics for a code change; add regression coverage for changed behavior where the test framework permits. Inspect commands before executing them if their effects are unclear.
- Report each acceptance criterion as passed, failed, blocked, or not run, with the command/tool, target runtime, and observed result. A proposed command is not executed evidence.
- Separate static checks, mocked/unit tests, MCP script checks, and actual button/UI checks. Record unsupported or untested environments without claiming support.
- Do not suppress new diagnostics, swallow errors, or install dependencies to make a review appear clean. Report pre-existing failures separately from regressions.
- Keep evidence concise in the conversation/handoff unless a persistent report is requested. Never send proprietary code, model data, secrets, or logs to an external service without authorization.
