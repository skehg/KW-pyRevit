# -*- coding: utf-8 -*-
"""Exercise the real name-only ReValue window/callback without modal interaction."""
import imp
import io
import os
import sys
import uuid
from pyrevit import DB
import filter_model as fm


def run(doc, uidoc, uiapp):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'script.py'))
    entry = imp.new_module('filter_manager_entry_test')
    entry.__file__ = path
    with io.open(path, encoding='utf-8-sig') as source:
        eval(compile(source.read(), path, 'exec'), entry.__dict__)
    service = fm.FilterService(doc)
    name = 'FM BETA ReValue test ' + str(uuid.uuid4())[:8]
    cats = [fm.id_value(DB.ElementId(DB.BuiltInCategory.OST_Walls))]
    fid = service.save(name, cats, fm.group(),
                       acknowledged=[r.id for r in service.matches(cats, fm.group())])
    service.refresh()
    record = service.get_record(fid)
    selection_before = set(fm.id_value(i) for i in uidoc.Selection.GetElementIds())
    paths_before = list(sys.path)
    original_load = entry.load_revalue
    checks = []

    def load(uiapp):
        module = original_load(uiapp)
        settings_before = module.load_session_settings()
        def show(dialog):
            assert dialog.is_filter_name_context and dialog.is_instance_mode
            assert not dialog.btn_mode.IsEnabled and not dialog.available_params
            assert dialog.preview_items.Count == 1
            assert dialog.preview_items[0].CurrentName == name
            preview = dialog.preview_items[0]
            for suffix in (' renamed', ' renamed twice'):
                preview.NewName = name + suffix
                proposals = dialog.get_revalue_map()
                assert set(fm.id_value(e.Id) for e in proposals) == set([fid])
                assert dialog.rename_writer(proposals) is True
                assert fm.name_of(doc.GetElement(fm.element_id(fid))) == name + suffix
            preview.NewName = 'Invalid | Name'
            try:
                dialog.rename_writer(dialog.get_revalue_map())
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid name should reject atomically')
            assert fm.name_of(doc.GetElement(fm.element_id(fid))) == name + ' renamed twice'
            dialog.persist_settings()
            assert module.load_session_settings() == settings_before
            dialog.applied = True
            dialog.window.Close()
        module.ReValueDialog.show_dialog = show
        return module
    entry.load_revalue = load
    assert entry.revalue_names(service, [record], uiapp) is True
    assert sys.path == paths_before
    assert set(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) == selection_before
    checks.extend(['actual ReValue window locks filter-own Name without type/parameter redirection',
                   'approved native names write atomically with repeated Apply',
                   'invalid proposal preserves existing name and ordinary ReValue settings',
                   'handoff restores module search paths and preserves Revit selection'])
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks), 'checks': checks}
