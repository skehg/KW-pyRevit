"""Preset dialogs against isolated libraries; no pyRevit runtime required."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import presets


class PresetDialogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(presets, "_app_data_dir", return_value=temporary.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.enterprise = os.path.join(temporary.name, "enterprise")
        os.makedirs(self.enterprise)
        presets.set_enterprise_folder(self.enterprise)
        self.forms = types.SimpleNamespace(
            SelectFromList=types.SimpleNamespace(show=Mock()),
            ask_for_string=Mock(return_value="Doors"),
            ask_for_one_item=Mock(return_value="[User root]"),
            pick_folder=Mock(),
            alert=Mock(return_value=True),
        )
        pyrevit = types.ModuleType("pyrevit")
        pyrevit.forms = self.forms
        pyrevit.script = types.SimpleNamespace(get_logger=lambda: Mock())
        spec = importlib.util.spec_from_file_location(
            "tested_preset_dialogs", os.path.join(ROOT, "ui", "preset_dialogs.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyrevit": pyrevit}):
            spec.loader.exec_module(self.module)
        self.workbook = {"selectionMode": "Current View", "sheets": []}

    def save(self, name, folder=""):
        path = presets.save_preset({"name": name, "sheets": []}, subfolder=folder)
        return next(item for item in presets.list_presets() if item["path"] == path)

    def test_delete_allows_multiple_user_presets_but_never_enterprise(self):
        items = [self.save("Doors"), self.save("Walls", "Audits")]
        enterprise_path = os.path.join(self.enterprise, "Doors.json")
        presets._write_json(enterprise_path, {"name": "Doors", "sheets": []})
        labels = [presets.preset_label(item) for item in items]
        self.forms.SelectFromList.show.side_effect = [self.module._DELETE, labels]

        self.module.manage_presets()

        listed = self.forms.SelectFromList.show.call_args_list[1].args[0]
        self.assertEqual(set(listed), set(labels))
        self.assertTrue(os.path.exists(enterprise_path))
        for item in items:
            self.assertFalse(os.path.exists(item["path"]))

    def test_cancelled_delete_confirmation_keeps_selected_presets(self):
        item = self.save("Doors")
        self.forms.SelectFromList.show.side_effect = [
            self.module._DELETE, [presets.preset_label(item)],
        ]
        self.forms.alert.return_value = False
        self.module.manage_presets()
        self.assertTrue(os.path.exists(item["path"]))

    def test_save_enterprise_preset_creates_user_copy_in_suggested_folder(self):
        original = os.path.join(self.enterprise, "Doors", "Audit.json")
        presets._write_json(original, {"name": "Audit", "sheets": []})
        self.workbook.update({
            "presetName": "Audit", "presetSource": presets.SOURCE_ENTERPRISE,
            "presetRelativePath": os.path.join("Doors", "Audit.json"),
        })
        self.forms.ask_for_string.return_value = "Audit"
        self.forms.ask_for_one_item.return_value = "Doors"
        with open(original, "rb") as stream:
            before = stream.read()

        name, path = self.module.save_from_grid(self.workbook, [])

        self.assertEqual(name, "Audit")
        self.assertEqual(path, os.path.join(presets.user_folder(), "Doors", "Audit.json"))
        self.assertEqual(self.forms.ask_for_one_item.call_args.kwargs["default"], "Doors")
        self.assertEqual(self.workbook["presetSource"], presets.SOURCE_USER)
        self.assertEqual(presets.default_preset()["source"], presets.SOURCE_USER)
        with open(original, "rb") as stream:
            self.assertEqual(before, stream.read())

    def test_new_nested_folder_is_created_on_save(self):
        self.forms.ask_for_one_item.return_value = "[New subfolder...]"
        self.forms.ask_for_string.side_effect = ["Audit", "Doors\\Checks"]
        name, path = self.module.save_from_grid(self.workbook, [])
        self.assertEqual(path, os.path.join(presets.user_folder(), "Doors", "Checks", "Audit.json"))
        self.assertTrue(os.path.isfile(path))

    def test_cancelled_folder_picker_writes_nothing(self):
        self.forms.ask_for_one_item.return_value = None
        self.assertIsNone(self.module.save_from_grid(self.workbook, []))
        self.assertFalse(os.path.exists(presets.user_folder()))

    def test_declined_overwrite_keeps_original(self):
        item = self.save("Doors")
        with open(item["path"], "rb") as stream:
            before = stream.read()
        self.forms.alert.return_value = False
        self.assertIsNone(self.module.save_from_grid(self.workbook, []))
        with open(item["path"], "rb") as stream:
            self.assertEqual(before, stream.read())

    def test_management_exposes_both_locations_and_clears_enterprise(self):
        self.forms.SelectFromList.show.return_value = self.module._CLEAR_ENTERPRISE
        self.module.manage_presets()
        actions = self.forms.SelectFromList.show.call_args.args[0]
        self.assertIn(self.module._SET_USER, actions)
        self.assertIn(self.module._SET_ENTERPRISE, actions)
        self.assertIsNone(presets.enterprise_folder())

    def test_changing_user_location_does_not_move_existing_files(self):
        item = self.save("Doors")
        target = os.path.join(self.enterprise, "..", "new-user")
        os.makedirs(target)
        self.forms.SelectFromList.show.return_value = self.module._SET_USER
        self.forms.pick_folder.return_value = target
        self.module.manage_presets()
        self.assertEqual(presets.user_folder(), os.path.abspath(target))
        self.assertTrue(os.path.exists(item["path"]))
        self.assertEqual(presets.list_presets(), [])

    def test_unavailable_enterprise_reports_issue_and_retains_user_results(self):
        self.save("Doors")
        os.rmdir(self.enterprise)
        with self.assertLogs("core.presets", level="WARNING"):
            items = self.module._list_presets()
        self.assertEqual(len(items), 1)
        self.assertIn("unavailable", self.forms.alert.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
