"""Live isolated reversing-control verification: python -m scripts.test_reversing_2023."""
import asyncio
import hashlib
import itertools
import json
from pathlib import Path
import time
import uuid

from src.autocad.connection import get_connection
from src.autocad.lisp import evaluate, quote
from src.autocad.utils import get_block_attributes, set_block_attributes
from src.tools import electrical
from scripts.test_native_2023 import retry_com


def energized(result, stop, forward, reverse, km1, km2):
    """Traverse actual wire endpoints and closed contacts, excluding coils."""
    def key(p):
        return tuple(round(v, 6) for v in p)
    graph = {}
    def edge(a, b):
        a, b = key(a), key(b)
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    for wire in result['wires']:
        edge(wire['start'], wire['end'])
    states = dict(stop=stop, forward_start=forward, reverse_start=reverse,
                  forward_holding=km1, reverse_holding=km2,
                  forward_interlock=not km2, reverse_interlock=not km1)
    for role, closed in states.items():
        if closed:
            edge(*result['components'][role]['terminals'])
    pending, seen = [key(result['supply_terminals'][0])], set()
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(graph.get(node, set()) - seen)
    return tuple(key(result['components'][d + '_coil']['terminals'][0]) in seen
                 for d in ('forward', 'reverse'))


def main():
    from src.server import mcp
    app = get_connection().app
    print('Connected to Electrical', app.Version, flush=True)
    assert app.Version.startswith('24.2'), app.Version
    assert app.GetAcadState().IsQuiescent
    previous = app.ActiveDocument.Name
    root = Path('artifacts/reversing-2023', uuid.uuid4().hex[:8]).resolve()
    root.mkdir(parents=True)
    library = Path(electrical.IEC2_LIBRARY)
    def hashes():
        return {str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in library.rglob('*') if p.is_file()}
    before = hashes()
    doc = app.Documents.Add('C:/Users/San/AppData/Local/Autodesk/AutoCAD Electrical 2023/R24.2/enu/Template/ACAD_ELECTRICAL_IEC.dwt')
    time.sleep(3)
    old_project = None
    try:
        old_project = evaluate(doc, '(progn (if (not wd_load) (load "wd_load.lsp")) (wd_load) (ace_getactiveproject))')
        doc.SaveAs(str(root / 'reversing.dwg'))
        source = Path(json.loads(old_project)).read_text(encoding='utf-8-sig', errors='replace').splitlines()
        wdp = root / ('reversing-' + root.name + '.wdp')
        wdp.write_text('\n'.join([line for line in source if line.startswith(('?', '+', '*'))]
                                 + ['reversing.dwg', '']), encoding='utf-8')
        evaluate(doc, f'(c:wd_makeproj_current {quote(wdp.as_posix())})')
        print('Temporary project activated', wdp, flush=True)
        doc = app.ActiveDocument
        assert Path(doc.FullName) == root / 'reversing.dwg'
        evaluate(doc, '(setq Aw_debug nil)')
        for i in range(doc.ModelSpace.Count):
            block = doc.ModelSpace.Item(i)
            if block.ObjectName == 'AcDbBlockReference' and block.Name.upper() == 'WD_M':
                set_block_attributes(block, {'XREF_STYLE': '0'})
        evaluate(doc, '(c:ace_GBL_wd_m 1)')
        print('Temporary drawing configured; invoking MCP circuit tool', flush=True)
        async def call(arguments):
            raw = await mcp.call_tool('create_reversing_circuit', arguments)
            return raw[1] if isinstance(raw, tuple) else json.loads(raw[0].text)
        result = asyncio.run(call({'x': 30, 'y': 240}))
        (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        assert result['success'], result
        assert len(result['components']) == 9
        assert len(result['wire_numbers']) == 7
        for state in itertools.product((False, True), repeat=5):
            stop, f, r, k1, k2 = state
            assert energized(result, *state) == (stop and (f or k1) and not k2,
                                                stop and (r or k2) and not k1), state
        print('PASS: 32 contact states including stop, holding and cross interlocks', flush=True)
        nets = []
        for wire in result['wires']:
            line = doc.HandleToObject(wire['handle'])
            assert line.Layer == 'WIRES'
            assert list(line.StartPoint) == wire['start'] and list(line.EndPoint) == wire['end']
            nets.append(evaluate(doc, f'''(mapcar (function (lambda (c)
              (cdr (assoc 5 (entget (car c))))))
              (nth 9 (c:wd_get_wire_netlst (handent {quote(wire['handle'])}) 1)))'''))
        # Native netlist must recognize each three-terminal parallel junction.
        for roles in [('stop', 'forward_start', 'forward_holding', 'reverse_start', 'reverse_holding'),
                      ('forward_start', 'forward_holding', 'forward_interlock'),
                      ('reverse_start', 'reverse_holding', 'reverse_interlock')]:
            assert any(all(result['components'][r]['handle'] in net for r in roles) for net in nets), roles
        attrs = [get_block_attributes(doc.ModelSpace.Item(i)) for i in range(doc.ModelSpace.Count)
                 if doc.ModelSpace.Item(i).ObjectName == 'AcDbBlockReference']
        assert {str(n) for n in range(101, 108)} <= {a.get('WIRENO') for a in attrs}
        for direction, other in [('forward', 'reverse'), ('reverse', 'forward')]:
            coil = result['components'][direction + '_coil']['attributes']
            for role in (direction + '_holding', other + '_interlock'):
                child = result['components'][role]['attributes']
                assert child['TAG2'] == coil['TAG1']
                assert all(child.get(k, '') == coil.get(k, '') for k in ('FAMILY', 'INST', 'LOC'))
            assert result['components'][direction + '_holding']['attributes']['CONTACT'] == 'NO'
            assert result['components'][direction + '_interlock']['attributes']['CONTACT'] == 'NC'
        duplicate = asyncio.run(call({}))
        assert not duplicate['success']
        assert before == hashes(), 'IEC2 modified'
        evaluate(doc, '(progn (command "_.QSAVE") T)')
        report = dict(result, native_networks=nets, logic_states=32,
                      iec2_files_hashed=len(before), iec2_unchanged=True, version=app.Version)
        (root / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('PASS: native networks, seven wire numbers, four XREF pairs, IEC2 SHA256 unchanged', flush=True)
        print('REPORT', root / 'verification.json', flush=True)
    finally:
        retry_com(lambda: doc.Close(False))
        time.sleep(.5)
        if old_project and old_project != 'nil':
            evaluate(retry_com(lambda: app.ActiveDocument), f'(c:wd_makeproj_current {old_project})')
        retry_com(lambda: app.Documents.Item(previous).Activate())
        print('Original drawing and project restored', flush=True)


if __name__ == '__main__':
    main()
