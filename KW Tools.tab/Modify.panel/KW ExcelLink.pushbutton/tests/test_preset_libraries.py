"""Library paths, identities, migration and write protection without Revit."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import presets


class PresetLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = temporary.name
        patcher = patch.object(presets, "_app_data_dir", return_value=self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.enterprise = os.path.join(self.folder, "enterprise")
        os.makedirs(self.enterprise)

    def publish(self, relative, name="Audit"):
        path = os.path.join(self.enterprise, relative)
        presets._write_json(path, {"name": name, "version": 2, "sheets": []})
        return path

    def user_preset(self, name="Audit", subfolder=""):
        return presets.save_preset({"name": name, "sheets": []}, subfolder=subfolder)

    def test_defaults_match_existing_user_location_and_blank_enterprise(self):
        self.assertEqual(presets.user_folder(), os.path.join(self.folder, "presets"))
        self.assertIsNone(presets.enterprise_folder())
        self.assertEqual(presets.list_presets(), [])

    def test_recursive_listing_keeps_duplicates_across_folders_and_libraries(self):
        presets.set_enterprise_folder(self.enterprise)
        self.publish(os.path.join("Doors", "Audit.json"))
        self.publish(os.path.join("Renumbering", "Audit.json"))
        self.user_preset(subfolder="Doors")
        self.user_preset()
        items = presets.list_presets()
        self.assertEqual(len(items), 4)
        self.assertEqual(len(set(presets.preset_label(item) for item in items)), 4)
        self.assertEqual(
            set(item["relativePath"] for item in items),
            {"Audit.json", os.path.join("Doors", "Audit.json"),
             os.path.join("Renumbering", "Audit.json")},
        )
        self.assertEqual(presets.user_subfolders(), ["Doors"])

    def test_enterprise_save_and_delete_rejected_at_storage_layer(self):
        presets.set_enterprise_folder(self.enterprise)
        original = self.publish("Audit.json")
        item = presets.list_presets()[0]
        with self.assertRaisesRegex(ValueError, "read-only"):
            presets.save_preset({"name": "Audit", "sheets": []}, presets.SOURCE_ENTERPRISE)
        with self.assertRaisesRegex(ValueError, "read-only"):
            presets.delete_preset(item)
        self.assertTrue(os.path.isfile(original))

    def test_user_folder_is_configurable_and_files_are_not_moved(self):
        original = self.user_preset()
        new = os.path.join(self.folder, "custom")
        os.makedirs(new)
        presets.set_user_folder(new)
        saved = self.user_preset("New", "Nested")
        self.assertTrue(saved.startswith(new + os.sep))
        self.assertTrue(os.path.isfile(original))
        self.assertEqual(len(presets.list_presets()), 1)

    def test_location_overlap_is_rejected_in_both_directions(self):
        self.user_preset()
        for enterprise in (presets.user_folder(), self.folder):
            with self.assertRaisesRegex(ValueError, "overlap"):
                presets.set_enterprise_folder(enterprise)
        presets.set_enterprise_folder(self.enterprise)
        for user in (self.enterprise, self.folder):
            with self.assertRaisesRegex(ValueError, "overlap"):
                presets.set_user_folder(user)

    def test_invalid_subfolder_paths_cannot_escape_or_use_windows_reserved_names(self):
        for folder in ("..", "Doors\\..\\..", "\\outside", "C:\\outside", "NUL", "Doors."):
            with self.subTest(folder=folder):
                with self.assertRaises(ValueError):
                    self.user_preset(subfolder=folder)
        self.assertFalse(os.path.exists(presets.user_folder()))

    def test_legacy_shared_folder_and_name_default_remain_available(self):
        self.publish("Audit.json")
        self.user_preset()
        presets.save_settings({"sharedFolder": self.enterprise, "defaultPreset": "Audit"})
        item = presets.default_preset()
        self.assertEqual(item["source"], presets.SOURCE_USER)
        self.assertEqual(presets.enterprise_folder(), self.enterprise)
        self.assertEqual(presets.load_settings()["defaultPreset"], presets.preset_reference(item))
        presets.set_enterprise_folder(None)
        self.assertIsNone(presets.enterprise_folder())
        self.assertNotIn("sharedFolder", presets.load_settings())

    def test_enterprise_default_does_not_fall_back_to_same_named_user_preset(self):
        presets.set_enterprise_folder(self.enterprise)
        path = self.publish(os.path.join("Doors", "Audit.json"))
        self.user_preset(subfolder="Doors")
        item = next(item for item in presets.list_presets()
                    if item["source"] == presets.SOURCE_ENTERPRISE)
        presets.set_default_preset(item)
        self.assertEqual(presets.default_preset()["path"], path)
        os.remove(path)
        self.assertIsNone(presets.default_preset())
        self.assertEqual(presets.load_settings()["defaultPreset"]["source"], presets.SOURCE_ENTERPRISE)

    def test_deleting_only_clears_exact_default_not_same_named_other_folder(self):
        self.user_preset(subfolder="Doors")
        self.user_preset(subfolder="Renumbering")
        first, second = presets.list_presets()
        presets.set_default_preset(first)
        presets.delete_preset(second)
        self.assertEqual(presets.default_preset()["path"], first["path"])
        presets.delete_preset(first)
        self.assertNotIn("defaultPreset", presets.load_settings())

    def test_malformed_and_newer_presets_are_reported_without_hiding_valid_ones(self):
        presets.set_enterprise_folder(self.enterprise)
        self.publish("valid.json")
        presets._write_json(os.path.join(self.enterprise, "bad.json"), {"sheets": "wrong"})
        presets._write_json(os.path.join(self.enterprise, "future.json"), {
            "version": presets.PRESET_VERSION + 1, "sheets": [],
        })
        issues = []
        with self.assertLogs("core.presets", level="WARNING"):
            items = presets.list_presets(issues)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(issues), 2)

    def test_corrupt_settings_raise_instead_of_resetting_locations(self):
        presets._write_json(presets._settings_path(), [])
        with self.assertRaisesRegex(ValueError, "JSON object"):
            presets.user_folder()

    def test_stale_or_forged_delete_path_is_rejected(self):
        self.user_preset()
        item = presets.list_presets()[0]
        item["path"] = os.path.join(self.enterprise, "Audit.json")
        with self.assertRaisesRegex(ValueError, "configured User"):
            presets.delete_preset(item)


if __name__ == "__main__":
    unittest.main()
