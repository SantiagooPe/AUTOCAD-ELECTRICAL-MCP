"""Explicit project lifecycle; native membership and verified completion.

No implicit migration of populated drawings. Power and control sheets share
the same WDP and project validation namespace.
"""
from pathlib import Path
import ntpath
import time
import re

from src.autocad.lisp import evaluate, quote
from src.tools.project_validation import _strings, path_key, require_valid_project

LOAD = '(if (not wd_load) (load "wd_load.lsp")) (wd_load) '


def resolve_drawing(drawings, query):
    """Resolve a full path, exact basename/stem, or unambiguous sheet number."""
    query = query.strip()
    matches = []
    for path in drawings:
        stem = ntpath.splitext(ntpath.basename(path))[0]
        exact = path_key(query) == path_key(path) or query.casefold() in (ntpath.basename(path).casefold(), stem.casefold())
        numeric = query.isdigit() and any(int(part) == int(query) for part in re.findall(r'\d+', stem))
        if exact or numeric:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError('El dibujo no pertenece al proyecto activo o la selección es ambigua')
    return matches[0]


def retry_com(operation):
    """Retry transient COM rejections while Electrical finishes a document switch."""
    deadline = time.monotonic() + 30
    while True:
        try:
            return operation()
        except Exception as exc:
            if getattr(exc, 'hresult', None) not in (-2147418111, -2147417846) and not isinstance(exc, AttributeError):
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(.3)


def context(doc):
    projects = _strings(retry_com(lambda: evaluate(doc, '(progn ' + LOAD + '(ace_getactiveproject))')))
    if len(projects) != 1 or not projects[0]:
        raise ValueError('No hay proyecto Electrical activo')
    project = projects[0]
    drawings = _strings(retry_com(lambda: evaluate(doc, '(nth 5 (c:wd_proj_wdp_data))')))
    return dict(project=project, drawings=[ntpath.normpath(ntpath.join(ntpath.dirname(project), p)) for p in drawings])


def activate(doc, path):
    retry_com(lambda: evaluate(doc, f'(progn {LOAD}(c:wd_makeproj_current {quote(Path(path).as_posix())}))'))
    result = context(doc)
    if path_key(result['project']) != path_key(str(path)):
        raise RuntimeError('Electrical no confirmó el proyecto solicitado')
    return result


def create_project(project_path, settings_from=None):
    """Create an exclusive WDP, copying settings only, never drawing entries."""
    from src.tools.project import _get_conn
    try:
        target = Path(project_path).resolve()
        if target.suffix.lower() != '.wdp':
            raise ValueError('Se requiere ruta .wdp')
        doc = _get_conn().get_active_document()
        source = Path(settings_from or context(doc)['project'])
        header = [line for line in source.read_text(encoding='utf-8-sig').splitlines()
                  if line.startswith(('?', '+', '*'))]
        if not header:
            raise ValueError('El proyecto base no contiene configuración Electrical')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write('\n'.join(header) + '\n')
        return dict(success=True, **activate(doc, target))
    except Exception as exc:
        return dict(success=False, error=str(exc))


def register_drawing(drawing_path=None, expected_project=None, section='', description=''):
    """Register an exact saved empty drawing; refuse foreign populated sheets."""
    from src.tools.project import _get_conn
    try:
        app = retry_com(lambda: _get_conn().get_application())
        original = retry_com(lambda: app.ActiveDocument)
        state = context(original)
        if expected_project and path_key(expected_project) != path_key(state['project']):
            raise ValueError('El proyecto activo no es el solicitado')
        path = Path(drawing_path or original.FullName).resolve()
        if not path.is_file() or path.suffix.lower() != '.dwg':
            raise ValueError('Se requiere un DWG guardado')
        if path_key(str(path)) in {path_key(p) for p in state['drawings']}:
            return dict(success=True, action='already_registered', **state)
        # Electrical replaces entries by basename: never allow an accidental replacement.
        if any(ntpath.basename(p).casefold() == path.name.casefold() for p in state['drawings']):
            raise ValueError('Otro dibujo del proyecto tiene el mismo nombre')
        doc = next((app.Documents.Item(i) for i in range(app.Documents.Count)
                    if path_key(app.Documents.Item(i).FullName) == path_key(str(path))), None)
        opened = doc is None
        if opened:
            doc = app.Documents.Open(str(path))
        try:
            doc.Activate()
            for i in range(doc.ModelSpace.Count):
                obj = doc.ModelSpace.Item(i)
                if obj.ObjectName == 'AcDbBlockReference':
                    from src.autocad.utils import get_block_attributes
                    attrs = get_block_attributes(obj)
                    if attrs.get('TAG1') or attrs.get('TAG2') or any(v.strip() for k, v in attrs.items() if k in ('XREF', 'XREFNO', 'XREFNC')):
                        raise ValueError('Dibujo ajeno con componentes o referencias: requiere migración explícita')
            if path_key(context(doc)['project']) != path_key(state['project']):
                raise ValueError('Cambió el proyecto activo')
            evaluate(doc, f'(c:ace_add_dwg_to_project {quote(path.as_posix())} (list {quote(section)} "" {quote(description)} nil nil))')
            after = context(doc)
            if path_key(str(path)) not in {path_key(p) for p in after['drawings']}:
                raise RuntimeError('Electrical no confirmó el alta del DWG')
            return dict(success=True, action='registered', **after)
        finally:
            if opened:
                doc.Close(False)
            retry_com(lambda: original.Activate())
    except Exception as exc:
        return dict(success=False, error=str(exc))


def create_project_drawing(drawing_path, template_path, expected_project=None, section='', description=''):
    """Create a fresh sheet from an explicit DWT and register that exact DWG."""
    from src.tools.project import _get_conn
    try:
        path, template = Path(drawing_path).resolve(), Path(template_path).resolve()
        if path.exists() or path.suffix.lower() != '.dwg':
            raise ValueError('El destino debe ser un DWG nuevo')
        if not template.is_file() or template.suffix.lower() != '.dwt':
            raise ValueError('Se requiere plantilla DWT Electrical')
        app = _get_conn().get_application()
        state = context(app.ActiveDocument)
        if expected_project and path_key(expected_project) != path_key(state['project']):
            raise ValueError('El proyecto activo no es el solicitado')
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = app.Documents.Add(str(template))
        time.sleep(2)
        doc = retry_com(lambda: app.ActiveDocument)
        retry_com(lambda: doc.SaveAs(str(path)))
        time.sleep(1)
        return register_drawing(str(path), state['project'], section, description)
    except Exception as exc:
        return dict(success=False, error=str(exc))


def rebuild_project():
    """Refresh database and project XREFs without retagging or renumbering."""
    from src.tools.project import _get_conn
    try:
        doc = _get_conn().get_active_document()
        require_valid_project(doc, allow_incomplete_xrefs=True)
        state = context(doc)
        app = doc.Application
        members = {path_key(p) for p in state['drawings']}
        for i in range(app.Documents.Count):
            sheet = app.Documents.Item(i)
            if path_key(sheet.FullName) in members:
                sheet.Save()
        from src.tools.electrical_native import DATABASE_REFRESH, project_xref_expression
        evaluate(doc, DATABASE_REFRESH, timeout=120)
        evaluate(doc, project_xref_expression('(nth 5 (c:wd_proj_wdp_data))'), timeout=120)
        report = require_valid_project(doc)
        return dict(success=True, validation=report, **state)
    except Exception as exc:
        return dict(success=False, error=str(exc), validation=getattr(exc, 'report', None))
