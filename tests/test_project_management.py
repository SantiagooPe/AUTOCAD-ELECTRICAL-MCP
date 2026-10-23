"""Project isolation and lifecycle regression tests, without AutoCAD."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from src.tools import project_management as pm, project_validation as v
from tests.test_project_validation import snapshot


class ManagementTests(unittest.TestCase):
    def test_drawing_selection_is_exact_and_project_scoped(self):
        paths = ['C:/P/sheet_01.dwg', 'C:/P/sheet_10.dwg']
        self.assertEqual(pm.resolve_drawing(paths, '1'), paths[0])
        for query in ('sheet', 'C:/Q/sheet_01.dwg'):
            with self.assertRaises(ValueError):
                pm.resolve_drawing(paths, query)
        with self.assertRaises(ValueError):
            pm.resolve_drawing(paths + ['C:/P/other_01.dwg'], '1')

    def test_busy_com_does_not_discard_connection(self):
        from src.autocad.connection import AutoCADConnection
        from unittest.mock import PropertyMock
        conn = AutoCADConnection()
        app = MagicMock()
        error = RuntimeError('busy'); error.hresult = -2147418111
        type(app).Name = PropertyMock(side_effect=error)
        conn._app = app
        self.assertTrue(conn.is_connected())
        self.assertIs(conn._app, app)

    def test_planned_child_requires_matching_parent_in_project_or_batch(self):
        parent = dict(TAG1='KM1', FAMILY='MS')
        child = dict(TAG2='KM1', FAMILY='MS')
        self.assertTrue(v.validate_snapshot(snapshot(), [parent, child])['success'])
        self.assertFalse(v.validate_snapshot(snapshot(), [child])['success'])
        self.assertFalse(v.validate_snapshot(snapshot(), [parent, dict(TAG2='KM1', FAMILY='CR')])['success'])

    def test_planned_inherited_references_block(self):
        self.assertFalse(v.validate_snapshot(snapshot(), [dict(TAG1='KM1', XREF='old-sheet')])['success'])

    def test_planned_batch_collisions_all_families(self):
        for tag in ('KM1', 'KM2', 'KT1', 'F1', 'Q1'):
            result = v.validate_snapshot(snapshot(), [dict(TAG1=tag), dict(TAG1=tag.lower(), FAMILY='OTHER')])
            self.assertFalse(result['success'], tag)

    def test_existing_family_cannot_hide_duplicate(self):
        self.assertFalse(v.validate_snapshot(snapshot(dict(TAG1='KM1', FAMILY='MS'),
                                                     dict(TAG1='KM1', FAMILY='CR')))['success'])

    def test_wire_native_and_numberable(self):
        data = snapshot()
        data['inventory'][0].update(non_numberable_wire_types=['WIRES'],
            wires=[dict(handle='A', layer='WIRES', object_name='AcDbPolyline')])
        codes = {i['code'] for i in v.validate_snapshot(data)['issues']}
        self.assertEqual(codes, {'non_native_wire', 'wire_numbering_disabled'})

    def test_project_copies_only_settings_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)/'base.wdp'; target = Path(directory)/'new.wdp'
            base.write_text('?header\n+setting\nold.dwg\n', encoding='utf-8')
            with patch('src.tools.project._get_conn'), patch.object(pm, 'activate', return_value={}):
                self.assertTrue(pm.create_project(str(target), str(base))['success'])
                self.assertEqual(target.read_text(), '?header\n+setting\n')
                self.assertFalse(pm.create_project(str(target), str(base))['success'])

    def test_wrong_project_blocks_before_creating_document(self):
        conn = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory)/'a.dwt'; template.touch()
            with patch('src.tools.project._get_conn', return_value=conn), \
                 patch.object(pm, 'context', return_value=dict(project='C:/P/a.wdp', drawings=[])):
                result = pm.create_project_drawing(str(Path(directory)/'a.dwg'), str(template), 'C:/Q/b.wdp')
        self.assertFalse(result['success'])
        conn.get_application.return_value.Documents.Add.assert_not_called()

    def test_rebuild_blocks_before_save_or_execute(self):
        with patch('src.tools.project._get_conn'), \
             patch.object(pm, 'require_valid_project', side_effect=ValueError('foreign')), \
             patch.object(pm, 'evaluate') as evaluate:
            self.assertFalse(pm.rebuild_project()['success'])
            evaluate.assert_not_called()

    def test_registration_blocks_populated_foreign_drawing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'foreign.dwg'; path.touch()
            conn = MagicMock(); app = conn.get_application.return_value
            doc = app.ActiveDocument; doc.FullName = str(path)
            app.Documents.Count = 1; app.Documents.Item.return_value = doc
            doc.ModelSpace.Count = 1
            block = doc.ModelSpace.Item.return_value
            block.ObjectName = 'AcDbBlockReference'
            with patch('src.tools.project._get_conn', return_value=conn), \
                 patch.object(pm, 'context', return_value=dict(project='C:/P/main.wdp', drawings=[])), \
                 patch('src.autocad.utils.get_block_attributes', return_value=dict(TAG1='KM1', XREF='old')), \
                 patch.object(pm, 'evaluate') as execute:
                self.assertFalse(pm.register_drawing(str(path))['success'])
                execute.assert_not_called()

    def test_registration_is_idempotent_and_rejects_basename_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'sheet.dwg'; path.touch()
            with patch('src.tools.project._get_conn'), patch.object(pm, 'evaluate') as execute:
                with patch.object(pm, 'context', return_value=dict(project='C:/P/main.wdp', drawings=[str(path)])):
                    self.assertEqual(pm.register_drawing(str(path))['action'], 'already_registered')
                with patch.object(pm, 'context', return_value=dict(project='C:/P/main.wdp', drawings=['C:/Other/sheet.dwg'])):
                    self.assertFalse(pm.register_drawing(str(path))['success'])
                execute.assert_not_called()
