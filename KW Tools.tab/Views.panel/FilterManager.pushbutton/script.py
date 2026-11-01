# -*- coding: utf-8 -*-
"""Filter Manager BETA: modal native definition editing and application."""
__title__ = 'Filter Manager'
__author__ = 'Kent Watson'
__min_revit_ver__ = 2023

import imp
import io
import os
import sys
import traceback

from pyrevit import forms, script
from filter_model import FilterService, id_value, element_id, ids
from filter_ui import ManagerDialog


def load_revalue(uiapp):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir,
                                       os.pardir, 'Modify.panel', 'col2.stack',
                                       'KW ReValue.pushbutton', 'script.py'))
    module = imp.new_module('kw_filter_manager_revalue')
    module.__file__ = path
    module.__revit__ = uiapp
    sys.path.insert(0, os.path.dirname(path))
    with io.open(path, encoding='utf-8-sig') as source:
        eval(compile(source.read(), path, 'exec'), module.__dict__)
    return module


def revalue_names(service, records, uiapp):
    snapshots = dict((r.id, r) for r in records)

    def writer(proposals):
        if uiapp.ActiveUIDocument is None or uiapp.ActiveUIDocument.Document != service.doc:
            raise ValueError('The active project changed. Reopen Filter Manager.')
        names = {}
        for element, name in proposals.items():
            fid = id_value(element.Id)
            if fid not in snapshots or element.Document != service.doc or element.UniqueId != snapshots[fid].unique_id:
                raise ValueError('ReValue returned a filter outside the approved selection.')
            names[fid] = name
        if not names:
            return True
        service.rename([snapshots[fid] for fid in names], names)
        service.refresh()
        for fid in snapshots:
            snapshots[fid] = service.get_record(fid)
        return True

    original_path = list(sys.path)
    try:
        module = load_revalue(uiapp)
        return module.show_filter_names([service.assert_current(r) for r in records], writer)
    finally:
        sys.path[:] = original_path


def main(uiapp):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None or uidoc.Document.IsFamilyDocument:
        forms.alert('Open a project document to manage view filters.', title='Filter Manager')
        return
    if int(uiapp.Application.VersionNumber) < 2023:
        forms.alert('Filter Manager requires Revit 2023 or newer.', title='Filter Manager')
        return
    service = FilterService(uidoc.Document)
    state = {}
    while True:
        window = ManagerDialog(service, uidoc, **state)
        result = window.show()
        state = window.state()
        if not result:
            return
        if result[0] == 'selection':
            uidoc.Selection.SetElementIds(ids(result[1]))
            return
        if result[0] == 'revalue':
            try:
                revalue_names(service, result[1], uiapp)
            except Exception as error:
                script.get_logger().error('Filter Manager ReValue: %s\n%s', error, traceback.format_exc())
                forms.alert(unicode(error), title='Filter Manager - ReValue not completed')
            service.refresh()


if __name__ == '__main__':
    try:
        main(__revit__)
    except Exception as error:
        script.get_logger().error('Filter Manager: %s\n%s', error, traceback.format_exc())
        forms.alert(unicode(error), title='Filter Manager - not completed')
