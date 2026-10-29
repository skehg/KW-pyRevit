param([string]$CapturePath)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
$commandDir = Split-Path $PSScriptRoot -Parent
function Load-Window([string]$name) {
    $path = Join-Path $commandDir $name
    $context = [System.Windows.Markup.ParserContext]::new()
    $context.BaseUri = [System.Uri]::new($path)
    return [System.Windows.Markup.XamlReader]::Parse(
        [System.IO.File]::ReadAllText($path), $context)
}
$window = Load-Window 'ReValueUI.xaml'

function Assert-SwitchLabels($switch, [string]$leftText, [string]$rightText) {
    $null = $switch.ApplyTemplate()
    $left = $switch.Template.FindName('switch_left_label', $switch)
    $right = $switch.Template.FindName('switch_right_label', $switch)
    $leftWeight = if ($switch.IsChecked) { 'Normal' } else { 'Bold' }
    $rightWeight = if ($switch.IsChecked) { 'Bold' } else { 'Normal' }
    if ($left.Text -ne $leftText -or $right.Text -ne $rightText -or
        $left.FontWeight.ToString() -ne $leftWeight -or
        $right.FontWeight.ToString() -ne $rightWeight) {
        throw 'Switches must show both static labels with only the active option bold.'
    }
}

function Assert-SwitchSpacing($switch) {
    $border = $switch.Template.FindName('switch_border', $switch)
    $track = $switch.Template.FindName('switch_track', $switch)
    $left = $switch.Template.FindName('switch_left_label', $switch)
    $right = $switch.Template.FindName('switch_right_label', $switch)
    $trackX = $track.TranslatePoint([System.Windows.Point]::new(0, 0), $switch).X
    $leftGap = $trackX - $left.TranslatePoint(
        [System.Windows.Point]::new($left.ActualWidth, 0), $switch).X
    $rightGap = $right.TranslatePoint(
        [System.Windows.Point]::new(0, 0), $switch).X - $trackX - $track.ActualWidth
    if ([Math]::Abs($leftGap - 8) -gt 0.1 -or [Math]::Abs($rightGap - 8) -gt 0.1) {
        throw 'Both switch labels must sit 8 px from the track.'
    }
    foreach ($label in @($left, $right)) {
        if ($label.ActualWidth -le 0 -or
            $label.ActualWidth + 0.1 -lt $label.DesiredSize.Width - $label.Margin.Left - $label.Margin.Right -or
            $label.TranslatePoint([System.Windows.Point]::new($label.ActualWidth, 0), $switch).X -gt
                $switch.ActualWidth + 0.1) {
            throw 'Switch labels must remain fully visible in both states.'
        }
    }
    $leftPadding = $track.TranslatePoint([System.Windows.Point]::new(0, 0), $border).X
    $rightPadding = $border.ActualWidth - $leftPadding - $track.ActualWidth
    if ([Math]::Abs($leftPadding - $rightPadding) -gt 0.1) {
        throw 'The switch hover highlight must retain symmetric padding.'
    }
}

