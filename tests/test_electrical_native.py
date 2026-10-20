import unittest
from unittest.mock import MagicMock, patch

from src.tools import electrical_native as native


class NativeTests(unittest.TestCase):
    def test_registration_requires_confirmed_receipt(self):
        with patch.object(native, 'evaluate', return_value='nil'):
            with self.assertRaises(RuntimeError):
                native.ensure_wire_type(MagicMock())

    def test_child_identity_must_match_before_database_update(self):
        for key in ('TAG2', 'FAMILY', 'INST', 'LOC'):
            parent = {'TAG1': 'KM1', 'FAMILY': 'MS', 'INST': '', 'LOC': ''}
            child = {'TAG2': 'KM1', 'FAMILY': 'MS', 'INST': '', 'LOC': ''}
            child[key] = 'OTHER'
            with patch.object(native, 'get_block_attributes', side_effect=[parent, child]), \
                 patch.object(native, 'evaluate') as evaluate:
                with self.assertRaises(ValueError):
                    native.update_cross_references(MagicMock(), 'A', 'B')
                evaluate.assert_not_called()

    def test_non_project_drawing_never_updates_database(self):
        attrs = [{'TAG1': 'KM1'}, {'TAG2': 'KM1'}]
        with patch.object(native, 'get_block_attributes', side_effect=attrs), \
             patch.object(native, 'evaluate', return_value='nil') as evaluate:
            result = native.update_cross_references(MagicMock(), 'A', 'B')
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'requires_project_drawing')
        self.assertEqual(evaluate.call_count, 1)
