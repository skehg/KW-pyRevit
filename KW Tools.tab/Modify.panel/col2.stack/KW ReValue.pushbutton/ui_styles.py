"""Load ReValue windows with file-relative shared resources."""
import io
import os
import clr

clr.AddReference('PresentationFramework')
from System.Windows.Markup import ParserContext, XamlReader

# Uri moves from System.dll to System.Private.Uri.dll in Revit 2025's .NET runtime.
clr.AddReference(clr.GetClrType(ParserContext).GetProperty('BaseUri').PropertyType.Assembly)
from System import Uri


def load_window(path):
    context = ParserContext()
    context.BaseUri = Uri(os.path.abspath(path))
    with io.open(path, encoding='utf-8') as source:
        return XamlReader.Parse(source.read(), context)
