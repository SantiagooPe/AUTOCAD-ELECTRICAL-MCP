"""Live MCP verification; creates and closes an unsaved temporary drawing.

Run: python -m scripts.test_start_stop_2023
"""
import asyncio
import hashlib
import json
from pathlib import Path

from src.autocad.connection import get_connection
from src.autocad.utils import get_block_attributes
from src.tools import electrical, symbol_catalog
from src.server import mcp


def connected(result, start_closed, holding_closed, stop_closed):
    def key(p):
        return tuple(round(v, 6) for v in p)
    graph = {}
    def edge(a, b):
        a, b = key(a), key(b)
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    for wire in result['wires']:
        edge(wire['start'], wire['end'])
    for role, closed in [('stop', stop_closed), ('start', start_closed), ('holding', holding_closed)]:
        if closed:
            edge(*result['components'][role]['terminals'])
    source = key(result['supply_terminals'][0])
    target = key(result['components']['coil']['terminals'][0])
    seen, pending = set(), [source]
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(graph.get(node, set()) - seen)
    return target in seen


async def main():
    conn = get_connection()
    app = conn.app
    assert app.Version.startswith('24.2'), app.Version
    assert app.GetAcadState().IsQuiescent
    paths = [Path(symbol_catalog.resolve(electrical.IEC2_LIBRARY, q)['path'])
             for q in ('pulsador NC', 'pulsador NA', 'bobina de contactor', 'VMS21')]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    previous = app.ActiveDocument
    doc = app.Documents.Add()
    await asyncio.sleep(3)
    try:
        for index, scale in enumerate((1, 2)):
            if index:
                for i in range(doc.ModelSpace.Count - 1, -1, -1):
                    doc.ModelSpace.Item(i).Delete()
            raw = await mcp.call_tool('create_start_stop_circuit', {'x': 30, 'y': 160, 'scale': scale})
            result = raw[1] if isinstance(raw, tuple) else json.loads(raw[0].text)
            assert result['success'], result
            assert len(result['components']) == 4 and len(result['wires']) == 10
            for role, data in result['components'].items():
                block = doc.HandleToObject(data['handle'])
                assert block.Name.upper() == data['symbol']
                assert abs(block.XScaleFactor - scale) < 1e-9
                attrs = get_block_attributes(block)
                for attr in block.GetAttributes():
                    if attr.TagString.upper() in ('NO', 'NC', 'CONTACT', 'FAMILY'):
                        assert attr.Invisible, (role, attr.TagString)
                if role == 'holding':
                    assert attrs['TAG2'] == 'KM1' and attrs['CONTACT'] == 'NO'
                    assert attrs['FAMILY'] == result['components']['coil']['attributes']['FAMILY'] == 'MS'
                elif role == 'coil':
                    assert attrs['TAG1'] == 'KM1'
                else:
                    assert attrs['CONTACT'] == ('NC' if role == 'stop' else 'NO')
                    assert attrs['TAG1'] == ('S0' if role == 'stop' else 'S1')
            for wire in result['wires']:
                line = doc.HandleToObject(wire['handle'])
                assert line.Layer == 'WIRES'
                assert tuple(line.StartPoint) == tuple(wire['start'])
                assert tuple(line.EndPoint) == tuple(wire['end'])
            for start in (False, True):
                for holding in (False, True):
                    for stop in (False, True):
                        assert connected(result, start, holding, stop) == (stop and (start or holding))
            duplicate = await mcp.call_tool('create_start_stop_circuit', {})
            duplicate = duplicate[1] if isinstance(duplicate, tuple) else json.loads(duplicate[0].text)
            assert not duplicate['success']
            assert all(doc.HandleToObject(w['handle']) for w in result['wires'])
            print(f'PASS scale={scale}: 4 symbols, 10 wires, 8 logic states, duplicate protection')
        app.ZoomExtents()
        assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        print('PASS: original IEC2 SHA256 unchanged')
    finally:
        await asyncio.sleep(1)
        doc.Close(False)
        previous.Activate()
    print('LIVE MCP START-STOP PASSED; temporary drawing closed without saving')


if __name__ == '__main__':
    asyncio.run(main())
