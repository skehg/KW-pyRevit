# -*- coding: utf-8 -*-
"""
family_param_utils.py
---------------------
Shared utility functions for Family Parameter analysis.

Consumed by:
  - Family Management.panel / Purge Parameters.pushbutton
  - Family Management.panel / Create Edit Parameters.pushbutton
  (and any future tool in this extension that needs family-parameter helpers)

Import pattern (pyRevit adds <extension>/lib/ to sys.path automatically):

    from family_param_utils import (
        get_family_parameters,
        find_directly_used_params,
        ...
    )
"""

import json
import os
import re

from Autodesk.Revit.DB import (
    Dimension,
    FilteredElementCollector,
    LabelUtils,
    LinearArray,
    RadialArray,
)

# Maximum number of BFS depth levels ever rendered (mirrors PurgeParameters cap).
MAX_DEPTH_CAP = 10


# Known label cleanup for historic typo variants in source lists.
GROUP_LABEL_NORMALIZATION_MAP = {
    "anal sis results": "analysis results",
    "constuction": "construction",
    "electrical - lighång": "electrical - lighting",
    "electrical - lightng": "electrical - lighting",
    "fire protecton": "fire protection",
    "green budding properties": "green building properties",
    "materials and finishes": "materials and finishes",
    "seaments and fittings": "segments and fittings",
    "stuctural": "structural",
    "stuctural analysis": "structural analysis",
    "stuctural section dimensions": "structural section dimensions",
    "visibiliy": "visibility",
}


# Fallback list mirrors the visible groups shown by Revit family parameter UI.
DEFAULT_VISIBLE_GROUP_LABELS = (
    "analysis results",
    "analytical alignment",
    "analytical model",
    "constraints",
    "construction",
    "data",
    "dimensions",
    "division geometry",
    "electrical",
    "electrical - circuiting",
    "electrical - lighting",
    "electrical - loads",
    "electrical engineering",
    "energy analysis",
    "fire protection",
    "forces",
    "general",
    "graphics",
    "green building properties",
    "identity data",
    "ifc parameters",
    "layers",
    "materials and finishes",
    "mechanical",
    "mechanical - flow",
    "mechanical - loads",
    "model properties",
    "moments",
    "other",
    "overall legend",
    "phasing",
    "photometrics",
    "plumbing",
    "primary end",
    "rebar set",
    "releases / member forces",
    "secondary end",
    "segments and fittings",
    "set",
    "slab shape edit",
    "structural",
    "structural analysis",
    "text",
    "title text",
    "visibility",
)


# ---------------------------------------------------------------------------
# Basic accessors
# ---------------------------------------------------------------------------

def get_family_parameters(fm):
    """Return a list of all FamilyParameter objects from FamilyManager *fm*."""
    getter = getattr(fm, "GetParameters", None)
    if callable(getter):
        try:
            return list(getter())
        except Exception:
            pass
    try:
        return list(fm.Parameters)
    except Exception:
        return []


def normalize_group_label(label):
    """Normalize a parameter-group label for robust matching."""
    normalized = " ".join((label or "").strip().lower().split())
    return GROUP_LABEL_NORMALIZATION_MAP.get(normalized, normalized)


def get_revit_major_version(doc):
    """Return major Revit version as int, or None on failure."""
    try:
        return int(doc.Application.VersionNumber)
    except Exception:
        return None


def _default_groupmap_search_dirs(extra_dirs=None):
    """Return candidate directories that may contain groupmap-<year>.yaml."""
    dirs = []

    # Preferred shared location: extension lib folder (this file's directory).
    try:
        dirs.append(os.path.dirname(__file__))
    except Exception:
        pass

    if extra_dirs:
        for d in extra_dirs:
            if d:
                dirs.append(d)

    unique = []
    seen = set()
    for d in dirs:
        try:
            key = os.path.normcase(os.path.normpath(d))
        except Exception:
            key = d
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def load_groupmap_payload(version, search_dirs=None):
    """Load group map payload for *version* from YAML frontmatter + JSON body.

    Returns a dict with keys: payload, path.
    Returns None when no valid file is found.
    """
    if not version:
        return None

    filename = "groupmap-{}.yaml".format(version)
    for base_dir in _default_groupmap_search_dirs(search_dirs):
        candidate = os.path.join(base_dir, filename)
        if not os.path.exists(candidate):
            continue

        try:
            with open(candidate, "r") as handle:
                raw = handle.read()
        except Exception:
            continue

        body = raw
        if raw.startswith("---"):
            # Frontmatter delimiter parsing must handle both LF and CRLF files.
            lines = raw.splitlines(True)
            if lines:
                for idx in range(1, len(lines)):
                    if lines[idx].strip() == "---":
                        body = "".join(lines[idx + 1:])
                        break

        try:
            payload = json.loads(body.lstrip(u"\ufeff"))
            return {"payload": payload, "path": candidate}
        except Exception:
            continue

    return None


