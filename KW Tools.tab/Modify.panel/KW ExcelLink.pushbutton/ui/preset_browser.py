# -*- coding: utf-8 -*-
"""Searchable folder tree for the Enterprise and User preset libraries."""

import os

from pyrevit import forms

from core import presets


def library_tree(items, query=""):
    query = query.strip().lower()
    roots = []
    for source in (presets.SOURCE_ENTERPRISE, presets.SOURCE_USER):
        root = {"label": source.title(), "children": [], "item": None}
        folders = {"": root}
        for item in items:
            if item["source"] != source:
                continue
            relative = item["relativePath"]
            searchable = "{0} {1} {2}".format(source, relative, item["name"])
            if query not in searchable.lower():
                continue
            parent = root
            parts = relative.replace("\\", "/").split("/")[:-1]
            path = ""
            for part in parts:
                path += "/" + part
                if path not in folders:
                    folders[path] = {"label": part, "children": [], "item": None}
                    parent["children"].append(folders[path])
                parent = folders[path]
            parent["children"].append({
                "label": "{0} ({1})".format(item["name"], os.path.basename(relative)),
                "children": [], "item": item,
            })
        roots.append(root)
    return roots


class PresetBrowserWindow(forms.WPFWindow):
    def __init__(self, items, title):
        self._items = items
        self.selected = None
        forms.WPFWindow.__init__(
            self, os.path.join(os.path.dirname(__file__), "preset_browser.xaml")
        )
        self.Title = title
        self.lblLocations.Text = "Enterprise (read-only): {0}\nUser: {1}".format(
            presets.enterprise_folder() or "not configured", presets.user_folder()
        )
        self._refresh()

    def _refresh(self):
        from System.Windows.Controls import TreeViewItem

        def add_nodes(collection, nodes, is_root=False):
            for node in nodes:
                control = TreeViewItem()
                control.Header = node["label"]
                control.Tag = node["item"]
                control.IsExpanded = bool(query) or is_root
                if node["item"]:
                    control.ToolTip = presets.preset_label(node["item"])
                collection.Add(control)
                add_nodes(control.Items, node["children"])

        query = self.txtSearch.Text or ""
        roots = library_tree(self._items, query)
        self.treePresets.Items.Clear()
        self.btnSelect.IsEnabled = False
        self.lblSelected.Text = "Select a preset. Folders cannot be loaded."
        add_nodes(self.treePresets.Items, roots, is_root=True)

    def on_search_changed(self, sender, args):
        if hasattr(self, "treePresets") and hasattr(self, "btnSelect"):
            self._refresh()

    def on_selection_changed(self, sender, args):
        control = self.treePresets.SelectedItem
        item = control.Tag if control is not None else None
        self.btnSelect.IsEnabled = item is not None
        self.lblSelected.Text = presets.preset_label(item) if item else "Select a preset."

    def on_select(self, sender, args):
        control = self.treePresets.SelectedItem
        if control is not None and control.Tag is not None:
            self.selected = control.Tag
            self.Close()

    def on_cancel(self, sender, args):
        self.Close()
