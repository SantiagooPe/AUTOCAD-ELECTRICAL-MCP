"""Compound circuits assembled from the read-only semantic IEC2 catalog."""
from __future__ import annotations

import math
import logging

from src.autocad.utils import get_block_attributes
from src.tools import electrical, symbol_catalog
from src.tools.electrical_primitives import (
    ensure_wire_type, update_cross_references, connection_points, configure_attributes,
    insert_iec_component, create_electrical_wires, associate_parent_child,
    number_wire,
)


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
        doc.StartUndoMark()
        undo_started = True
        blocks, components = {}, {}
        for spec, entry in zip(specs, entries):
            role, _, dx, dy, attributes = spec
            component = insert_iec_component(
                doc, electrical.IEC2_LIBRARY, spec[1], x + dx * scale, y + dy * scale,
                scale, attributes=attributes, entry=entry, created=created,
                require_vertical_terminals=True)
            blocks[role] = component["terminals"]
            components[role] = component
        components["holding"]["attributes"] = associate_parent_child(
            doc, components["coil"]["handle"], components["holding"]["handle"],
            assign=False, identity_keys=("FAMILY",))
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
        wires = create_electrical_wires(doc, segments, created=created, register_type=False)
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


def create_reversing_circuit(x: float = 0, y: float = 0, scale: float = 1) -> dict:
    """Compose common STOP and two maintained, cross-interlocked control branches.

    S0/S1/S2 and KM1/KM2 must be unused. Seven native wire networks receive
    numbers 101..107. XREF requires a saved drawing in the active project.
    A completed drawing is retained if final numbering/XREF verification fails,
    with success=False and explicit stage results so callers can repair it.
    """
    created, components, segments, representatives = [], {}, [], []
    wires, numbering, references = [], [], []
    doc, undo_started, assembled = None, False, False
    try:
        x, y, scale = map(float, (x, y, scale))
        if not all(map(math.isfinite, (x, y, scale))) or scale <= 0:
            raise ValueError("Coordenadas finitas y escala positiva requeridas")
        specs = [("stop", "pulsador NC", 0, 0,
                  {"TAG1": "S0", "DESC1": "PARO", "TERM01": "11", "TERM02": "12"})]
        for direction, dx, tag, other, button, label in (
                ("forward", 0, "KM1", "KM2", "S1", "ADELANTE"),
                ("reverse", 180, "KM2", "KM1", "S2", "REVERSA")):
            for role, symbol, cx, cy, attrs in (
                    ("start", "pulsador NA", dx, -60, {"TAG1": button, "DESC1": "MARCHA " + label, "TERM01": "13", "TERM02": "14"}),
                    ("holding", "VMS21", dx + 60, -60, {"TAG2": tag, "DESC1": "MANTENIMIENTO", "TERM01": "13", "TERM02": "14"}),
                    ("interlock", "VMS22", dx, -120, {"TAG2": other, "DESC1": "ENCLAVAMIENTO", "TERM01": "21", "TERM02": "22"}),
                    ("coil", "bobina de contactor", dx, -180, {"TAG1": tag, "DESC1": label, "TERM01": "A1", "TERM02": "A2"})):
                specs.append((direction + "_" + role, symbol, cx, cy, attrs))
        entries = [symbol_catalog.resolve(electrical.IEC2_LIBRARY, spec[1]) for spec in specs]
        conn = electrical._get_conn()
        if not conn.get_application().GetAcadState().IsQuiescent:
            raise RuntimeError("AutoCAD está ocupado")
        doc = conn.get_active_document()
        for i in range(doc.ModelSpace.Count):
            obj = doc.ModelSpace.Item(i)
            if obj.ObjectName == "AcDbBlockReference":
                attrs = get_block_attributes(obj)
                if any(attrs.get(k, "").strip().casefold() in {"s0", "s1", "s2", "km1", "km2"} for k in ("TAG1", "TAG2")):
                    raise ValueError("Ya existen identificadores del circuito en el dibujo")
        wire_type = ensure_wire_type(doc)
        doc = conn.get_active_document()
        doc.StartUndoMark()
        undo_started = True
        for spec, entry in zip(specs, entries):
            role, symbol, dx, dy, attrs = spec
            components[role] = insert_iec_component(doc, electrical.IEC2_LIBRARY, symbol,
                x + dx * scale, y + dy * scale, scale, attributes=attrs,
                entry=entry, created=created, require_vertical_terminals=True)
        pairs = [("forward_coil", "forward_holding"), ("forward_coil", "reverse_interlock"),
                 ("reverse_coil", "reverse_holding"), ("reverse_coil", "forward_interlock")]
        for parent, child in pairs:
            associate_parent_child(doc, components[parent]["handle"], components[child]["handle"])
        def point(dx, dy):
            return [x + dx * scale, y + dy * scale, 0]
        def wire(a, b, numbered=False):
            if numbered:
                representatives.append(len(segments))
            segments.append((a, b))
        supply, neutral = point(0, 30), point(0, -210)
        wire(supply, components["stop"]["terminals"][0], True)
        wire(components["stop"]["terminals"][1], point(0, -30), True)
        # Split buses at every branch endpoint for native network recognition.
        for a, b in ((0, 60), (60, 180), (180, 240)):
            wire(point(a, -30), point(b, -30))
        for direction, dx in (("forward", 0), ("reverse", 180)):
            start, holding, interlock, coil = [components[direction + "_" + role]["terminals"]
                                                for role in ("start", "holding", "interlock", "coil")]
            wire(point(dx, -30), start[0])
            wire(point(dx + 60, -30), holding[0])
            wire(start[1], point(dx, -90), True)
            wire(holding[1], point(dx + 60, -90))
            wire(point(dx + 60, -90), point(dx, -90))
            wire(point(dx, -90), interlock[0])
            wire(interlock[1], coil[0], True)
            wire(coil[1], point(dx, -210))
        wire(neutral, point(180, -210), True)
        wires = create_electrical_wires(doc, segments, created=created, register_type=False)
        doc.Regen(1)
        doc.EndUndoMark()
        undo_started = False
        assembled = True
        for index, representative in enumerate(representatives, 101):
            try:
                numbering.append(dict(number_wire(doc, wires[representative]["handle"], str(index)), success=True))
            except Exception as exc:
                numbering.append({"success": False, "wire_number": str(index),
                                  "handle": wires[representative]["handle"], "error": str(exc)})
        for parent, child in pairs:
            try:
                doc = conn.get_active_document()
                references.append(update_cross_references(doc, components[parent]["handle"], components[child]["handle"]))
            except Exception as exc:
                references.append({"success": False, "status": "failed", "error": str(exc),
                                   "parent_handle": components[parent]["handle"],
                                   "child_handle": components[child]["handle"]})
        doc = conn.get_active_document()
        for component in components.values():
            component["attributes"] = get_block_attributes(doc.HandleToObject(component["handle"]))
        return {"success": all(r["success"] for r in numbering + references),
                "assembled": True, "drawing": doc.Name, "components": components,
                "wires": wires, "wire_type": wire_type, "wire_numbers": numbering,
                "cross_references": references, "supply_terminals": [supply, point(180, -210)],
                "topology": "STOP_NC -- [(S1_NO || KM1_NO) -- KM2_NC -- KM1; (S2_NO || KM2_NO) -- KM1_NC -- KM2]"}
    except Exception as exc:
        remaining = []
        if not assembled:
            for entity in reversed(created):
                try:
                    entity.Delete()
                except Exception:
                    try:
                        remaining.append(entity.Handle)
                    except Exception:
                        remaining.append("unknown")
        result = {"success": False, "assembled": assembled, "error": str(exc), "remaining_handles": remaining}
        if assembled:
            result.update(components=components, wires=wires, wire_numbers=numbering,
                          cross_references=references)
        return result
    finally:
        if undo_started:
            try:
                conn.get_active_document().EndUndoMark()
            except Exception:
                logging.getLogger(__name__).exception("Could not close reversing circuit undo group")


