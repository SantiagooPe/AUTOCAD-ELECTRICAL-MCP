"""Regression coverage for reusable Electrical operations without AutoCAD."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

from src.tools import circuits, electrical_primitives as p


class PrimitiveTests(unittest.TestCase):
    def test_bad_wire_geometry_precedes_registration_and_mutation(self):
        doc = MagicMock()
        with patch.object(p, 'ensure_wire_type') as register:
            for end in ([0, 0, 0], [float('nan'), 1, 0], [1, 2]):
                with self.assertRaises(ValueError):
                    p.create_electrical_wires(doc, [([0, 0, 0], end)])
            register.assert_not_called()
        doc.ModelSpace.AddLine.assert_not_called()

    def test_wire_registration_and_partial_failure_cleanup(self):
        doc = MagicMock()
        line = MagicMock()
        doc.ModelSpace.AddLine.side_effect = [line, RuntimeError('failure')]
        with patch.object(p, 'ensure_wire_type') as register, patch.object(p, 'ensure_layer'):
            with self.assertRaises(RuntimeError):
                p.create_electrical_wires(doc, [([0, 0, 0], [0, 1, 0])] * 2, 'RED')
            register.assert_called_once_with(doc, 'RED')
        self.assertEqual(line.Layer, 'RED')
        line.Delete.assert_called_once()

    def test_numbering_uses_native_api_and_propagates_failure(self):
        doc = MagicMock()
        doc.HandleToObject.return_value.ObjectName = 'AcDbLine'
        doc.HandleToObject.return_value.Layer = 'WIRES'
        with patch.object(p, 'ensure_wire_type'), patch.object(p, 'evaluate', return_value='T') as evaluate:
            self.assertEqual(p.number_wire(doc, 'AB', '101'), {'handle': 'AB', 'wire_number': '101'})
            evaluate.assert_called_once_with(doc, '(c:wd_putwn (handent "AB") "101")')
        with patch.object(p, 'ensure_wire_type'), patch.object(p, 'evaluate', return_value='nil'):
            with self.assertRaises(RuntimeError):
                p.number_wire(doc, 'AB', '101')

    def test_association_copies_complete_identity(self):
        doc = MagicMock()
        parent = {'TAG1': 'KM7', 'FAMILY': 'MS', 'INST': 'P1', 'LOC': 'L1'}
        child = {'TAG2': 'OLD', 'FAMILY': 'MS', 'INST': '', 'LOC': ''}
        with patch.object(p, 'get_block_attributes', side_effect=[parent, child]), \
             patch.object(p, 'configure_attributes', return_value=parent) as configure:
            p.associate_parent_child(doc, 'A', 'B')
        configure.assert_called_once_with(doc.HandleToObject.return_value,
            {'TAG2': 'KM7', 'FAMILY': 'MS', 'INST': 'P1', 'LOC': 'L1'})

    def test_existing_association_mismatch_does_not_mutate_child(self):
        with patch.object(p, 'get_block_attributes', side_effect=[
                {'TAG1': 'KM1', 'FAMILY': 'MS'}, {'TAG2': 'KM1', 'FAMILY': 'CR'}]), \
             patch.object(p, 'configure_attributes') as configure:
            with self.assertRaises(RuntimeError):
                p.associate_parent_child(MagicMock(), 'A', 'B', assign=False,
                                         identity_keys=('FAMILY',))
            configure.assert_not_called()

    def test_insertion_journals_before_attribute_failure(self):
        doc, journal = MagicMock(), []
        block = doc.ModelSpace.InsertBlock.return_value
        with patch.object(p.symbol_catalog, 'resolve', return_value={'path': 'read-only.dwg', 'symbol': 'VMS1'}), \
             patch.object(p, 'configure_attributes', side_effect=RuntimeError('attrs')):
            with self.assertRaises(RuntimeError):
                p.insert_iec_component(doc, 'IEC2', 'bobina', 0, 0, created=journal)
        self.assertEqual(journal, [block])
        block.Delete.assert_not_called()


class CircuitRegressionTests(unittest.TestCase):
    def run_circuit(self, x=0, y=0, scale=1, tag='KM1', wire_failure=False, xref_failure=False):
        conn = MagicMock()
        doc = conn.get_active_document.return_value
        doc.Name = 'control.dwg'
        doc.ModelSpace.Count = 0
        entities = {}

        def insert(position, path, sx, sy, sz, rotation):
            role = len(entities)
            attrs = {'TAG1': '', 'TAG2': '', 'DESC1': '', 'DESC2': '', 'TERM01': '', 'TERM02': '', 'FAMILY': 'MS'}
            block = MagicMock(Handle=str(role), Name=path)
            attributes = [SimpleNamespace(TagString=k, TextString=v, Invisible=False, Update=lambda: None)
                          for k, v in attrs.items()]
            attributes += [SimpleNamespace(TagString='X2TERM01', TextString='', Invisible=True,
                                           InsertionPoint=[position[0], position[1]+7.5*sx, 0], Update=lambda: None),
                           SimpleNamespace(TagString='X8TERM02', TextString='', Invisible=True,
                                           InsertionPoint=[position[0], position[1]-7.5*sx, 0], Update=lambda: None)]
            block.GetAttributes.return_value = attributes
            block.GetConstantAttributes.return_value = []
            entities[str(role)] = block
            return block

        lines = []
        def add_line(a, b):
            if wire_failure and len(lines) == 2:
                raise RuntimeError('wire failure')
            line = MagicMock(Handle='W'+str(len(lines)))
            lines.append(line)
            return line

        doc.ModelSpace.InsertBlock.side_effect = insert
        doc.ModelSpace.AddLine.side_effect = add_line
        doc.HandleToObject.side_effect = entities.__getitem__
        with ExitStack() as stack:
            stack.enter_context(patch.object(circuits, "require_valid_project"))
            stack.enter_context(patch.object(circuits.electrical, '_get_conn', return_value=conn))
            stack.enter_context(patch.object(p, 'point3d', side_effect=lambda a,b,c=0: (a,b,c)))
            stack.enter_context(patch.object(circuits.symbol_catalog, 'resolve', side_effect=lambda lib,s: {'path': s+'.dwg', 'symbol': s}))
            stack.enter_context(patch.object(circuits, 'ensure_wire_type', return_value={'layer': 'WIRES', 'registered': True, 'numbering_enabled': True}))
            stack.enter_context(patch.object(p, 'ensure_layer'))
            xref = stack.enter_context(patch.object(circuits, 'update_cross_references',
                return_value={'success': False, 'status': 'requires_project_drawing'},
                side_effect=RuntimeError('xref failure') if xref_failure else None))
            result = circuits.create_start_stop_circuit(x, y, scale, tag)
        return result, doc, entities, lines, xref

    def test_layout_response_and_identity_are_preserved(self):
        for x,y,s,tag in [(0,0,1,'KM1'), (10,20,2,'KM7')]:
            with self.subTest(scale=s):
                result, doc, entities, lines, xref = self.run_circuit(x,y,s,tag)
                self.assertTrue(result['success'], result)
                self.assertEqual(set(result), {'success','drawing','components','wire_type','cross_references',
                    'wires','junctions','supply_terminals','topology','note'})
                self.assertEqual(result['topology'], 'STOP_NC -- (START_NO || KM_AUX_NO) -- KM_COIL')
                self.assertEqual(result['junctions'], [[x,y-30*s,0],[x,y-90*s,0]])
                self.assertEqual(result['supply_terminals'], [[x,y+30*s,0],[x,y-150*s,0]])
                offsets = [(0,30,0,7.5),(0,-7.5,0,-30),(0,-30,0,-52.5),
                           (0,-67.5,0,-90),(0,-90,0,-112.5),(0,-127.5,0,-150),
                           (0,-30,60,-30),(60,-30,60,-52.5),(60,-67.5,60,-90),(60,-90,0,-90)]
                self.assertEqual(result['wires'], [dict(handle='W'+str(i),start=[x+a*s,y+b*s,0],end=[x+c*s,y+d*s,0])
                    for i,(a,b,c,d) in enumerate(offsets)])
                components = result['components']
                self.assertEqual(components['coil']['attributes']['TAG1'],tag)
                self.assertEqual(components['holding']['attributes']['TAG2'],tag)
                for role, terminals in [('stop',('11','12')),('start',('13','14')),('coil',('A1','A2')),('holding',('13','14'))]:
                    self.assertEqual(tuple(components[role]['attributes'][k] for k in ('TERM01','TERM02')),terminals)
                self.assertTrue(all(line.Layer == 'WIRES' for line in lines))
                xref.assert_called_once_with(doc,'2','3')
                doc.EndUndoMark.assert_called_once()
                doc.SendCommand.assert_not_called()

    def test_wire_failure_rolls_back_all_new_entities(self):
        result,doc,entities,lines,xref = self.run_circuit(wire_failure=True)
        self.assertFalse(result['success'])
        self.assertEqual(result['remaining_handles'],[])
        for obj in [*entities.values(),*lines]:
            obj.Delete.assert_called_once()
        doc.EndUndoMark.assert_called_once()
        xref.assert_not_called()

    def test_xref_failure_keeps_completed_circuit(self):
        result,doc,entities,lines,xref = self.run_circuit(xref_failure=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['cross_references'], {'success':False,'status':'failed','error':'xref failure'})
        for obj in [*entities.values(),*lines]:
            obj.Delete.assert_not_called()