function Assert-RaisedButton($button) {
    $initiallyEnabled = $button.IsEnabled
    $button.IsEnabled = $true
    $null = $button.ApplyTemplate()
    $face = $button.Template.FindName('button_face', $button)
    $highlight = $button.Template.FindName('button_highlight', $button)
    $surface = $button.Template.FindName('button_surface', $button)
    if ($null -eq $face -or $face.CornerRadius.TopLeft -ne 6 -or
        $face.Background -isnot [System.Windows.Media.LinearGradientBrush] -or
        $face.Effect -isnot [System.Windows.Media.Effects.DropShadowEffect] -or
        $face.Effect.ShadowDepth -gt 1 -or $highlight.IsHitTestVisible) {
        throw 'Action buttons must have rounded, raised faces and non-interactive highlights.'
    }
    $button.IsEnabled = $false
    if ($null -ne $face.Effect -or $surface.Opacity -ne 0.5) {
        throw 'Disabled action buttons must be faded and flat.'
    }
    $button.IsEnabled = $true
    if ($null -eq $face.Effect -or $surface.Opacity -ne 1) {
        throw 'Re-enabled buttons must restore their raised appearance.'
    }
    $peer = [System.Windows.Automation.Peers.UIElementAutomationPeer]::CreatePeerForElement($button)
    if ($null -eq $peer.GetPattern([System.Windows.Automation.Peers.PatternInterface]::Invoke)) {
        throw 'Styled buttons must retain accessible invocation.'
    }
    $button.IsEnabled = $initiallyEnabled
}
foreach ($name in @('btn_clear_sort', 'btn_add_token', 'btn_clear_filters',
        'btn_edit_filters', 'btn_help', 'btn_apply', 'btn_close')) {
    Assert-RaisedButton $window.FindName($name)
}
Write-Output 'PASS: rounded raised action buttons, disabled-state restoration and accessible invocation.'
$source = [System.IO.File]::ReadAllText((Join-Path $commandDir 'script.py'))
foreach ($match in [regex]::Matches($source, "FindName\('([^']+)'\)")) {
    if ($null -eq $window.FindName($match.Groups[1].Value)) {
        throw "Missing named control: $($match.Groups[1].Value)"
    }
}