def create_star_delta_circuit(x: float = 0, y: float = 0, scale: float = 1, transition_seconds: float = 5) -> dict:
    """Compose maintained star/delta control with on-delay KT1 and cross NC interlocks.

    transition_seconds labels the timer setting in seconds. Numbering/XREF
    failures retain the assembled drawing for repair. IEC2 is read only.
    """
    created, components, segments, representatives = [], {}, [], []
    wires, numbering, references = [], [], []
    doc, undo_started, assembled = None, False, False
    try:
        x, y, scale = map(float, (x, y, scale))
        if not all(map(math.isfinite, (x, y, scale))) or scale <= 0:
            raise ValueError("Coordenadas finitas y escala positiva requeridas")
        transition_seconds = float(transition_seconds)
        if not math.isfinite(transition_seconds) or transition_seconds <= 0:
            raise ValueError("Tiempo de transición finito y positivo requerido")
        specs = []
        def spec(role, symbol, dx, dy, tag, label, nc=False, coil=False, **extra):
            attrs = {"TAG1" if coil or role in ("stop", "start") else "TAG2": tag,
                     "DESC1": label, "TERM01": "A1" if coil else "11" if nc else "13",
                     "TERM02": "A2" if coil else "12" if nc else "14", **extra}
            specs.append((role, symbol, dx, dy, attrs))
        spec("stop", "pulsador NC", 0, 0, "S0", "PARO", nc=True)
        spec("start", "pulsador NA", 0, -60, "S1", "MARCHA")
        spec("holding", "VMS21", 60, -60, "KM1", "MANTENIMIENTO")
        for role, dx, tag, symbol, label in (
                ("main_coil", 0, "KM1", "VMS1", "PRINCIPAL"),
                ("timer_coil", 120, "KT1", "VTD1N", "TEMPORIZADOR"),
                ("star_coil", 240, "KM2", "VMS1", "ESTRELLA"),
                ("delta_coil", 360, "KM3", "VMS1", "TRIANGULO")):
            extra = {"DESC2": f"{transition_seconds:g} s"} if tag == "KT1" else {}
            spec(role, symbol, dx, -330, tag, label, coil=True, **extra)
        spec("star_timer", "VTD22N", 240, -150, "KT1", "APERTURA TEMPORIZADA", nc=True)
        spec("delta_timer", "VTD21N", 360, -150, "KT1", "CIERRE TEMPORIZADO")
        spec("star_interlock", "VMS22", 240, -240, "KM3", "BLOQUEO TRIANGULO", nc=True)
        spec("delta_interlock", "VMS22", 360, -240, "KM2", "BLOQUEO ESTRELLA", nc=True)
        entries = [symbol_catalog.resolve(electrical.IEC2_LIBRARY, spec[1]) for spec in specs]
        conn = electrical._get_conn()
        if not conn.get_application().GetAcadState().IsQuiescent:
            raise RuntimeError("AutoCAD está ocupado")
        doc = conn.get_active_document()
        for i in range(doc.ModelSpace.Count):
            obj = doc.ModelSpace.Item(i)
            if obj.ObjectName == "AcDbBlockReference":
                attrs = get_block_attributes(obj)
                if any(attrs.get(k, "").strip().casefold() in {"s0", "s1", "km1", "km2", "km3", "kt1"} for k in ("TAG1", "TAG2")):
                    raise ValueError("Ya existen identificadores del circuito en el dibujo")
        wire_type = ensure_wire_type(doc)
        doc = conn.get_active_document()
        doc.StartUndoMark()
        undo_started = True
        for spec, entry in zip(specs, entries):
            role, symbol, dx, dy, attrs = spec
            components[role] = insert_iec_component(doc, electrical.IEC2_LIBRARY, symbol,
                x + dx * scale, y + dy * scale, scale, attributes=attrs,
                entry=entry, created=created, require_vertical_terminals=True)
        pairs = [("main_coil", "holding"), ("timer_coil", "star_timer"),
                 ("timer_coil", "delta_timer"), ("star_coil", "delta_interlock"),
                 ("delta_coil", "star_interlock")]
        for parent, child in pairs:
            associate_parent_child(doc, components[parent]["handle"], components[child]["handle"])
        def point(dx, dy):
            return [x + dx * scale, y + dy * scale, 0]
        def wire(a, b, numbered=False):
            if numbered:
                representatives.append(len(segments))
            segments.append((a, b))
        supply, neutral = point(0, 30), point(360, -390)
        def terminals(role):
            return components[role]["terminals"]
        wire(supply, terminals("stop")[0], True)
        wire(terminals("stop")[1], point(0, -30), True)
        wire(point(0, -30), terminals("start")[0])
        wire(point(0, -30), point(60, -30))
        wire(point(60, -30), terminals("holding")[0])
        wire(terminals("start")[1], point(0, -90), True)
        wire(terminals("holding")[1], point(60, -90))
        # Split every bus at branch endpoints for native Electrical netlists.
        for a, b in ((0, 60), (60, 120), (120, 240), (240, 360)):
            wire(point(a, -90), point(b, -90))
        for role, dx in (("main", 0), ("timer", 120), ("star", 240), ("delta", 360)):
            top, bottom = terminals(role + "_coil")
            if role in ("star", "delta"):
                timed, interlock = terminals(role + "_timer"), terminals(role + "_interlock")
                wire(point(dx, -90), timed[0])
                wire(timed[1], interlock[0], True)
                wire(interlock[1], top, True)
            else:
                wire(point(dx, -90), top)
            wire(bottom, point(dx, -390))
        for a, b in ((0, 120), (120, 240), (240, 360)):
            wire(point(a, -390), point(b, -390), a == 0)
        wires = create_electrical_wires(doc, segments, created=created, register_type=False)
        doc.Regen(1)
        doc.EndUndoMark()
        undo_started = False
        assembled = True
        for index, representative in enumerate(representatives, 101):
            try:
                numbering.append(dict(number_wire(doc, wires[representative]["handle"], str(index)), success=True))
            except Exception as exc:
                numbering.append({"success": False, "wire_number": str(index),
                                  "handle": wires[representative]["handle"], "error": str(exc)})
        for parent, child in pairs:
            try:
                doc = conn.get_active_document()
                references.append(update_cross_references(doc, components[parent]["handle"], components[child]["handle"]))
            except Exception as exc:
                references.append({"success": False, "status": "failed", "error": str(exc),
                                   "parent_handle": components[parent]["handle"],
                                   "child_handle": components[child]["handle"]})
        doc = conn.get_active_document()
        for component in components.values():
            component["attributes"] = get_block_attributes(doc.HandleToObject(component["handle"]))
        return {"success": all(r["success"] for r in numbering + references),
                "assembled": True, "drawing": doc.Name, "components": components,
                "wires": wires, "wire_type": wire_type, "wire_numbers": numbering,
                "cross_references": references, "supply_terminals": [supply, neutral],
                "transition_seconds": transition_seconds,
                "topology": "STOP_NC -- (START_NO || KM1_NO) -- [KM1; KT1; KT1_NC -- KM3_NC -- KM2; KT1_NO -- KM2_NC -- KM3]"}

    except Exception as exc:
        remaining = []
        if not assembled:
            for entity in reversed(created):
                try:
                    entity.Delete()
                except Exception:
                    try:
                        remaining.append(entity.Handle)
                    except Exception:
                        remaining.append("unknown")
        result = {"success": False, "assembled": assembled, "error": str(exc), "remaining_handles": remaining}
        if assembled:
            result.update(components=components, wires=wires, wire_numbers=numbering,
                          cross_references=references)
        return result
    finally:
        if undo_started:
            try:
                conn.get_active_document().EndUndoMark()
            except Exception:
                logging.getLogger(__name__).exception("Could not close star/delta circuit undo group")