def get_group_label_filter(doc, fallback_labels=None, search_dirs=None):
    """Return map-driven group label metadata for the running Revit version.

    Output dict keys:
      - labels: ordered display labels
      - normalized_set: normalized labels set for membership tests
      - order: normalized label -> zero-based order index
      - source: "groupmap" or "fallback"
      - path: source file path when map-driven
      - version: Revit major version (or None)
    """
    version = get_revit_major_version(doc)
    loaded = load_groupmap_payload(version, search_dirs=search_dirs)

    labels = []
    allowed_type_ids = set()
    source = "fallback"
    source_path = None

    if loaded:
        payload = loaded.get("payload") or {}
        groups = payload.get("groups") or {}
        actual = groups.get("actual_group_labels") or []
        actual_groups = groups.get("actual_groups") or []

        if isinstance(actual_groups, list):
            for item in actual_groups:
                if not isinstance(item, dict):
                    continue
                type_id = item.get("type_id")
                if isinstance(type_id, str) and type_id.strip():
                    allowed_type_ids.add(type_id.strip())

        if isinstance(actual, list):
            labels = [x for x in actual if isinstance(x, str) and x.strip()]
            if labels:
                source = "groupmap"
                source_path = loaded.get("path")

    if not labels:
        base = fallback_labels or DEFAULT_VISIBLE_GROUP_LABELS
        labels = [x for x in base if isinstance(x, str) and x.strip()]

    normalized_set = set()
    order = {}
    ordered_labels = []

    for label in labels:
        normalized = normalize_group_label(label)
        if normalized in normalized_set:
            continue
        normalized_set.add(normalized)
        order[normalized] = len(order)
        ordered_labels.append(label)

    return {
        "labels": ordered_labels,
        "normalized_set": normalized_set,
        "allowed_type_ids": allowed_type_ids,
        "order": order,
        "source": source,
        "path": source_path,
        "version": version,
    }


def safe_formula(fp):
    """Return the formula string for *fp*, or '' on any error."""
    try:
        return fp.Formula or ""
    except Exception:
        return ""


def param_name(fp):
    """Return the Definition.Name of a FamilyParameter, or '' on error."""
    try:
        return fp.Definition.Name or ""
    except Exception:
        return ""


def group_label(fp):
    """Return a human-readable group label for a FamilyParameter."""
    try:
        g = fp.Definition.ParameterGroup
    except Exception:
        return ""
    try:
        return LabelUtils.GetLabelFor(g)
    except Exception:
        try:
            return str(g)
        except Exception:
            return ""


def data_type_label(fp):
    """Return a human-readable data-type string for a FamilyParameter."""
    try:
        dt = fp.Definition.ParameterType
        return str(dt)
    except Exception:
        pass
    try:
        dt = fp.Definition.GetDataType()
        return LabelUtils.GetLabelForSpec(dt)
    except Exception:
        pass
    return ""


