"""Host-independent tests for deferred parameter sorting."""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from test_value_editing import SCRIPT, TREE, load_functions
from test_group_sort_menu import NetList


def group_parameters(parameters):
    groups = {}
    for parameter in parameters:
        groups.setdefault(parameter.group, []).append(parameter)
    return groups, {}


class SortPreviewTests(unittest.TestCase):
    def setUp(self):
        path = SCRIPT.parents[3] / "lib" / "sort_param_utils.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "build_reordered_list")
        self.namespace = {
            "group_parameters": group_parameters,
            "get_group_info": lambda p: (p.group, p.group),
            "param_name": lambda p: p.Name,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
             self.namespace)
        self.namespace["_sort_build_reordered_list"] = self.namespace["build_reordered_list"]
        self.namespace["_sort_group_parameters"] = group_parameters
        self.functions = load_functions(
            ["_preview_parameter_order", "on_apply_sorting", "on_reset_sorting",
             "_on_editor_closing", "_update_sort_buttons", "_has_pending_order"],
            self.namespace)
        self.parameters = [
            SimpleNamespace(Id=index, Name=name, group=group, IsInstance=False)
            for index, (name, group) in enumerate(
                [("Z", "dimensions"), ("Other", "other"), ("A", "dimensions")])]
        self.window = SimpleNamespace(
            _pending_group_sorts={"dimensions": ("Name Only", False)},
            _pending_group_orders={},
            _set_status=Mock(), _refresh_sort_preview=Mock(),
            btnApplySorting=SimpleNamespace(), btnResetSorting=SimpleNamespace())
        self.window._preview_parameter_order = lambda parameters: (
            self.functions._preview_parameter_order(self.window, parameters))
        self.window._has_pending_order = lambda: self.functions._has_pending_order(self.window)

    def test_preview_sorts_without_mutating_saved_order(self):
        result = self.window._preview_parameter_order(self.parameters)
        self.assertEqual([p.Name for p in result], ["A", "Other", "Z"])
        self.assertEqual([p.Name for p in self.parameters], ["Z", "Other", "A"])
        self.assertTrue(self.window._pending_group_sorts)

    def test_preview_rebases_after_rename_creation_deletion_and_group_moves(self):
        self.parameters[0].Name = "0"
        result = self.window._preview_parameter_order(self.parameters)
        self.assertEqual(result, self.parameters)
        self.assertFalse(self.window._pending_group_sorts)
        self.window._pending_group_sorts["dimensions"] = ("Name Only", True)
        self.parameters.append(SimpleNamespace(
            Id=9, Name="X", group="dimensions", IsInstance=False))
        result = self.window._preview_parameter_order(self.parameters)
        self.assertEqual([p.Name for p in result], ["X", "Other", "A", "0"])
        for parameter in self.parameters:
            parameter.group = "other"
        self.window._preview_parameter_order(self.parameters)
        self.assertFalse(self.window._pending_group_sorts)

    def test_reset_clears_only_pending_sort_and_refreshes_saved_order(self):
        self.functions.on_reset_sorting(self.window, None, None)
        self.assertEqual(self.window._pending_group_sorts, {})
        self.window._refresh_sort_preview.assert_called_once_with()

    def configure_apply(self):
        class GenericList:
            def __class_getitem__(cls, item):
                return NetList

        self.transaction = Mock()
        self.transaction.return_value.__enter__ = Mock()
        self.transaction.return_value.__enter__.return_value.status = "committed"
        self.transaction.return_value.__exit__ = Mock(return_value=False)
        self.transaction.return_value.Commit.return_value = "committed"
        self.namespace.update(
            _sort_get_current_order=lambda fm: self.parameters,
            _sort_supports_reorder=lambda fm: True,
            List=GenericList, FamilyParameter=object,
            TransactionStatus=SimpleNamespace(Committed="committed", Started="started"),
            Transaction=self.transaction, doc=object(),
            revit=SimpleNamespace(Transaction=self.transaction))
        self.window.fm = SimpleNamespace(ReorderParameters=Mock())

    def test_apply_commits_complete_preview_once_and_clears_pending(self):
        self.configure_apply()
        self.assertTrue(self.functions.on_apply_sorting(self.window, None, None))
        self.transaction.assert_called_once_with(
            self.namespace["doc"], "Apply Parameter Sorting")
        saved = self.window.fm.ReorderParameters.call_args.args[0]
        self.assertEqual([p.Name for p in saved], ["A", "Other", "Z"])
        self.assertEqual(self.window._saved_parameter_order, saved)
        self.assertFalse(self.window._pending_group_sorts)
        self.window._refresh_sort_preview.assert_called_once_with()

    def test_apply_failure_preserves_pending_sort_for_retry(self):
        self.configure_apply()
        self.transaction.return_value.GetStatus.return_value = "started"
        self.window.fm.ReorderParameters.side_effect = RuntimeError("Rejected")
        self.assertFalse(self.functions.on_apply_sorting(self.window, None, None))
        self.assertTrue(self.window._pending_group_sorts)
        self.window._refresh_sort_preview.assert_not_called()
        self.assertEqual(self.window._set_status.call_args.args[1], "error")
        self.transaction.return_value.RollBack.assert_called_once_with()
        self.transaction.return_value.Dispose.assert_called_once_with()

    def test_unchanged_apply_does_not_create_transaction(self):
        self.configure_apply()
        self.parameters.reverse()
        self.assertTrue(self.functions.on_apply_sorting(self.window, None, None))
        self.transaction.assert_not_called()
        self.assertFalse(self.window._pending_group_sorts)

    def test_rolled_back_commit_keeps_preview(self):
        self.configure_apply()
        self.transaction.return_value.Commit.return_value = "rolled_back"
        self.assertFalse(self.functions.on_apply_sorting(self.window, None, None))
        self.assertTrue(self.window._pending_group_sorts)
        self.window._refresh_sort_preview.assert_not_called()

    def test_close_apply_discard_cancel_and_failed_apply(self):
        show = Mock()
        self.namespace["forms"] = SimpleNamespace(
            CommandSwitchWindow=SimpleNamespace(show=show))
        for choice, apply_success, cancelled in (
                ("Apply Sorting", True, False),
                ("Apply Sorting", False, True),
                ("Discard Sorting", True, False),
                ("Cancel", True, True), (None, True, True)):
            with self.subTest(choice=choice, apply_success=apply_success):
                self.window._pending_group_sorts = {"dimensions": ("Name Only", False)}
                self.window.on_apply_sorting = Mock(return_value=apply_success)
                show.return_value = choice
                args = SimpleNamespace(Cancel=False)
                self.functions._on_editor_closing(self.window, None, args)
                self.assertEqual(args.Cancel, cancelled)
                if choice == "Apply Sorting":
                    self.window.on_apply_sorting.assert_called_once_with(None, None)
                elif choice == "Discard Sorting":
                    self.assertFalse(self.window._pending_group_sorts)
                else:
                    self.window.on_apply_sorting.assert_not_called()
                    self.assertTrue(self.window._pending_group_sorts)

    def test_buttons_track_pending_sort(self):
        for pending in (True, False):
            if not pending:
                self.window._pending_group_sorts.clear()
            self.functions._update_sort_buttons(self.window)
            self.assertEqual(self.window.btnApplySorting.IsEnabled, pending)
            self.assertEqual(self.window.btnResetSorting.IsEnabled, pending)

    def test_manual_preview_survives_rename_delete_and_new_members(self):
        self.window._pending_group_sorts.clear()
        self.window._pending_group_orders["dimensions"] = [2, 0]
        self.parameters[2].Name = "Renamed"
        self.parameters.append(SimpleNamespace(
            Id=5, Name="New", group="dimensions", IsInstance=False))
        result = self.window._preview_parameter_order(self.parameters)
        self.assertEqual([p.Id for p in result], [2, 1, 0, 5])
        self.parameters = [p for p in self.parameters if p.Id != 0]
        result = self.window._preview_parameter_order(self.parameters)
        self.assertEqual([p.Id for p in result], [1, 2, 5])
        self.assertFalse(self.window._has_pending_order())

    def test_manual_and_alphabetical_previews_apply_together(self):
        self.configure_apply()
        self.parameters.extend([
            SimpleNamespace(Id=3, Name="X", group="other", IsInstance=False),
            SimpleNamespace(Id=4, Name="B", group="other", IsInstance=False)])
        self.window._pending_group_orders["other"] = [3, 4, 1]
        self.assertTrue(self.functions.on_apply_sorting(self.window, None, None))
        result = self.window.fm.ReorderParameters.call_args.args[0]
        self.assertEqual([p.Id for p in result], [2, 3, 0, 4, 1])
        self.transaction.assert_called_once()
        self.assertFalse(self.window._has_pending_order())

    def test_reset_clears_manual_orders_too(self):
        self.window._pending_group_orders["other"] = [1]
        self.functions.on_reset_sorting(self.window, None, None)
        self.assertFalse(self.window._has_pending_order())

    def test_close_prompts_for_manual_only_preview(self):
        self.window._pending_group_sorts.clear()
        self.window._pending_group_orders["dimensions"] = [2, 0]
        show = Mock(return_value="Cancel")
        self.namespace["forms"] = SimpleNamespace(
            CommandSwitchWindow=SimpleNamespace(show=show))
        args = SimpleNamespace(Cancel=False)
        self.functions._on_editor_closing(self.window, None, args)
        show.assert_called_once()
        self.assertTrue(args.Cancel)


class GridReorderTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {
            "_sort_group_parameters": group_parameters,
            "_sort_supports_reorder": lambda fm: True,
        }
        self.functions = load_functions(
            ["_move_parameter_items", "_reorder_move", "_update_reorder_buttons",
             "_refresh_sort_preview"], self.namespace)
        self.parameters = [
            SimpleNamespace(Id=i, Name=str(i), group=group)
            for i, group in enumerate(["a", "b", "a", "b", "a", "a"])]
        self.selected = [SimpleNamespace(Param=p)
                         for p in (self.parameters[2], self.parameters[3])]
        self.window = SimpleNamespace(
            _ui_ready=True, fm=object(),
            txtSearch=SimpleNamespace(Text=""),
            _all_items=[SimpleNamespace(Param=p) for p in self.parameters],
            _selected_parameter_items=lambda: self.selected,
            _pending_group_sorts={"a": ("Name Only", True)},
            _pending_group_orders={}, _refresh_sort_preview=Mock(), _set_status=Mock(),
            btnReorderTop=SimpleNamespace(), btnReorderUp=SimpleNamespace(),
            btnReorderDown=SimpleNamespace(), btnReorderBottom=SimpleNamespace())

    def test_moves_stable_selected_blocks_and_handles_boundaries(self):
        items = [SimpleNamespace(Id=i) for i in range(6)]
        move = self.functions._move_parameter_items
        for action, expected in (
                ("top", [1, 2, 4, 0, 3, 5]),
                ("up", [1, 2, 0, 4, 3, 5]),
                ("down", [0, 3, 1, 2, 5, 4]),
                ("bottom", [0, 3, 5, 1, 2, 4])):
            with self.subTest(action=action):
                result = move(items, {1, 2, 4}, action)
                self.assertEqual([p.Id for p in result], expected)
                self.assertEqual([p.Id for p in items], list(range(6)))
        self.assertEqual(move(items, {0, 1}, "up"), items)
        self.assertEqual(move(items, {4, 5}, "down"), items)
        self.assertEqual(move(items, set(range(6)), "top"), items)

    def test_move_stages_each_group_independently_and_overrides_sort(self):
        self.functions._reorder_move(self.window, "top")
        self.assertEqual(self.window._pending_group_orders, {
            "a": [2, 0, 4, 5], "b": [3, 1]})
        self.assertEqual(self.window._pending_group_sorts, {})
        self.window._refresh_sort_preview.assert_called_once_with()

    def test_search_blocks_moves_and_disabled_buttons_explain_why(self):
        self.window.txtSearch.Text = "formula"
        self.functions._reorder_move(self.window, "up")
        self.assertEqual(self.window._pending_group_orders, {})
        self.window._refresh_sort_preview.assert_not_called()
        self.functions._update_reorder_buttons(self.window)
        for button in (self.window.btnReorderTop, self.window.btnReorderUp,
                       self.window.btnReorderDown, self.window.btnReorderBottom):
            self.assertFalse(button.IsEnabled)
            self.assertIn("Clear the search", button.ToolTip)

    def test_group_filter_does_not_block_moves_and_boundary_buttons_disable(self):
        self.window.cmbGroupFilter = SimpleNamespace(SelectedItem="a")
        self.selected[:] = [SimpleNamespace(Param=self.parameters[0])]
        self.functions._update_reorder_buttons(self.window)
        self.assertFalse(self.window.btnReorderTop.IsEnabled)
        self.assertFalse(self.window.btnReorderUp.IsEnabled)
        self.assertIn("boundary", self.window.btnReorderTop.ToolTip)
        self.assertTrue(self.window.btnReorderDown.IsEnabled)
        self.assertTrue(self.window.btnReorderBottom.IsEnabled)

    def test_empty_selection_and_unavailable_api_explain_disabled_buttons(self):
        self.selected.clear()
        self.functions._update_reorder_buttons(self.window)
        self.assertFalse(self.window.btnReorderDown.IsEnabled)
        self.assertIn("Select parameters", self.window.btnReorderDown.ToolTip)
        self.namespace["_sort_supports_reorder"] = lambda fm: False
        self.functions._update_reorder_buttons(self.window)
        self.assertIn("unavailable", self.window.btnReorderDown.ToolTip)

    def test_preview_refresh_reuses_rows_and_view_without_reloading_parameters(self):
        class SelectionList(NetList):
            def Clear(self):
                self.clear()

            def Contains(self, item):
                return item in self

        class MovingList(SelectionList):
            def IndexOf(self, item):
                return self.index(item)

            def Move(self, old, new):
                self.insert(new, self.pop(old))

        grid = SimpleNamespace(
            SelectedItems=SelectionList(), SelectedItem=None, ScrollIntoView=Mock())
        self.window.lstParameters = grid
        self.window._all_items = self.selected + [
            item for item in self.window._all_items
            if item.Param.Id not in {2, 3}]
        self.window._selected_parameter_item = lambda: self.selected[0]
        self.window._update_reorder_buttons = Mock()
        self.window._update_sort_buttons = Mock()
        self.window._saved_parameter_order = list(self.parameters)
        self.window._preview_parameter_order = Mock(return_value=list(reversed(self.parameters)))
        self.window._param_view = SimpleNamespace(Refresh=Mock())
        self.window._reload_parameter_items = Mock(
            side_effect=AssertionError("A preview must not reload Revit parameter data"))
        self.namespace["_parameter_group_display_key"] = lambda label: label
        for item in self.window._all_items:
            item.GroupLabel = item.Param.group
        rows = list(self.window._all_items)
        self.window._filtered_items = MovingList(sorted(
            rows, key=lambda item: item.GroupLabel))
        self.window._param_view.Refresh.side_effect = AssertionError(
            "A preview must not reset the WPF view")
        self.functions._refresh_sort_preview(self.window)
        self.assertEqual([item.Param.Id for item in grid.SelectedItems], [2, 3])
        self.window._reload_parameter_items.assert_not_called()
        self.window._param_view.Refresh.assert_not_called()
        self.assertFalse(self.window._refreshing_order)
        self.assertEqual([item.Param.Id for item in self.window._all_items],
                         list(reversed(range(6))))
        self.assertTrue(all(any(item is row for row in rows)
                            for item in self.window._all_items))
        self.assertEqual([item.Param.Id for item in self.window._filtered_items],
                         [5, 4, 2, 0, 3, 1])
        self.window._update_sort_buttons.assert_called_once_with()
        self.window._preview_parameter_order.return_value = self.parameters
        self.window._filtered_items.Move = Mock(side_effect=RuntimeError("Move failed"))
        with self.assertRaisesRegex(RuntimeError, "Move failed"):
            self.functions._refresh_sort_preview(self.window)
        self.assertFalse(self.window._refreshing_order)

    def test_selection_events_during_preview_do_not_refresh_editor_or_batch(self):
        handler = load_functions(["on_param_selected"], {}).on_param_selected
        window = SimpleNamespace(
            _refreshing_order=True, _set_editor_from_selected=Mock(),
            _update_batch_panel=Mock(), _update_reorder_buttons=Mock())
        handler(window, None, None)
        window._set_editor_from_selected.assert_not_called()
        window._update_batch_panel.assert_not_called()
        window._update_reorder_buttons.assert_not_called()

    def test_xaml_arrows_under_grid_status_separate_and_old_tab_removed(self):
        root = ET.parse(str(SCRIPT.with_name("ParameterEditor.xaml"))).getroot()
        name_key = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
        named = {e.get(name_key): e for e in root.iter() if e.get(name_key)}
        parent = {child: node for node in root.iter() for child in node}
        grid_container = parent[named["lstParameters"]]
        reorder_bar = parent[named["btnReorderTop"]]
        self.assertEqual(named["btnReorderUp"].get("Content"), "\u25b2")
        self.assertEqual(named["btnReorderDown"].get("Content"), "\u25bc")
        for name, geometry in (
                ("btnReorderTop", "M 0,0 H 12 V 2 H 0 Z M 6,4 L 12,12 H 0 Z"),
                ("btnReorderBottom", "M 0,10 H 12 V 12 H 0 Z M 0,0 H 12 L 6,8 Z")):
            self.assertEqual(named[name].get("Padding"), "0")
            self.assertEqual(named[name].get("HorizontalContentAlignment"), "Center")
            self.assertEqual(named[name].get("VerticalContentAlignment"), "Center")
            icon = named[name].find("{http://schemas.microsoft.com/winfx/2006/xaml/presentation}Path")
            self.assertIsNotNone(icon)
            self.assertEqual(icon.get("Width"), "12")
            self.assertEqual(icon.get("Height"), "12")
            self.assertEqual(icon.get("Data"), geometry)
            self.assertEqual(icon.get("Fill"),
                             "{Binding Foreground, RelativeSource={RelativeSource AncestorType=Button}}")
        for name in ("btnReorderTop", "btnReorderUp", "btnReorderDown", "btnReorderBottom"):
            button = named[name]
            self.assertIs(parent[parent[button]], grid_container)
            self.assertEqual(parent[button].get("Grid.Row"), "2")
            self.assertEqual(button.get("ToolTipService.ShowOnDisabled"), "True")
            self.assertEqual(button.get("Width"), "28")
            self.assertEqual(button.get("Height"), "24")
        for name, handler in (("btnApplySorting", "on_apply_sorting"),
                              ("btnResetSorting", "on_reset_sorting")):
            button = named[name]
            self.assertIs(parent[button], reorder_bar)
            self.assertEqual(button.get("Click"), handler)
            self.assertEqual(button.get("Height"), "24")
            self.assertEqual(button.get("IsEnabled"), "False")
        self.assertEqual(named["txtStatus"].get("Grid.Row"), "2")
        self.assertFalse(any(e.get("Header") == "Reorder Parameters" for e in root.iter()))
        obsolete = {"_reorder_items", "lstReorderParams", "cmbReorderGroup",
                    "_populate_reorder_groups", "_populate_reorder_list", "btnReorderApply"}
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in obsolete
                             for n in ast.walk(TREE)))


if __name__ == "__main__":
    unittest.main()
