# -*- coding: utf-8 -*-
"""Parameter identity and semantic data types, independent of display names."""

import json
import re

from core.types import element_id_value


def compatible_spec(spec_id):
    """Forge spec patch/minor versions do not change the physical quantity."""
    return re.sub(r"-([0-9]+)\.[0-9]+\.[0-9]+$", r"-\1", spec_id)


def parameter_group_key(descriptor):
    return json.dumps(["field", descriptor["name"],
                       compatible_spec(descriptor["specTypeId"]),
                       descriptor["storageType"]], separators=(",", ":"))


def collapse_usage(usage, conflicts):
    groups = {}
    for key, entry in usage.items():
        groups.setdefault(parameter_group_key(entry), []).append(key)
    result = {}
    for group_key, keys in groups.items():
        # Coexisting definitions cannot be represented by one cell without data loss.
        if group_key in conflicts:
            identities = {}
            for key in keys:
                identities.setdefault(usage[key]["identity"], []).append(key)
            for identity, member_keys in identities.items():
                if len(member_keys) == 1:
                    key = member_keys[0]
                    entry = dict(usage[key])
                else:
                    entry = next(iter(collapse_usage(
                        dict((key, usage[key]) for key in member_keys), set()).values()))
                    key = json.dumps([identity, compatible_spec(entry["specTypeId"]),
                                      entry["storageType"]], separators=(",", ":"))
                    entry["key"] = key
                    entry["identity"] = identity
                entry["displayName"] = "{0} [{1}; {2}]".format(
                    entry["name"], entry["dataType"], entry["identity"])
                result[key] = entry
            continue
        entry = dict(usage[keys[0]])
        entry["key"] = group_key
        entry["identity"] = group_key
        entry["members"] = sorted(keys)
        entry["guid"] = None
        entry["builtin"] = None
        entry["displayName"] = entry["name"]
        for flag in ("isType", "isInstance", "usefulType", "usefulInstance"):
            entry[flag] = any(usage[key].get(flag, False) for key in keys)
        for field in ("categoryIds", "typeCategoryIds", "instanceCategoryIds",
                      "usefulTypeCategoryIds", "usefulInstanceCategoryIds"):
            entry[field] = sorted(set(value for key in keys
                                      for value in usage[key].get(field, [])))
        labels = {}
        for key in keys:
            labels.update(zip(usage[key]["categoryIds"], usage[key]["categoryNames"]))
        entry["categoryNames"] = [labels[value] for value in entry["categoryIds"]]
        entry["categoryCount"] = len(entry["categoryIds"])
        result[group_key] = entry
    names = {}
    for key, entry in result.items():
        names.setdefault(entry["name"], []).append(key)
    for keys in names.values():
        if len(keys) > 1:
            for key in keys:
                entry = result[key]
                if "members" in entry and entry["identity"] == parameter_group_key(entry):
                    entry["displayName"] = "{0} [{1}]".format(entry["name"], entry["dataType"])
    return result


def restore_parameter_keys(usage, keys):
    """Keep existing presets' explicit identity selections valid after UI grouping."""
    for key in keys:
        if key in usage:
            continue
        for entry in list(usage.values()):
            if key not in entry.get("members", []):
                continue
            identity, spec, storage = json.loads(key)
            restored = dict(entry, key=key, identity=identity, specTypeId=spec,
                            storageType=storage)
            restored.pop("members", None)
            restored["guid"] = identity[len("shared:"):] if identity.startswith("shared:") else None
            restored["builtin"] = int(identity[len("builtin:"):]) if identity.startswith("builtin:") else None
            usage[key] = restored
            break


def canonical_parameter_keys(usage, keys):
    """Resolve old picker selections to current groups without adding alias rows."""
    members = {}
    for key, entry in usage.items():
        for member in entry.get("members", []):
            members[member] = key
    result = []
    for original in keys:
        key = members.get(original, original)
        if key not in usage:
            # A prior conflict group used identity + version-independent spec.
            try:
                parts = json.loads(original)
            except (TypeError, ValueError):
                parts = []
            matches = set()
            if isinstance(parts, list) and len(parts) == 3:
                identity, spec, storage = parts
                for member, group in members.items():
                    member_identity, member_spec, member_storage = json.loads(member)
                    if (member_identity == identity and member_storage == storage
                            and compatible_spec(member_spec) == compatible_spec(spec)):
                        matches.add(group)
            if len(matches) == 1:
                key = matches.pop()
        if key not in result:
            result.append(key)
    return result


def parameter_identity(doc, owner, parameter):
    from Autodesk.Revit.DB import ElementType, ParameterElement

    if parameter.IsShared:
        return "shared:" + str(parameter.GUID)
    parameter_id = element_id_value(parameter.Id)
    if parameter_id < 0:
        return "builtin:{0}".format(parameter_id)
    definition_element = doc.GetElement(parameter.Id)
    if isinstance(definition_element, ParameterElement):
        return "project:" + definition_element.UniqueId
    type_element = owner if isinstance(owner, ElementType) else doc.GetElement(owner.GetTypeId())
    family = getattr(type_element, "Family", None)
    scope = family.UniqueId if family is not None else owner.UniqueId
    return "local:{0}:{1}".format(scope, parameter_id)


def parameter_descriptor(doc, owner, parameter):
    from Autodesk.Revit.DB import Category, LabelUtils

    spec = parameter.Definition.GetDataType()
    spec_id = spec.TypeId
    storage = str(parameter.StorageType)
    if not spec_id:
        label = "Reference" if storage == "ElementId" else "Unspecified ({0})".format(storage)
    elif Category.IsBuiltInCategory(spec):
        category = Category.GetCategory(doc, Category.GetBuiltInCategory(spec))
        if category is None:
            raise ValueError("Cannot resolve the category data type for '{0}'.".format(
                parameter.Definition.Name))
        label = "{0} reference".format(category.Name)
    else:
        label = LabelUtils.GetLabelForSpec(spec)
    identity = parameter_identity(doc, owner, parameter)
    key = json.dumps([identity, spec_id, storage], separators=(",", ":"))
    return {
        "key": key,
        "identity": identity,
        "name": parameter.Definition.Name,
        "dataType": label,
        "specTypeId": spec_id,
        "storageType": storage,
        "guid": str(parameter.GUID) if parameter.IsShared else None,
        "builtin": element_id_value(parameter.Id) if element_id_value(parameter.Id) < 0 else None,
    }
