"""Exercise wizard transitions without displaying dialogs or using Revit."""
import copy
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


class WizardNavigationTests(unittest.TestCase):
    def setUp(self):
        dependencies = {
            "pyrevit": ["forms"],
            "core.element_refs": ["ReferenceCatalog"],
            "core.parameter_map": ["build_parameter_usage_map"],
            "core.presets": ["default_preset", "load_preset", "preset_label"],
            "core.schedule_defaults": ["build_schedule_layout", "read_schedule_defaults", "schedule_parameters"],
            "core.selection": ["category_options", "elements_for_category", "resolve_source_elements"],
            "core.types": ["element_id_value"],
            "core.workbook_builder": ["build_import_workbook", "build_preset_workbook", "build_sheet"],
            "ui.import_dialogs": ["pick_xlsx", "report_import_issues"],
            "ui.preset_dialogs": ["choose_preset", "manage_presets", "report_preset_issues"],
            "ui.wizard": ["ChoiceWizardWindow", "ParameterWizardWindow"],
        }
        modules = {}
        for name, members in dependencies.items():
            module = types.ModuleType(name)
            for member in members:
                setattr(module, member, Mock())
            modules[name] = module
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "workflow.py")
        spec = importlib.util.spec_from_file_location("tested_workflow", path)
        self.flow = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.flow)
        f = self.flow
        self.source = [types.SimpleNamespace(Id=1), types.SimpleNamespace(Id=2)]
        self.categories = [
            {"category_id": 1, "label": "Doors [1]"},
            {"category_id": 2, "label": "Walls [2]"},
        ]
        f.category_options.return_value = self.categories
        f.resolve_source_elements.return_value = self.source
        f.elements_for_category.side_effect = lambda elements, key: [elements[key - 1]]
        f.build_parameter_usage_map.return_value = {"Mark": {}, "Level": {}, "Width": {}}
        f.element_id_value.side_effect = lambda value: value
        f.default_preset.return_value = None
        f.read_schedule_defaults.return_value = None
        f.build_sheet.side_effect = lambda doc, catalog, label, key, elements, fields, mode, usage, **kwargs: {
            "categoryId": key, "name": label, "parameters": fields, "rows": [],
            "categories": kwargs.get("categories", []),
        }
        self.actions = []
        self.visits = []
        self.contexts = []

        def choice(options, title, selected=None, **kwargs):
            step = int(title[5])
            self.visits.append((step, list(selected or [])))
            self.contexts.append(kwargs.get("context_text", ""))
            item = self.actions.pop(0)
            expected, action, values = item[:3]
            layout = item[3] if len(item) > 3 else kwargs.get("grid_layout")
            self.assertEqual(expected, step)
            return types.SimpleNamespace(
                action=action, selected=values,
                grid_layout=layout,
                ShowDialog=lambda: None
            )

        def parameters(label, usage, mode, selected=None, last=True, **kwargs):
            self.visits.append((label, list(selected or []), last))
            self.contexts.append(kwargs.get("context_text", ""))
            expected, action, values = self.actions.pop(0)
            self.assertEqual(expected, label)
            return types.SimpleNamespace(
                action=action, selected_parameters=values, ShowDialog=lambda: None
            )
        f.ChoiceWizardWindow.side_effect = choice
        f.ParameterWizardWindow.side_effect = parameters

    def workbook(self):
        return {
            "selectionMode": "Current View", "parameterMode": "Instances Mode",
            "sheets": [
                {"categoryId": 1, "parameters": ["Mark", "Level"],
                 "layout": {"formulas": {"Mark": {"expression": '="test"'}}}},
                {"categoryId": 2, "parameters": ["Width"], "layout": {"widths": {"Width": 150}}},
            ],
        }

    def test_forward_and_back_preserve_choices_and_column_order(self):
        self.actions = [
            (1, "next", ["Current View"]),
            (2, "next", ["Doors [1]", "Walls [2]"]),
            (3, "next", ["Instances Mode"]),
            ("Doors [1]", "next", ["Level", "Mark"]),
            ("Walls [2]", "back", ["Width"]),
            ("Doors [1]", "back", ["Level", "Mark"]),
            (3, "back", ["Types Mode"]),
            (2, "back", ["Doors [1]", "Walls [2]"]),
            (1, "next", ["Entire Project File"]),
            (2, "next", ["Doors [1]", "Walls [2]"]),
            (3, "next", ["Instances Mode"]),
            ("Doors [1]", "next", ["Level", "Mark"]),
            ("Walls [2]", "next", ["Width"]),
        ]
        workbook, source = self.flow.run_wizard(None, None)
        self.assertEqual(source, self.source)
        self.assertEqual(workbook["selectionMode"], "Entire Project File")
        self.assertEqual(workbook["sheets"][0]["parameters"], ["Level", "Mark"])
        self.assertIn(("Doors [1]", ["Level", "Mark"], False), self.visits)
        self.assertIn((3, ["Types Mode"]), self.visits)
        self.assertTrue(any("2 element(s) in scope" in item for item in self.contexts))
        self.assertTrue(any("Category 1 of 2" in item for item in self.contexts))
        self.assertEqual(self.actions, [])

    def test_selection_mode_options_distinguish_project_and_used_model(self):
        options, _ = self.flow._step_one_options()
        self.assertEqual(options, [
            "Selected Elements", "Current View", "Entire Model",
            "Entire Project File", "Import XLSX...", "Load Preset...",
            "Manage presets...",
        ])

    def test_default_preset_stays_in_preset_group(self):
        item = {"name": "Doors"}
        self.flow.default_preset.return_value = item
        self.flow.preset_label.return_value = "Doors"
        options, default_item = self.flow._step_one_options()
        self.assertIs(default_item, item)
        self.assertEqual(options[-3:], [
            "Load Preset...", "Manage presets...", "Open default preset: Doors",
        ])

    def test_step_one_passes_group_boundaries(self):
        self.actions = [(1, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(None, None))
        self.assertEqual(
            self.flow.ChoiceWizardWindow.call_args.kwargs["separator_before"],
            ("Import XLSX...", "Load Preset..."),
        )

    def launch_with_selection(self, category_ids):
        selected = [types.SimpleNamespace(Id=key) for key in category_ids]
        self.flow.resolve_source_elements.side_effect = (
            lambda uidoc, mode: selected if mode == "Selected Elements" else self.source
        )
        self.flow.category_options.side_effect = (
            lambda elements: [
                item for item in self.categories
                if any(element.Id == item["category_id"] for element in elements)
            ]
        )
        return types.SimpleNamespace()

    def test_launch_selection_preselects_mode_and_all_selected_categories(self):
        uidoc = self.launch_with_selection([1, 2])
        self.actions = [(1, "next", ["Selected Elements"]), (2, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits, [
            (1, ["Selected Elements"]), (2, ["Doors [1]", "Walls [2]"]),
        ])

    def test_no_launch_selection_keeps_current_view_and_no_category_defaults(self):
        uidoc = self.launch_with_selection([])
        self.actions = [(1, "next", ["Current View"]), (2, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits, [(1, ["Current View"]), (2, [])])

    def test_selected_categories_seed_broader_scope_only_where_available(self):
        uidoc = self.launch_with_selection([1, 99])
        self.actions = [(1, "next", ["Entire Model"]), (2, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits[-1], (2, ["Doors [1]"]))

    def test_schedule_preselects_all_scope_categories_over_launch_selection(self):
        uidoc = self.launch_with_selection([1])
        self.flow.read_schedule_defaults.return_value = {"schedule": True}
        self.actions = [(1, "next", ["Current View"]), (2, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits[-1], (2, ["Doors [1]", "Walls [2]"]))

    def test_back_keeps_explicitly_empty_category_selection(self):
        uidoc = self.launch_with_selection([1])
        self.actions = [
            (1, "next", ["Selected Elements"]),
            (2, "back", []),
            (1, "next", ["Selected Elements"]),
            (2, "cancel", []),
        ]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits[-1], (2, []))

    def test_scope_switch_restores_user_category_choices_not_schedule_defaults(self):
        uidoc = self.launch_with_selection([1])
        self.flow.read_schedule_defaults.side_effect = (
            lambda uidoc, mode: {"schedule": True} if mode == "Current View" else None
        )
        self.actions = [
            (1, "next", ["Current View"]),
            (2, "back", ["Walls [2]"]),
            (1, "next", ["Selected Elements"]),
            (2, "back", ["Doors [1]"]),
            (1, "next", ["Current View"]),
            (2, "cancel", []),
        ]
        self.assertIsNone(self.flow.run_wizard(uidoc, None))
        self.assertEqual(self.visits[-1], (2, ["Walls [2]"]))

    def test_grid_resume_does_not_read_or_apply_launch_selection(self):
        self.actions = [("Walls [2]", "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(
            types.SimpleNamespace(), None, self.workbook(), self.source, 1))
        self.flow.resolve_source_elements.assert_not_called()
        self.assertEqual(self.visits[0], ("Walls [2]", ["Width"], True))
        self.assertFalse(
            self.flow.ParameterWizardWindow.call_args.kwargs["combined_categories"]
        )

    def test_combined_layout_uses_one_shared_parameter_picker_and_sheet(self):
        self.actions = [
            (1, "next", ["Current View"]),
            (2, "next", ["Doors [1]", "Walls [2]"], "combined"),
            (3, "next", ["Instances Mode"]),
            ("Combined categories", "next", ["Mark", "Level"]),
        ]
        workbook, _ = self.flow.run_wizard(None, None)
        self.assertEqual(workbook["gridLayout"], "combined")
        self.assertEqual(len(workbook["sheets"]), 1)
        self.assertIsNone(workbook["sheets"][0]["categoryId"])
        self.assertEqual(workbook["sheets"][0]["parameters"], ["Mark", "Level"])
        self.assertEqual(len(workbook["sheets"][0]["categories"]), 2)
        self.assertIn(("Combined categories", [], True), self.visits)
        self.assertTrue(
            self.flow.ParameterWizardWindow.call_args.kwargs["combined_categories"]
        )

    def test_grid_resume_starts_at_active_category_and_preserves_layout(self):
        previous = self.workbook()
        previous.update({
            "presetName": "Audit", "presetSource": "enterprise",
            "presetRelativePath": os.path.join("Doors", "Audit.json"),
        })
        self.actions = [("Walls [2]", "next", ["Width", "Level"])]
        workbook, _ = self.flow.run_wizard(None, None, previous, self.source, 1)
        self.assertEqual(self.visits[0], ("Walls [2]", ["Width"], True))
        self.assertEqual(workbook["sheets"][1]["parameters"], ["Width", "Level"])
        self.assertEqual(workbook["sheets"][0]["layout"], previous["sheets"][0]["layout"])
        for key in ("presetName", "presetSource", "presetRelativePath"):
            self.assertEqual(workbook[key], previous[key])

    def test_cancel_does_not_mutate_existing_workbook(self):
        previous = self.workbook()
        original = copy.deepcopy(previous)
        self.actions = [("Doors [1]", "next", ["Level"]), ("Walls [2]", "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(None, None, previous, self.source))
        self.assertEqual(previous, original)
        self.flow.build_sheet.assert_not_called()

    def test_cancel_file_picker_returns_to_selection_mode(self):
        self.flow.pick_xlsx.return_value = None
        self.actions = [(1, "next", ["Import XLSX..."]), (1, "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(None, None))
        self.assertEqual([step for step, values in self.visits], [1, 1])

    def test_schedule_defaults_seed_order_and_layout(self):
        self.flow.read_schedule_defaults.return_value = {"schedule": True}
        self.flow.schedule_parameters.return_value = ["Level", "Mark"]
        layout = {"filters": {"advanced": {"join": "and", "rules": [
            {"title": "Mark (Instance)", "op": "startsWith", "value": "D"}
        ]}}}
        self.flow.build_schedule_layout.return_value = (layout, [])
        self.actions = [
            (1, "next", ["Current View"]),
            (2, "next", ["Doors [1]"]),
            (3, "next", ["Instances Mode"]),
            ("Combined categories", "next", ["Level", "Mark"]),
        ]
        workbook, _ = self.flow.run_wizard(None, None)
        self.assertIn(("Combined categories", ["Level", "Mark"], True), self.visits)
        self.assertEqual(workbook["sheets"][0]["layout"], layout)
        self.assertEqual(workbook["gridLayout"], "combined")

    def test_schedule_defaults_do_not_replace_grid_choices(self):
        self.flow.read_schedule_defaults.return_value = {"schedule": True}
        self.actions = [
            ("Doors [1]", "back", ["Level", "Mark"]),
            (3, "back", ["Instances Mode"]),
            (2, "back", ["Doors [1]", "Walls [2]"]),
            (1, "next", ["Current View"]),
            (2, "next", ["Doors [1]", "Walls [2]"]),
            (3, "next", ["Instances Mode"]),
            ("Doors [1]", "next", ["Level", "Mark"]),
            ("Walls [2]", "next", ["Width"]),
        ]
        previous = self.workbook()
        workbook, _ = self.flow.run_wizard(None, None, previous, self.source)
        self.flow.schedule_parameters.assert_not_called()
        self.flow.build_schedule_layout.assert_not_called()
        self.assertEqual(workbook["sheets"][0]["layout"], previous["sheets"][0]["layout"])

    def test_loading_preset_prompts_for_new_scope(self):
        self.flow.load_preset.return_value = {"selectionMode": "Current View"}
        built = {"sheets": []}
        self.flow.build_preset_workbook.return_value = (built, [])
        self.flow.ChoiceWizardWindow.side_effect = lambda *args, **kwargs: types.SimpleNamespace(
            action="next", selected=["Entire Model"], ShowDialog=lambda: None
        )
        item = {
            "path": "preset.json", "name": "Doors", "source": "enterprise",
            "relativePath": os.path.join("Doors", "Audit.json"),
        }
        result = self.flow._run_preset(None, None, item)
        self.flow.resolve_source_elements.assert_called_once_with(None, "Entire Model")
        self.flow.build_preset_workbook.assert_called_once_with(
            None, self.flow.load_preset.return_value, "Entire Model", self.source
        )
        self.assertEqual(result, (built, self.source))
        self.assertEqual(built["presetRelativePath"], item["relativePath"])
        self.assertEqual(built["presetSource"], "enterprise")

    def test_cancelling_preset_scope_does_not_collect_or_build(self):
        self.flow.load_preset.return_value = {"selectionMode": "Current View"}
        self.flow.ChoiceWizardWindow.side_effect = lambda *args, **kwargs: types.SimpleNamespace(
            action="back", ShowDialog=lambda: None
        )
        self.assertIsNone(self.flow._run_preset(
            None, None, {"path": "preset.json", "name": "Doors"}
        ))
        self.flow.resolve_source_elements.assert_not_called()
        self.flow.build_preset_workbook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
