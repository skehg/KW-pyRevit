# -*- coding: utf-8 -*-
# GroupMapBuilder — Generate version-specific parameter group mapping files
# Runs inside pyRevit for each Revit version

import clr
import json
import os
import System
from datetime import datetime
from System.Reflection import BindingFlags

from pyrevit import revit, script

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import LabelUtils

try:
    from Autodesk.Revit.DB import GroupTypeId
    _GROUPTYPEID_AVAILABLE = True
except ImportError:
    GroupTypeId = None
    _GROUPTYPEID_AVAILABLE = False

try:
    from Autodesk.Revit.DB import BuiltInParameterGroup
    _BIPG_AVAILABLE = True
except ImportError:
    BuiltInParameterGroup = None
    _BIPG_AVAILABLE = False


LABEL_NORMALIZATION_MAP = {
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

REQUIRED_GROUP_FALLBACKS = {
    "other": ("autodesk.parameter.group:other-1.0.0", "Other"),
    "view to sheet positioning": (
        "autodesk.parameter.group:viewToSheetPositioning-1.0.0",
        "View to Sheet Positioning",
    ),
}

FAMILY_PARAM_GROUP_LABELS = frozenset((
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
))

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def get_revit_version():
    """Return major Revit version as int."""
    app = revit.doc.Application
    return int(app.VersionNumber)


def get_version_block(version):
    """Return the version block label used by the production tool."""
    if version <= 2022:
        return "2020-2022"
    if version <= 2024:
        return "2023-2024"
    return "2025-2027"


def get_group_api_type_name():
    """Return the underlying Revit API type used for parameter groups."""
    if _GROUPTYPEID_AVAILABLE:
        return "Autodesk.Revit.DB.GroupTypeId"
    if _BIPG_AVAILABLE:
        return "Autodesk.Revit.DB.BuiltInParameterGroup"
    return "unknown"

def get_group_values():
    """Return parameter group values for the running Revit version."""
    group_values = []
    seen = set()

    def add_candidate(value):
        if value is None:
            return

        key = forgeid_to_string(value)
        if not key or key in seen:
            return

        seen.add(key)
        group_values.append(value)

    if _GROUPTYPEID_AVAILABLE:
        for attr_name in dir(GroupTypeId):
            if attr_name.startswith('_'):
                continue

            try:
                value = getattr(GroupTypeId, attr_name)
            except Exception:
                continue

            add_candidate(value)

        try:
            clr_type = clr.GetClrType(GroupTypeId)
            flags = BindingFlags.Public | BindingFlags.Static

            for prop in clr_type.GetProperties(flags):
                try:
                    add_candidate(prop.GetValue(None, None))
                except Exception:
                    continue

            for field in clr_type.GetFields(flags):
                try:
                    add_candidate(field.GetValue(None))
                except Exception:
                    continue
        except Exception:
            pass

    elif _BIPG_AVAILABLE:
        try:
            for group in System.Enum.GetValues(BuiltInParameterGroup):
                add_candidate(group)
        except Exception:
            pass

    return group_values


def is_user_assignable_group(group_value, label):
    """Return True when Revit is likely to expose this group in the UI."""
    if group_value is None:
        return False

    fm = getattr(revit.doc, "FamilyManager", None) if getattr(revit.doc, "IsFamilyDocument", False) else None

    try:
        checker = getattr(fm, "IsUserAssignableParameterGroup", None)
        if callable(checker):
            return bool(checker(group_value))
    except Exception:
        pass

    try:
        from Autodesk.Revit.DB import FamilyManager
        checker = getattr(FamilyManager, "IsUserAssignableParameterGroup", None)
        if callable(checker):
            return bool(checker(group_value))
    except Exception:
        pass

    normalized_label = normalize_group_label(label)
    return normalized_label in FAMILY_PARAM_GROUP_LABELS


def normalize_group_label(label):
    """Return a normalized group label for comparisons."""
    normalized = " ".join((label or "").strip().lower().split())
    return LABEL_NORMALIZATION_MAP.get(normalized, normalized)


def load_expected_group_labels(base_dir, version):
    """Load expected group labels from the local comparison file if it exists."""
    expected_path = os.path.join(base_dir, "groupactual-{}.txt".format(version))
    if not os.path.exists(expected_path):
        return []

    labels = []
    seen = set()

    with open(expected_path, "r") as expected_file:
        for raw_line in expected_file:
            label = raw_line.strip()
            normalized = normalize_group_label(label)
            if not label or normalized in seen:
                continue
            seen.add(normalized)
            labels.append(label)

    return labels


def ensure_expected_groups(mapping, expected_labels):
    """Supplement mapping with known fallbacks for expected labels."""
    present = set(normalize_group_label(label) for label in mapping.values())
    missing = []

    for label in expected_labels:
        normalized = normalize_group_label(label)
        if normalized in present:
            continue

        fallback = REQUIRED_GROUP_FALLBACKS.get(normalized)
        if fallback:
            type_id, display_label = fallback
            mapping[type_id] = display_label
            present.add(normalized)
            continue

        missing.append(label)

    return missing

def build_group_entry(type_id, label, bucket, version_block, source):
    """Return a fully-described group record for the production manifest."""
    normalized_label = normalize_group_label(label)
    return {
        "type_id": type_id,
        "label": label,
        "normalized_label": normalized_label,
        "bucket": bucket,
        "version_block": version_block,
        "source": source,
    }


def build_group_manifest(group_records, expected_labels, version_block):
    """Split groups into UI-confirmed labels and other labels, plus lookup tables."""
    items_by_label = {}
    items_by_type_id = {}

    for item in group_records:
        type_id = item["type_id"]
        normalized = item["normalized_label"]
        if normalized not in items_by_label:
            items_by_label[normalized] = item
            items_by_type_id[type_id] = item

    actual_groups = []
    used_labels = set()

    if not expected_labels:
        for normalized, item in sorted(items_by_label.items()):
            if not item.get("is_user_assignable"):
                continue
            actual_item = dict(item)
            actual_item["bucket"] = "actual"
            actual_item["source"] = "api_user_assignable"
            actual_groups.append(actual_item)
            items_by_label[normalized] = actual_item
            items_by_type_id[actual_item["type_id"]] = actual_item
            used_labels.add(normalized)

    for label in expected_labels:
        normalized = normalize_group_label(label)
        if normalized in used_labels:
            continue

        item = items_by_label.get(normalized)
        if item is None:
            continue

        actual_item = dict(item)
        actual_item["bucket"] = "actual"
        actual_item["source"] = "expected_list"
        actual_groups.append(actual_item)
        items_by_label[normalized] = actual_item
        items_by_type_id[actual_item["type_id"]] = actual_item
        used_labels.add(normalized)

    for label in expected_labels:
        normalized = normalize_group_label(label)
        if normalized in used_labels:
            continue

        fallback = REQUIRED_GROUP_FALLBACKS.get(normalized)
        if not fallback:
            continue

        type_id, display_label = fallback
        fallback_item = build_group_entry(type_id, display_label, "actual", version_block, "fallback")
        actual_groups.append(fallback_item)
        items_by_label[normalized] = fallback_item
        items_by_type_id[type_id] = fallback_item
        used_labels.add(normalized)

    other_groups = []
    for normalized, item in sorted(items_by_label.items()):
        if normalized in used_labels:
            continue
        other_item = dict(item)
        other_item["bucket"] = "other"
        other_item["source"] = item["source"]
        other_groups.append(other_item)

    return actual_groups, other_groups, items_by_label, items_by_type_id

def resolve_display_name(ftid):
    """Return UI display name for a group value."""
    try:
        return LabelUtils.GetLabelForGroup(ftid)
    except Exception:
        pass
    try:
        return LabelUtils.GetLabelFor(ftid)
    except Exception:
        return None

def forgeid_to_string(ftid):
    """Return a stable identifier string for a group value."""
    type_id = getattr(ftid, 'TypeId', None)
    if type_id:
        return type_id
    if _BIPG_AVAILABLE:
        try:
            return "enum:{}".format(str(ftid))
        except Exception:
            pass
    return None

# ------------------------------------------------------------
# Build mapping
# ------------------------------------------------------------

output = script.get_output()
version = get_revit_version()
version_block = get_version_block(version)
group_api_type = get_group_api_type_name()
ext_dir = os.path.dirname(__file__)

output.print_md("## Building Group Map for Revit {} ({})".format(version, version_block))

mapping = {}
group_records = []

for ftid in get_group_values():
    try:
        key = forgeid_to_string(ftid)
        name = resolve_display_name(ftid)

        if name:
            mapping[key] = name
            group_records.append(build_group_entry(
                key,
                name,
                "other",
                version_block,
                "api",
            ))
            group_records[-1]["is_user_assignable"] = is_user_assignable_group(ftid, name)
    except Exception as ex:
        output.print_md("*Failed on {}: {}*".format(ftid, ex))

expected_labels = load_expected_group_labels(ext_dir, version)
missing_labels = ensure_expected_groups(mapping, expected_labels)

seen_record_ids = set(item["type_id"] for item in group_records)
for type_id, label in mapping.items():
    if type_id in seen_record_ids:
        continue
    item = build_group_entry(type_id, label, "other", version_block, "fallback")
    item["is_user_assignable"] = normalize_group_label(label) in FAMILY_PARAM_GROUP_LABELS
    group_records.append(item)

actual_groups, other_groups, items_by_label, items_by_type_id = build_group_manifest(group_records, expected_labels, version_block)

if missing_labels:
    output.print_md("### Missing expected group labels")
    for label in missing_labels:
        output.print_md("- {}".format(label))
elif not expected_labels:
    output.print_md("### No expected comparison list found")
    output.print_md("Using API-derived user-assignable groups for the actual list.")

# Sort mapping deterministically
sorted_mapping = {k: mapping[k] for k in sorted(mapping.keys())}

# ------------------------------------------------------------
# Build YAML frontmatter + JSON body
# ------------------------------------------------------------

frontmatter = {
    "revit_version": version,
    "schema_version": 1,
    "source": "api-reflection",
    "generated_by": "GroupMapBuilder 1.0",
    "group_api_type": group_api_type,
    "forge_namespace": group_api_type,
    "mapping_type": "parameter_group_displaynames",
    "version_block": version_block,
    "last_verified": datetime.now().strftime("%Y-%m-%d")
}

group_manifest = {
    "actual_group_labels": [item["label"] for item in actual_groups],
    "other_group_labels": [item["label"] for item in other_groups],
    "actual_groups": actual_groups,
    "other_groups": other_groups,
    "missing_expected_labels": missing_labels,
    "lookup": {
        "by_type_id": items_by_type_id,
        "by_normalized_label": items_by_label,
    },
}

# ------------------------------------------------------------
# Write file
# ------------------------------------------------------------

outfile = os.path.join(ext_dir, "groupmap-{}.yaml".format(version))

with open(outfile, "w") as f:
    # YAML frontmatter
    f.write("---\n")
    for k, v in frontmatter.items():
        f.write("{}: {}\n".format(k, v))
    f.write("---\n")

    # JSON body
    f.write(json.dumps({
        "version": version,
        "version_block": version_block,
        "group_api_type": group_api_type,
        "mapping": sorted_mapping,
        "groups": group_manifest,
    }, indent=4))

output.print_md("### ✔ Group map written to:")
output.print_md("`{}`".format(outfile))
