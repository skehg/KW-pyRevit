# -*- coding: utf-8 -*-
"""Reusable Markdown help viewer for pyRevit tools.

pyRevit notes:
- This module is designed for lazy import from button handlers so tool startup stays fast.
- It avoids Revit document writes and transactions (UI-only behavior).
- External links are opened with the OS default handler instead of navigating away in the embedded browser.
"""

import os
import sys
import codecs

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from pyrevit import forms
from System import Uri
from System.Diagnostics.Process import Start
from System.Windows.Markup import XamlReader
from System.Windows.Navigation import NavigatingCancelEventHandler


MARKDOWN_EXTENSIONS = [
    "fenced_code",
    "tables",
    "toc",
    "admonition"
]


GITHUB_LIKE_CSS = """
:root {
    --fg: #24292f;
    --muted: #57606a;
    --bg: #ffffff;
    --surface: #f6f8fa;
    --line: #d0d7de;
    --link: #0969da;
    --link-visited: #8250df;
    --code-bg: #f6f8fa;
}
html, body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.55;
}
.markdown-body {
    max-width: 980px;
    margin: 0 auto;
    padding: 28px;
    box-sizing: border-box;
}
h1, h2, h3, h4, h5, h6 {
    margin-top: 1.35em;
    margin-bottom: 0.55em;
    line-height: 1.25;
    font-weight: 600;
}
h1 { padding-bottom: 0.3em; border-bottom: 1px solid var(--line); }
h2 { padding-bottom: 0.25em; border-bottom: 1px solid var(--line); }
p, ul, ol, table, pre, blockquote {
    margin-top: 0;
    margin-bottom: 1em;
}
a {
    color: var(--link);
    text-decoration: none;
}
a:hover { text-decoration: underline; }
a:visited { color: var(--link-visited); }
code, pre, kbd, samp {
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.92em;
}
code {
    background: var(--code-bg);
    border: 1px solid var(--line);
    border-radius: 5px;
    padding: 0.1em 0.35em;
}
pre {
    background: var(--code-bg);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 12px;
    overflow: auto;
}
pre code {
    border: 0;
    background: transparent;
    padding: 0;
}
table {
    border-collapse: collapse;
    width: 100%;
    display: block;
    overflow-x: auto;
}
thead th {
    background: var(--surface);
}
th, td {
    border: 1px solid var(--line);
    padding: 8px 10px;
    text-align: left;
    vertical-align: top;
}
tr:nth-child(even) td {
    background: #fcfcfd;
}
blockquote {
    color: var(--muted);
    border-left: 4px solid var(--line);
    padding: 0 1em;
}
img {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
}
.admonition {
    border: 1px solid var(--line);
    border-left-width: 4px;
    border-left-color: #1f883d;
    background: #f6fff8;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 1em 0;
}
.admonition-title {
    margin: 0 0 0.5em 0;
    font-weight: 600;
}
"""


_HELP_WINDOW_XAML = """
<Window xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\"
        xmlns:x=\"http://schemas.microsoft.com/winfx/2006/xaml\"
        Title=\"Help\"
        Height=\"760\" Width=\"1080\"
        MinHeight=\"480\" MinWidth=\"760\"
        WindowStartupLocation=\"CenterScreen\"
        ResizeMode=\"CanResize\">
    <Grid Margin=\"12\">
        <Grid.RowDefinitions>
            <RowDefinition Height=\"Auto\"/>
            <RowDefinition Height=\"*\"/>
            <RowDefinition Height=\"Auto\"/>
        </Grid.RowDefinitions>

        <Border Grid.Row=\"0\" BorderBrush=\"#D0D7DE\" BorderThickness=\"1\" CornerRadius=\"6\" Padding=\"10\" Background=\"#F6F8FA\">
            <TextBlock x:Name=\"txt_title\" FontSize=\"16\" FontWeight=\"SemiBold\" />
        </Border>

        <Border Grid.Row=\"1\" Margin=\"0,10,0,10\" BorderBrush=\"#D0D7DE\" BorderThickness=\"1\" CornerRadius=\"6\" ClipToBounds=\"True\">
            <Grid>
                <WebBrowser x:Name=\"help_browser\" />
            </Grid>
        </Border>

        <StackPanel Grid.Row=\"2\" Orientation=\"Horizontal\" HorizontalAlignment=\"Right\">
            <Button x:Name=\"btn_close\" Content=\"Close\" Width=\"100\" Height=\"30\" />
        </StackPanel>
    </Grid>
</Window>
"""


