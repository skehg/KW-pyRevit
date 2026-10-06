# Family Clean Manager

## Purpose

Create a pyRevit tool called **Family Clean Manager** that helps users identify and remove unnecessary content from Revit family files (.rfa).

The tool should prioritize:

* Safety
* User control
* Fast startup
* Progressive analysis
* No automatic modification of nested families

The tool is intended for family documents only.

If launched outside a family document, show an appropriate error message.

---

# User Experience

## First Launch

When the tool is opened:

* Analyse ONLY the currently active family document.
* Do not inspect nested families.
* Analysis should complete quickly.

The UI should be modeless if possible.

If a true modeless implementation is difficult in pyRevit/WPF, create the architecture so that a modeless implementation can be added later.

---

# Primary Workflow

Users should be able to:

1. Open Family Clean Manager.
2. Review issues in the current family.
3. Delete or replace selected items.
4. Click "Analyse Family" to refresh results.
5. Optionally run a Deep Scan.
6. Open nested families for manual cleaning.

The workflow is intentionally iterative.

Example:

* Delete unused materials.
* Re-analyse.
* Fill patterns become unused.
* Delete fill patterns.
* Re-analyse.
* Continue until clean.

The system must NOT assume that all dependencies can be solved in one pass.

---

# Categories To Analyse

The following categories must be implemented as independent scanner modules.

---

## Materials

Detect:

* Total materials.
* Unused materials.

Allow:

* Multi-select deletion.
* Refresh analysis after deletion.

---

## Fill Patterns

Detect usage in:

* Materials.
* Filled regions.
* Revit 2023+ Fill Pattern parameters.

Allow:

* Multi-select deletion.
* Replacement of one fill pattern with another.

Built-in protected patterns (for example Solid Fill) must not be deletable.

---

## Line Patterns

Detect:

* Custom line patterns.
* Potentially unused patterns.

Allow:

* Multi-select deletion.

Conservative behaviour is preferred.

---

## Arrowheads

Detect:

* Custom arrowheads.
* Potentially unused arrowheads.

Allow:

* Multi-select deletion.

---

## Subcategories

Do NOT attempt to determine usage.

Simply display all subcategories.

Allow:

* User selection.
* Manual deletion.

This behaviour intentionally mirrors the existing pyRevit "Wipe Subcategories" tool.

The user is responsible for deciding what to remove.

---

## DWG Imports

Detect:

* ImportInstance elements.
* Imported file names where possible.

Allow:

* User deletion.

---

## Exploded CAD Indicators

Do not automatically delete.

Only report:

* CAD-style subcategory names.
* Layer 0.
* A-*, S-*, M-* naming conventions.
* Large numbers of imported line patterns.

These are advisory warnings only.

---

# Deep Scan

A button called:

"Deep Scan Nested Families"

should:

* Discover nested families.
* Analyse them.
* Build a summary.

Deep Scan must NOT automatically modify nested families.

The purpose is to generate recommendations.

Example:

Vendor_Hinge.rfa

* 1 DWG import
* 14 subcategories
* 3 line patterns

---

# Nested Family Actions

Each nested family entry should provide:

Open

The Open action should:

* Activate the family document if already open.
* Otherwise call EditFamily().
* Switch Revit to that family.
* Trigger a refresh of Family Clean Manager.

The user should then clean that family manually.

No automatic save or reload behaviour should occur.

The user remains in control.

---

# UI Requirements

Preferred:

Modeless WPF window.

Required:

A design that can support modeless behaviour later.

Suggested layout:

Family Name

Buttons:

* Analyse Family
* Deep Scan Nested Families

Tabs:

* Materials
* Fill Patterns
* Line Patterns
* Arrowheads
* Subcategories
* DWG Imports
* Nested Families

Each tab should support:

* Multi-selection.
* Delete Selected.
* Refresh.

---

# Architecture

Create independent scanner classes.

Examples:

MaterialScanner
FillPatternScanner
LinePatternScanner
ArrowheadScanner
SubcategoryScanner
DWGScanner
NestedFamilyScanner

Each scanner should return:

Issue objects.

Suggested structure:

class Issue:
category
name
element_id
severity
can_delete
can_replace
notes

The UI should consume these Issue objects.

The architecture should make it easy to add future scanners.

---

# Safety Requirements

Never automatically delete anything.

Always require explicit user selection.

Never automatically modify nested families.

Never automatically save family files.

Never automatically reload nested families.

Always allow the user to refresh analysis after making changes.

---

# Revit Version Support

Target:

Revit 2023+

Specifically support:

* Fill Pattern parameter types introduced in Revit 2023.

The implementation should gracefully degrade on later versions if API behaviour changes.

---

# Phase 1 Deliverable

The initial implementation should include:

* Materials
* Fill Patterns
* Subcategories
* DWG Imports
* Deep Scan summaries
* Open Nested Family action

Line patterns, arrowheads, and advanced dependency analysis may be implemented afterward.

# pyRevit Integration

The tool should live under a dedicated:

Family Tools

panel.

The command should only be visible and usable when the active document is a family document (.rfa).

If launched from a project document, display a clear message explaining that Family Clean Manager only operates on family files.

---

# UI Implementation Strategy

Phase 1 should use a standard WPF window.

Do NOT implement a true modeless or dockable pane in Phase 1.

However, the architecture must be designed so that a future version can replace the window implementation with:

* A modeless WPF window.
* A dockable pane.
* Automatic refresh when the active document changes.

Avoid coupling business logic to UI implementation details.

All scanner and action logic must remain independent of the window implementation.

---

# Extensibility Requirements

Every scanner must be independently testable.

Scanners should not communicate directly with one another.

Each scanner must:

* Accept a Document object.
* Return Issue objects.
* Contain no UI logic.
* Contain no transaction management except where explicitly required.

Future scanners should be easy to add without modifying existing implementations.

Examples of future modules:

* LinePatternScanner
* ArrowheadScanner
* FamilyTypeScanner
* ParameterScanner
* ReferencePlaneScanner
* ExplodedCADScanner

The system should follow an extensible plugin-style architecture wherever practical.