$root = $window.Content
$finalCase = $window.FindName('combo_final_case')
$caseLabels = @('None', 'UPPER', 'lower', 'Title Case', 'Sentence case')
$caseValues = @('None', 'upper', 'lower', 'title', 'sentence')
for ($i = 0; $i -lt $caseLabels.Count; $i++) {
    if ($finalCase.Items[$i].Content -ne $caseLabels[$i] -or
        $finalCase.Items[$i].Tag -ne $caseValues[$i]) {
        throw 'Final Case options must demonstrate the case without changing their internal values.'
    }
}
if ($window.FindName('combo_editor_mode').SelectedIndex -ne 0 -or
    $window.FindName('token_editor_panel').Visibility -ne 'Visible') {
    throw 'The token interface must be the default.'
}
Write-Output 'PASS: token interface is the default.'
$caret = $window.FindName('token_insertion_caret')
$bar = $window.FindName('token_bar')
if ($caret.Visibility -ne 'Collapsed' -or
    $caret.Parent -isnot [System.Windows.Controls.Canvas] -or
    $caret.Parent.IsHitTestVisible -or -not $caret.Parent.ClipToBounds -or
    $caret.Parent.Parent -ne $bar.Parent) {
    throw 'The insertion caret must be a hidden, non-interactive overlay beside the token bar.'
}
Write-Output 'PASS: insertion caret overlay does not intercept drag events or occupy token space.'
foreach ($label in @('Start', 'End', 'Following')) {
    $direction = New-Object System.Windows.Controls.RadioButton
    $direction.Style = $window.FindResource('TokenDirectionStyle')
    $direction.Content = $label
    $direction.Measure([System.Windows.Size]::new(300, 100))
    if ($direction.DesiredSize.Width -gt 85 -or $direction.DesiredSize.Height -gt 28 -or
        $direction.FontSize -lt 12) {
        throw 'Direction toggles must remain compact with legible labels.'
    }
    $null = $direction.ApplyTemplate()
    $segment = $direction.Template.FindName('segment', $direction)
    $direction.IsChecked = $true
    if ($segment.Background.Color.ToString() -ne '#FF38BDF8') {
        throw 'Checked direction toggles must be visibly selected.'
    }
}
Write-Output 'PASS: compact labelled direction toggles and checked appearance.'
$chip = New-Object System.Windows.Controls.Button
$chip.Style = $window.FindResource('TokenPillStyle')
$chip.Padding = [System.Windows.Thickness]::new(9, 1, 9, 1)
$chip.Content = 'Token 1: Door'
$null = $chip.ApplyTemplate()
$pill = $chip.Template.FindName('pill', $chip)
$chip.Measure([System.Windows.Size]::new(300, 100))
if ($pill.CornerRadius.TopLeft -ne 11 -or
    $chip.Background.GradientStops[1].Color.ToString() -ne '#FF38BDF8' -or
    $chip.DesiredSize.Height -gt 24) {
    throw 'Tokens must use compact sky-blue pill styling.'
}
Write-Output 'PASS: compact sky-blue pill template and height.'
foreach ($width in @(60, 140, 280)) {
    $chip.Arrange([System.Windows.Rect]::new(0, 0, $width, 22))
    $chip.UpdateLayout()
    if ($pill.ActualHeight -ne 22 -or
        $pill.CornerRadius.TopLeft * 2 -ne $pill.ActualHeight) {
        throw 'Pill end radius must equal half its height at every width.'
    }
}
Write-Output 'PASS: semicircular pill ends at narrow and wide token widths.'
$highlight = $chip.Template.FindName('pill_highlight', $chip)
if ($chip.Background -isnot [System.Windows.Media.LinearGradientBrush] -or
    $pill.Effect -isnot [System.Windows.Media.Effects.DropShadowEffect] -or
    $pill.Effect.ShadowDepth -gt 1 -or $highlight.IsHitTestVisible) {
    throw 'Raised tokens require a gradient, restrained shadow and non-interactive highlight.'
}
$chip.IsEnabled = $false
if ($null -ne $pill.Effect) { throw 'Disabled tokens must not cast a raised shadow.' }
$chip.IsEnabled = $true
if ($null -eq $pill.Effect) { throw 'Enabled tokens must restore their raised shadow.' }
Write-Output 'PASS: raised token gradient, highlight, shadow and disabled-state restoration.'
# Existing compact-layout checks cover Advanced Pattern mode.
$window.FindName('token_editor_panel').Visibility = 'Collapsed'
$window.Content = $null
$preview = $window.FindName('preview_grid')
$more = $window.FindName('more_settings')
$settingsRow = $window.FindName('settings_row')
$previewRow = $window.FindName('preview_row')
$help = $window.FindName('btn_help')
$apply = $window.FindName('btn_apply')
if (-not [System.Windows.Controls.ToolTipService]::GetShowOnDisabled($apply)) {
    throw 'Apply tooltip must be available while the button is disabled.'
}
$applyTooltip = $apply.FindResource('NewValueFilterToolTip')
if ($applyTooltip.Inlines.Count -ne 3 -or
    $applyTooltip.Inlines.FirstInline.NextInline.Text -ne 'New Value' -or
    $applyTooltip.Inlines.FirstInline.NextInline.FontWeight -ne [System.Windows.FontWeights]::Bold -or
    ([System.Windows.Documents.TextRange]::new(
        $applyTooltip.ContentStart, $applyTooltip.ContentEnd)).Text -ne 'Clear New Value filter to apply') {
    throw 'Apply tooltip must contain the short reminder with New Value in bold.'
}
$close = $window.FindName('btn_close')
if ($close.Content -ne 'Close') { throw 'The main dialog exit button must say Close.' }
$useOrig = $window.FindName('btn_use_orig')
if ($useOrig -isnot [System.Windows.Controls.Primitives.ToggleButton]) {
    throw 'The original-pattern shortcut must be a toggle.'
}
if ($useOrig.IsChecked) { throw 'The original-pattern toggle must start off.' }
if ($useOrig.Content -ne 'Pattern') { throw 'The switch must show Pattern when off.' }
$null = $useOrig.ApplyTemplate()
$track = $useOrig.Template.FindName('switch_track', $useOrig)
$thumb = $useOrig.Template.FindName('switch_thumb', $useOrig)
if ($null -eq $track -or $null -eq $thumb) { throw 'The switch track and thumb are missing.' }
if ($thumb.HorizontalAlignment -ne 'Left' -or $track.Background.Color.ToString() -ne '#FF777777') {
    throw 'The off switch must have a grey track and left-aligned thumb.'
}
$useOrig.IsChecked = $true
Assert-SwitchLabels $useOrig 'Pattern' 'Source'
if ($thumb.HorizontalAlignment -ne 'Right' -or $track.Background.Color.ToString() -ne '#FF287D46') {
    throw 'The on switch must have a green track and right-aligned thumb.'
}
if ($useOrig.ToolTip -notlike 'Using Source*') { throw 'The on tooltip must describe the current Source state.' }
$useOrig.IsChecked = $false
if ($useOrig.Content -ne 'Pattern') { throw 'The switch must return to showing Pattern when off.' }
if ($thumb.HorizontalAlignment -ne 'Left') { throw 'The thumb must return to the left when off.' }
if ($useOrig.ToolTip -notlike 'Using your pattern*') { throw 'The off tooltip must describe the current Pattern state.' }
$switchPeer = [System.Windows.Automation.Peers.UIElementAutomationPeer]::CreatePeerForElement($useOrig)
$toggleProvider = $switchPeer.GetPattern([System.Windows.Automation.Peers.PatternInterface]::Toggle)
$toggleProvider.Toggle()
if (-not $useOrig.IsChecked) {
    throw 'The switch must support accessible toggle actions.'
}
$toggleProvider.Toggle()
Assert-SwitchLabels $useOrig 'Pattern' 'Source'
Write-Output 'PASS: switch appearance, current-state labels, tooltips and accessible toggling.'
foreach ($spec in @(@('btn_mode', 'Type', 'Instance'), @('btn_sort_direction', 'Asc', 'Desc'))) {
    $switch = $window.FindName($spec[0])
    if ($switch -isnot [System.Windows.Controls.Primitives.ToggleButton]) {
        throw "$($spec[0]) must be a toggle switch."
    }
    $null = $switch.ApplyTemplate()
    $switchTrack = $switch.Template.FindName('switch_track', $switch)
    $switchThumb = $switch.Template.FindName('switch_thumb', $switch)
    $offColour = $switchTrack.Background.Color.ToString()
    Assert-SwitchLabels $switch $spec[1] $spec[2]
    if ($switch.IsChecked -or $switch.Content -ne $spec[1] -or $switchThumb.HorizontalAlignment -ne 'Left') {
        throw "$($spec[0]) has an incorrect initial state."
    }
    $peer = [System.Windows.Automation.Peers.UIElementAutomationPeer]::CreatePeerForElement($switch)
    $provider = $peer.GetPattern([System.Windows.Automation.Peers.PatternInterface]::Toggle)
    $provider.Toggle()
    Assert-SwitchLabels $switch $spec[1] $spec[2]
    if (-not $switch.IsChecked -or
        $switchThumb.HorizontalAlignment -ne 'Right' -or
        $switchTrack.Background.Color.ToString() -ne $offColour) {
        throw "$($spec[0]) must move its thumb and change its state label without changing colour."
    }
    $provider.Toggle()
    Assert-SwitchLabels $switch $spec[1] $spec[2]
}
Write-Output 'PASS: Mode and direction switches have current-state labels, neutral colours and accessible toggling.'
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
    $closePosition = $close.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
    if ([Math]::Abs($helpPosition.Y - $applyPosition.Y) -gt 1 -or
        [Math]::Abs($applyPosition.Y - $closePosition.Y) -gt 1) {
        throw 'Footer buttons do not share the same horizontal row.'
    }
    if ($helpPosition.X -gt 10 -or $applyPosition.X -le $root.ActualWidth / 2) {
        throw 'Help must be left justified and Apply/Close right justified.'
    }
    if ($closePosition.Y + $close.ActualHeight -gt $root.ActualHeight + 0.5) {
        throw 'Footer buttons extend below the dialog.'
    }
}

