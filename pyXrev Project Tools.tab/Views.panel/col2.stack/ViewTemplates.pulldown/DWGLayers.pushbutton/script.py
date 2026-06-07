import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('System.Xml')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    BuiltInCategory,
    Color,
    ElementId,
    FilteredElementCollector,
    ImportInstance,
    LinePatternElement,
    OverrideGraphicSettings,
    Transaction,
    View,
)
from System import Object
from System.IO import File, Path
from System.Windows.Markup import XamlReader
from System.Windows import SystemParameters, WindowStartupLocation
from System.Text.RegularExpressions import Regex
from System.Collections.ObjectModel import ObservableCollection

from pyrevit import forms, script


logger = script.get_logger()
doc = __revit__.ActiveUIDocument.Document

NO_OVERRIDE_TOKEN = '<No Override>'


class SelectableViewItem(object):
    def __init__(self, element, item_type, view_type_name):
        self.Element = element
        self.Name = element.Name
        self.ItemType = item_type
        self.ViewTypeName = view_type_name

    def ToString(self):
        return "[{0}] {1}".format(self.ItemType, self.Name)


class DwgCategoryItem(object):
    def __init__(self, category):
        self.Category = category
        self.Name = category.Name

    def ToString(self):
        return self.Name


class LayerRow(object):
    def __init__(self, category, name, is_visible, color_text, pattern_name, line_weight):
        self.Category = category
        self.LayerName = name
        self.IsVisible = is_visible
        self.Color = color_text
        self.LinePattern = pattern_name
        self.LineWeight = line_weight


def _cfg_get(name):
    cfg = script.get_config()
    try:
        return getattr(cfg, name)
    except:
        return None


def _cfg_set(name, value):
    cfg = script.get_config()
    setattr(cfg, name, value)


def _is_rect_on_screen(left, top, width, height):
    try:
        v_left = float(SystemParameters.VirtualScreenLeft)
        v_top = float(SystemParameters.VirtualScreenTop)
        v_width = float(SystemParameters.VirtualScreenWidth)
        v_height = float(SystemParameters.VirtualScreenHeight)
    except:
        return True

    v_right = v_left + v_width
    v_bottom = v_top + v_height
    right = left + width
    bottom = top + height

    if right < v_left:
        return False
    if left > v_right:
        return False
    if bottom < v_top:
        return False
    if top > v_bottom:
        return False
    return True


def restore_window_position(window, key):
    left = _cfg_get(key + '_left')
    top = _cfg_get(key + '_top')
    if left is None or top is None:
        return

    try:
        left = float(left)
        top = float(top)
    except:
        return

    width = 800.0
    height = 600.0
    try:
        if window.Width > 0:
            width = float(window.Width)
        if window.Height > 0:
            height = float(window.Height)
    except:
        pass

    if _is_rect_on_screen(left, top, width, height):
        window.WindowStartupLocation = WindowStartupLocation.Manual
        window.Left = left
        window.Top = top


def save_window_position(window, key):
    try:
        _cfg_set(key + '_left', float(window.Left))
        _cfg_set(key + '_top', float(window.Top))
        script.save_config()
    except:
        pass


def load_xaml_window(xaml_name):
    script_dir = Path.GetDirectoryName(__file__)
    xaml_path = Path.Combine(script_dir, xaml_name)
    if not File.Exists(xaml_path):
        forms.alert('XAML not found: {0}'.format(xaml_path), exitscript=True)

    # pyRevit/IronPython does not provide compiled backing classes for x:Class,
    # so remove x:Class from loose XAML before parsing.
    xaml_text = File.ReadAllText(xaml_path)
    xaml_text = Regex.Replace(xaml_text, '\\s+x:Class="[^"]*"', '')
    return XamlReader.Parse(xaml_text)


def get_all_views_and_templates(document):
    views = []
    templates = []
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            if v.IsTemplate:
                templates.append(v)
            elif not v.ViewType.ToString().startswith('Internal'):
                views.append(v)
        except:
            pass
    return views, templates


def get_view_type_name(view):
    try:
        return view.ViewType.ToString()
    except:
        return 'Unknown'


def get_line_pattern_names(document):
    names = []
    for lp in FilteredElementCollector(document).OfClass(LinePatternElement):
        try:
            names.append(lp.Name)
        except:
            pass
    names = sorted(list(set(names)), key=lambda x: x.lower())
    return names


