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
            "core.presets": ["default_preset_name", "find_preset", "load_preset", "preset_label"],
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
        f.find_preset.return_value = None
        f.read_schedule_defaults.return_value = None
        f.build_sheet.side_effect = lambda doc, catalog, label, key, elements, fields, mode, usage: {
            "categoryId": key, "name": label, "parameters": fields, "rows": []
        }
        self.actions = []
        self.visits = []

        def choice(options, title, selected=None, **kwargs):
            step = int(title[5])
            self.visits.append((step, list(selected or [])))
            expected, action, values = self.actions.pop(0)
            self.assertEqual(expected, step)
            return types.SimpleNamespace(
                action=action, selected=values, ShowDialog=lambda: None
            )

        def parameters(label, usage, mode, selected=None, last=True):
            self.visits.append((label, list(selected or []), last))
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
            (1, "next", ["Entire Model"]),
            (2, "next", ["Doors [1]", "Walls [2]"]),
            (3, "next", ["Instances Mode"]),
            ("Doors [1]", "next", ["Level", "Mark"]),
            ("Walls [2]", "next", ["Width"]),
        ]
        workbook, source = self.flow.run_wizard(None, None)
        self.assertEqual(source, self.source)
        self.assertEqual(workbook["selectionMode"], "Entire Model")
        self.assertEqual(workbook["sheets"][0]["parameters"], ["Level", "Mark"])
        self.assertIn(("Doors [1]", ["Level", "Mark"], False), self.visits)
        self.assertIn((3, ["Types Mode"]), self.visits)
        self.assertEqual(self.actions, [])

    def test_grid_resume_starts_at_active_category_and_preserves_layout(self):
        previous = self.workbook()
        self.actions = [("Walls [2]", "next", ["Width", "Level"])]
        workbook, _ = self.flow.run_wizard(None, None, previous, self.source, 1)
        self.assertEqual(self.visits[0], ("Walls [2]", ["Width"], True))
        self.assertEqual(workbook["sheets"][1]["parameters"], ["Width", "Level"])
        self.assertEqual(workbook["sheets"][0]["layout"], previous["sheets"][0]["layout"])

    def test_cancel_does_not_mutate_existing_workbook(self):
        previous = self.workbook()
        original = copy.deepcopy(previous)
        self.actions = [("Doors [1]", "next", ["Level"]), ("Walls [2]", "cancel", [])]
        self.assertIsNone(self.flow.run_wizard(None, None, previous, self.source))
        self.assertEqual(previous, original)
        self.flow.build_sheet.assert_not_called()

    def test_cancel_file_picker_returns_to_selection_mode(self):
        self.flow.pick_xlsx.return_value = None
        self.actions = [(1, "next", ["Import edited XLSX..."]), (1, "cancel", [])]
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
            ("Doors [1]", "next", ["Level", "Mark"]),
        ]
        workbook, _ = self.flow.run_wizard(None, None)
        self.assertIn(("Doors [1]", ["Level", "Mark"], True), self.visits)
        self.assertEqual(workbook["sheets"][0]["layout"], layout)

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
        result = self.flow._run_preset(None, None, {"path": "preset.json", "name": "Doors"})
        self.flow.resolve_source_elements.assert_called_once_with(None, "Entire Model")
        self.flow.build_preset_workbook.assert_called_once_with(
            None, self.flow.load_preset.return_value, "Entire Model", self.source
        )
        self.assertEqual(result, (built, self.source))

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