def _find_longest_param_matches(formula_text, known_param_names):
    """Return non-overlapping longest parameter-name matches in *formula_text*.

    Matching uses the same token-boundary rule as formula parsing, and resolves
    collisions by preferring the longest name at each position.
    """
    if not formula_text or not known_param_names:
        return []

    candidates = []
    seen_names = set()

    for raw_name in known_param_names:
        name = (raw_name or "").strip()
        if not name:
            continue

        name_lower = name.lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        try:
            pattern = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(re.escape(name))
            for m in re.finditer(pattern, formula_text, flags=re.IGNORECASE):
                candidates.append((m.start(), m.end(), name_lower))
        except Exception:
            continue

    if not candidates:
        return []

    # Keep the longest match when multiple names start at the same position.
    best_by_start = {}
    for start, end, name_lower in candidates:
        current = best_by_start.get(start)
        if current is None or (end - start) > (current[1] - current[0]):
            best_by_start[start] = (start, end, name_lower)

    # Suppress nested overlaps (e.g. "handle" inside "handle Offset").
    accepted = []
    for start in sorted(best_by_start.keys()):
        start_i, end_i, name_i = best_by_start[start]
        if accepted and start_i < accepted[-1][1]:
            continue
        accepted.append((start_i, end_i, name_i))

    return accepted


def formula_references_parameter(formula_text, parameter_name, known_param_names=None):
    """Return True when *parameter_name* is truly referenced in *formula_text*.

    When *known_param_names* is provided, matching is resolved against that full
    parameter-name set and prefers the longest valid name at each position.
    """
    if not formula_text or not parameter_name:
        return False

    target_name = (parameter_name or "").strip().lower()
    if not target_name:
        return False

    try:
        if known_param_names:
            matches = _find_longest_param_matches(formula_text, known_param_names)
            return any(name == target_name for _, _, name in matches)

        pattern = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(re.escape(parameter_name))
        return re.search(pattern, formula_text, flags=re.IGNORECASE) is not None
    except Exception:
        return False


def is_family_type_parameter(fp):
    """Return True if *fp* is a FamilyType parameter (should never be purged or deleted)."""
    try:
        from Autodesk.Revit.DB import ParameterType
        return fp.Definition.ParameterType == ParameterType.FamilyType
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import SpecTypeId
        return fp.Definition.GetDataType() == SpecTypeId.Reference.FamilyType
    except Exception:
        pass
    return "familytype" in data_type_label(fp).lower().replace(" ", "")


def is_system_parameter(fp):
    """Return True if *fp* is a built-in / system parameter (negative ElementId).

    System params like 'Model', 'Manufacturer', 'URL' etc. are built-in and
    should never be shown in purge/delete UIs.
    """
    try:
        pid = fp.Id
        try:
            int_val = int(pid.Value)        # Revit 2024+ (Int64)
        except AttributeError:
            int_val = int(pid.IntegerValue)
        return int_val < 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core "in-use" detection
# ---------------------------------------------------------------------------

def _revit_obj_name(obj):
    """Safely get a name from a Revit object that might be a .NET null.

    In IronPython, methods returning a null Revit reference type come back as
    a Python object that is NOT None but has no usable data.  Accessing any
    real property on it (like .Id) throws, which we use to detect nulls.
    """
    if obj is None:
        return None
    try:
        _ = obj.Id      # throws on .NET null wrappers
        return param_name(obj) or None
    except Exception:
        return None


