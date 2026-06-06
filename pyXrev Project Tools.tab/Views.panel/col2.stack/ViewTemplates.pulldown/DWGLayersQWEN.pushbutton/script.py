# -*- coding: utf-8 -*-
# pyRevit IronPython 2.7
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View,
    BuiltInCategory,
    Transaction,
    OverrideGraphicSettings,
    Color,
)
from Autodesk.Revit.UI import UIApplication
from System import Enum
from System.IO import File, Path
from System.Windows.Markup import XamlReader
from System.Xml import XmlReader

from pyrevit import forms, script

__doc__ = 'Set DWG layer states (on/off, color, lineweight, pattern) on multiple Views/View Templates.'

logger = script.get_logger()
output = script.get_output()

uiapp = __revit__
app = uiapp.Application
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document


# -----------------------------
# Helpers
# -----------------------------
def load_xaml(xaml_name):
    """Load XAML file located next to this script."""
    script_dir = Path.GetDirectoryName(__file__)
    xaml_path = Path.Combine(script_dir, xaml_name)
    if not File.Exists(xaml_path):
        forms.alert('XAML not found: {0}'.format(xaml_path), exitscript=True)
    with File.OpenRead(xaml_path) as fs:
        xml_reader = XmlReader.Create(fs)
        window = XamlReader.Load(xml_reader)
    return window


def get_all_views_and_templates(document):
    """Return (views, templates) as lists of View elements."""
    views = []
    templates = []
    col = FilteredElementCollector(document).OfClass(View)
    for v in col:
        try:
            if v.IsTemplate:
                templates.append(v)
            else:
                # skip internal or invalid views
                if not v.ViewType.ToString().startswith("Internal"):
                    views.append(v)
        except:
            pass
    return views, templates


def get_imported_categories_root(document):
    """Get the root Imported Categories category (OST_ImportObjectStyles)."""
    try:
        settings = document.Settings
        cats = settings.Categories
        root_cat = cats.get_Item(BuiltInCategory.OST_ImportObjectStyles)
        return root_cat
    except:
        logger.warning("Could not get OST_ImportObjectStyles category.")
        return None


def get_dwg_file_categories(document):
    """Return list of top-level imported categories (one per DWG file)."""
    root_cat = get_imported_categories_root(document)
    if root_cat is None:
        return []
    dwg_cats = []
    for subcat in root_cat.SubCategories:
        # Each subcat here should represent a DWG file
        dwg_cats.append(subcat)
    return dwg_cats


def get_layer_categories_for_dwg(dwg_cat):
    """Return list of layer Category objects for a given DWG file category."""
    layers = []
    if dwg_cat is None:
        return layers
    for subcat in dwg_cat.SubCategories:
        # Each subcat here should represent a DWG layer
        layers.append(subcat)
    return layers


def get_line_patterns(document):
    """Collect all line patterns in the document."""
    from Autodesk.Revit.DB import LinePatternElement
    patterns = []
    col = FilteredElementCollector(document).OfClass(LinePatternElement)
    for lp in col:
        patterns.append(lp)
    return patterns


# -----------------------------
# WPF Windows
# -----------------------------
class SelectViewsWindow(forms.WPFWindow):
    def __init__(self):
        xaml_name = 'SelectViewTemplate.xaml'
        wpf_window = load_xaml(xaml_name)
        forms.WPFWindow.__init__(self, wpf_window)

        self.views, self.templates = get_all_views_and_templates(doc)
        self.show_views = True
        self.show_templates = True
        self.filter_text = ''

        # wire up events
        self.FindName('chkShowViews').IsChecked = True
        self.FindName('chkShowTemplates').IsChecked = True

        self.FindName('chkShowViews').Checked += self._on_filter_changed
        self.FindName('chkShowViews').Unchecked += self._on_filter_changed
        self.FindName('chkShowTemplates').Checked += self._on_filter_changed
        self.FindName('chkShowTemplates').Unchecked += self._on_filter_changed
        self.FindName('txtFilter').TextChanged += self._on_filter_changed

        self.FindName('btnNext').Click += self._on_next
        self.FindName('btnCancel').Click += self._on_cancel

        self._refresh_list()

        self.selected_views = []

    def _on_filter_changed(self, sender, args):
        self.show_views = bool(self.FindName('chkShowViews').IsChecked)
        self.show_templates = bool(self.FindName('chkShowTemplates').IsChecked)
        self.filter_text = self.FindName('txtFilter').Text or ''
        self._refresh_list()

    def _refresh_list(self):
        lb = self.FindName('lstViews')
        lb.Items.Clear()
        f = self.filter_text.lower()
        if self.show_views:
            for v in self.views:
                name = v.Name
                if f and f not in name.lower():
                    continue
                lb.Items.Add(v)
        if self.show_templates:
            for t in self.templates:
                name = t.Name
                if f and f not in name.lower():
                    continue
                lb.Items.Add(t)

    def _on_next(self, sender, args):
        lb = self.FindName('lstViews')
        sel = list(lb.SelectedItems)
        if not sel:
            forms.alert('Please select at least one View or View Template.')
            return
        self.selected_views = sel
        self.DialogResult = True
        self.Close()

    def _on_cancel(self, sender, args):
        self.selected_views = []
        self.DialogResult = False
        self.Close()