def get_dwg_categories(document):
    items = []
    seen_cat_ids = set()

    # Prefer categories coming from actual imported instances; these map to DWG names.
    for imp in FilteredElementCollector(document).OfClass(ImportInstance):
        try:
            cat = imp.Category
            if cat is None:
                continue
            cid = cat.Id.IntegerValue
            if cid in seen_cat_ids:
                continue
            seen_cat_ids.add(cid)
            items.append(DwgCategoryItem(cat))
        except:
            pass

    if items:
        items.sort(key=lambda x: x.Name.lower())
        return items

    # Fallback: use Imported Object Styles and keep only categories with subcategories.
    try:
        root = document.Settings.Categories.get_Item(BuiltInCategory.OST_ImportObjectStyles)
    except:
        root = None
    if root is None:
        return []

    for cat in root.SubCategories:
        try:
            has_layers = False
            for _ in cat.SubCategories:
                has_layers = True
                break
            if has_layers:
                items.append(DwgCategoryItem(cat))
        except:
            pass

    items.sort(key=lambda x: x.Name.lower())
    return items


def get_layer_categories(dwg_category):
    if dwg_category is None:
        return []
    return [cat for cat in dwg_category.SubCategories]


def color_to_text(color_obj):
    if color_obj is None:
        return ''
    try:
        return '{0},{1},{2}'.format(color_obj.Red, color_obj.Green, color_obj.Blue)
    except:
        return ''


def parse_color_text(text):
    if text is None:
        return None
    value = str(text).strip()
    if not value or value.lower() in ['default', 'none', '-']:
        return None
    parts = value.replace(';', ',').replace(' ', ',').split(',')
    parts = [p for p in parts if p != '']
    if len(parts) != 3:
        return None
    try:
        r = max(0, min(255, int(parts[0])))
        g = max(0, min(255, int(parts[1])))
        b = max(0, min(255, int(parts[2])))
        return Color(r, g, b)
    except:
        return None


def parse_lineweight(value):
    try:
        lw = int(value)
        return lw if lw > 0 else None
    except:
        return None


def is_no_override_value(value):
    if value is None:
        return False
    return str(value).strip().lower() == NO_OVERRIDE_TOKEN.lower()


class SelectViewTemplateDialog(object):
    def __init__(self):
        self.window = load_xaml_window('SelectViewTemplate.xaml')
        self.filter_combo = self.window.FindName('FilterCombo')
        self.view_type_filter_combo = self.window.FindName('ViewTypeFilterCombo')
        self.search_box = self.window.FindName('SearchBox')
        self.selection_list = self.window.FindName('SelectionList')
        self.cancel_btn = self.window.FindName('CancelBtn')
        self.next_btn = self.window.FindName('NextBtn')

        self.views, self.templates = get_all_views_and_templates(doc)
        self.filtered_items = ObservableCollection[Object]()
        self.selected_elements = []

        self.selection_list.ItemsSource = self.filtered_items

        self._populate_view_type_filter()

        self.filter_combo.SelectionChanged += self._on_filter_or_search_changed
        self.view_type_filter_combo.SelectionChanged += self._on_filter_or_search_changed
        self.search_box.TextChanged += self._on_filter_or_search_changed
        self.cancel_btn.Click += self._on_cancel
        self.next_btn.Click += self._on_next

        self.refresh_list()

    def _populate_view_type_filter(self):
        self.view_type_filter_combo.Items.Clear()
        self.view_type_filter_combo.Items.Add('All Types')

        type_names = set()
        for v in self.views:
            type_names.add(get_view_type_name(v))
        for t in self.templates:
            type_names.add(get_view_type_name(t))

        for type_name in sorted(type_names, key=lambda x: x.lower()):
            self.view_type_filter_combo.Items.Add(type_name)

        self.view_type_filter_combo.SelectedIndex = 0

    def _on_filter_or_search_changed(self, sender, args):
        self.refresh_list()

    def refresh_list(self):
        self.filtered_items.Clear()

        mode = self.filter_combo.SelectedIndex
        search_text = (self.search_box.Text or '').lower().strip()
        selected_view_type = self.view_type_filter_combo.SelectedItem
        if selected_view_type is None:
            selected_view_type = 'All Types'

        if mode in [0, 1]:
            for v in self.views:
                view_type_name = get_view_type_name(v)
                if search_text and search_text not in v.Name.lower():
                    continue
                if selected_view_type != 'All Types' and view_type_name != selected_view_type:
                    continue
                item = SelectableViewItem(v, 'View', view_type_name)
                self.filtered_items.Add(item)

        if mode in [0, 2]:
            for t in self.templates:
                view_type_name = get_view_type_name(t)
                if search_text and search_text not in t.Name.lower():
                    continue
                if selected_view_type != 'All Types' and view_type_name != selected_view_type:
                    continue
                item = SelectableViewItem(t, 'Template', view_type_name)
                self.filtered_items.Add(item)

    def _on_cancel(self, sender, args):
        self.selected_elements = []
        self.window.DialogResult = False
        self.window.Close()

    def _on_next(self, sender, args):
        selected = []
        for item in self.selection_list.SelectedItems:
            try:
                selected.append(item.Element)
            except:
                pass
        if not selected:
            forms.alert('Please select at least one View or View Template.')
            return
        self.selected_elements = selected
        self.window.DialogResult = True
        self.window.Close()

    def show(self):
        restore_window_position(self.window, 'dwg_layers_select_views')
        result = self.window.ShowDialog()
        save_window_position(self.window, 'dwg_layers_select_views')
        return bool(result)


