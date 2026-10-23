# -*- coding: utf-8 -*-
"""Parameter identity and semantic data types, independent of display names."""

import json

from core.types import element_id_value


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
