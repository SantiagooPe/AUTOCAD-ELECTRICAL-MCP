"""Live isolated lifecycle regression. Retains temporary artifacts for review."""
import hashlib
import json
from pathlib import Path
import uuid
import time
from src.autocad.connection import get_connection
from src.tools import project_management as pm, electrical, circuits
from src.tools.project_validation import validate_project
from scripts.test_native_2023 import retry_com


def main(resume=None):
    app = get_connection().app
    assert app.Version.startswith('24.2'), app.Version
    original = app.ActiveDocument
    old = pm.context(original)['project']
    root = Path(resume).resolve() if resume else Path('artifacts/project-management-2023', uuid.uuid4().hex[:8]).resolve()
    root.mkdir(parents=True, exist_ok=bool(resume))
    template = Path('C:/Users/San/AppData/Local/Autodesk/AutoCAD Electrical 2023/R24.2/enu/Template/ACAD_ELECTRICAL_IEC.dwt')
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in electrical.IEC2_LIBRARY.rglob('*') if p.is_file()}
    before = hashes()
    report = dict(success=False, version=app.Version, directory=str(root), original_project=old)
    if resume:
        report.update(json.loads((root/'report.json').read_text(encoding='utf-8')))
    def checked(label, result):
        report[label] = result
        print(label, result.get('success'), result.get('error'), flush=True)
        assert result['success'], result
    try:
        if resume:
            pm.activate(original, root/('test-' + root.name + '.wdp'))
            control = app.Documents.Open(str(root/'control.dwg'))
            time.sleep(2)
            app.Documents.Open(str(root/'power.dwg'))
            time.sleep(2)
        else:
            checked('create', pm.create_project(str(root/('test-' + root.name + '.wdp')), old))
            checked('control', pm.create_project_drawing(str(root/'control.dwg'), str(template), str(root/('test-' + root.name + '.wdp')), 'CONTROL'))
            control = app.ActiveDocument
            checked('power', pm.create_project_drawing(str(root/'power.dwg'), str(template), str(root/('test-' + root.name + '.wdp')), 'POWER'))
        retry_com(lambda: control.Activate())
        time.sleep(1)
        checked('idempotent', pm.register_drawing())
        checked('preflight', validate_project(control))
        checked('circuit', circuits.create_start_stop_circuit(30, 160))
        count = control.ModelSpace.Count
        duplicate = circuits.create_start_stop_circuit(130, 160)
        report['duplicate'] = duplicate
        assert not duplicate['success'] and count == control.ModelSpace.Count
        checked('rebuild', pm.rebuild_project())
        checked('final_validation', validate_project(control))
        assert hashes() == before
        report.update(success=True, iec2_unchanged=True)
    finally:
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for i in range(retry_com(lambda: app.Documents.Count) - 1, -1, -1):
            doc = retry_com(lambda: app.Documents.Item(i))
            if str(retry_com(lambda: doc.FullName)).casefold().startswith(str(root).casefold() + '\\'):
                retry_com(lambda: doc.Close(False))
                time.sleep(.5)
        retry_com(lambda: original.Activate())
        pm.activate(original, old)
        report['original_context_restored'] = True
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(root/'report.json', flush=True)


if __name__ == '__main__':
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)

