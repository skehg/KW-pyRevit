import ast
import os
import types
import unittest
from unittest import mock


COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ElementId(object):
    InvalidElementId = -1


class ElementType(object):
    def __init__(self, family_name):
        self.FamilyName = family_name


class View(object):
    pass


class Element(object):
    def __init__(self, element_id, category, type_id=-1):
        self.Id = element_id
        self.category = category
        self.type_id = type_id

    def GetTypeId(self):
        return self.type_id


class Collector(object):
    calls = []
    view_valid = True

    @staticmethod
    def IsViewValidForElementIteration(document, view_id):
        return Collector.view_valid

    def __init__(self, document, view_id=None):
        self.document = document
        self.view_id = view_id
        self.category = None

    def OfCategoryId(self, category):
        self.category = category
        return self

    def WhereElementIsNotElementType(self):
        return self

    def values(self):
        values = self.document.elements
        return [element for element in values
                if element.category == self.category
                and (self.view_id is None or element.Id in self.document.visible)]

    def GetElementCount(self):
        self.calls.append(('count', self.view_id, self.category))
        return len(self.values())

    def ToElementIds(self):
        self.calls.append(('ids', self.view_id, self.category))
        return [element.Id for element in self.values()]

    def __iter__(self):
        self.calls.append(('families', self.view_id, self.category))
        return iter(self.values())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(COMMAND_DIR, 'category_selection.py')
        with open(path, encoding='utf-8') as source:
            tree = ast.parse(source.read())
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)
                     and node.name in ('CategoryData', 'CategorySource')]
        namespace = dict(
            DB=types.SimpleNamespace(
                FilteredElementCollector=Collector, ElementId=ElementId,
                ElementType=ElementType, View=View),
            RevitArgumentException=ValueError, element_id_value=lambda value: value)
        exec(compile(tree, path, 'exec'), namespace)
        cls.source_class = namespace['CategorySource']

    def setUp(self):
        Collector.calls = []
        Collector.view_valid = True
        self.categories = [
            types.SimpleNamespace(Id=1, Name='Doors'),
            types.SimpleNamespace(Id=2, Name='Walls'),
            types.SimpleNamespace(Id=3, Name='Sheets'),
            types.SimpleNamespace(Id=4, Name='Empty'),
        ]
        self.elements = [
            Element(10, 1, 100), Element(11, 1, 100),
            Element(12, 1, 101), Element(13, 2, 102), Element(14, 3),
        ]
        self.types = {100: ElementType('Single'), 101: ElementType('Double'),
                      102: ElementType('Basic Wall')}
        self.lookups = []

        def get_element(element_id):
            self.lookups.append(element_id)
            return self.types.get(element_id)

        self.document = types.SimpleNamespace(
            Settings=types.SimpleNamespace(Categories=self.categories),
            elements=self.elements, visible={10, 13, 14}, GetElement=get_element)
        self.source = self.source_class(self.document, types.SimpleNamespace(Id=90))

    def test_discovery_is_scoped_count_only_and_cached(self):
        rows = self.source.categories('view')
        self.assertEqual(['Doors', 'Sheets', 'Walls'], [row.name for row in rows])
        self.assertEqual([1, 1, 1], [row.count for row in rows])
        self.assertTrue(all(call[0] == 'count' for call in Collector.calls))
        self.assertEqual([], self.lookups)
        calls = list(Collector.calls)
        self.assertIs(rows, self.source.categories('view'))
        self.assertEqual(calls, Collector.calls)

    def test_families_loaded_only_on_demand_and_once_per_type(self):
        category = self.source.categories('project')[0]
        groups = self.source.families('project', category)
        self.assertEqual({'Single': [10, 11], 'Double': [12]}, groups)
        self.assertEqual([100, 101], self.lookups)
        calls = list(Collector.calls)
        self.assertIs(groups, self.source.families('project', category))
        self.assertEqual(calls, Collector.calls)
        self.assertEqual([100, 101], self.lookups)

    def test_scope_caches_are_separate_but_share_type_names(self):
        project = self.source.categories('project')[0]
        view = self.source.categories('view')[0]
        self.source.families('project', project)
        self.assertEqual({'Single': [10]}, self.source.families('view', view))
        self.assertEqual([100, 101], self.lookups)

    def test_family_subset_is_per_category_and_none_is_supported(self):
        rows = self.source.categories('project')
        doors = next(row for row in rows if row.name == 'Doors')
        sheets = next(row for row in rows if row.name == 'Sheets')
        self.assertEqual([12], self.source.selected_ids(
            'project', doors, dict(all=False, families={'Double'})))
        self.assertEqual({None: [14]}, self.source.families('project', sheets))
        self.assertEqual([], self.source.selected_ids(
            'project', doors, dict(all=False, families=set())))

    def test_all_families_does_not_load_families_to_collect_ids(self):
        category = self.source.categories('project')[0]
        self.assertEqual([10, 11, 12], self.source.selected_ids(
            'project', category, dict(all=True, families=set())))
        self.assertEqual([], self.lookups)
        self.assertFalse(any(call[0] == 'families' for call in Collector.calls))

    def test_all_families_reuses_cached_ids(self):
        category = self.source.categories('project')[0]
        self.source.families('project', category)
        calls = list(Collector.calls)
        self.assertEqual({10, 11, 12}, set(self.source.selected_ids(
            'project', category, dict(all=True, families=set()))))
        self.assertEqual(calls, Collector.calls)

    def test_system_family_name_comes_from_type(self):
        walls = next(row for row in self.source.categories('project')
                     if row.name == 'Walls')
        self.assertEqual({'Basic Wall': [13]}, self.source.families('project', walls))

    def test_views_do_not_offer_view_types_as_families(self):
        sheet = View()
        sheet.GetTypeId = lambda: 100
        self.assertIsNone(self.source.family_name(sheet))
        self.assertEqual([], self.lookups)

    def test_unsupported_view_does_not_silently_collect_project(self):
        Collector.view_valid = False
        source = self.source_class(self.document, types.SimpleNamespace(Id=90))
        self.assertFalse(source.view_available)
        with self.assertRaises(ValueError):
            source.categories('view')
        self.assertEqual([], Collector.calls)


