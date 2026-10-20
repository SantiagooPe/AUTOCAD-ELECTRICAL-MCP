"""Failure isolation and terminal validation without a live AutoCAD."""
import unittest
from unittest.mock import MagicMock, patch

from src.tools import circuits, electrical_primitives as primitives


class StartStopTests(unittest.TestCase):
    def test_invalid_layout_never_connects(self):
        with patch.object(circuits.electrical, '_get_conn') as connect:
            for kwargs in ({'scale': 0}, {'scale': -1}, {'x': float('nan')},
                           {'scale': float('inf')}, {'coil_tag': ' '}, {'coil_tag': 's0'}, {'coil_tag': 'S1'}):
                self.assertFalse(circuits.create_start_stop_circuit(**kwargs)['success'])
            connect.assert_not_called()

    def test_insertion_failure_removes_only_new_entities(self):
        conn = MagicMock()
        doc = conn.get_active_document.return_value
        doc.ModelSpace.Count = 0
        first = MagicMock()
        doc.ModelSpace.InsertBlock.side_effect = [first, RuntimeError('insert failed')]
        with patch.object(circuits.symbol_catalog, 'resolve', return_value={'path': 'symbol.dwg', 'symbol': 'VTEST'}), \
             patch.object(circuits, 'ensure_wire_type'), \
             patch.object(circuits.electrical, '_get_conn', return_value=conn), \
             patch.object(primitives, 'configure_attributes', side_effect=lambda block, attrs: attrs), \
             patch.object(primitives, 'connection_points', return_value=[[0, 7.5, 0], [0, -7.5, 0]]):
            result = circuits.create_start_stop_circuit()
        self.assertFalse(result['success'])
        first.Delete.assert_called_once()
        doc.EndUndoMark.assert_called_once()
        doc.ModelSpace.AddLine.assert_not_called()

    def test_instance_visibility_preserves_metadata(self):
        attrs = []
        for tag, value in [('TAG2', 'KM1'), ('CONTACT', 'NO'), ('NO', 'NO'),
                           ('NC', 'NC'), ('FAMILY', 'MS'), ('X2TERM01', ''),
                           ('TERM01', '13'), ('DESC1', 'ENCLAVAMIENTO')]:
            attr = MagicMock(TagString=tag, TextString=value, Invisible=False)
            attrs.append(attr)
        block = MagicMock()
        block.GetAttributes.return_value = attrs
        circuits.configure_attributes(block, {'TAG2': 'KM1'})
        for attr in attrs:
            self.assertEqual(attr.Invisible, attr.TagString in ('CONTACT', 'NO', 'NC', 'FAMILY', 'X2TERM01'))
        self.assertEqual(attrs[1].TextString, 'NO')

    def test_terminals_ignore_link_attributes(self):
        def attr(tag, point):
            return type('Attribute', (), {'TagString': tag, 'InsertionPoint': point})()
        block = MagicMock()
        block.GetAttributes.return_value = [attr('X1LINK', [99, 0, 0]), attr('X8TERM02', [2, -7, 0])]
        block.GetConstantAttributes.return_value = [attr('X2TERM01', [2, 7, 0])]
        self.assertEqual(circuits.connection_points(block), [[2, 7, 0], [2, -7, 0]])


if __name__ == '__main__':
    unittest.main()
