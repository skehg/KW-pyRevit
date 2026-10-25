"""Preset management dialog tests; no pyRevit runtime required."""
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import Mock, call, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PresetDeleteDialogTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"name": "Doors", "source": "personal", "path": "doors.json"},
            {"name": "Walls", "source": "shared", "path": "walls.json"},
        ]
        self.preset_api = types.SimpleNamespace(
            SOURCE_PERSONAL="personal",
            SOURCE_SHARED="shared",
            default_preset_name=lambda: None,
            shared_folder=lambda: None,
            list_presets=lambda: self.items,
            preset_label=lambda item: item["name"],
            delete_preset=Mock(),
        )
        self.forms = types.SimpleNamespace(
            SelectFromList=types.SimpleNamespace(show=Mock()),
            alert=Mock(return_value=True),
        )
        pyrevit = types.ModuleType("pyrevit")
        pyrevit.forms = self.forms
        pyrevit.script = types.SimpleNamespace()
        core = types.ModuleType("core")
        core.presets = self.preset_api
        path = os.path.join(ROOT, "ui", "preset_dialogs.py")
        spec = importlib.util.spec_from_file_location("tested_preset_dialogs", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyrevit": pyrevit, "core": core}):
            spec.loader.exec_module(self.module)

    def test_delete_action_allows_multiple_selection_and_deletes_confirmed_items(self):
        self.forms.SelectFromList.show.side_effect = [
            self.module._DELETE,
            ["Doors", "Walls"],
        ]

        self.module.manage_presets()

        self.assertEqual(
            self.forms.SelectFromList.show.call_args_list[1],
            call(
                ["Doors", "Walls"], title="Choose presets to delete",
                button_name="Delete", multiselect=True,
            ),
        )
        self.forms.alert.assert_called_once()
        self.assertEqual(
            self.preset_api.delete_preset.call_args_list,
            [call(self.items[0]), call(self.items[1])],
        )

    def test_cancelled_confirmation_keeps_all_selected_presets(self):
        self.forms.SelectFromList.show.side_effect = [
            self.module._DELETE,
            ["Doors", "Walls"],
        ]
        self.forms.alert.return_value = False

        self.module.manage_presets()

        self.preset_api.delete_preset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
