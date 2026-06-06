import sys
import os
import clr

# WPF & UI Assemblies
clr.AddReference('System')
clr.AddReference('System.Windows')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Data')
clr.AddReference('System.Windows.Controls.Data')

# Revit Assemblies
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitNodes') # Optional, if using Dynamo nodes later

from System.Windows import Window, MessageBoxResult, MessageBox
from System.Windows.Markup import XamlReader
from System.Windows.Controls import DataGrid
from System.Collections.ObjectModel import ObservableCollection
from System.Windows.Data import Binding
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.DB.Architecture import *
from Autodesk.Revit.DB.Structure import *
from Autodesk.Revit.DB.Plumbing import *
from Autodesk.Revit.DB.Mechanical import *
from Autodesk.Revit.DB.Electrical import *

# Get current document and UIDocument
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Resolve script path for XAML loading
script_path = os.path.dirname(os.path.abspath(__file__))

# =========================================================================
# DATA CLASSES FOR WPF BINDING (IronPython 2.7 compatible)
# =========================================================================
class LayerData:
    def __init__(self, name, is_visible, color, pattern, weight):
        self.LayerName = name
        self.IsVisible = is_visible
        self.Color = color
        self.LinePattern = pattern
        self.LineWeight = weight

class ViewTemplateData:
    def __init__(self, name, elem):
        self.Name = name
        self.Element = elem

# =========================================================================
# WINDOW 1: SELECT VIEWS / VIEW TEMPLATES
# =========================================================================
xaml1_path = os.path.join(script_path, 'SelectViewTemplate.xaml')
with open(xaml1_path, 'r') as f:
    xaml1 = f.read()
window1 = XamlReader.Parse(xaml1)

filter_combo = window1.FindName('FilterCombo')
search_box = window1.FindName('SearchBox')
selection_list = window1.FindName('SelectionList')
cancel_btn1 = window1.FindName('CancelBtn')
next_btn1 = window1.FindName('NextBtn')

available_elements = []
selected_elements = []

def populate_list():
    global available_elements
    available_elements[:] = []
    selection_list.Items.Clear()
    filter_val = filter_combo.SelectedIndex
    
    collector = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
    for elem in collector:
        is_match = False
        if isinstance(elem, View):
            if filter_val == 0 or filter_val == 1: is_match = True
        elif isinstance(elem, ViewTemplate):
            if filter_val == 0 or filter_val == 2: is_match = True
            
        if is_match:
            available_elements.append(elem)
            selection_list.Items.Add(elem.Name)

def on_search_changed(sender, e):
    text = search_box.Text.lower()
    available_elements[:] = [el for el in available_elements if text in el.Name.lower()]
    selection_list.Items.Clear()
    for elem in available_elements:
        selection_list.Items.Add(elem.Name)

def on_cancel(sender, e):
    sys.exit(0)

def on_next(sender, e):
    global selected_elements
    selected_elements[:] = []
    for item in selection_list.SelectedItems:
        for elem in available_elements:
            if elem.Name == item:
                selected_elements.append(elem)
                break
    
    if not selected_elements:
        MessageBox.Show('Please select at least one View or View Template.', 'Warning', MessageBoxButton.OK, MessageBoxImage.Warning)
        return

    # Load and show Window 2
    load_window2()
    window1.Hide()

# Attach events
filter_combo.SelectionChanged += lambda s, e: populate_list()
search_box.TextChanged += on_search_changed
cancel_btn1.Click += on_cancel
next_btn1.Click += on_next

populate_list()
window1.ShowDialog()

