"""Reusable Electrical operations. IEC2 source drawings are read only."""
import math
import re
from src.autocad.utils import point3d, ensure_layer, get_block_attributes, set_block_attributes
from src.autocad.lisp import evaluate, quote
from src.tools import symbol_catalog
from src.tools.electrical_native import ensure_wire_type, update_cross_references

def connection_points(block):
    """Read Electrical wire attributes in WCS, including constant attributes."""
    attrs = (*block.GetAttributes(), *block.GetConstantAttributes())
    points = [list(a.InsertionPoint) for a in attrs
              if re.fullmatch(r"X[1248]TERM\d+", a.TagString.upper())]
    if len(points) != 2:
        raise ValueError(f"{block.Name}: se esperaban dos bornes, hay {len(points)}")
    points.sort(key=lambda p: -p[1])
    if abs(points[0][0] - points[1][0]) > 1e-6 or points[0][1] <= points[1][1]:
        raise ValueError("El circuito requiere símbolos verticales con dos bornes alineados")
    return points


def configure_attributes(block, expected):
    """Format this reference only; retain Electrical metadata and IEC2 sources."""
    if set_block_attributes(block, expected) != len(expected):
        raise RuntimeError("No se pudieron asignar los atributos del componente")
    visible = re.compile(r"TAG[12]|DESC[123]|TERM\d+|XREF(?:NO|NC)?")
    for attr in block.GetAttributes():
        tag = attr.TagString.upper()
        attr.Invisible = not bool(visible.fullmatch(tag))
        attr.Update()
    actual = get_block_attributes(block)
    if any(actual.get(tag) != value for tag, value in expected.items()):
        raise RuntimeError("Los atributos insertados no coinciden con los solicitados")
    return actual


def insert_iec_component(doc, library, symbol, x, y, scale=1, rotation=0,
                         attributes=None, *, entry=None, created=None,
                         require_vertical_terminals=False):
    """Insert a catalog symbol; rotation is in degrees.

    An optional pre-resolved entry permits preflight of compound circuits.
    Record each entity immediately in the caller's rollback journal.
    """
    x, y, scale, rotation = map(float, (x, y, scale, rotation))
    if not all(map(math.isfinite, (x, y, scale, rotation))) or scale <= 0:
        raise ValueError("Coordenadas finitas y escala positiva requeridas")
    if entry is None:
        entry = symbol_catalog.resolve(library, symbol)
    block = doc.ModelSpace.InsertBlock(point3d(x, y), entry["path"],
                                       scale, scale, scale, math.radians(rotation))
    if created is not None:
        created.append(block)
    try:
        actual = configure_attributes(block, attributes or {})
        result = {"handle": block.Handle, "symbol": entry["symbol"], "attributes": actual}
        if require_vertical_terminals:
            result["terminals"] = connection_points(block)
        return result
    except Exception:
        if created is None:
            block.Delete()
        raise


def create_electrical_wires(doc, segments, layer="WIRES", *, created=None,
                            register_type=True):
    """Create LINEs on a native Electrical wire type, enabled for numbering.

    register_type=False requires prior ensure_wire_type on this document.
    Validate all geometry before inserting and journal partial failures.
    """
    segments = [(list(p), list(q)) for p, q in segments]
    for p, q in segments:
        if (len(p) != 3 or len(q) != 3
                or not all(math.isfinite(v) for v in (*p, *q))):
            raise ValueError("Bornes WCS finitos de tres coordenadas requeridos")
        if math.dist(p, q) <= 1e-8:
            raise ValueError("Conductor de longitud cero")
    if register_type:
        ensure_wire_type(doc, layer)
    ensure_layer(doc, layer, color=1)
    journal = created if created is not None else []
    wires = []
    try:
        for p, q in segments:
            line = doc.ModelSpace.AddLine(point3d(*p), point3d(*q))
            journal.append(line)
            line.Layer = layer
            wires.append({"handle": line.Handle, "start": p, "end": q})
        return wires
    except Exception:
        if created is None:
            for line in reversed(journal):
                line.Delete()
        raise


def number_wire(doc, wire_handle, number):
    """Assign a native Electrical wire number by handle using wd_putwn."""
    number = str(number).strip()
    if not number or any(ord(c) < 32 for c in number):
        raise ValueError("Número de conductor inválido")
    wire = doc.HandleToObject(wire_handle)
    if wire.ObjectName != "AcDbLine":
        raise ValueError("El conductor debe ser una línea Electrical")
    ensure_wire_type(doc, wire.Layer)
    value = evaluate(doc, f'(c:wd_putwn (handent {quote(wire_handle)}) {quote(number)})')
    if value in ("nil", "", None):
        raise RuntimeError("No se confirmó la numeración Electrical")
    return {"handle": wire_handle, "wire_number": number}


def associate_parent_child(doc, parent_handle, child_handle, *, assign=True,
                           identity_keys=("FAMILY", "INST", "LOC")):
    """Associate instance identities, or validate an already assigned pair.

    identity_keys allows legacy assemblers to retain their identity policy.
    Cross-reference updates always validate the full Electrical identity.
    """
    parent = get_block_attributes(doc.HandleToObject(parent_handle))
    child = doc.HandleToObject(child_handle)
    if not parent.get("TAG1"):
        raise ValueError("El padre requiere TAG1")
    existing = get_block_attributes(child)
    if not assign:
        if (existing.get("TAG2") != parent["TAG1"]
                or any(existing.get(key) != parent.get(key) for key in identity_keys)):
            raise RuntimeError("El auxiliar no está asociado a la bobina")
        return existing
    expected = {"TAG2": parent["TAG1"]}
    for key in identity_keys:
        value = parent.get(key, "")
        if key in existing:
            expected[key] = value
        elif value:
            raise ValueError(f"El hijo requiere {key}")
    return configure_attributes(child, expected)