if ($more.IsExpanded) { throw 'More Settings should start collapsed.' }
$sortColumn = $window.FindName('col_sort_value')
if ($sortColumn.Visibility -ne 'Collapsed' -or -not $window.FindName('col_current').CanUserSort -or
    $window.FindName('col_new').CanUserSort -or $preview.Columns[0].CanUserSort) {
    throw 'Only Current Value may sort from its header; the Sort column starts hidden.'
}
$currentSortHint = $window.FindName('current_sort_hint')
$currentHeaderHint = $window.FindName('current_header_sort_hint')
if ($null -eq $currentSortHint -or $currentSortHint.Text -ne (' ' + [char]0x2195) -or
    $currentSortHint.Visibility -ne 'Visible' -or
    $currentHeaderHint.ToolTip -ne 'Click to sort ascending.') {
    throw 'The unsorted Current Value header must show a muted sort cue and an explanatory tooltip.'
}
Write-Output 'PASS: header sorting limited to Current Value; Sort column hidden by default.'
foreach ($size in @(@(1010, 880), @(720, 430), @(1440, 880), @(1920, 880))) {
    Measure-Layout $size[0] $size[1]
    foreach ($checked in @($true, $false)) {
        foreach ($spec in @(@('btn_mode', 'Type', 'Instance'),
                @('btn_sort_direction', 'Asc', 'Desc'), @('btn_use_orig', 'Pattern', 'Source'))) {
            $switch = $window.FindName($spec[0])
            $switch.IsChecked = $checked
            Measure-Layout $size[0] $size[1]
            Assert-SwitchLabels $switch $spec[1] $spec[2]
            Assert-SwitchSpacing $switch
            $position = $switch.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            if ($position.X + $switch.ActualWidth -gt $root.ActualWidth + 0.1) {
                throw 'Both toggle states must fit within the main dialog.'
            }
            $clearSort = $window.FindName('btn_clear_sort')
            $finalCase = $window.FindName('combo_final_case')
            $clearPosition = $clearSort.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            $casePosition = $finalCase.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            $direction = $window.FindName('btn_sort_direction')
            $directionPosition = $direction.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            if ([Math]::Abs($clearPosition.X - $casePosition.X) -gt 0.1 -or
                [Math]::Abs($clearPosition.X - $directionPosition.X - $direction.ActualWidth - 8) -gt 0.1) {
                throw "Clear sort must align with Final Case without overlapping direction (size $size, clear $($clearPosition.X), case $($casePosition.X), direction right $($directionPosition.X + $direction.ActualWidth))."
            }
            $desc = $direction.Template.FindName('switch_right_label', $direction)
            $track = $direction.Template.FindName('switch_track', $direction)
            $descPosition = $desc.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            $trackPosition = $track.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            $beforeDesc = $descPosition.X - $trackPosition.X - $track.ActualWidth
            $afterDesc = $clearPosition.X - $descPosition.X - $desc.ActualWidth
            if ([Math]::Abs($beforeDesc - $afterDesc) -gt 0.1) {
                throw "Desc must have equal gaps to the switch track and the clear-sort button (before $beforeDesc, after $afterDesc)."
            }
            $sortBy = $window.FindName('combo_sort_by')
            $sortPosition = $sortBy.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
            if ([Math]::Abs($directionPosition.X - $sortPosition.X - $sortBy.ActualWidth - 5) -gt 0.1) {
                throw 'The sort dropdown and direction toggle must stay grouped beside Clear sort as the dialog widens.'
            }
        }
    }
    if ($preview.ActualHeight -lt $root.ActualHeight / 2) {
        throw "Preview occupies less than half the dialog at $size."
    }
    $currentColumn = $window.FindName('col_current')
    $newColumn = $window.FindName('col_new')
    if ($currentColumn.ActualWidth -lt 200 -or $newColumn.ActualWidth -lt 200) {
        throw 'Value columns must retain usable widths.'
    }
    $sortBy = $window.FindName('combo_sort_by')
    $sortDirection = $window.FindName('btn_sort_direction')
    foreach ($control in @($sortBy, $sortDirection, $window.FindName('btn_mode'), $window.FindName('btn_clear_sort'))) {
        $position = $control.TranslatePoint([System.Windows.Point]::new(0, 0), $root)
        if ($control.ActualWidth -le 0 -or
            $position.X + $control.ActualWidth -gt $root.ActualWidth + 0.5) {
            throw "Sort controls must stay visible within the dialog at $size."
        }
    }
    if ($sortBy.ActualWidth -lt 100 -or $window.FindName('combo_orig_param').ActualWidth -lt 100) {
        throw "Source and Sort by dropdowns must remain usable at $size."
    }
    if ($splitter.Visibility -ne 'Collapsed') {
        throw 'Divider should be hidden when More Settings is collapsed.'
    }
    Assert-Footer
    $pattern = $window.FindName('txt_pattern')
    if ($pattern.ActualWidth -lt 100 -or
        $useOrig.ActualWidth + $useOrig.Margin.Left + $useOrig.Margin.Right + 0.1 -lt $useOrig.DesiredSize.Width) {
        throw 'Pattern and the original-pattern shortcut must remain usable.'
    }
    Write-Output ("PASS: collapsed {0}x{1}, preview height {2:N0} ({3:P0})." -f
        $size[0], $size[1], $preview.ActualHeight,
        ($preview.ActualHeight / $root.ActualHeight))
}
$sortColumn.Visibility = 'Visible'
Measure-Layout 720 430
$currentWidth = $window.FindName('col_current').ActualWidth
$newWidth = $window.FindName('col_new').ActualWidth
if ($currentWidth -lt 120 -or $newWidth -lt 120) {
    throw 'Value columns must stay usable while the Sort column is shown.'
}
$sortColumn.Visibility = 'Collapsed'
Write-Output ('PASS: Sort column fits at 720 (Current {0:N0}, New {1:N0}).' -f
    $currentWidth, $newWidth)

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