# =========================================================================
# WINDOW 2: SELECT DWG & EDIT LAYERS
# =========================================================================
def load_window2():
    xaml2_path = os.path.join(script_path, 'DWGLayers.xaml')
    with open(xaml2_path, 'r') as f:
        xaml2 = f.read()
    window2 = XamlReader.Parse(xaml2)
    
    dwg_combo = window2.FindName('DwgCombo')
    layer_grid = window2.FindName('LayerGrid')
    cancel_btn2 = window2.FindName('CancelBtn')
    next_btn2 = window2.FindName('NextBtn')
    
    # Collect unique linked DWG names from selected views
    dwg_names = set()
    for elem in selected_elements:
        # Unsure of this API call: FilteredElementCollector(doc, elem.Id) for linked instances
        collector = FilteredElementCollector(doc, elem.Id).OfClass(RevitLinkInstance).ToElements()
        for link in collector:
            if link.Definition:
                dwg_names.add(link.Definition.Name)
    
    dwg_list = sorted(list(dwg_names))
    for name in dwg_list:
        dwg_combo.Items.Add(name)
    
    layer_data_source = ObservableCollection[LayerData]()
    layer_grid.ItemsSource = layer_data_source
    
    current_layers = []
    
    def on_dwg_selected(sender, e):
        layer_data_source.Clear()
        current_layers[:] = []
        selected_dwg = dwg_combo.SelectedItem
        if not selected_dwg: return
        
        # Get first linked instance with this name to inspect options
        target_link = None
        for elem in selected_elements:
            collector = FilteredElementCollector(doc, elem.Id).OfClass(RevitLinkInstance).ToElements()
            for link in collector:
                if link.Definition and link.Definition.Name == selected_dwg:
                    target_link = link
                    break
            if target_link: break
            
        if not target_link: return
        
        # Unsure of this API call: target_link.Options or target_link.GetOptions()
        options = target_link.Options if hasattr(target_link, 'Options') else None
        if not options:
            # Fallback debug: print(dir(target_link))
            MessageBox.Show('Could not retrieve DWG link options. Check Revit API version compatibility.', 'Error', MessageBoxButton.OK, MessageBoxImage.Error)
            return
            
        # Unsure of this API call: options.LayerNames or options.GetLayerNames()
        layer_names = []
        if hasattr(options, 'LayerNames'):
            layer_names = options.LayerNames
        elif hasattr(options, 'GetLayerNames'):
            layer_names = options.GetLayerNames()
            
        for lname in layer_names:
            # Unsure of this API call: options.GetLayerOverride or options.GetLayerState
            is_vis = True
            color = "Default"
            pattern = "Default"
            weight = "Default"
            
            if hasattr(options, 'GetLayerOverride'):
                # Unsure of this API call: options.GetLayerOverride(lname)
                override = options.GetLayerOverride(lname)
                if override:
                    is_vis = override.IsVisible
                    color = str(override.Color) if override.Color else "Default"
                    weight = str(override.LineWeight) if override.LineWeight else "Default"
                    pattern = str(override.LinePattern) if override.LinePattern else "Default"
            
            current_layers.append({
                'name': lname,
                'is_visible': is_vis,
                'color': color,
                'pattern': pattern,
                'weight': weight
            })
            layer_data_source.Add(LayerData(lname, is_vis, color, pattern, weight))
            
    def on_cancel2(sender, e):
        window2.Close()
        
    def on_next2(sender, e):
        if not dwg_combo.SelectedItem:
            MessageBox.Show('Please select a DWG file.', 'Warning', MessageBoxButton.OK, MessageBoxImage.Warning)
            return
            
        # Show confirmation window
        show_confirmation(window2, dwg_combo.SelectedItem, layer_data_source)
        window2.Close()
        
    dwg_combo.SelectionChanged += on_dwg_selected
    cancel_btn2.Click += on_cancel2
    next_btn2.Click += on_next2
    
    window2.ShowDialog()

# =========================================================================
# WINDOW 3: CONFIRMATION & APPLY
# =========================================================================
def show_confirmation(parent_window, dwg_name, layer_source):
    xaml_confirm = """
    <Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
            xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
            Title="Confirm Layer Overrides" Width="400" Height="300" ResizeMode="NoResize">
        <Grid Margin="10">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <TextBlock Grid.Row="0" Text="The following Views/Templates will be updated:" Margin="0,0,0,5"/>
            <ListBox Grid.Row="1" x:Name="ConfirmList" Margin="0,0,0,5"/>
            <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right">
                <Button Content="Cancel" Width="80" Margin="0,0,5,0" x:Name="CancelBtn"/>
                <Button Content="Apply" Width="80" x:Name="ApplyBtn"/>
            </StackPanel>
        </Grid>
    </Window>
    """
    confirm_win = XamlReader.Parse(xaml_confirm)
    confirm_list = confirm_win.FindName('ConfirmList')
    cancel_btn3 = confirm_win.FindName('CancelBtn')
    apply_btn3 = confirm_win.FindName('ApplyBtn')
    
    for elem in selected_elements:
        confirm_list.Items.Add(elem.Name)
        
    def on_cancel3(sender, e):
        confirm_win.Close()
        
    def on_apply3(sender, e):
        confirm_win.Close()
        apply_layer_overrides(dwg_name, layer_source)
        
    cancel_btn3.Click += on_cancel3
    apply_btn3.Click += on_apply3
    confirm_win.ShowDialog()

# =========================================================================
# APPLY LOGIC
# =========================================================================
def apply_layer_overrides(dwg_name, layer_source):
    # Unsure of this API call: Transaction handling
    t = Transaction(doc, 'Apply DWG Layer Overrides')
    try:
        t.Start()
        for elem in selected_elements:
            collector = FilteredElementCollector(doc, elem.Id).OfClass(RevitLinkInstance).ToElements()
            for link in collector:
                if link.Definition and link.Definition.Name == dwg_name:
                    # Unsure of this API call: link.Options or link.GetOptions()
                    options = link.Options if hasattr(link, 'Options') else None
                    if not options: continue
                    
                    for item in layer_source:
                        # Unsure of this API call: options.SetLayerOverride or options.SetLayerState
                        if hasattr(options, 'SetLayerOverride'):
                            # Unsure of this API call: options.SetLayerOverride(lname, color, weight, pattern, visible)
                            options.SetLayerOverride(
                                item.LayerName,
                                item.IsVisible,
                                Color.Parse(item.Color) if item.Color != "Default" else Color(),
                                item.LineWeight,
                                item.LinePattern
                            )
                        elif hasattr(options, 'SetLayerState'):
                            # Unsure of this API call: options.SetLayerState(lname, visible, color, weight, pattern)
                            options.SetLayerState(
                                item.LayerName,
                                item.IsVisible,
                                Color.Parse(item.Color) if item.Color != "Default" else Color(),
                                item.LineWeight,
                                item.LinePattern
                            )
        t.Commit()
        MessageBox.Show('Layer overrides applied successfully.', 'Success', MessageBoxButton.OK, MessageBoxImage.Information)
    except Exception as ex:
        t.RollBack()
        MessageBox.Show('Error applying overrides:\n' + str(ex), 'Error', MessageBoxButton.OK, MessageBoxImage.Error)
