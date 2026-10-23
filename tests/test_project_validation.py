"""Project preflight regressions, independent of COM and installed Electrical."""
from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch
from src.tools import project_validation as v, circuits, components, electrical, project


def snapshot(*attrs):
    return dict(project='C:/P/main.wdp', drawings=['C:/P/a.dwg', 'C:/P/b.dwg'],
                active_drawing='C:/P/a.dwg', complete=True, inventory=[
                    dict(path='C:/P/a.dwg', wire_types=['WIRES'], wires=[],
                         components=[dict(handle=str(i), attributes=a) for i, a in enumerate(attrs)]),
                    dict(path='C:/P/b.dwg', wire_types=[], wires=[], components=[])])


class ProjectValidationTests(unittest.TestCase):
    def codes(self, data, **kwargs):
        return {i['code'] for i in v.validate_snapshot(data, **kwargs)['issues']}

    def test_cross_sheet_duplicate_and_ambiguous_parent(self):
        data = snapshot(dict(TAG1='KM1'), dict(TAG2=' km1 ', XREF='1-A'))
        data['inventory'][1]['components'] = [dict(handle='0', attributes=dict(TAG1='km1'))]
        self.assertEqual(self.codes(data), {'duplicate_tag', 'ambiguous_parent'})

    def test_multiple_children_are_not_duplicate_tags(self):
        data = snapshot(dict(TAG1='KM1', XREFNO='2-A,2-B'),
                        dict(TAG2='KM1', CONTACT='NO', XREF='1-A'),
                        dict(TAG2='KM1', CONTACT='NO', XREF='1-A'))
        self.assertTrue(v.validate_snapshot(data)['success'])

    def test_identity_and_orphan(self):
        for field in ('INST', 'LOC', 'FAMILY'):
            data = snapshot(dict(TAG1='KM1', **{field:'A'}), dict(TAG2='KM1', **{field:'B'}))
            self.assertIn('child_without_parent', self.codes(data))

    def test_incomplete_and_split_references(self):
        for pa, ca in [({}, {}), ({'XREF':'??'}, {'XREF':'1-A'}),
                           ({'XREFNO':'2-A'}, {'CONTACT':'NC','XREF':'1-A'})]:
            data = snapshot(dict(TAG1='KM1', **pa), dict(TAG2='KM1', **ca))
            self.assertIn('incomplete_cross_reference', self.codes(data))
            self.assertTrue(v.validate_snapshot(data, allow_incomplete_xrefs=True)['success'])
        self.assertFalse(v.validate_snapshot(snapshot(dict(TAG2='KM1')), allow_incomplete_xrefs=True)['success'])

    def test_unregistered_wires_and_foreign_drawing(self):
        data = snapshot()
        data['active_drawing'] = 'C:/Else/a.dwg'
        data['inventory'][0]['wires'] = [dict(handle='W', layer='CUSTOM')]
        self.assertEqual(self.codes(data), {'unregistered_wire','drawing_outside_project'})

    def test_incomplete_coverage_always_blocks(self):
        data = snapshot(); data['complete'] = False
        self.assertFalse(v.validate_snapshot(data)['success'])

    def test_planned_tags_collide_across_project_before_insertion(self):
        data = snapshot()
        data['inventory'][1]['components'] = [dict(handle='A', attributes=dict(TAG1='KM1', FAMILY='MS'))]
        self.assertIn('duplicate_tag', self.codes(data, planned=[dict(TAG1='km1')]))

    def test_validator_does_not_change_snapshot_or_geometry(self):
        data = snapshot(dict(TAG1='KM1'), dict(TAG2='KM1'))
        before = deepcopy(data)
        v.validate_snapshot(data)
        self.assertEqual(data, before)

    def test_all_circuit_creators_block_before_any_mutation(self):
        conn = MagicMock(); doc = conn.get_active_document.return_value
        doc.ModelSpace.Count = 0
        report = dict(success=False, complete=True, issues=[dict(code='duplicate_tag')])
        with patch.object(circuits.electrical, '_get_conn', return_value=conn), \
             patch.object(circuits.symbol_catalog, 'resolve', return_value={}), \
             patch.object(v, 'validate_project', return_value=report), \
             patch.object(circuits, 'ensure_wire_type') as register:
            for create in (circuits.create_start_stop_circuit, circuits.create_reversing_circuit, circuits.create_star_delta_circuit):
                result = create()
                self.assertFalse(result['success'])
                self.assertEqual(result['validation'], report)
            register.assert_not_called()
        doc.StartUndoMark.assert_not_called()
        doc.ModelSpace.InsertBlock.assert_not_called()
        doc.ModelSpace.AddLine.assert_not_called()

    def test_attribute_update_validates_proposed_orphan_and_duplicate(self):
        doc = MagicMock(FullName='C:/P/a.dwg')
        for data, changes in [(snapshot(dict(TAG1='KM1'), dict(TAG2='KM1')), {'TAG1':'KM2'}),
                              (snapshot(dict(TAG1='KM1'), dict(TAG1='KM2')), {'TAG1':'KM2'})]:
            # Complete references for the first current state.
            for component in data['inventory'][0]['components']:
                component['attributes']['XREF'] = '1-A'
            with patch.object(v, 'collect_snapshot', return_value=data):
                self.assertFalse(v.validate_component_update(doc, 'KM1', changes)['success'])

    def test_public_updates_do_not_send_commands_or_write_on_failure(self):
        conn = MagicMock()
        failure = dict(success=False, issues=[dict(code='inspection_failed')])
        for module, action in [(components, lambda: components.update_component('KM1', {'DESC1':'X'})),
                               (electrical, lambda: electrical.edit_component_attributes('KM1', {'DESC1':'X'})),
                               (project, project.sync_project)]:
            with patch.object(module, '_get_conn', return_value=conn), \
                 patch.object(v, 'validate_project', return_value=failure), \
                 patch.object(v, 'validate_component_update', return_value=failure):
                self.assertFalse(action()['success'])
        conn.send_command.assert_not_called()
        conn.get_active_document.return_value.Regen.assert_not_called()

    def test_inspection_exception_fails_closed(self):
        with patch.object(v, 'collect_snapshot', side_effect=RuntimeError('COM failed')):
            result = v.validate_project(MagicMock())
        self.assertFalse(result['success'])
        self.assertFalse(result['complete'])

    def test_collector_uses_active_wdp_and_reports_closed_sheets(self):
        doc = MagicMock(FullName='C:/P/a.dwg')
        doc.Application.Documents.Count = 1
        doc.Application.Documents.Item.return_value = doc
        doc.ModelSpace.Count = 1
        line = doc.ModelSpace.Item.return_value
        line.ObjectName = 'AcDbLine'; line.Handle = 'W'; line.Layer = 'WIRES'
        with patch.object(v, 'evaluate', side_effect=[
                '"C:/P/main.wdp"', '("a.dwg" "b.dwg")', 'nil']):
            data = v.collect_snapshot(doc)
        codes = self.codes(data)
        self.assertIn('drawing_not_inspected', codes)
        self.assertIn('unregistered_wire', codes)
        self.assertFalse(data['complete'])
        doc.Save.assert_not_called()
        doc.ModelSpace.AddLine.assert_not_called()
        doc.Activate.assert_called()

    def test_collector_restores_original_on_entity_read_failure(self):
        doc = MagicMock(FullName='C:/P/a.dwg')
        doc.Application.Documents.Count = 1
        doc.Application.Documents.Item.return_value = doc
        doc.ModelSpace.Count = 1
        doc.ModelSpace.Item.side_effect = RuntimeError('cannot read entity')
        with patch.object(v, 'evaluate', side_effect=[
                '"C:/P/main.wdp"', '("a.dwg")', 'nil']):
            result = v.validate_project(doc)
        self.assertFalse(result['success'])
        self.assertEqual(doc.Activate.call_count, 2)
        doc.Save.assert_not_called()

    def test_native_xref_blocks_before_save_or_database_update(self):
        from src.tools import electrical_native as native
        doc = MagicMock()
        report = dict(success=False, issues=[dict(code='ambiguous_parent')])
        with patch.object(v, 'validate_project', return_value=report), \
             patch.object(native, 'evaluate') as execute:
            with self.assertRaises(v.ProjectValidationError):
                native.update_cross_references(doc, 'A', 'B')
        execute.assert_not_called()
        doc.HandleToObject.assert_not_called()

    def test_lisp_string_paths_preserve_windows_paths(self):
        self.assertEqual(v._strings(r'("C:\\P\\a.dwg" "b.dwg")'), ['C:\\P\\a.dwg', 'b.dwg'])


if __name__ == '__main__':
    unittest.main()
