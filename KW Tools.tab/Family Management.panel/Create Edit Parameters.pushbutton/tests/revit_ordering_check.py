"""Integration check: call run(uiapp, doc, app) ONLY inside a rolled-back dry run.

Creates uniquely named parameters, invokes real editor handlers, and applies their
preview order. The caller MUST roll back the entire run, including setup.
"""
import io
import os
import sys
import uuid


def run(uiapp, doc, app):
    from pyrevit.api import DB
    from System.Diagnostics import Stopwatch

    bundle = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(os.path.dirname(os.path.dirname(bundle)))
    for directory in [os.path.join(root, "lib"), bundle]:
        if directory not in sys.path:
            sys.path.insert(0, directory)
    path = os.path.join(bundle, "script.py")
    namespace = {
        "__file__": path, "__name__": "parameter_editor_live_test", "__revit__": uiapp}
    with io.open(path, encoding="utf-8-sig") as stream:
        code = stream.read()
    # Agent runs resolve relative XAML paths against their own command directory.
    code = code.replace(
        'forms.WPFWindow.__init__(self, "ParameterEditor.xaml")',
        'forms.WPFWindow.__init__(self, os.path.join(SCRIPT_DIR, "ParameterEditor.xaml"))')
    eval(compile(code, path, "exec"), namespace)
    manager = doc.FamilyManager
    prefix = "__KW_ORDER_TEST_" + uuid.uuid4().hex[:8] + "_"
    transaction = DB.Transaction(doc, "Create disposable reorder test parameters")
    transaction.Start()
    parameters = []
    for index, suffix in enumerate(["A", "B", "C", "D", "E", "F"]):
        group = DB.GroupTypeId.Data if index < 3 else DB.GroupTypeId.IdentityData
        parameters.append(manager.AddParameter(
            prefix + suffix, group, DB.SpecTypeId.Number, False))
    transaction.Commit()
    identifiers = [parameter.Id for parameter in parameters]
    window = None
    checks = []
    try:
        window = namespace["ParameterEditorWindow"](manager)
        window._reload_parameter_items()

        def select(*wanted):
            window.lstParameters.SelectedItems.Clear()
            for identifier in wanted:
                row = next(row for row in window._all_items if row.Param.Id == identifier)
                window.lstParameters.SelectedItems.Add(row)

        def visible_order(group_id):
            return [row.Param.Id for group in window._param_view.Groups
                    for row in group.Items if row.Name.startswith(prefix)
                    and row.Param.Definition.GetGroupTypeId() == group_id]

        select(identifiers[2], identifiers[5])
        timer = Stopwatch.StartNew()
        window._reorder_move("top")
        window.lstParameters.UpdateLayout()
        timer.Stop()
        move_ms = timer.ElapsedMilliseconds
        assert visible_order(DB.GroupTypeId.Data) == [
            identifiers[2], identifiers[0], identifiers[1]], "Data group did not move"
        assert visible_order(DB.GroupTypeId.IdentityData) == [
            identifiers[5], identifiers[3], identifiers[4]], "Identity group did not move"
        checks.append("multi-group preview moves real WPF group rows")

        select(identifiers[0])
        window.currentValueEditor.Content.Text = "42"
        window.on_apply_value(None, None)
        assert abs(manager.CurrentType.AsDouble(parameters[0]) - 42) < 0.00001
        assert visible_order(DB.GroupTypeId.Data) == [
            identifiers[2], identifiers[0], identifiers[1]], "Value lost preview"
        checks.append("value edit preserves pending reorder")

        window.on_toggle_instance_type(None, None)
        assert parameters[0].IsInstance, "Type to Instance failed"
        window.on_toggle_instance_type(None, None)
        assert not parameters[0].IsInstance, "Instance to Type failed"
        assert visible_order(DB.GroupTypeId.Data) == [
            identifiers[2], identifiers[0], identifiers[1]], "Scope change lost preview"
        checks.append("both scope conversions preserve reorder")

        target_label = DB.LabelUtils.GetLabelForGroup(DB.GroupTypeId.IdentityData)
        window.cmbEditGroup.SelectedItem = next(
            option for option in window._group_options if option.Label == target_label)
        window.on_apply_param_settings(None, None)
        assert parameters[0].Definition.GetGroupTypeId() == DB.GroupTypeId.IdentityData
        assert visible_order(DB.GroupTypeId.Data) == [identifiers[2], identifiers[1]]
        expected_other = [identifiers[5], identifiers[3], identifiers[4], identifiers[0]]
        assert visible_order(DB.GroupTypeId.IdentityData) == expected_other
        checks.append("group edit rebases both groups correctly")

        window._formula_set_text("2 + 3")
        window.on_apply_formula(None, None)
        assert parameters[0].Formula, "Formula did not save"
        assert abs(manager.CurrentType.AsDouble(parameters[0]) - 5) < 0.00001
        window.on_clear_formula(None, None)
        window.on_apply_formula(None, None)
        assert not parameters[0].Formula, "Clear formula failed"
        assert visible_order(DB.GroupTypeId.IdentityData) == expected_other
        checks.append("formula apply and clear preserve reorder")

        window.chkNewShared.IsChecked = False
        window.chkNewInstance.IsChecked = False
        window.txtNewName.Text = prefix + "NEW"
        window.txtNewInitialValue.Text = "99"
        window.cmbNewGroup.SelectedItem = next(
            option for option in window._group_options if option.Label == target_label)
        number_type = (namespace["ParameterType"].Number
                       if namespace["_PT_AVAILABLE"] else DB.SpecTypeId.Number)
        window.cmbNewType.ItemsSource = [namespace["OptionItem"]("Number", number_type)]
        window.cmbNewType.SelectedIndex = 0
        window._rtb_set_text(window.txtNewFormula, "")
        window.on_create_parameter(None, None)
        created = next((parameter for parameter in manager.GetParameters()
                        if parameter.Definition.Name == prefix + "NEW"), None)
        assert created is not None, window.txtStatus.Text
        assert abs(manager.CurrentType.AsDouble(created) - 99) < 0.00001
        expected_other.append(created.Id)
        assert visible_order(DB.GroupTypeId.IdentityData) == expected_other
        checks.append("new parameter joins pending preview")

        before = [parameter.Id for parameter in manager.GetParameters()
                  if parameter.Definition.Name.startswith(prefix)
                  and parameter.Definition.GetGroupTypeId() == DB.GroupTypeId.IdentityData]
        assert before != visible_order(DB.GroupTypeId.IdentityData), "Preview committed prematurely"
        assert window.on_apply_sorting(None, None), window.txtStatus.Text
        after = [parameter.Id for parameter in manager.GetParameters()
                 if parameter.Definition.Name.startswith(prefix)
                 and parameter.Definition.GetGroupTypeId() == DB.GroupTypeId.IdentityData]
        assert after == expected_other, "Committed order does not match preview"
        assert not window._has_pending_order()
        checks.append("Apply commits complete preview after all modifications")

        select(created.Id)
        window._reorder_move("top")
        assert window._has_pending_order()
        window.on_reset_sorting(None, None)
        assert not window._has_pending_order()
        assert visible_order(DB.GroupTypeId.IdentityData) == expected_other
        assert abs(manager.CurrentType.AsDouble(created) - 99) < 0.00001
        checks.append("Reset restores applied order without reverting value or creation")
        return {
            "checks": checks, "preview_move_ms": move_ms,
            "test_parameters": 7, "revit_version": app.VersionNumber,
        }
    finally:
        if window is not None:
            window._pending_group_sorts.clear()
            window._pending_group_orders.clear()
            window.Close()
