# -*- coding: utf-8 -*-
import os

from pyrevit import forms


class ShapeOffsetWindow(forms.WPFWindow):
    def __init__(self, title, unit_label, defaults):
        xaml_path = os.path.join(os.path.dirname(__file__), 'ui.xaml')
        forms.WPFWindow.__init__(self, xaml_path)

        self.Title = '{} | Options'.format(title)
        self._result = None

        self.txtOffsetLabel.Text = 'Offset value ({})'.format(unit_label)

        self._set_combo_items(self.cmbRegion, [
            'Boundary',
            'Internal',
            'Both',
        ])
        self._set_combo_items(self.cmbMode, [
            'Add To Existing Values',
            'Reset And Equalize To Value',
        ])

        self._select_combo_value(self.cmbRegion, defaults.get('region', 'Both'))
        self._select_combo_value(self.cmbMode, defaults.get('mode', 'Add To Existing Values'))
        self.txtOffset.Text = str(defaults.get('offset_text', '0'))

    @property
    def result(self):
        return self._result

    def _set_combo_items(self, combo, values):
        combo.Items.Clear()
        for value in values:
            combo.Items.Add(value)

    def _select_combo_value(self, combo, value):
        try:
            idx = combo.Items.IndexOf(value)
            if idx >= 0:
                combo.SelectedIndex = idx
                return
        except Exception:
            pass

        if combo.Items.Count > 0:
            combo.SelectedIndex = 0

    def _get_selected_text(self, combo, fallback):
        try:
            selected = combo.SelectedItem
            if selected is not None:
                return str(selected)
        except Exception:
            pass
        return fallback

    def on_run(self, sender, args):
        offset_text = str(self.txtOffset.Text or '').strip()
        if not offset_text:
            forms.alert('Offset value must be numeric.', title='Shape Offset')
            return

        try:
            float(offset_text)
        except Exception:
            forms.alert('Offset value must be numeric.', title='Shape Offset')
            return

        self._result = {
            'region': self._get_selected_text(self.cmbRegion, 'Both'),
            'mode': self._get_selected_text(self.cmbMode, 'Add To Existing Values'),
            'offset_text': offset_text,
        }
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