class DwgLayersDialog(object):
    def __init__(self, selected_views):
        self.window = load_xaml_window('DWGLayers.xaml')
        self.selected_views = selected_views

        self.dwg_combo = self.window.FindName('DwgCombo')
        self.layer_grid = self.window.FindName('LayerGrid')
        self.batch_visible_value = self.window.FindName('BatchVisibleValue')
        self.batch_color_box = self.window.FindName('BatchColorBox')
        self.batch_line_pattern_combo = self.window.FindName('BatchLinePatternCombo')
        self.batch_line_weight_box = self.window.FindName('BatchLineWeightBox')
        self.apply_to_selected_btn = self.window.FindName('ApplyToSelectedBtn')
        self.cancel_btn = self.window.FindName('CancelBtn')
        self.next_btn = self.window.FindName('NextBtn')

        self.selected_dwg_item = None
        self.layer_rows = ObservableCollection[Object]()
        self.accepted = False

        self.dwg_items = get_dwg_categories(doc)
        for item in self.dwg_items:
            self.dwg_combo.Items.Add(item)

        self.dwg_combo.SelectionChanged += self._on_dwg_changed
        self.apply_to_selected_btn.Click += self._on_apply_to_selected
        self.cancel_btn.Click += self._on_cancel
        self.next_btn.Click += self._on_next

        self._populate_line_patterns()

        # Default batch visibility control to indeterminate (ignore).
        self.batch_visible_value.IsChecked = None

        if self.dwg_combo.Items.Count > 0:
            self.dwg_combo.SelectedIndex = 0

    def _on_dwg_changed(self, sender, args):
        self.selected_dwg_item = self.dwg_combo.SelectedItem
        self._build_layer_rows()

    def _populate_line_patterns(self):
        self.batch_line_pattern_combo.Items.Clear()
        self.batch_line_pattern_combo.Items.Add('')
        self.batch_line_pattern_combo.Items.Add(NO_OVERRIDE_TOKEN)
        for name in get_line_pattern_names(doc):
            self.batch_line_pattern_combo.Items.Add(name)
        self.batch_line_pattern_combo.SelectedIndex = 0

    def _build_layer_rows(self):
        self.layer_rows = ObservableCollection[Object]()
        self.layer_grid.ItemsSource = self.layer_rows

        if self.selected_dwg_item is None:
            return

        source_view = self.selected_views[0] if self.selected_views else None
        for layer_cat in get_layer_categories(self.selected_dwg_item.Category):
            is_visible = True
            color_text = ''
            line_pattern = ''
            line_weight = ''

            if source_view is not None:
                try:
                    is_visible = not source_view.GetCategoryHidden(layer_cat.Id)
                except:
                    pass

                try:
                    ogs = source_view.GetCategoryOverrides(layer_cat.Id)
                    color_text = color_to_text(ogs.ProjectionLineColor)

                    lp_id = ogs.ProjectionLinePatternId
                    if lp_id is not None and lp_id.IntegerValue != -1:
                        lp_el = doc.GetElement(lp_id)
                        if lp_el is not None:
                            line_pattern = lp_el.Name

                    lw = ogs.ProjectionLineWeight
                    if lw is not None and lw > 0:
                        line_weight = lw
                except:
                    pass

            self.layer_rows.Add(LayerRow(layer_cat, layer_cat.Name, is_visible, color_text, line_pattern, line_weight))

    def _on_apply_to_selected(self, sender, args):
        selected_rows = []
        for row in self.layer_grid.SelectedItems:
            selected_rows.append(row)

        if not selected_rows:
            forms.alert('Select one or more layer rows to update.')
            return

        vis_value = self.batch_visible_value.IsChecked
        color_text = (self.batch_color_box.Text or '').strip()
        line_pattern = self.batch_line_pattern_combo.SelectedItem
        line_pattern_text = ''
        if line_pattern is not None:
            line_pattern_text = str(line_pattern).strip()
        line_weight_text = (self.batch_line_weight_box.Text or '').strip()

        apply_visibility = (vis_value is not None)
        apply_color = bool(color_text)
        apply_pattern = bool(line_pattern_text)
        apply_line_weight = bool(line_weight_text)

        has_changes = False
        for row in selected_rows:
            if apply_visibility:
                row.IsVisible = bool(vis_value)
                has_changes = True

            if apply_color:
                row.Color = color_text
                has_changes = True

            if apply_pattern:
                row.LinePattern = line_pattern_text
                has_changes = True

            if apply_line_weight:
                row.LineWeight = line_weight_text
                has_changes = True

        if not has_changes:
            forms.alert('No update values were provided. Enter at least one value in the bulk update fields.')
            return

        try:
            self.layer_grid.Items.Refresh()
        except:
            pass

    def _on_cancel(self, sender, args):
        self.accepted = False
        self.window.DialogResult = False
        self.window.Close()

    def _on_next(self, sender, args):
        if self.selected_dwg_item is None:
            forms.alert('Please select a DWG file.')
            return

        view_names = '\n - '.join([v.Name for v in self.selected_views])
        msg = 'DWG: {0}\n\nViews/View Templates to update:\n - {1}\n\nProceed?'.format(
            self.selected_dwg_item.Name,
            view_names,
        )
        if not forms.alert(msg, yes=True, no=True):
            return

        self.accepted = True
        self.window.DialogResult = True
        self.window.Close()

    def show(self):
        restore_window_position(self.window, 'dwg_layers_edit_layers')
        result = self.window.ShowDialog()
        save_window_position(self.window, 'dwg_layers_edit_layers')
        return bool(result)


