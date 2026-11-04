---
name: revit-transactions
description: Use whenever a pyRevit tool creates, changes, deletes, or otherwise mutates Revit model data.
---

# Revit Transactions

Treat model edits as explicit, minimal, reversible operations. Confirm document context and modifiability before making changes.

1. Separate read/plan work from mutation.
2. Validate selections, element state, and inputs before opening a transaction.
3. Use the transaction abstraction appropriate to the verified pyRevit/API context; do not mix transaction ownership patterns without understanding them.
4. Define atomic versus partial-success behavior before writing. Keep scope small; check transaction status, commit only after validated success, and roll back on failure. Never swallow a write error and report success.
5. Do not nest top-level transactions. Use a verified SubTransaction or TransactionGroup only when the operation needs its documented semantics; do not hold transactions open across user input, network calls, or background work.
6. Report intended versus actual changes and any explicit partial-failure behavior. Verify postconditions, failure rollback, and Undo in an approved test document.

For live MCP tests, load [pyrevit-mcp-testing](../pyrevit-mcp-testing/SKILL.md). Both dry runs and commits execute mutation logic and require scoped authorization and a safe test document. Rollback does not undo filesystem/network/process side effects; never put these inside a supposedly reversible test.
