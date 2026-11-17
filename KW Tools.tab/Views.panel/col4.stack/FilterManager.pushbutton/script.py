# -*- coding: utf-8 -*-
"""Filter Manager BETA: integrated definitions, attachments and graphics workspace."""
__title__ = 'Filter Manager'
__author__ = 'Kent Watson'
__min_revit_ver__ = 2023

import imp
import io
import os
import sys
import traceback

from pyrevit import DB, forms, script
from filter_model import FilterService, id_value, element_id, ids
from filter_workspace import WorkspaceDialog


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


def revalue_drafts(service, records, proposals, uiapp):
    """Return transformed names by filter id without changing the model."""
    snapshots = dict((r.id, r) for r in records)
    if set(proposals) != set(snapshots):
        raise ValueError('ReValue proposals must match the remaining rename grid.')
    if any(not isinstance(value, basestring) for value in proposals.values()):
        raise ValueError('ReValue proposals must be text.')
    elements = [service.assert_current(r) for r in records]
    original = dict((r.id, unicode(proposals[r.id])) for r in records)
    accepted = {}

    def receive(values):
        if uiapp.ActiveUIDocument is None or uiapp.ActiveUIDocument.Document != service.doc:
            raise ValueError('The active project changed. Reopen Filter Manager.')
        updates = {}
        for element, value in values.items():
            fid = id_value(element.Id)
            if (fid not in snapshots or element.Document != service.doc or
                    element.UniqueId != snapshots[fid].unique_id):
                raise ValueError('ReValue returned a filter outside the remaining rename grid.')
            if not isinstance(value, basestring):
                raise ValueError('ReValue returned a non-text name proposal.')
            updates[fid] = unicode(value)
        accepted.update(original)
        accepted.update(updates)
        return True

    original_path = list(sys.path)
    try:
        module = load_revalue(uiapp)
        initial = dict((e.UniqueId, original[id_value(e.Id)]) for e in elements)
        confirmed = module.show_filter_name_drafts(elements, initial, receive)
        return accepted if confirmed else None
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
    browser_ids = [id_value(e.Id) for e in
                   (uidoc.Document.GetElement(i) for i in uidoc.Selection.GetElementIds())
                   if isinstance(e, DB.View)]
    state = {}
    while True:
        window = WorkspaceDialog(service, uidoc, browser_ids=browser_ids, state=state)
        result = window.show()
        state = window.state()
        if not result:
            return
        if result[0] == 'selection':
            uidoc.Selection.SetElementIds(ids(result[1]))
            return
        if result[0] == 'revalue':
            try:
                proposals = revalue_drafts(service, result[1], result[2], uiapp)
                if proposals is not None:
                    state.setdefault('rename_proposals', {}).update(proposals)
            except Exception as error:
                script.get_logger().error('Filter Manager ReValue: %s\n%s', error, traceback.format_exc())
                forms.alert(unicode(error), title='Filter Manager - ReValue not completed')


if __name__ == '__main__':
    try:
        main(__revit__)
    except Exception as error:
        script.get_logger().error('Filter Manager: %s\n%s', error, traceback.format_exc())
        forms.alert(unicode(error), title='Filter Manager - not completed')
