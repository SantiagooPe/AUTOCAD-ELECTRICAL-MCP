"""Isolate unrelated circuit identities, regenerate natively, verify invariants."""
import hashlib
import json
from pathlib import Path
from src.autocad.connection import get_connection
from src.autocad.lisp import evaluate, quote
from src.autocad.utils import set_block_attributes
from src.tools.electrical import IEC2_LIBRARY
from src.tools.electrical_native import update_cross_references
from scripts.test_xref_recovery_2023 import snapshot

def main():
    doc = get_connection().get_active_document()
    assert doc.Name.lower() == 'estrella_triangulo.dwg', doc.Name
    root = Path('artifacts/star-delta-xref-repair').resolve()
    root.mkdir(exist_ok=True)
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in Path(IEC2_LIBRARY).rglob('*') if p.is_file()}
    library = hashes()
    topology, before = snapshot(doc)
    old = json.loads(evaluate(doc, '(progn (if (not wd_load) (load "wd_load.lsp")) (wd_load) (ace_getactiveproject))'))
    report = dict(drawing=doc.FullName, original_project=old, before=before)
    report_path = root / 'verification.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    source = Path(old).read_text(encoding='utf-8-sig', errors='replace').splitlines()
    project = root / 'estrella_triangulo.wdp'
    project.write_text('\n'.join([s for s in source if s.startswith(('?', '+', '*'))]
                                 + [doc.FullName, '']), encoding='utf-8')
    evaluate(doc, f'(c:wd_makeproj_current {quote(project.as_posix())})')
    doc = get_connection().app.ActiveDocument
    # Clear derived text only. Electrical reconstructs every native relationship.
    for handle, attrs in before.items():
        set_block_attributes(doc.HandleToObject(handle), {k: '' for k in attrs if k.startswith('XREF')})
    parents = {a['TAG1']: h for h, a in before.items() if a.get('TAG1') in ('KM1','KM2','KM3','KT1')}
    pairs = [(parents[a['TAG2']], h) for h, a in before.items() if a.get('TAG2') in parents]
    for p, c in pairs:
        assert update_cross_references(doc, p, c)['success']
    middle_topology, middle = snapshot(doc)
    assert middle_topology == topology
    for p, c in reversed(pairs):
        assert update_cross_references(doc, p, c)['success']
    after_topology, after = snapshot(doc)
    assert after_topology == topology
    assert after == middle, 'References depend on update order'
    assert not any('??' in v for a in after.values() for k,v in a.items() if k.startswith('XREF'))
    assert after[parents['KM1']]['XREFNC'] == ''
    assert after[parents['KM2']]['XREFNO'] == ''
    assert library == hashes(), 'IEC2 changed'
    report.update(success=True, project=str(project), after=after,
                  topology_unchanged=True, order_independent=True, iec2_unchanged=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PASS: native XREF, reverse-order stability, topology and IEC2 unchanged')
    print(report_path)

if __name__ == '__main__':
    main()
