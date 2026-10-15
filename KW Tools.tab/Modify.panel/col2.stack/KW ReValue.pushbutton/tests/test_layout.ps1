param([string]$CapturePath)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
$commandDir = Split-Path $PSScriptRoot -Parent
$window = [System.Windows.Markup.XamlReader]::Parse(
    [System.IO.File]::ReadAllText((Join-Path $commandDir 'ReValueUI.xaml')))
$source = [System.IO.File]::ReadAllText((Join-Path $commandDir 'script.py'))
foreach ($match in [regex]::Matches($source, "FindName\('([^']+)'\)")) {
    if ($null -eq $window.FindName($match.Groups[1].Value)) {
        throw "Missing named control: $($match.Groups[1].Value)"
    }
}

$root = $window.Content
$window.Content = $null
$preview = $window.FindName('preview_grid')
$more = $window.FindName('more_settings')
$settingsRow = $window.FindName('settings_row')
$previewRow = $window.FindName('preview_row')
$help = $window.FindName('btn_help')
$apply = $window.FindName('btn_apply')
$cancel = $window.FindName('btn_cancel')
$splitter = $root.Children | Where-Object { $_ -is [System.Windows.Controls.GridSplitter] }
$scroll = $more.Content
$filterSummary = $window.FindName('txt_filter_summary')
$filterStatus = $window.FindName('txt_filter_status')

Add-Type -TypeDefinition @'
public class ReValueLayoutRow {
    public string CurrentName { get; set; }
    public string NewName { get; set; }
    public bool final { get; set; }
    public string tooltip { get; set; }
    public bool HasChanges { get { return CurrentName != NewName; } }
}
'@
$rows = New-Object 'System.Collections.ObjectModel.ObservableCollection[object]'
$rows.Add((New-Object ReValueLayoutRow -Property @{
    CurrentName = 'Door-A'; NewName = 'Entry-A'; tooltip = 'OK'
}))
$rows.Add((New-Object ReValueLayoutRow -Property @{
    CurrentName = 'Door-B'; NewName = 'Door-B'; tooltip = 'OK'
}))
$preview.ItemsSource = $rows

function Measure-Layout([double]$width, [double]$height) {
    $root.Measure([System.Windows.Size]::new($width, $height))
    $root.Arrange([System.Windows.Rect]::new(0, 0, $width, $height))
    $root.UpdateLayout()
    $root.Dispatcher.Invoke([System.Action]{}, [System.Windows.Threading.DispatcherPriority]::Background)
    $root.UpdateLayout()
}

function Assert-Footer {
    $helpPosition = $help.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
    $applyPosition = $apply.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
    $cancelPosition = $cancel.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
    if ([Math]::Abs($helpPosition.Y - $applyPosition.Y) -gt 1 -or
        [Math]::Abs($applyPosition.Y - $cancelPosition.Y) -gt 1) {
        throw 'Footer buttons do not share the same horizontal row.'
    }
    if ($helpPosition.X -gt 10 -or $applyPosition.X -le $root.ActualWidth / 2) {
        throw 'Help must be left justified and Apply/Cancel right justified.'
    }
    if ($cancelPosition.Y + $cancel.ActualHeight -gt $root.ActualHeight) {
        throw 'Footer buttons extend below the dialog.'
    }
}

if ($more.IsExpanded) { throw 'More Settings should start collapsed.' }
foreach ($size in @(@(1010, 880), @(720, 430))) {
    Measure-Layout $size[0] $size[1]
    if ($preview.ActualHeight -lt $root.ActualHeight / 2) {
        throw "Preview occupies less than half the dialog at $size."
    }
    if ($preview.Columns[1].ActualWidth -lt 200 -or $preview.Columns[2].ActualWidth -lt 200) {
        throw 'Value columns must retain usable widths.'
    }
    if ($splitter.Visibility -ne 'Collapsed') {
        throw 'Divider should be hidden when More Settings is collapsed.'
    }
    Assert-Footer
    Write-Output ("PASS: collapsed {0}x{1}, preview height {2:N0} ({3:P0})." -f
        $size[0], $size[1], $preview.ActualHeight,
        ($preview.ActualHeight / $root.ActualHeight))
}

