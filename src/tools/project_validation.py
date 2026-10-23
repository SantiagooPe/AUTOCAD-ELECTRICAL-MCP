"""Read-only project preflight. Never repairs or rewires a drawing."""
from collections import defaultdict
import ntpath
import re
from src.autocad.lisp import evaluate


def normalize(value):
    return str(value).strip().casefold()


def path_key(value):
    return ntpath.normcase(ntpath.normpath(value))


def validate_snapshot(snapshot, planned=(), allow_incomplete_xrefs=False):
    """Validate a detached project inventory; handles are scoped by drawing."""
    issues = list(snapshot.get('issues', []))
    if not snapshot.get('complete', True):
        issues.append(dict(code='incomplete_project_inventory'))
    def issue(code, **context):
        issues.append(dict(code=code, **context))
    members = {path_key(p) for p in snapshot['drawings']}
    if path_key(snapshot['active_drawing']) not in members:
        issue('drawing_outside_project', drawing=snapshot['active_drawing'])
    parents, children = defaultdict(list), []
    for drawing in snapshot['inventory']:
        if path_key(drawing['path']) not in members:
            issue('drawing_outside_project', drawing=drawing['path'])
            continue
        registered = {normalize(n) for n in drawing['wire_types']}
        for wire in drawing['wires']:
            if normalize(wire['layer']) not in registered:
                issue('unregistered_wire', drawing=drawing['path'], **wire)
        for component in drawing['components']:
            attrs = component['attributes']
            location = dict(drawing=drawing['path'], handle=component['handle'])
            identity = tuple(normalize(attrs.get(k, '')) for k in ('INST', 'LOC', 'FAMILY'))
            if normalize(attrs.get('TAG1', '')):
                parents[(normalize(attrs['TAG1']), *identity)].append((attrs, location))
            if normalize(attrs.get('TAG2', '')):
                children.append(((normalize(attrs['TAG2']), *identity), attrs, location))
    for key, matches in parents.items():
        if len(matches) > 1:
            issue('duplicate_tag', tag=key[0], entities=[loc for _, loc in matches])
    for attrs in planned:
        key = (normalize(attrs.get('TAG1', '')), *(normalize(attrs.get(k, '')) for k in ('INST', 'LOC', 'FAMILY')))
        collisions = [loc for identity, values in parents.items()
                      if key[0] == identity[0] and key[1:3] == identity[1:3]
                      for _, loc in values]
        if key[0] and collisions:
            issue('duplicate_tag', tag=key[0], planned=True, entities=collisions)
    for key, attrs, location in children:
        matches = parents.get(key, [])
        if not matches:
            issue('child_without_parent', tag=key[0], **location)
        elif len(matches) > 1:
            issue('ambiguous_parent', tag=key[0], candidates=[loc for _, loc in matches], **location)
        else:
            pa = matches[0][0]
            def valid_refs(values):
                refs = [v.strip() for k, v in values.items() if k.startswith('XREF') and v.strip()]
                return bool(refs) and all('??' not in v for v in refs)
            complete = valid_refs(pa) and valid_refs(attrs)
            contact = attrs.get('CONTACT', '').strip().upper()
            if contact in ('NO', 'NC') and ('XREFNO' in pa or 'XREFNC' in pa):
                complete = complete and bool(pa.get('XREF' + contact, '').strip())
            if not complete:
                issue('incomplete_cross_reference', tag=key[0], **location)
    blocking = [i for i in issues if not (allow_incomplete_xrefs and i['code'] == 'incomplete_cross_reference')]
    return dict(success=not blocking, complete=snapshot.get('complete', True), issues=issues,
                project=snapshot.get('project'), drawing_count=len(snapshot['inventory']))


def _strings(value):
    # AutoLISP printed strings escape backslashes and quotes, not JSON Unicode.
    return [re.sub(r'\\(.)', r'\1', s) for s in re.findall(r'"((?:\\.|[^"\\])*)"', value)]