class Cancelled(Exception):
    pass


class EntrySelectionTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(COMMAND_DIR, 'script.py')
        with open(path, encoding='utf-8') as source:
            tree = ast.parse(source.read())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'get_selected_elements']
        self.selection = mock.Mock()
        self.selection.GetElementIds.return_value = types.SimpleNamespace(Count=0)
        self.doc = mock.Mock()
        self.doc.GetElement.side_effect = lambda element_id: 'element:' + str(element_id)
        self.forms = mock.Mock()
        self.namespace = dict(
            doc=self.doc, uidoc=types.SimpleNamespace(Selection=self.selection),
            forms=self.forms, ObjectType=types.SimpleNamespace(Element='element'),
            OperationCanceledException=Cancelled)
        exec(compile(tree, path, 'exec'), self.namespace)
        self.get_elements = self.namespace['get_selected_elements']

    def test_preselection_bypasses_both_dialogs(self):
        class Ids(list):
            Count = 2
        self.selection.GetElementIds.return_value = Ids([10, 11])
        self.assertEqual(['element:10', 'element:11'], self.get_elements())
        self.forms.CommandSwitchWindow.show.assert_not_called()
        self.selection.PickObjects.assert_not_called()

    def test_screen_selection_deduplicates_and_resolves(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Select on Screen'
        self.selection.PickObjects.return_value = [
            types.SimpleNamespace(ElementId=10), types.SimpleNamespace(ElementId=10),
            types.SimpleNamespace(ElementId=12)]
        self.assertEqual(['element:10', 'element:12'], self.get_elements())

    def test_cancel_initial_choice(self):
        self.forms.CommandSwitchWindow.show.return_value = None
        self.assertIsNone(self.get_elements())
        self.selection.PickObjects.assert_not_called()

    def test_explicit_cancel_choice(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Cancel'
        self.assertIsNone(self.get_elements())
        self.selection.PickObjects.assert_not_called()

    def test_screen_escape_is_quiet_cancellation(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Select on Screen'
        self.selection.PickObjects.side_effect = Cancelled()
        self.assertIsNone(self.get_elements())

    def test_unexpected_pick_error_is_not_swallowed(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Select on Screen'
        self.selection.PickObjects.side_effect = RuntimeError('Failure')
        with self.assertRaises(RuntimeError):
            self.get_elements()

    def test_category_picker_loaded_only_when_requested(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Select Categories'
        module = types.ModuleType('category_selection')
        module.select_by_categories = mock.Mock(return_value=['chosen element'])
        with mock.patch.dict('sys.modules', {'category_selection': module}):
            self.assertEqual(['chosen element'], self.get_elements())
        module.select_by_categories.assert_called_once_with(self.doc, self.doc.ActiveView)
        self.selection.PickObjects.assert_not_called()

    def test_category_cancel_propagates_without_opening_main_dialog(self):
        self.forms.CommandSwitchWindow.show.return_value = 'Select Categories'
        module = types.ModuleType('category_selection')
        module.select_by_categories = mock.Mock(return_value=None)
        with mock.patch.dict('sys.modules', {'category_selection': module}):
            self.assertIsNone(self.get_elements())


if __name__ == '__main__':
    unittest.main()
