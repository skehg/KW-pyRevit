"""Verify CLR imports in a fresh IronPython engine, not MCP's preloaded engine."""
import io
import os
import clr

from System import AppDomain


def run_checks():
    assembly = next(
        item for item in AppDomain.CurrentDomain.GetAssemblies()
        if item.GetName().Name in ('IronPython', 'pyRevitLabs.IronPython'))
    clr.AddReference(assembly)
    from IronPython.Hosting import Python

    command_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with io.open(os.path.join(command_dir, 'ui_styles.py'), encoding='utf-8') as source:
        startup = source.read().split('\ndef load_window', 1)[0]
    # This engine tests CLR discovery only; pyRevit supplies the standard library.
    startup = '\n'.join(
        line for line in startup.splitlines()
        if line not in ('import io', 'import os'))
    engine = Python.CreateEngine()
    try:
        scope = engine.CreateScope()
        engine.Execute(startup, scope)
        for filename, button in (
                ('ReValueUI.xaml', 'btn_apply'),
                ('FilterEditor.xaml', 'use_filters'),
                ('CategorySelection.xaml', 'use_selection')):
            path = os.path.join(command_dir, filename)
            with io.open(path, encoding='utf-8') as source:
                scope.SetVariable('markup', source.read())
            scope.SetVariable('path', path)
            scope.SetVariable('button_name', button)
            engine.Execute(
                "context = ParserContext()\n"
                "context.BaseUri = Uri(path)\n"
                "window = XamlReader.Parse(markup, context)\n"
                "try:\n"
                "    button = window.FindName(button_name)\n"
                "    button.IsEnabled = True\n"
                "    button.ApplyTemplate()\n"
                "    face = button.Template.FindName('button_face', button)\n"
                "    assert face.CornerRadius.TopLeft == 6\n"
                "    assert face.Effect.ShadowDepth == 1\n"
                "finally:\n"
                "    window.Close()\n", scope)
    finally:
        engine.Runtime.Shutdown()
    return 'PASS: fresh IronPython CLR imports and shared rounded styles in all three windows.'