def find_directly_used_params(doc, fm):
    """Return the set of FamilyParameter objects that are directly in use.

    Uses only read-only API calls — no transaction tests.

    Pass 1 – Dimension labels: any parameter assigned as a dimension label is
             directly in use.

    Pass 2 – GetAssociatedFamilyParameter: for every non-type element in the
             document, iterates its parameters and calls
             FamilyManager.GetAssociatedFamilyParameter(param).  This covers
             nested family instance parameters, array-count parameters,
             element visibility conditions, and Yes/No parameters.

    Pass 3 – Array count & label associations on LinearArray / RadialArray.
    """
    all_params = get_family_parameters(fm)
    directly_used_names = set()

    # Pass 1: dimension labels
    try:
        dims = FilteredElementCollector(doc).OfClass(Dimension).ToElements()
        for dim in dims:
            try:
                lbl = dim.FamilyLabel
                if lbl is not None:
                    directly_used_names.add(param_name(lbl))
            except Exception:
                pass
    except Exception:
        pass

    # Pass 2: element parameter associations
    try:
        elements = (
            FilteredElementCollector(doc)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        for elem in elements:
            try:
                for p in elem.Parameters:
                    try:
                        assoc_fp = fm.GetAssociatedFamilyParameter(p)
                        n = _revit_obj_name(assoc_fp)
                        if n:
                            directly_used_names.add(n)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    # Pass 3: array count / label associations
    for array_class in (LinearArray, RadialArray):
        try:
            arrays = (
                FilteredElementCollector(doc)
                .OfClass(array_class)
                .WhereElementIsNotElementType()
                .ToElements()
            )
            for arr in arrays:
                for attr in ("FamilyParameterForCount", "Label"):
                    try:
                        n = _revit_obj_name(getattr(arr, attr, None))
                        if n:
                            directly_used_names.add(n)
                    except Exception:
                        pass
        except Exception:
            pass

    return set(fp for fp in all_params if param_name(fp) in directly_used_names)


def find_formula_referencing_params(fm, target_param_name):
    """Return a list of parameter names whose formulas reference *target_param_name*.

    Used by the Delete button to warn the user which other parameters will
    have broken formulas if *target_param_name* is deleted.
    """
    all_params = get_family_parameters(fm)
    known_names = [param_name(fp) for fp in all_params if param_name(fp)]

    referencing = []
    for fp in all_params:
        f = safe_formula(fp)
        if f and formula_references_parameter(f, target_param_name, known_param_names=known_names):
            referencing.append(param_name(fp))
    return referencing


# ---------------------------------------------------------------------------
# BFS depth analysis (used by Purge Parameters)
# ---------------------------------------------------------------------------

def build_depth_analysis(fm, directly_used, max_depth):
    """BFS from the directly-used set following formula dependencies.

    At each depth level we look for parameters (not yet marked unsafe) whose
    name appears in the formula of a parameter in the current unsafe frontier.
    Repeats up to *max_depth* times.

    Returns (safe_list, unsafe_name_set).
    """
    all_params = get_family_parameters(fm)
    known_names = [param_name(fp) for fp in all_params if param_name(fp)]
    name_to_formula = {param_name(fp): safe_formula(fp) for fp in all_params}

    unsafe_names = set(param_name(fp) for fp in directly_used)
    frontier = set(unsafe_names)

    for _depth in range(max_depth):
        next_frontier = set()
        for fp in all_params:
            name = param_name(fp)
            if name in unsafe_names:
                continue
            for f_name in frontier:
                formula = name_to_formula.get(f_name, "")
                if formula and formula_references_parameter(formula, name, known_param_names=known_names):
                    next_frontier.add(name)
                    break
        if not next_frontier:
            break
        unsafe_names |= next_frontier
        frontier = next_frontier

    safe_params = [
        fp for fp in all_params
        if param_name(fp) not in unsafe_names
        and not is_family_type_parameter(fp)
        and not is_system_parameter(fp)
    ]
    return safe_params, unsafe_names


def compute_reverse_deps(safe_params, max_depth):
    """Within the safe pool, compute reverse formula dependencies at each depth hop.

    Returns a dict: {param_name: {1: "name1, name2", 2: "name3", ...}}.

    Depth 1 = safe params whose own formula directly references this param.
    Depth 2 = safe params whose formula references a D1 intermediate, etc.
    """
    safe_names = set(param_name(fp) for fp in safe_params)
    known_names = [param_name(fp) for fp in safe_params if param_name(fp)]
    name_to_formula = {param_name(fp): safe_formula(fp) for fp in safe_params}

    # direct_refs[a] = set of safe param names that appear in formula of 'a'
    direct_refs = {}
    for fp in safe_params:
        name = param_name(fp)
        formula = name_to_formula.get(name, "")
        direct_refs[name] = set()
        if formula:
            for other in safe_names:
                if other != name and formula_references_parameter(formula, other, known_param_names=known_names):
                    direct_refs[name].add(other)

    # reverse_refs[b] = set of safe param names whose formula references 'b'
    reverse_refs = {name: set() for name in safe_names}
    for a, refs in direct_refs.items():
        for b in refs:
            reverse_refs[b].add(a)

    result = {name: {} for name in safe_names}

    for pname in safe_names:
        visited = {pname}
        current_level = reverse_refs.get(pname, set()) - visited
        for depth in range(1, max_depth + 1):
            if not current_level:
                break
            result[pname][depth] = ", ".join(sorted(current_level))
            visited |= current_level
            next_level = set()
            for n in current_level:
                for parent in reverse_refs.get(n, set()):
                    if parent not in visited:
                        next_level.add(parent)
            current_level = next_level

    return result