$editor = Load-Window 'FilterEditor.xaml'
foreach ($name in @('clear_rules', 'use_filters', 'cancel_editor')) {
    Assert-RaisedButton $editor.FindName($name)
}
$dynamicButton = [System.Windows.Controls.Button]::new()
$editor.FindName('rules_panel').Children.Add($dynamicButton) | Out-Null
Assert-RaisedButton $dynamicButton
$editorSource = [System.IO.File]::ReadAllText((Join-Path $commandDir 'filter_editor.py'))
foreach ($match in [regex]::Matches($editorSource, "FindName\('([^']+)'\)")) {
    if ($null -eq $editor.FindName($match.Groups[1].Value)) {
        throw "Missing filter editor control: $($match.Groups[1].Value)"
    }
}
Write-Output 'PASS: separate filter editor XAML and all named controls resolve.'

$categoryWindow = Load-Window 'CategorySelection.xaml'
foreach ($name in @('cancel_selection', 'use_selection')) {
    $button = $categoryWindow.FindName($name)
    $enabled = $button.IsEnabled
    $button.IsEnabled = $true
    Assert-RaisedButton $button
    $button.IsEnabled = $enabled
}
foreach ($name in @('scope_toggle', 'category_list', 'family_list',
        'search_categories', 'search_families', 'family_toggle',
        'family_heading', 'family_modes', 'selection_summary', 'selection_status',
        'use_selection', 'cancel_selection')) {
    if ($null -eq $categoryWindow.FindName($name)) {
        throw "Missing category selector control: $name"
    }
}
$scopeViewLabel = $categoryWindow.FindName('scope_view_label')
$scopeProjectLabel = $categoryWindow.FindName('scope_project_label')
$scopeSwitch = $categoryWindow.FindName('scope_toggle')
if ($scopeViewLabel.Text -ne 'Current View' -or
    $scopeViewLabel.Parent -ne $scopeSwitch.Parent -or
    $scopeViewLabel.Parent.Children.IndexOf($scopeViewLabel) -ge
        $scopeSwitch.Parent.Children.IndexOf($scopeSwitch)) {
    throw 'The static Current View label must sit to the left of the scope switch.'
}
if ($scopeProjectLabel.Text -ne 'Entire Project' -or
    $scopeProjectLabel.Parent -ne $scopeSwitch.Parent -or
    $scopeProjectLabel.Parent.Children.IndexOf($scopeProjectLabel) -le
        $scopeSwitch.Parent.Children.IndexOf($scopeSwitch)) {
    throw 'The static Entire Project label must sit outside and to the right of the scope switch.'
}
foreach ($spec in @(@('scope_toggle', '', ''),
        @('family_toggle', 'All families', 'Selected families only'))) {
    $switch = $categoryWindow.FindName($spec[0])
    if ($switch -isnot [System.Windows.Controls.Primitives.ToggleButton]) {
        throw "$($spec[0]) must be a toggle switch."
    }
    $null = $switch.ApplyTemplate()
    $track = $switch.Template.FindName('switch_track', $switch)
    $thumb = $switch.Template.FindName('switch_thumb', $switch)
    if ($switch.IsChecked -or $switch.Content -ne $spec[1] -or $thumb.HorizontalAlignment -ne 'Left') {
        throw "$($spec[0]) must initially report its default state."
    }
    $colour = $track.Background.Color.ToString()
    $peer = [System.Windows.Automation.Peers.UIElementAutomationPeer]::CreatePeerForElement($switch)
    $provider = $peer.GetPattern([System.Windows.Automation.Peers.PatternInterface]::Toggle)
    $provider.Toggle()
    if ($spec[0] -eq 'family_toggle') {
        Assert-SwitchLabels $switch $spec[1] $spec[2]
    }
    if (-not $switch.IsChecked -or
        $thumb.HorizontalAlignment -ne 'Right' -or
        $track.Background.Color.ToString() -ne $colour -or
        $switch.ToolTip -notlike '*Click*') {
        throw "$($spec[0]) must report its checked state with a neutral track and action tooltip."
    }
    $switch.IsEnabled = $false
    if ($switch.Template.FindName('switch_border', $switch).Opacity -ne 0.5) {
        throw "$($spec[0]) must appear disabled."
    }
    $switch.IsEnabled = $true
    $provider.Toggle()
    if ($spec[0] -eq 'family_toggle') {
        Assert-SwitchLabels $switch $spec[1] $spec[2]
    }
}
if ($scopeViewLabel.Text -ne 'Current View' -or $scopeProjectLabel.Text -ne 'Entire Project' -or
    $scopeSwitch.Content -ne '' -or
    $scopeSwitch.ToolTip -ne 'Scope: Current View. Click to switch to Entire Project.') {
    throw 'Both scope labels must stay visible and unchanged after toggling back.'
}
if (-not [System.Windows.Controls.ToolTipService]::GetShowOnDisabled(
        $categoryWindow.FindName('scope_toggle'))) {
    throw 'The unavailable Current View explanation must remain accessible on the disabled scope switch.'
}
Write-Output 'PASS: static scope labels on either side, current-state family label, neutral styling and accessible toggling.'
foreach ($checked in @($false, $true, $false)) {
    $scopeSwitch.IsChecked = $checked
    $scopeSwitch.Measure([System.Windows.Size]::new(300, 100))
    $scopeSwitch.Arrange([System.Windows.Rect]::new(
        0, 0, $scopeSwitch.DesiredSize.Width, $scopeSwitch.DesiredSize.Height))
    $scopeSwitch.UpdateLayout()
    $viewWeight = if ($checked) { 'Normal' } else { 'Bold' }
    $projectWeight = if ($checked) { 'Bold' } else { 'Normal' }
    if ($scopeViewLabel.FontWeight.ToString() -ne $viewWeight -or
        $scopeProjectLabel.FontWeight.ToString() -ne $projectWeight) {
        throw 'Only the active Scope label must be bold, including after toggling back.'
    }
    $border = $scopeSwitch.Template.FindName('switch_border', $scopeSwitch)
    $track = $scopeSwitch.Template.FindName('switch_track', $scopeSwitch)
    $left = $track.TranslatePoint([System.Windows.Point]::new(0, 0), $border).X
    $right = $border.ActualWidth - $left - $track.ActualWidth
    if ($track.ActualWidth -ne 36 -or [Math]::Abs($left - $right) -gt 0.1) {
        throw 'Scope switch hover padding must be equal on both sides in either state.'
    }
}
$scopeSwitch.IsChecked = $false
$scopeRow = $scopeSwitch.Parent
$scopeRow.Measure([System.Windows.Size]::new(600, 100))
$scopeRow.Arrange([System.Windows.Rect]::new(0, 0, $scopeRow.DesiredSize.Width, $scopeRow.DesiredSize.Height))
$scopeRow.UpdateLayout()
$track = $scopeSwitch.Template.FindName('switch_track', $scopeSwitch)
$trackLeft = $track.TranslatePoint([System.Windows.Point]::new(0, 0), $scopeRow).X
$viewRight = $scopeViewLabel.TranslatePoint([System.Windows.Point]::new(0, 0), $scopeRow).X +
    $scopeViewLabel.ActualWidth