def apply_layer_settings(target_views, selected_dwg_item, layer_rows):
    if not target_views or selected_dwg_item is None:
        return

    line_pattern_by_name = {}
    for lp in FilteredElementCollector(doc).OfClass(LinePatternElement):
        line_pattern_by_name[lp.Name] = lp

    t = Transaction(doc, 'Apply DWG Layer Overrides')
    t.Start()
    try:
        for view in target_views:
            for row in layer_rows:
                layer_cat = row.Category
                if layer_cat is None:
                    continue

                try:
                    view.SetCategoryHidden(layer_cat.Id, not bool(row.IsVisible))
                except:
                    logger.debug('Failed to set visibility for layer {0} in view {1}'.format(row.LayerName, view.Name))

                try:
                    ogs = view.GetCategoryOverrides(layer_cat.Id)
                except:
                    ogs = OverrideGraphicSettings()

                color_obj = parse_color_text(row.Color)
                if is_no_override_value(row.Color):
                    try:
                        ogs.SetProjectionLineColor(Color.InvalidColorValue)
                    except:
                        # If InvalidColorValue is not supported in this Revit version,
                        # leave as-is rather than guessing an unsafe API call.
                        pass
                elif color_obj is not None:
                    try:
                        ogs.SetProjectionLineColor(color_obj)
                    except:
                        logger.debug('Failed to set color for layer {0} in view {1}'.format(row.LayerName, view.Name))

                if is_no_override_value(row.LineWeight):
                    try:
                        ogs.SetProjectionLineWeight(-1)
                    except:
                        logger.debug('Failed to set line weight for layer {0} in view {1}'.format(row.LayerName, view.Name))
                else:
                    lw = parse_lineweight(row.LineWeight)
                    if lw is not None:
                        try:
                            ogs.SetProjectionLineWeight(lw)
                        except:
                            logger.debug('Failed to set line weight for layer {0} in view {1}'.format(row.LayerName, view.Name))

                lp_name = str(row.LinePattern).strip() if row.LinePattern is not None else ''
                if is_no_override_value(lp_name):
                    try:
                        ogs.SetProjectionLinePatternId(ElementId.InvalidElementId)
                    except:
                        logger.debug('Failed to clear line pattern for layer {0} in view {1}'.format(row.LayerName, view.Name))
                elif lp_name:
                    lp = line_pattern_by_name.get(lp_name)
                    if lp is not None:
                        try:
                            ogs.SetProjectionLinePatternId(lp.Id)
                        except:
                            logger.debug('Failed to set line pattern for layer {0} in view {1}'.format(row.LayerName, view.Name))

                try:
                    view.SetCategoryOverrides(layer_cat.Id, ogs)
                except:
                    logger.debug('Failed to apply overrides for layer {0} in view {1}'.format(row.LayerName, view.Name))

        t.Commit()
    except Exception as ex:
        t.RollBack()
        raise ex


def main():
    select_dialog = SelectViewTemplateDialog()
    if not select_dialog.show() or not select_dialog.selected_elements:
        return

    dwg_dialog = DwgLayersDialog(select_dialog.selected_elements)
    if not dwg_dialog.dwg_items:
        forms.alert('No imported DWG categories found in this document.', title='DWG Layer Overrides')
        return

    if not dwg_dialog.show() or not dwg_dialog.accepted:
        return

    try:
        apply_layer_settings(
            select_dialog.selected_elements,
            dwg_dialog.selected_dwg_item,
            dwg_dialog.layer_rows,
        )
        forms.alert('DWG layer settings applied.', title='DWG Layer Overrides')
    except Exception as ex:
        forms.alert('Error applying DWG layer settings:\n{0}'.format(ex), title='DWG Layer Overrides')


if __name__ == '__main__':
    main()
