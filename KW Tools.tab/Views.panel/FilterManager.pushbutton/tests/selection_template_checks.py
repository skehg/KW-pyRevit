# -*- coding: utf-8 -*-
"""Read-only WPF acceptance checks for range selection and the Penpot template picker."""
from System.Windows import Size, Rect
from System.Windows.Controls import ComboBox, SelectionMode
from System.Windows.Input import Mouse, MouseButton, MouseButtonEventArgs, ModifierKeys
import filter_model as fm
import filter_ui as ui


def run(doc, uidoc):
    service = fm.FilterService(doc)
    selection_before = set(fm.id_value(i) for i in uidoc.Selection.GetElementIds())
    assignments_before = [(fm.id_value(v.Id), fm.id_value(v.ViewTemplateId)) for v in service.views]
    manager = ui.ManagerDialog(service, uidoc)
    manager.Content.Measure(Size(manager.Width - 32, manager.Height - 48))
    manager.Content.Arrange(Rect(0, 0, manager.Width - 32, manager.Height - 48))
    manager.UpdateLayout()
    assert manager.list.SelectionMode == SelectionMode.Extended
    visible = [item.Tag for item in manager.list.Items]
    assert len(visible) >= 4
    checks = []
    none = getattr(ModifierKeys, 'None')
    original_keyboard = ui.Keyboard
    class KeyboardState(object):
        Modifiers = none
    def click(fid, modifiers=none, checkbox=False):
        KeyboardState.Modifiers = modifiers
        item = next(i for i in manager.list.Items if i.Tag == fid)
        manager.list.ScrollIntoView(item)
        manager.UpdateLayout()
        source = manager.row_checks[fid] if checkbox else item.Content.Children[1]
        event = MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Left)
        event.RoutedEvent = Mouse.PreviewMouseDownEvent
        source.RaiseEvent(event)
    ui.Keyboard = KeyboardState
    try:
        click(visible[0])
        assert manager.highlighted == set([visible[0]]) and not manager.checked
        click(visible[2], ModifierKeys.Control)
        assert manager.highlighted == set([visible[0], visible[2]]) and not manager.checked
        click(visible[0], ModifierKeys.Control)
        assert manager.highlighted == set([visible[2]]) and not manager.checked
        click(visible[0], ModifierKeys.Shift)
        assert manager.highlighted == set([visible[0]])
        click(visible[0])
        click(visible[3], ModifierKeys.Shift)
        assert manager.highlighted == set(visible[:4])
        assert manager.focused == visible[3]
        click(visible[1], ModifierKeys.Shift)
        assert manager.highlighted == set(visible[:2])
        click(visible[3], ModifierKeys.Control)
        click(visible[2], ModifierKeys.Control | ModifierKeys.Shift)
        assert manager.highlighted == set(visible[:4])
        checks.append('routed Ctrl clicks add/remove highlights; Shift expands/contracts ranges; Ctrl+Shift adds a range without ticking')

        click(visible[1], checkbox=True)
        assert manager.checked == set(visible[:4])
        assert manager.highlighted == set(visible[:4])
        assert all(manager.row_checks[fid].IsChecked for fid in visible[:4])
        click(visible[2], checkbox=True)
        assert not manager.checked and manager.highlighted == set(visible[:4])
        click(visible[0], checkbox=True)
        click(visible[1], ModifierKeys.Control)
        click(visible[0], checkbox=True)
        assert manager.checked == set([visible[1]])
        assert manager.highlighted == set([visible[0], visible[2], visible[3]])
        click(visible[1], checkbox=True)
        assert not manager.checked and manager.highlighted == set([visible[0], visible[2], visible[3]])
        assert manager.count.Text == '0 checked / 3 highlighted'
        checks.append('checkbox click checks/unchecks every highlighted row; unhighlighted checkbox changes only itself')

        manager.row_checks[visible[0]].IsChecked = True
        manager.unselect_all(None, None)
        assert not manager.checked and manager.highlighted == set([visible[0], visible[2], visible[3]])
        state = manager.state()
        reopened = ui.ManagerDialog(service, uidoc, **state)
        assert reopened.highlighted == manager.highlighted
        reopened.Close()
        checks.append('Unselect All retains highlights; manager handoff state preserves separate checked/highlighted sets')
    finally:
        ui.Keyboard = original_keyboard

    assert not any(isinstance(child, ComboBox) for child in manager.template_wrap.Children)
    picker = ui.TemplateDialog(service)
    assert picker.heading.Text == 'Select View Template' and picker.accept_button.Content == 'Use This Template'
    assert picker.list.SelectionMode == SelectionMode.Single
    assert picker.templates
    template = picker.templates[0]
    fid = fm.id_value(template.Id)
    picker.search.Text = fm.name_of(template)
    assert fid in [item.Tag for item in picker.list.Items]
    picker.list.SelectedItem = next(item for item in picker.list.Items if item.Tag == fid)
    assert picker.accept_button.IsEnabled and fm.name_of(template) in picker.impact.Text
    assert '1 selected' in picker.summary.Text
    picker.search.Text = 'nonexistent template 10bd67e3'
    assert not picker.list.Items.Count and not picker.accept_button.IsEnabled
    assert picker.impact.Text == 'No matching templates.'
    picker.search.Text = ''
    for item in picker.types.Items:
        if item.Tag == str(template.ViewType):
            picker.types.SelectedItem = item
            break
    assert picker.list.Items.Count
    assert all(str(doc.GetElement(fm.element_id(i.Tag)).ViewType) == str(template.ViewType)
               for i in picker.list.Items)
    picker.list.SelectedItem = next(item for item in picker.list.Items if item.Tag == fid)
    picker.accept(None, None)
    assert picker.result == fid
    checks.append('Penpot page 04 picker has searchable single selection, type filter, aligned details, dependency impact and empty-state guard')

    original_show = ui.TemplateDialog.show
    opened = []
    def show(window, owner=None):
        opened.append(window.selected)
        window.Close()
        return fid
    ui.TemplateDialog.show = show
    try:
        radio = next(r for r in manager.target_section.Content.Child.Children[0].Children if r.Tag == 2)
        manager.radio_changed(radio, None)
        assert opened == [None]
        assert manager.selected_template == fid and manager.resolve_target().Id == template.Id
        assert manager.template_name.Text == fm.name_of(template)
        assert manager.state()['selected_template'] == fid
        def cancel(window, owner=None):
            opened.append(window.selected)
            window.Close()
            return None
        ui.TemplateDialog.show = cancel
        manager.choose_template(None, None)
        assert opened == [None, fid] and manager.selected_template == fid
        restored = ui.ManagerDialog(service, uidoc, **manager.state())
        assert restored.resolve_target().Id == template.Id and opened == [None, fid]
        restored.Close()
    finally:
        ui.TemplateDialog.show = original_show
    checks.append('selected-template radio opens dialog; chosen target is shown without a dropdown; cancel preserves previous template')

    minimum = ui.TemplateDialog(service, fid)
    minimum.Width, minimum.Height = minimum.MinWidth, minimum.MinHeight
    minimum.Content.Measure(Size(minimum.Width - 32, minimum.Height - 48))
    minimum.Content.Arrange(Rect(0, 0, minimum.Width - 32, minimum.Height - 48))
    minimum.UpdateLayout()
    assert minimum.list.ActualHeight >= 80
    assert minimum.actions.ActualHeight > 0
    minimum.Close()
    checks.append('template picker keeps a usable list and visible actions at its resizable minimum')

    assert [(fm.id_value(v.Id), fm.id_value(v.ViewTemplateId)) for v in service.views] == assignments_before
    assert set(fm.id_value(i) for i in uidoc.Selection.GetElementIds()) == selection_before
    manager.Close()
    return {'version': doc.Application.VersionNumber, 'checks_passed': len(checks), 'checks': checks}