def collect_snapshot(doc):
    """Use Electrical's active WDP, never infer it from neighbouring files.

    Closed drawings deliberately fail coverage: opening/saving them during a
    preflight could change application state. Open all project sheets first.
    """
    prefix = '(if (not wd_load) (load "wd_load.lsp")) (wd_load) '
    project = _strings(evaluate(doc, '(progn ' + prefix + '(ace_getactiveproject))'))
    if len(project) != 1 or not project[0]:
        raise RuntimeError('No se pudo determinar el proyecto Electrical activo')
    paths = _strings(evaluate(doc, '(progn ' + prefix + '(nth 5 (c:wd_proj_wdp_data)))'))
    if not paths:
        raise RuntimeError('No se pudo obtener la lista de dibujos del proyecto activo')
    paths = [ntpath.normpath(ntpath.join(ntpath.dirname(project[0]), p)) for p in paths]
    app = doc.Application
    opened = {path_key(app.Documents.Item(i).FullName): app.Documents.Item(i)
              for i in range(app.Documents.Count)}
    snapshot = dict(project=project[0], drawings=paths, active_drawing=doc.FullName,
                    inventory=[], issues=[], complete=True)
    for path in paths:
        current = opened.get(path_key(path))
        if current is None:
            snapshot['complete'] = False
            snapshot['issues'].append(dict(code='drawing_not_inspected', drawing=path))
            continue
        # evaluate only on the active document; registered types of other sheets
        # are read by a short activation, restored even when the call fails.
        try:
            current.Activate()
            wire_types = _strings(evaluate(current, '(progn ' + prefix + '(c:ace_get_wiretype_list nil))'))
            drawing = dict(path=path, components=[], wires=[], wire_types=wire_types)
            for index in range(current.ModelSpace.Count):
                obj = current.ModelSpace.Item(index)
                if obj.ObjectName == 'AcDbBlockReference':
                    attrs = {a.TagString.upper(): a.TextString
                             for a in [*obj.GetConstantAttributes(), *obj.GetAttributes()]}
                    drawing['components'].append(dict(handle=obj.Handle, attributes=attrs))
                elif obj.ObjectName == 'AcDbLine':
                    # WIRES is the conventional unregistered candidate; registered
                    # custom wire layers are also included. Other geometry is ignored.
                    if normalize(obj.Layer) == 'wires' or normalize(obj.Layer) in {normalize(w) for w in wire_types}:
                        drawing['wires'].append(dict(handle=obj.Handle, layer=obj.Layer))
            snapshot['inventory'].append(drawing)
        finally:
            doc.Activate()
    return snapshot


def validate_project(doc=None, planned=(), allow_incomplete_xrefs=False):
    try:
        if doc is None:
            from src.tools.project import _get_conn
            doc = _get_conn().get_active_document()
        return validate_snapshot(collect_snapshot(doc), planned, allow_incomplete_xrefs)
    except Exception as exc:
        return dict(success=False, complete=False, issues=[dict(code='inspection_failed', error=str(exc))])


class ProjectValidationError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('Validación de proyecto fallida: ' + ', '.join(sorted({i['code'] for i in report['issues']})))


def require_valid_project(doc, planned=(), allow_incomplete_xrefs=False):
    report = validate_project(doc, planned, allow_incomplete_xrefs)
    if not report['success']:
        raise ProjectValidationError(report)
    return report


def validate_component_update(doc, tag, changes):
    """Check both current project and the projected attribute state before writing."""
    try:
        snapshot = collect_snapshot(doc)
        current = validate_snapshot(snapshot)
        if not current['success']:
            return current
        matches = [component for drawing in snapshot['inventory']
                   if path_key(drawing['path']) == path_key(doc.FullName)
                   for component in drawing['components']
                   if normalize(component['attributes'].get('TAG1', '')) == normalize(tag)]
        if len(matches) != 1:
            return dict(success=False, issues=[dict(code='ambiguous_update_target', tag=tag)])
        matches[0]['attributes'].update({k.upper(): v for k, v in changes.items()})
        return validate_snapshot(snapshot)
    except Exception as exc:
        return dict(success=False, complete=False, issues=[dict(code='inspection_failed', error=str(exc))])
