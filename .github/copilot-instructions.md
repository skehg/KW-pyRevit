# Workspace workflow

- Read the [project coding instructions](../copilot-instructions.md) before changing or reviewing extension code.
- Load [workspace-tooling](./skills/workspace-tooling/SKILL.md) when using extensions, MCP integrations, or test evidence. Discover actual tools; installed extensions alone do not establish callable capabilities.
- Use only task-relevant skills and agents. Keep simple work direct; use bounded specialist handoffs for substantial independent work.
- Resolve unknown or conflicting target engine/Revit versions before implementation. Never infer the deployed engine from the editor interpreter or an MCP query's engine.
- Preserve unrelated work. Use focused tests and report passed, failed, blocked, and not-run checks honestly; never equate static checks with live Revit/UI verification.
