"""Regenerate KM1/KM2 XREFs in the active drawing; preserve circuit topology.

Run with Electrical idle: python -m scripts.test_xref_recovery_2023.
The regression clears only KM1's split references, regenerates them through
Electrical, repeats in reverse parent order, and saves the repaired drawing.
"""
import json
from pathlib import Path

from src.autocad.connection import get_connection
from src.autocad.utils import get_block_attributes, set_block_attributes
from src.tools.electrical_native import update_cross_references


def snapshot(doc):
    topology, components = {}, {}
    for entity in doc.ModelSpace:
        if entity.ObjectName == 'AcDbLine' and entity.Layer == 'WIRES':
            topology[entity.Handle] = [entity.Layer, list(entity.StartPoint), list(entity.EndPoint)]
        elif entity.ObjectName == 'AcDbBlockReference':
            attrs = get_block_attributes(entity)
            if attrs.get('TAG1') or attrs.get('TAG2'):
                components[entity.Handle] = attrs
                topology[entity.Handle] = [entity.Name, list(entity.InsertionPoint), entity.Rotation,
                    entity.XScaleFactor, entity.YScaleFactor, entity.ZScaleFactor,
                    {k: v for k, v in attrs.items() if not k.startswith('XREF')}]
    return topology, components


def main():
    doc = get_connection().get_active_document()
    before, attrs = snapshot(doc)
    parents = {a['TAG1']: h for h, a in attrs.items() if a.get('TAG1') in ('KM1', 'KM2')}
    assert set(parents) == {'KM1', 'KM2'}, parents
    pairs = []
    for tag, parent in parents.items():
        children = [(h, a) for h, a in attrs.items() if a.get('TAG2') == tag]
        assert {a.get('CONTACT') for _, a in children} == {'NO', 'NC'}, children
        for child, a in children:
            assert all(a.get(k, '') == attrs[parent].get(k, '') for k in ('FAMILY', 'INST', 'LOC'))
            pairs.append((parent, child))
    report = {'drawing': doc.FullName, 'before': attrs, 'updates': []}
    try:
        set_block_attributes(doc.HandleToObject(parents['KM1']), {'XREFNO': '', 'XREFNC': ''})
        for parent, child in pairs:
            result = update_cross_references(doc, parent, child)
            report['updates'].append(result)
            assert result['success'], result
        stable_topology, stable = snapshot(doc)
        assert stable_topology == before, 'Circuit topology or non-XREF attributes changed'
        for tag, handle in parents.items():
            assert stable[handle]['XREFNO'].strip(), tag
            assert stable[handle]['XREFNC'].strip(), tag
        for parent, child in reversed(pairs):
            result = update_cross_references(doc, parent, child)
            assert result['success'], result
        final_topology, final = snapshot(doc)
        assert final_topology == before, 'Topology changed during repeated update'
        assert stable == final, 'References depend on update order'
        report.update(success=True, after=final, topology_unchanged=True, order_independent=True)
        print('PASS: KM1 recovered, KM2 verified, NO/NC populated, repeat/order stable, topology unchanged')
    finally:
        path = Path('artifacts/xref-recovery-2023.json')
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(path.resolve())


if __name__ == '__main__':
    main()
