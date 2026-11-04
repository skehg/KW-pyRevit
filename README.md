# KW-pyRevit
KW Tools for pyRevit

## Agent-assisted development

The [workspace instructions](.github/copilot-instructions.md) connect the [four agents](.github/agents) and [task-specific skills](.github/skills). Use the orchestrator for multi-part work, the pyRevit engineer for command logic, the UI/UX engineer for interfaces, and QA for independent review. Small changes can stay direct.

The [tooling skill](.github/skills/workspace-tooling/SKILL.md) explains how to use installed VS Code extensions, pyRevit MCP, and Penpot MCP without assuming unavailable capabilities. Extension commands are not automatically chat tools; actual runtime and design checks require the relevant connected session.

Each handoff should carry acceptance criteria, runtime targets, file ownership, and verification evidence. Reports distinguish static/unit checks from live Revit/UI tests and explicitly identify blocked or unrun checks. Live writes, including rollback previews, require an approved test document and scope.
