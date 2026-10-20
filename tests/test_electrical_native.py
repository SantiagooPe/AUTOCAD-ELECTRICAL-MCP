import unittest
from unittest.mock import MagicMock, patch

from src.tools import electrical_native as native


class NativeTests(unittest.TestCase):
    def test_split_parent_requires_the_contact_attribute_even_if_missing(self):
        parent = dict(TAG1='KM1', XREFNO='4-A')
        child = dict(TAG2='KM1', CONTACT='NC', XREF='3-B')
        with patch.object(native, 'get_block_attributes', side_effect=[parent, child, parent, child]), \
             patch.object(native, 'evaluate', return_value='T'):
            self.assertFalse(native.update_cross_references(MagicMock(), 'A', 'B')['success'])

    def test_split_parent_does_not_pass_with_only_the_other_contact_reference(self):
        for tag in ('KM1', 'KM2'):
            for contact, other in (('NO', 'NC'), ('NC', 'NO')):
                with self.subTest(tag=tag, contact=contact):
                    parent = dict(TAG1=tag, FAMILY='MS', XREFNO='', XREFNC='')
                    child = dict(TAG2=tag, FAMILY='MS', CONTACT=contact, XREF='3-B')
                    stale = dict(parent, **{'XREF' + other: 'old'})
                    with patch.object(native, 'get_block_attributes', side_effect=[
                            parent, child, stale, child]), \
                         patch.object(native, 'evaluate', return_value='T'):
                        result = native.update_cross_references(MagicMock(), 'A', 'B')
                    self.assertFalse(result['success'])
                    self.assertEqual(result['status'], 'unverified')

    def test_cross_references_save_refresh_database_then_verify_both_instances(self):
        parent, child = {'TAG1': 'KM1'}, {'TAG2': 'KM1'}
        with patch.object(native, 'get_block_attributes', side_effect=[
                parent, child, dict(parent, XREF='2-B1'), dict(child, XREF='1-A1')]), \
             patch.object(native, 'evaluate', return_value='T') as evaluate:
            result = native.update_cross_references(MagicMock(), 'A', 'B')
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'updated')
        expressions = [call.args[1] for call in evaluate.call_args_list]
        self.assertIn('wd_is_cur_dwg_in_proj', expressions[0])
        self.assertIn('QSAVE', expressions[1])
        self.assertIn('wd_pds_freshen_project_db', expressions[2])
        self.assertIn('ace_projwide_util_dbx', expressions[3])
        self.assertIn('(list 0 0 1) (list nil nil) nil', expressions[3])
        self.assertNotIn('wd_xref_doit', expressions[3])
        self.assertIn('QSAVE', expressions[4])
        self.assertEqual(result['parent_references'], {'XREF': '2-B1'})
        self.assertEqual(result['child_references'], {'XREF': '1-A1'})

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
