"""Live isolated star_delta-control verification: python -m scripts.test_star_delta_2023."""
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


from tests.test_star_delta import energized


def main():
    from src.server import mcp
    app = get_connection().app
    print('Connected to Electrical', app.Version, flush=True)
    assert app.Version.startswith('24.2'), app.Version
    assert app.GetAcadState().IsQuiescent
    previous = app.ActiveDocument.Name
    root = Path('artifacts/star_delta-2023', uuid.uuid4().hex[:8]).resolve()
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
        doc.SaveAs(str(root / 'star_delta.dwg'))
        source = Path(json.loads(old_project)).read_text(encoding='utf-8-sig', errors='replace').splitlines()
        wdp = root / ('star_delta-' + root.name + '.wdp')
        wdp.write_text('\n'.join([line for line in source if line.startswith(('?', '+', '*'))]
                                 + ['star_delta.dwg', '']), encoding='utf-8')
        evaluate(doc, f'(c:wd_makeproj_current {quote(wdp.as_posix())})')
        print('Temporary project activated', wdp, flush=True)
        doc = app.ActiveDocument
        assert Path(doc.FullName) == root / 'star_delta.dwg'
        evaluate(doc, '(setq Aw_debug nil)')
        for i in range(doc.ModelSpace.Count):
            block = doc.ModelSpace.Item(i)
            if block.ObjectName == 'AcDbBlockReference' and block.Name.upper() == 'WD_M':
                set_block_attributes(block, {'XREF_STYLE': '0'})
        evaluate(doc, '(c:ace_GBL_wd_m 1)')
        print('Temporary drawing configured; invoking MCP circuit tool', flush=True)
        async def call(arguments):
            raw = await mcp.call_tool('create_star_delta_circuit', arguments)
            return raw[1] if isinstance(raw, tuple) else json.loads(raw[0].text)
        result = asyncio.run(call({'x': 30, 'y': 240}))
        (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        assert result['success'], result
        assert len(result['components']) == 11
        assert len(result['wire_numbers']) == 8
        for state in itertools.product((False, True), repeat=6):
            stop, start, main, star, delta, elapsed = state
            run = stop and (start or main)
            actual = energized(result, *state)
            assert actual == (run, run, run and not elapsed and not delta,
                              run and elapsed and not star), state
            assert not (actual[2] and actual[3]), state
        print('PASS: 64 contact states, holding, transfer and stop', flush=True)
        nets = []
        for wire in result['wires']:
            line = doc.HandleToObject(wire['handle'])
            assert line.Layer == 'WIRES'
            assert list(line.StartPoint) == wire['start'] and list(line.EndPoint) == wire['end']
            nets.append(evaluate(doc, f'''(mapcar (function (lambda (c)
              (cdr (assoc 5 (entget (car c))))))
              (nth 9 (c:wd_get_wire_netlst (handent {quote(wire['handle'])}) 1)))'''))
        # Native netlist must recognize each three-terminal parallel junction.
        for roles in [('stop', 'start', 'holding'),
                      ('start', 'holding', 'main_coil', 'timer_coil', 'star_timer', 'delta_timer'),
                      ('main_coil', 'timer_coil', 'star_coil', 'delta_coil')]:
            assert any(all(result['components'][r]['handle'] in net for r in roles) for net in nets), roles
        attrs = [get_block_attributes(doc.ModelSpace.Item(i)) for i in range(doc.ModelSpace.Count)
                 if doc.ModelSpace.Item(i).ObjectName == 'AcDbBlockReference']
        assert {str(n) for n in range(101, 109)} <= {a.get('WIRENO') for a in attrs}
        for parent, child in [('main_coil', 'holding'), ('timer_coil', 'star_timer'),
                              ('timer_coil', 'delta_timer'), ('star_coil', 'delta_interlock'),
                              ('delta_coil', 'star_interlock')]:
            coil = result['components'][parent]['attributes']
            aux = result['components'][child]['attributes']
            assert aux['TAG2'] == coil['TAG1']
            assert all(aux.get(k, '') == coil.get(k, '') for k in ('FAMILY', 'INST', 'LOC'))
        for role, contact in [('holding','NO'), ('star_timer','NC'), ('delta_timer','NO'),
                              ('star_interlock','NC'), ('delta_interlock','NC')]:
            assert result['components'][role]['attributes']['CONTACT'] == contact
        duplicate = asyncio.run(call({}))
        assert not duplicate['success']
        assert before == hashes(), 'IEC2 modified'
        evaluate(doc, '(progn (command "_.QSAVE") T)')
        report = dict(result, native_networks=nets, logic_states=64,
                      iec2_files_hashed=len(before), iec2_unchanged=True, version=app.Version)
        (root / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('PASS: native networks, eight wire numbers, five XREF pairs, IEC2 SHA256 unchanged', flush=True)
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
