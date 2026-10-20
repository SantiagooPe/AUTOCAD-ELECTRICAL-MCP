"""Topology and failure regressions for the composed reversing control."""
import itertools
import unittest
from unittest.mock import patch

from src.tools import circuits
from tests import test_electrical_primitives as fixtures
from scripts.test_reversing_2023 import energized


class ReversingTests(unittest.TestCase):
    def assemble(self, scale=1, wire_failure=False, numbering_failure=False):
        with patch.object(circuits, 'create_start_stop_circuit',
                          side_effect=lambda x,y,s,tag: circuits.create_reversing_circuit(x,y,s)), \
             patch.object(circuits, 'number_wire',
                          side_effect=RuntimeError('number failure') if numbering_failure else
                          lambda doc,handle,number: dict(handle=handle,wire_number=number)):
            return fixtures.CircuitRegressionTests().run_circuit(scale=scale, wire_failure=wire_failure)

    def test_geometry_and_all_contact_states(self):
        for scale in (1, 2):
            result, doc, entities, lines, xref = self.assemble(scale)
            self.assertTrue(result['assembled'], result)
            self.assertFalse(result['success'])  # fixture has no project
            self.assertEqual(len(result['components']), 9)
            self.assertEqual(len(result['wire_numbers']), 7)
            self.assertEqual(xref.call_count, 4)
            for state in itertools.product((False, True), repeat=5):
                stop, f, r, k1, k2 = state
                self.assertEqual(energized(result, *state),
                    (stop and (f or k1) and not k2, stop and (r or k2) and not k1))
            self.assertTrue(all(line.Layer == 'WIRES' for line in lines))

    def test_partial_wire_failure_rolls_back(self):
        result, doc, entities, lines, xref = self.assemble(wire_failure=True)
        self.assertFalse(result['success'])
        for entity in [*entities.values(), *lines]:
            entity.Delete.assert_called_once()
        xref.assert_not_called()
        doc.EndUndoMark.assert_called_once()

    def test_numbering_failure_retains_repairable_circuit(self):
        result, doc, entities, lines, xref = self.assemble(numbering_failure=True)
        self.assertTrue(result['assembled'])
        self.assertFalse(result['success'])
        self.assertTrue(all(not n['success'] for n in result['wire_numbers']))
        for entity in [*entities.values(), *lines]:
            entity.Delete.assert_not_called()

    def test_invalid_geometry_does_not_connect(self):
        with patch.object(circuits.electrical, '_get_conn') as conn:
            for args in ({'scale': 0}, {'scale': -1}, {'x': float('nan')}, {'y': float('inf')}):
                self.assertFalse(circuits.create_reversing_circuit(**args)['success'])
            conn.assert_not_called()
