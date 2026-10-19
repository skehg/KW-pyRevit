# -*- coding: utf-8 -*-

import json
import os


def save_workbook(workbook, file_path):
    directory = os.path.dirname(file_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    if file_path.lower().endswith(".xlsx"):
        from core.xlsx_export import write_xlsx

        return write_xlsx(workbook, file_path)
    with open(file_path, "w") as output_file:
        json.dump(workbook, output_file, indent=2, sort_keys=True)
    return file_path


def load_workbook(file_path):
    with open(file_path, "r") as input_file:
        workbook = json.load(input_file)
    if not isinstance(workbook, dict) or not isinstance(workbook.get("sheets"), list):
        raise ValueError("The selected file is not an ExcelLink workbook.")
    return workbook
