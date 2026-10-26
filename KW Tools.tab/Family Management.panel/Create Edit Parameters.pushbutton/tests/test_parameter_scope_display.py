"""Host-independent checks for the parameter grid's scope indicators."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


class ParameterScopeDisplayTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "ParameterEditor.xaml"
        root = ET.parse(str(path)).getroot()
        self.ns = {"w": "http://schemas.microsoft.com/winfx/2006/xaml/presentation"}
        grid = next(node for node in root.iter()
                    if node.get("{http://schemas.microsoft.com/winfx/2006/xaml}Name")
                    == "lstParameters")
        self.columns = grid.find("w:DataGrid.Columns", self.ns)
        self.name_column = next(node for node in self.columns
                                if node.get("Header") == "Name")

    def test_scope_column_is_hidden(self):
        column = next(node for node in self.columns if node.get("Header") == "Inst/Type")
        self.assertEqual(column.get("Visibility"), "Collapsed")

    def test_instance_names_are_italic_and_type_names_are_normal(self):
        style = self.name_column.find("w:DataGridTextColumn.ElementStyle/w:Style", self.ns)
        defaults = {node.get("Property"): node.get("Value")
                    for node in style.findall("w:Setter", self.ns)}
        self.assertEqual(defaults["FontStyle"], "Normal")
        trigger = style.find("w:Style.Triggers/w:DataTrigger", self.ns)
        self.assertEqual(trigger.get("Binding"), "{Binding InstanceTypeLabel}")
        self.assertEqual(trigger.get("Value"), "Instance")
        setter = trigger.find("w:Setter", self.ns)
        self.assertEqual((setter.get("Property"), setter.get("Value")),
                         ("FontStyle", "Italic"))
        overrides = {node.get("Property"): node.get("Value")
                     for node in trigger.findall("w:Setter", self.ns)}
        self.assertEqual(overrides["Foreground"], "#0D47A1")
        self.assertNotIn("Foreground", defaults)

    def test_name_header_has_right_aligned_scope_legend(self):
        style = self.name_column.find("w:DataGridTextColumn.HeaderStyle/w:Style", self.ns)
        setter = style.find("w:Setter", self.ns)
        self.assertEqual((setter.get("Property"), setter.get("Value")),
                         ("HorizontalContentAlignment", "Stretch"))
        header = self.name_column.find(
            "w:DataGridTextColumn.HeaderTemplate/w:DataTemplate/w:Grid", self.ns)
        labels = header.findall("w:TextBlock", self.ns)
        self.assertEqual(labels[0].get("Text"), "Name")
        self.assertEqual(labels[1].get("Grid.Column"), "1")
        self.assertEqual(labels[1].get("HorizontalAlignment"), "Right")
        runs = labels[1].findall("w:Run", self.ns)
        self.assertEqual([run.get("Text") for run in runs], ["Inst", "/Type"])
        self.assertEqual(runs[0].get("FontStyle"), "Italic")
        self.assertEqual(runs[0].get("Foreground"), "#0D47A1")
        self.assertIsNone(runs[1].get("FontStyle"))
        self.assertIsNone(runs[1].get("Foreground"))


if __name__ == "__main__":
    unittest.main()
