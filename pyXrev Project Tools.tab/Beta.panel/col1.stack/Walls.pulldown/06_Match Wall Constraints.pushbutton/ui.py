# -*- coding: utf-8 -*-
import os

from pyrevit import forms


class MatchConstraintsWindow(forms.WPFWindow):
    def __init__(self, presets, levels, defaults, title):
        xaml_path = os.path.join(os.path.dirname(__file__), 'ui.xaml')
        forms.WPFWindow.__init__(self, xaml_path)

        self._result = None
        self._presets = list(presets)
        self._levels = list(levels)

        self.Title = title

        self.cmbPreset.ItemsSource = self._presets
        self.cmbBaseLevel.ItemsSource = self._levels
        self.cmbTopLevel.ItemsSource = self._levels

        self._apply_defaults(defaults)

        self.chkEnableMapping.Click += self.on_toggle_mapping
        self.chkOverrideBase.Click += self.on_toggle_base
        self.chkOverrideTop.Click += self.on_toggle_top

    @property
    def result(self):
        return self._result

    def _select_combo_text(self, combo, text_value):
        if not text_value:
            return
        for item in combo.ItemsSource:
            if str(item) == str(text_value):
                combo.SelectedItem = item
                return

    def _apply_defaults(self, defaults):
        enable_mapping = bool(defaults.get('enable_mapping', True))
        self.chkEnableMapping.IsChecked = enable_mapping

        self._select_combo_text(self.cmbPreset, defaults.get('preset'))
        if self.cmbPreset.SelectedItem is None and self._presets:
            self.cmbPreset.SelectedItem = self._presets[0]

        self.txtMatchOffset.Text = defaults.get('match_offset', '0') or '0'

        base_override = bool(defaults.get('override_base', False))
        top_override = bool(defaults.get('override_top', False))

        self.chkOverrideBase.IsChecked = base_override
        self.chkOverrideTop.IsChecked = top_override

        self._select_combo_text(self.cmbBaseLevel, defaults.get('base_level'))
        self._select_combo_text(self.cmbTopLevel, defaults.get('top_level'))

        self.cmbPreset.IsEnabled = enable_mapping
        self.txtMatchOffset.IsEnabled = enable_mapping
        self.cmbBaseLevel.IsEnabled = base_override
        self.cmbTopLevel.IsEnabled = top_override

    def _safe_float(self, value, field_name):
        text = (value or '').strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except Exception:
            forms.alert('{} must be a numeric value.'.format(field_name), title='Wall Match: Constraints')
            return None

    def on_toggle_base(self, sender, args):
        self.cmbBaseLevel.IsEnabled = bool(self.chkOverrideBase.IsChecked)

    def on_toggle_top(self, sender, args):
        self.cmbTopLevel.IsEnabled = bool(self.chkOverrideTop.IsChecked)

    def on_toggle_mapping(self, sender, args):
        enabled = bool(self.chkEnableMapping.IsChecked)
        self.cmbPreset.IsEnabled = enabled
        self.txtMatchOffset.IsEnabled = enabled

    def on_start(self, sender, args):
        enable_mapping = bool(self.chkEnableMapping.IsChecked)

        preset = self.cmbPreset.SelectedItem
        if enable_mapping and not preset:
            forms.alert('Please select a mapping preset.', title='Wall Match: Constraints')
            return

        match_offset = self._safe_float(self.txtMatchOffset.Text, 'Match offset')
        if match_offset is None:
            return

        override_base = bool(self.chkOverrideBase.IsChecked)
        override_top = bool(self.chkOverrideTop.IsChecked)

        base_level = self.cmbBaseLevel.SelectedItem if override_base else ''
        top_level = self.cmbTopLevel.SelectedItem if override_top else ''

        if override_base and not base_level:
            forms.alert('Select a base level or disable base override.', title='Wall Match: Constraints')
            return

        if override_top and not top_level:
            forms.alert('Select a top level or disable top override.', title='Wall Match: Constraints')
            return

        if not enable_mapping and not override_base and not override_top:
            forms.alert('Mapping is disabled. Enable at least one override to continue.', title='Wall Match: Constraints')
            return

        self._result = {
            'enable_mapping': enable_mapping,
            'preset': str(preset),
            'match_offset_display': float(match_offset),
            'override_base': override_base,
            'override_top': override_top,
            'base_level': str(base_level) if base_level else '',
            'top_level': str(top_level) if top_level else '',
        }

        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