_markdown_module = None


def _html_escape(text):
    value = "" if text is None else str(text)
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _resolve_markdown_module():
    """Lazy-load markdown module on first Help click."""
    global _markdown_module
    if _markdown_module is not None:
        return _markdown_module

    lib_dir = os.path.dirname(__file__)
    vendor_dir = os.path.join(lib_dir, "vendor")
    if os.path.isdir(vendor_dir) and vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    try:
        import markdown as md  # pylint: disable=import-error
        _markdown_module = md
        return _markdown_module
    except Exception:
        return None


def _to_file_base_uri(folder_path):
    folder = os.path.abspath(folder_path)
    if not folder.endswith(os.sep):
        folder = folder + os.sep
    return Uri(folder).AbsoluteUri


def _build_html_document(tool_name, body_html, base_uri):
    safe_title = _html_escape(tool_name)
    return (
        "<!DOCTYPE html>"
        "<html>"
        "<head>"
        "<meta charset='utf-8'/>"
        "<meta http-equiv='X-UA-Compatible' content='IE=edge'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<base href='{}' />"
        "<title>{}</title>"
        "<style>{}</style>"
        "</head>"
        "<body>"
        "<article class='markdown-body'>{}</article>"
        "</body>"
        "</html>"
    ).format(base_uri, safe_title, GITHUB_LIKE_CSS, body_html)


class HelpWindow(object):
    """Small reusable WPF window hosting WebBrowser-rendered help."""

    def __init__(self, tool_name, html_content):
        self._window = XamlReader.Parse(_HELP_WINDOW_XAML)
        self._title_text = self._window.FindName("txt_title")
        self._browser = self._window.FindName("help_browser")
        self._close_btn = self._window.FindName("btn_close")

        self._title_text.Text = "{} Help".format(tool_name)
        self._close_btn.Click += self._on_close

        # Keep this handler on the instance to avoid delegate GC issues.
        self._nav_handler = NavigatingCancelEventHandler(self._on_navigating)
        self._browser.Navigating += self._nav_handler
        self._browser.NavigateToString(html_content)

    def _on_close(self, sender, args):
        self._window.Close()

    def _on_navigating(self, sender, args):
        uri = getattr(args, "Uri", None)
        if uri is None:
            return

        scheme = ""
        try:
            scheme = (uri.Scheme or "").lower()
        except Exception:
            scheme = ""

        # Keep in-document anchors and local file references inside WebBrowser.
        if scheme in ("", "about", "file"):
            return

        # Open external destinations in user's default browser/mail client.
        if scheme in ("http", "https", "mailto"):
            try:
                Start(uri.AbsoluteUri)
                args.Cancel = True
            except Exception:
                pass

    def show_dialog(self):
        self._window.ShowDialog()


def show_help(tool_dir, tool_name):
    """Render tool_dir/help.md and open it in a reusable help window."""
    help_path = os.path.join(tool_dir, "help.md")
    if not os.path.exists(help_path):
        forms.alert(
            "Help file was not found.\n\nExpected: {}".format(help_path),
            title="{} - Help".format(tool_name)
        )
        return

    md = _resolve_markdown_module()
    if md is None:
        forms.alert(
            "Markdown renderer is unavailable.\n"
            "Install/package the markdown module under lib/vendor or runtime path.",
            title="{} - Help".format(tool_name)
        )
        return

    try:
        with codecs.open(help_path, "r", "utf-8") as fp:
            markdown_text = fp.read()
    except Exception as ex:
        forms.alert(
            "Could not read help file:\n{}\n\n{}".format(help_path, str(ex)),
            title="{} - Help".format(tool_name)
        )
        return

    try:
        body_html = md.markdown(
            markdown_text,
            extensions=MARKDOWN_EXTENSIONS,
            output_format="html5"
        )
    except Exception as ex:
        forms.alert(
            "Could not render Markdown help.\n\n{}".format(str(ex)),
            title="{} - Help".format(tool_name)
        )
        return

    base_uri = _to_file_base_uri(os.path.dirname(help_path))
    html_doc = _build_html_document(tool_name, body_html, base_uri)
    HelpWindow(tool_name, html_doc).show_dialog()