$window.FindName('txt_pattern').Text = '{orig}-{count}'
$window.FindName('txt_counter_start').Text = 'A'
$window.FindName('txt_find').Text = 'Door'
$filterSummary.Text = '3 rules - Custom grouping'
$more.IsExpanded = $true
$settingsRow.Height = [System.Windows.GridLength]::new(2, [System.Windows.GridUnitType]::Star)
$previewRow.Height = [System.Windows.GridLength]::new(3, [System.Windows.GridUnitType]::Star)
foreach ($size in @(@(1010, 880), @(720, 430))) {
    Measure-Layout $size[0] $size[1]
    if ($preview.ActualHeight -lt 120 -or $splitter.Visibility -ne 'Visible') {
        throw 'Expanded layout must retain a usable preview and visible divider.'
    }
    Assert-Footer
}
if ($scroll.ScrollableHeight -le 0) {
    throw 'Advanced settings should scroll independently in the smaller dialog.'
}
$filterStatus.Text = '1 of 2 rows displayed. 1 row(s) excluded: blank/non-numeric or unsupported display format (use decimal project units).'
Measure-Layout 720 430
Assert-Footer
if ($preview.ActualHeight -lt 100) {
    throw 'An active filter warning must retain a usable preview.'
}
$previousPreviewHeight = $preview.ActualHeight
$settingsRow.Height = [System.Windows.GridLength]::new(60)
Measure-Layout 720 430
if ($scroll.ScrollableHeight -le 0 -or $preview.ActualHeight -le $previousPreviewHeight) {
    throw 'Resizing settings must preserve scrolling and give space to the preview.'
}

$more.IsExpanded = $false
$settingsRow.Height = [System.Windows.GridLength]::Auto
$previewRow.Height = [System.Windows.GridLength]::new(3, [System.Windows.GridUnitType]::Star)
Measure-Layout 1010 880
foreach ($entry in @(
    @('txt_pattern', '{orig}-{count}'),
    @('txt_counter_start', 'A'),
    @('txt_find', 'Door'),
    @('txt_filter_summary', '3 rules - Custom grouping')
)) {
    if ($window.FindName($entry[0]).Text -ne $entry[1]) {
        throw "Collapsing settings reset $($entry[0])."
    }
}
Write-Output 'PASS: expanded layout, independent scrolling, divider resizing, preserved inputs and footer alignment.'

$editor = [System.Windows.Markup.XamlReader]::Parse(
    [System.IO.File]::ReadAllText((Join-Path $commandDir 'FilterEditor.xaml')))
$editorSource = [System.IO.File]::ReadAllText((Join-Path $commandDir 'filter_editor.py'))
foreach ($match in [regex]::Matches($editorSource, "FindName\('([^']+)'\)")) {
    if ($null -eq $editor.FindName($match.Groups[1].Value)) {
        throw "Missing filter editor control: $($match.Groups[1].Value)"
    }
}
Write-Output 'PASS: separate filter editor XAML and all named controls resolve.'

$categoryWindow = [System.Windows.Markup.XamlReader]::Parse(
    [System.IO.File]::ReadAllText((Join-Path $commandDir 'CategorySelection.xaml')))
foreach ($name in @('scope_view', 'scope_project', 'category_list', 'family_list',
        'search_categories', 'search_families', 'all_families', 'selected_families',
        'family_heading', 'family_modes', 'selection_summary', 'selection_status',
        'use_selection', 'cancel_selection')) {
    if ($null -eq $categoryWindow.FindName($name)) {
        throw "Missing category selector control: $name"
    }
}
$categoryRoot = $categoryWindow.Content
$categoryWindow.Content = $null
foreach ($size in @(@(900,650), @(720,460))) {
    $categoryRoot.Measure([System.Windows.Size]::new($size[0], $size[1]))
    $categoryRoot.Arrange([System.Windows.Rect]::new(0, 0, $size[0], $size[1]))
    $categoryRoot.UpdateLayout()
    $list = $categoryWindow.FindName('category_list')
    $families = $categoryWindow.FindName('family_list')
    if ($list.ActualHeight -lt 160 -or $families.ActualHeight -lt 140) {
        throw "Category/family lists are too small at $size"
    }
}
Write-Output 'PASS: category picker XAML, named controls and list space at default/minimum size.'

if ($CapturePath) {
    $root.Background = [System.Windows.Media.Brushes]::WhiteSmoke
    Measure-Layout 1010 880
    $bitmap = [System.Windows.Media.Imaging.RenderTargetBitmap]::new(
        1010, 880, 96, 96, [System.Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($root)
    $encoder = [System.Windows.Media.Imaging.PngBitmapEncoder]::new()
    $encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $stream = [System.IO.File]::Create($CapturePath)
    try { $encoder.Save($stream) } finally { $stream.Dispose() }
}