$projectLeft = $scopeProjectLabel.TranslatePoint([System.Windows.Point]::new(0, 0), $scopeRow).X
$leftGap = $trackLeft - $viewRight
$rightGap = $projectLeft - ($trackLeft + $track.ActualWidth)
if ($leftGap -le 0 -or [Math]::Abs($leftGap - $rightGap) -gt 0.1) {
    throw "Scope labels must be equally spaced from the switch track (left $leftGap, right $rightGap)."
}
Write-Output "PASS: Scope switch highlight is symmetrical and labels sit $leftGap px from the track on both sides."
$categoryRoot = $categoryWindow.Content
$categoryWindow.Content = $null
foreach ($size in @(@(900,650), @(720,460))) {
    $categoryRoot.Measure([System.Windows.Size]::new($size[0], $size[1]))
    $categoryRoot.Arrange([System.Windows.Rect]::new(0, 0, $size[0], $size[1]))
    $categoryRoot.UpdateLayout()
    $familySwitch = $categoryWindow.FindName('family_toggle')
    foreach ($checked in @($true, $false)) {
        $familySwitch.IsChecked = $checked
        $categoryRoot.Measure([System.Windows.Size]::new($size[0], $size[1]))
        $categoryRoot.Arrange([System.Windows.Rect]::new(0, 0, $size[0], $size[1]))
        $categoryRoot.UpdateLayout()
        Assert-SwitchLabels $familySwitch 'All families' 'Selected families only'
        Assert-SwitchSpacing $familySwitch
        $position = $familySwitch.TranslatePoint([System.Windows.Point]::new(0, 0), $categoryRoot)
        if ($position.X + $familySwitch.ActualWidth -gt $categoryRoot.ActualWidth + 0.1) {
            throw 'Both family options must fit within the category dialog.'
        }
    }
    $list = $categoryWindow.FindName('category_list')
    $families = $categoryWindow.FindName('family_list')
    if ($list.ActualHeight -lt 160 -or $families.ActualHeight -lt 140) {
        throw "Category/family lists are too small at $size"
    }
}
Write-Output 'PASS: category picker XAML, named controls and list space at default/minimum size.'

if ($CapturePath) {
    $root.Resources.MergedDictionaries.Add($window.Resources)
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
