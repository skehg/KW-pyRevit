# -*- coding: utf-8 -*-

MODE_TYPES = "Types Mode"
MODE_INSTANCES = "Instances Mode"

TARGET_TYPE = "type"
TARGET_INSTANCE = "instance"
TARGET_TYPE_NAME = "typeName"


def element_id_value(element_id):
    if element_id is None:
        return None
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)
