"""Compound circuits assembled from the read-only semantic IEC2 catalog."""
from __future__ import annotations

import math
import re

from src.autocad.utils import point3d, ensure_layer, get_block_attributes, set_block_attributes
from src.tools import electrical, symbol_catalog
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


def create_start_stop_circuit(x: float = 0, y: float = 0, scale: float = 1,
                              coil_tag: str = "KM1") -> dict:
    """Insert STOP NC in series with (START NO || auxiliary NO) and coil.

    x/y locate STOP; scale controls the entire layout. Uses actual XnTERM
    connection positions and WIRES line segments. Auxiliary TAG2 shares the
    coil TAG1. Registers the Electrical wire type and updates cross-references
    when this drawing is saved and belongs to the active project.
    On failure removes only entities created by this call.
    """
    created = []
    doc = None
    undo_started = False
    try:
        x, y, scale = map(float, (x, y, scale))
        if not all(map(math.isfinite, (x, y, scale))) or scale <= 0:
            raise ValueError("Coordenadas finitas y escala positiva requeridas")
        coil_tag = coil_tag.strip()
        if not coil_tag or coil_tag.upper() in ("S0", "S1") or any(ord(c) < 32 for c in coil_tag):
            raise ValueError("Identificador de bobina inválido")
        specs = [
            ("stop", "pulsador NC", 0, 0, {"TAG1": "S0", "DESC1": "PARO", "TERM01": "11", "TERM02": "12"}),
            ("start", "pulsador NA", 0, -60, {"TAG1": "S1", "DESC1": "MARCHA", "TERM01": "13", "TERM02": "14"}),
            ("coil", "bobina de contactor", 0, -120, {"TAG1": coil_tag, "DESC1": "CONTACTOR", "TERM01": "A1", "TERM02": "A2"}),
            ("holding", "VMS21", 60, -60, {"TAG2": coil_tag, "FAMILY": "MS", "DESC1": "ENCLAVAMIENTO", "TERM01": "13", "TERM02": "14"}),
        ]
        # Resolve every symbol before changing the document.
        entries = [symbol_catalog.resolve(electrical.IEC2_LIBRARY, s[1]) for s in specs]
        conn = electrical._get_conn()
        app = conn.get_application()
        if not app.GetAcadState().IsQuiescent:
            raise RuntimeError("AutoCAD está ocupado")
        doc = conn.get_active_document()
        ms = doc.ModelSpace
        for i in range(ms.Count):
            obj = ms.Item(i)
            if obj.ObjectName == "AcDbBlockReference":
                attrs = get_block_attributes(obj)
                tags = {attrs.get(k, "").strip().casefold() for k in ("TAG1", "TAG2")}
                if tags & {"s0", "s1", coil_tag.casefold()}:
                    raise ValueError("Ya existen identificadores del circuito en el dibujo")
        wire_type = ensure_wire_type(doc)
        doc = conn.get_active_document()
        ms = doc.ModelSpace
        doc.StartUndoMark()
        undo_started = True
        ensure_layer(doc, "WIRES", color=1)
        blocks, components = {}, {}
        for spec, entry in zip(specs, entries):
            role, _, dx, dy, attributes = spec
            block = ms.InsertBlock(point3d(x + dx * scale, y + dy * scale),
                                   entry["path"], scale, scale, scale, 0)
            created.append(block)
            actual = configure_attributes(block, attributes)
            terminals = connection_points(block)
            blocks[role] = terminals
            components[role] = {"handle": block.Handle, "symbol": entry["symbol"],
                                "attributes": actual, "terminals": terminals}
        if (components["holding"]["attributes"].get("TAG2") != components["coil"]["attributes"].get("TAG1")
                or components["holding"]["attributes"].get("FAMILY") != components["coil"]["attributes"].get("FAMILY")):
            raise RuntimeError("El auxiliar no está asociado a la bobina")
        stop_top, stop_bottom = blocks["stop"]
        start_top, start_bottom = blocks["start"]
        coil_top, coil_bottom = blocks["coil"]
        holding_top, holding_bottom = blocks["holding"]
        upper = [x, y - 30 * scale, 0]
        lower = [x, y - 90 * scale, 0]
        upper_right = [holding_top[0], upper[1], 0]
        lower_right = [holding_bottom[0], lower[1], 0]
        segments = [([x, y + 30 * scale, 0], stop_top), (stop_bottom, upper),
                    (upper, start_top), (start_bottom, lower), (lower, coil_top),
                    (coil_bottom, [x, y - 150 * scale, 0]),
                    (upper, upper_right), (upper_right, holding_top),
                    (holding_bottom, lower_right), (lower_right, lower)]
        wires = []
        for p, q in segments:
            if math.dist(p, q) <= 1e-8:
                raise ValueError("Conductor de longitud cero")
            line = ms.AddLine(point3d(*p), point3d(*q))
            created.append(line)
            line.Layer = "WIRES"
            wires.append({"handle": line.Handle, "start": p, "end": q})
        doc.Regen(1)
        doc.EndUndoMark()
        undo_started = False
        try:
            cross_references = update_cross_references(
                doc, components["coil"]["handle"], components["holding"]["handle"])
        except Exception as exc:
            cross_references = {"success": False, "status": "failed", "error": str(exc)}
        for component in components.values():
            component["attributes"] = get_block_attributes(doc.HandleToObject(component["handle"]))
        return {"success": True, "drawing": doc.Name, "components": components,
                "wire_type": wire_type, "cross_references": cross_references,
                "wires": wires, "junctions": [upper, lower],
                "supply_terminals": [[x, y + 30 * scale, 0], [x, y - 150 * scale, 0]],
                "topology": "STOP_NC -- (START_NO || KM_AUX_NO) -- KM_COIL",
                "note": "Conductores registrados en Electrical; consultar cross_references para el resultado de actualización."}
    except Exception as exc:
        remaining = []
        for entity in reversed(created):
            try:
                entity.Delete()
            except Exception:
                try:
                    remaining.append(entity.Handle)
                except Exception:
                    remaining.append("unknown")
        return {"success": False, "error": str(exc), "remaining_handles": remaining}
    finally:
        if undo_started:
            doc.EndUndoMark()