class DWGLayersWindow(forms.WPFWindow):
    def __init__(self, target_views):
        xaml_name = 'DWGLayers.xaml'
        wpf_window = load_xaml(xaml_name)
        forms.WPFWindow.__init__(self, wpf_window)

        self.target_views = target_views
        self.selected_dwg_cat = None
        self.layer_rows = []  # list of dicts

        # populate DWG dropdown
        self.dwg_cats = get_dwg_file_categories(doc)
        cmb = self.FindName('cmbDWG')
        for cat in self.dwg_cats:
            cmb.Items.Add(cat)
        if cmb.Items.Count > 0:
            cmb.SelectedIndex = 0

        cmb.SelectionChanged += self._on_dwg_changed

        self.FindName('btnNext').Click += self._on_next
        self.FindName('btnBack').Click += self._on_back
        self.FindName('btnCancel').Click += self._on_cancel

        self._on_dwg_changed(None, None)

        self.confirmed = False

    def _on_dwg_changed(self, sender, args):
        cmb = self.FindName('cmbDWG')
        self.selected_dwg_cat = cmb.SelectedItem
        self._build_layer_grid()

    def _build_layer_grid(self):
        grid = self.FindName('dgLayers')
        grid.Items.Clear()
        self.layer_rows = []

        if self.selected_dwg_cat is None:
            return

        layers = get_layer_categories_for_dwg(self.selected_dwg_cat)
        if not layers:
            logger.warning("No layer subcategories found for DWG category: {0}".format(self.selected_dwg_cat.Name))

        # Use first target view as source for current overrides
        source_view = None
        if self.target_views:
            source_view = self.target_views[0]

        for layer_cat in layers:
            row = {
                'Category': layer_cat,
                'LayerName': layer_cat.Name,
                'IsOn': True,
                'Color': None,
                'LinePatternName': '',
                'LineWeight': 1,
            }

            if source_view is not None:
                try:
                    # on/off
                    hidden = source_view.GetCategoryHidden(layer_cat.Id)  # Unsure of this API call
                    row['IsOn'] = not hidden
                except:
                    logger.debug("Could not read hidden state for layer {0}".format(layer_cat.Name))

                try:
                    ogs = source_view.GetCategoryOverrides(layer_cat.Id)  # Unsure of this API call
                    # color
                    try:
                        col = ogs.ProjectionLineColor  # Unsure of this API call
                        row['Color'] = col
                    except:
                        pass
                    # lineweight
                    try:
                        lw = ogs.ProjectionLineWeight  # Unsure of this API call
                        row['LineWeight'] = lw
                    except:
                        pass
                    # line pattern
                    try:
                        lp_id = ogs.ProjectionLinePatternId  # Unsure of this API call
                        if lp_id is not None and lp_id.IntegerValue != -1:
                            lp_el = doc.GetElement(lp_id)
                            if lp_el is not None:
                                row['LinePatternName'] = lp_el.Name
                    except:
                        pass
                except:
                    logger.debug("Could not read overrides for layer {0}".format(layer_cat.Name))

            self.layer_rows.append(row)
            grid.Items.Add(row)

    def _read_grid_back(self):
        """Read user edits from DataGrid into self.layer_rows."""
        grid = self.FindName('dgLayers')
        # In this simple approach, we assume the underlying dicts are updated by WPF binding.
        # If not, this is a good place to add debug code to inspect grid.Items.
        # Unsure of how WPF binding updates Python dicts in IronPython 2.7
        rows = []
        for item in grid.Items:
            rows.append(item)
        self.layer_rows = rows

    def _on_next(self, sender, args):
        if self.selected_dwg_cat is None:
            forms.alert('Please select a DWG file.')
            return
        self._read_grid_back()

        # Confirmation text
        view_names = [v.Name for v in self.target_views]
        msg = "DWG: {0}\n\nViews/View Templates to update:\n - {1}\n\nProceed?".format(
            self.selected_dwg_cat.Name,
            "\n - ".join(view_names)
        )
        if not forms.alert(msg, yes=True, no=True):
            return

        self.confirmed = True
        self.DialogResult = True
        self.Close()

    def _on_back(self, sender, args):
        self.confirmed = False
        self.DialogResult = False
        self.Close()

    def _on_cancel(self, sender, args):
        self.confirmed = False
        self.DialogResult = False
        self.Close()


