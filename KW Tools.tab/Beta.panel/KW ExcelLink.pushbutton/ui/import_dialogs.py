# -*- coding: utf-8 -*-
"""File picker and output-window reporting shared by the wizard and grid import."""

import os

import clr
from pyrevit import script


def pick_xlsx(initial_path=None):
    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import DialogResult, OpenFileDialog

    dialog = OpenFileDialog()
    dialog.Title = "Import edited ExcelLink workbook"
    dialog.Filter = "Excel workbook (*.xlsx)|*.xlsx"
    dialog.CheckFileExists = True
    if initial_path:
        folder = os.path.dirname(initial_path)
        if os.path.isdir(folder):
            dialog.InitialDirectory = folder
        if os.path.isfile(initial_path):
            dialog.FileName = os.path.basename(initial_path)
    if dialog.ShowDialog() != DialogResult.OK:
        return None
    return dialog.FileName


def open_with_shell(path):
    """Open a file or folder with its default Windows application.

    Revit 2025 runs on .NET 8, where Process.Start only opens documents when
    UseShellExecute is set explicitly.
    """
    from System.Diagnostics import Process, ProcessStartInfo

    start_info = ProcessStartInfo(path)
    start_info.UseShellExecute = True
    Process.Start(start_info)


def report_import_issues(file_path, issues, missing=0):
    if not issues and not missing:
        return
    output = script.get_output()
    output.print_md("## KW ExcelLink import notes")
    output.print_md("File: `{0}`".format(file_path))
    lines = []
    if missing:
        lines.append(
            "{0} row(s) refer to elements that no longer exist in this model "
            "and were ignored.".format(missing)
        )
    for issue in issues:
        location = [issue.get("sheet") or ""]
        if issue.get("row"):
            location.append("row {0}".format(issue["row"]))
        if issue.get("column"):
            location.append(issue["column"])
        lines.append(u"{0}: {1}".format(u" / ".join(location), issue.get("message")))
    output.print_code(u"\n".join(lines))
