"""Live isolated project verification of native Electrical behavior."""
import hashlib
import json
from pathlib import Path
import time
import uuid
import asyncio

from src.autocad.connection import get_connection
from src.autocad.lisp import evaluate, quote
from src.autocad.utils import get_block_attributes
from src.tools import electrical
from src.tools.electrical_native import ensure_wire_type
from src.tools.electrical_primitives import number_wire


def retry_com(operation):
    deadline = time.monotonic() + 30
    while True:
        try:
            return operation()
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.3)


def cleanup_test_documents(original_drawing, original_project):
    app = get_connection().app
    root = str(Path('artifacts/native-2023').resolve()).casefold() + '\\'
    for index in range(retry_com(lambda: app.Documents.Count) - 1, -1, -1):
        path = retry_com(lambda: app.Documents.Item(index).FullName)
        if path.casefold().startswith(root):
            retry_com(lambda: app.Documents.Item(index).Close(False))
            time.sleep(.5)
    retry_com(lambda: app.Documents.Item(original_drawing).Activate())
    evaluate(retry_com(lambda: app.ActiveDocument), f'(c:wd_makeproj_current {quote(original_project)})')
    print('All task temporary drawings closed; original drawing and project restored', flush=True)


def main():
    conn = get_connection()
    app = conn.app
    assert app.Version.startswith('24.2'), app.Version
    previous_name = app.ActiveDocument.Name
    root = Path('artifacts/native-2023', uuid.uuid4().hex[:8]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    library = Path(electrical.IEC2_LIBRARY)
    def hashes():
        return {str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in library.rglob('*') if p.is_file()}
    before = hashes()
    doc = app.Documents.Add('C:/Users/San/AppData/Local/Autodesk/AutoCAD Electrical 2023/R24.2/enu/Template/ACAD_ELECTRICAL_IEC.dwt')
    time.sleep(2)
    old_project = None
    try:
        old_project = evaluate(doc, '(progn (if (not wd_load) (load "wd_load.lsp")) (wd_load) (ace_getactiveproject))')
        print('OLD PROJECT', old_project, flush=True)
        doc.SaveAs(str(root / 'start-stop.dwg'))
        time.sleep(2)
        # A separate WDP keeps the user's current project untouched.
        wdp = root / f'native-test-{root.name}.wdp'
        source = Path(json.loads(old_project)).read_text(encoding='utf-8-sig', errors='replace').splitlines()
        header = [line for line in source if line.startswith(('?', '+', '*'))]
        wdp.write_text('\n'.join(header + ['start-stop.dwg', '']), encoding='utf-8')
        evaluate(doc, f'(c:wd_makeproj_current {quote(wdp.as_posix())})')
        doc = app.ActiveDocument
        print('ACTIVE', doc.FullName, 'READONLY', doc.ReadOnly, flush=True)
        assert Path(doc.FullName) == root / 'start-stop.dwg'
        doc.Activate()
        for expr in ['(c:ace_get_wiretype_list nil)']:
            print('PROBE', expr, evaluate(doc, expr), flush=True)
        evaluate(doc, '(setq Aw_debug nil)')
        for i in range(doc.ModelSpace.Count):
            block = doc.ModelSpace.Item(i)
            if block.ObjectName == 'AcDbBlockReference' and block.Name.upper() == 'WD_M':
                from src.autocad.utils import set_block_attributes
                set_block_attributes(block, {'XREF_STYLE': '0'})
        evaluate(doc, '(c:ace_GBL_wd_m 1)')
        from src.server import mcp
        async def call(name, arguments):
            raw = await mcp.call_tool(name, arguments)
            return raw[1] if isinstance(raw, tuple) else json.loads(raw[0].text)
        result = asyncio.run(call('create_start_stop_circuit', {'x': 30, 'y': 160}))
        print('CIRCUIT', result.get('success'), result.get('error'), result.get('cross_references'), flush=True)
        assert result['success'], result
        assert result['wire_type']['registered']
        networks = []
        for wire in result['wires']:
            h = quote(wire['handle'])
            networks.append(evaluate(doc, f'''(mapcar (function (lambda (c)
              (list (cdr (assoc 5 (entget (car c))))) ))
              (nth 9 (c:wd_get_wire_netlst (handent {h}) 1)))'''))
        print('NATIVE NETWORKS', networks, flush=True)
        for index, expected in [(1, ('stop', 'start', 'holding')), (3, ('start', 'holding', 'coil'))]:
            assert all(result['components'][role]['handle'] in networks[index] for role in expected), networks
        number = number_wire(doc, result["wires"][1]["handle"], "101")
        print('NATIVE NUMBER', number, flush=True)
        assert number['wire_number'] == '101'
        numbers = [get_block_attributes(doc.ModelSpace.Item(i)) for i in range(doc.ModelSpace.Count)
                   if doc.ModelSpace.Item(i).ObjectName == 'AcDbBlockReference']
        assert any(a.get('WIRENO') == '101' for a in numbers), numbers
        assert result['cross_references']['success'], result['cross_references']
        repeated = asyncio.run(call('update_cross_references', {
            'coil_handle': result['components']['coil']['handle'],
            'child_handle': result['components']['holding']['handle']}))
        assert repeated['success'], repeated
        assert repeated['parent_references'] == result['cross_references']['parent_references']
        assert repeated['child_references'] == result['cross_references']['child_references']
        evaluate(doc, '(progn (command "_.QSAVE") T)')
        assert before == hashes(), 'IEC2 modified'
        report = dict(result, native_networks=networks, wire_number='101',
                      iec2_files_hashed=len(before), iec2_unchanged=True, version=app.Version)
        (root / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        blank = app.Documents.Add()
        time.sleep(2)
        try:
            assert ensure_wire_type(blank)['registered']
            assert evaluate(blank, '(member "WIRES" (c:ace_get_wiretype_list nil))') != 'nil'
            print('PASS registration in an unconfigured blank drawing', flush=True)
        finally:
            blank.Close(False)
            doc.Activate()
        print('PASS native wires, numbering, netlist, parent/child cross references, IEC2 hashes', flush=True)
    finally:
        # Close the test document before switching projects: Electrical may
        # invalidate COM document wrappers during a project change.
        retry_com(lambda: doc.Close(False))
        time.sleep(.5)
        if old_project and old_project != 'nil':
            evaluate(retry_com(lambda: app.ActiveDocument), f'(c:wd_makeproj_current {old_project})')
            print('Previous project restored', flush=True)
        retry_com(lambda: app.Documents.Item(previous_name).Activate())


if __name__ == '__main__':
    import sys
    if '--cleanup-only' in sys.argv:
        if len(sys.argv) != 4:
            raise SystemExit('Usage: --cleanup-only ORIGINAL_DRAWING ORIGINAL_PROJECT_WDP')
        cleanup_test_documents(sys.argv[2], sys.argv[3])
    else:
        main()