# -----------------------------
# Apply settings
# -----------------------------
def apply_layer_settings_to_views(target_views, dwg_cat, layer_rows):
    if not target_views or dwg_cat is None or not layer_rows:
        return

    # Build lookup of line patterns by name
    lp_by_name = {}
    for lp in get_line_patterns(doc):
        lp_by_name[lp.Name] = lp

    t = Transaction(doc, "Set DWG Layer States")
    t.Start()
    try:
        for v in target_views:
            for row in layer_rows:
                layer_cat = row.get('Category')
                if layer_cat is None:
                    continue

                # on/off
                try:
                    is_on = bool(row.get('IsOn', True))
                    v.SetCategoryHidden(layer_cat.Id, not is_on)  # Unsure of this API call
                except:
                    logger.debug("Failed to set hidden for {0} in view {1}".format(layer_cat.Name, v.Name))

                # overrides
                try:
                    ogs = v.GetCategoryOverrides(layer_cat.Id)  # Unsure of this API call
                except:
                    ogs = OverrideGraphicSettings()  # Unsure of this API call

                # color
                col = row.get('Color')
                if col is not None:
                    try:
                        ogs.SetProjectionLineColor(col)  # Unsure of this API call
                    except:
                        logger.debug("Failed to set color for {0} in view {1}".format(layer_cat.Name, v.Name))

                # lineweight
                lw = row.get('LineWeight')
                if lw is not None:
                    try:
                        ogs.SetProjectionLineWeight(int(lw))  # Unsure of this API call
                    except:
                        logger.debug("Failed to set lineweight for {0} in view {1}".format(layer_cat.Name, v.Name))

                # line pattern
                lp_name = row.get('LinePatternName')
                if lp_name:
                    lp_el = lp_by_name.get(lp_name)
                    if lp_el is not None:
                        try:
                            ogs.SetProjectionLinePatternId(lp_el.Id)  # Unsure of this API call
                        except:
                            logger.debug("Failed to set line pattern for {0} in view {1}".format(layer_cat.Name, v.Name))

                try:
                    v.SetCategoryOverrides(layer_cat.Id, ogs)  # Unsure of this API call
                except:
                    logger.debug("Failed to apply overrides for {0} in view {1}".format(layer_cat.Name, v.Name))

        t.Commit()
    except Exception as ex:
        logger.error("Error applying DWG layer settings: {0}".format(ex))
        t.RollBack()


# -----------------------------
# Main
# -----------------------------
def main():
    # Step 1: select views/templates
    win1 = SelectViewsWindow()
    res1 = win1.show_dialog()
    if not res1 or not win1.selected_views:
        return

    selected_views = win1.selected_views

    # Step 2: DWG + layers
    win2 = DWGLayersWindow(selected_views)
    res2 = win2.show_dialog()
    if not res2 or not win2.confirmed:
        return

    apply_layer_settings_to_views(
        win2.target_views,
        win2.selected_dwg_cat,
        win2.layer_rows
    )

    forms.alert('DWG layer settings applied.', title='DWG Layer States')


if __name__ == '__main__':
    main()
