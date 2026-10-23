"""Topology, sequence and failure regressions for star/delta control."""
import itertools
import unittest
from unittest.mock import patch

from src.tools import circuits
from tests import test_electrical_primitives as fixtures


def energized(result, stop, start, main, star, delta, elapsed):
    """Walk the actual returned wires and closed contacts from supply to coils."""
    def key(p):
        return tuple(round(v, 6) for v in p)
    graph = {}
    def edge(a, b):
        a, b = key(a), key(b)
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    for wire in result['wires']:
        edge(wire['start'], wire['end'])
    states = dict(stop=stop, start=start, holding=main, star_timer=not elapsed,
                  delta_timer=elapsed, star_interlock=not delta, delta_interlock=not star)
    for role, closed in states.items():
        if closed:
            edge(*result['components'][role]['terminals'])
    pending, seen = [key(result['supply_terminals'][0])], set()
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(graph.get(node, set()) - seen)
    return tuple(key(result['components'][r + '_coil']['terminals'][0]) in seen
                 for r in ('main', 'timer', 'star', 'delta'))


class StarDeltaTests(unittest.TestCase):
    def assemble(self, scale=1, wire_failure=False, numbering_failure=False, xref_failure=False):
        with patch.object(circuits, 'create_start_stop_circuit',
                          side_effect=lambda x,y,s,tag: circuits.create_star_delta_circuit(x,y,s)), \
             patch.object(circuits, 'number_wire',
                          side_effect=RuntimeError('number failure') if numbering_failure else
                          lambda doc,h,n: dict(handle=h,wire_number=n)):
            return fixtures.CircuitRegressionTests().run_circuit(scale=scale, wire_failure=wire_failure,
                                                       xref_failure=xref_failure)

    def test_all_states_and_sequence(self):
        for scale in (0.5, 1, 2):
            result, doc, entities, lines, xref = self.assemble(scale)
            self.assertTrue(result['assembled'], result)
            self.assertEqual(len(result['components']), 11)
            self.assertEqual(len(result['wire_numbers']), 8)
            self.assertEqual(xref.call_count, 5)
            for state in itertools.product((False, True), repeat=6):
                stop, start, main, star, delta, elapsed = state
                run = stop and (start or main)
                expected = (run, run, run and not elapsed and not delta,
                            run and elapsed and not star)
                actual = energized(result, *state)
                self.assertEqual(actual, expected, state)
                self.assertFalse(actual[2] and actual[3])
            # Start, release start, timer transfer, delta pickup, stop, reset.
            for state, expected in [
                ((1,1,0,0,0,0), (1,1,1,0)),
                ((1,0,1,1,0,0), (1,1,1,0)),
                ((1,0,1,1,0,1), (1,1,0,0)),
                ((1,0,1,0,0,1), (1,1,0,1)),
                ((1,0,1,0,1,1), (1,1,0,1)),
                ((0,0,1,0,1,1), (0,0,0,0)),
                ((1,0,0,0,0,0), (0,0,0,0))]:
                self.assertEqual(energized(result, *state), expected)
            self.assertTrue(all(line.Layer == 'WIRES' for line in lines))

    def test_wire_failure_rolls_back(self):
        result, doc, entities, lines, xref = self.assemble(wire_failure=True)
        self.assertFalse(result['assembled'])
        for entity in [*entities.values(), *lines]:
            entity.Delete.assert_called_once()
        xref.assert_not_called()
        doc.EndUndoMark.assert_called_once()

    def test_finalization_failure_retains_drawing(self):
        for kwargs in ({'numbering_failure': True}, {'xref_failure': True}):
            result, doc, entities, lines, xref = self.assemble(**kwargs)
            self.assertTrue(result['assembled'])
            self.assertFalse(result['success'])
            for entity in [*entities.values(), *lines]:
                entity.Delete.assert_not_called()

    def test_invalid_input_precedes_connection(self):
        with patch.object(circuits.electrical, '_get_conn') as conn:
            for args in ({'scale': 0}, {'x': float('nan')}, {'y': float('inf')},
                         {'transition_seconds': 0}, {'transition_seconds': float('inf')}):
                self.assertFalse(circuits.create_star_delta_circuit(**args)['success'])
            conn.assert_not_called()

    def test_missing_timer_symbol_precedes_document_mutation(self):
        with patch.object(circuits.symbol_catalog, 'resolve',
                          side_effect=ValueError('VTD22N missing')), \
             patch.object(circuits.electrical, '_get_conn') as conn:
            result = circuits.create_star_delta_circuit()
            self.assertFalse(result['assembled'])
            self.assertIn('VTD22N missing', result['error'])
            conn.assert_not_called()
