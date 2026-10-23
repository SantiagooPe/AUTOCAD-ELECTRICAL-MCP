"""AutoCAD Electrical-specific tools.

Provides MCP tools for electrical symbols, ladder diagrams, PLC modules,
cross-references, wire number tags, and component attributes.

Symbols from the local AutoCAD Electrical 2023 IEC2 library are inserted
synchronously through COM ModelSpace.InsertBlock. Other Electrical commands
are sent through SendCommand.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any
from src.tools import symbol_catalog

from src.autocad.connection import get_connection, AutoCADConnectionError
from src.autocad.utils import point3d, get_block_attributes, set_block_attributes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_conn():
    conn = get_connection(auto_connect=False)
    if not conn.is_connected():
        try:
            conn.connect()
        except AutoCADConnectionError as exc:
            raise AutoCADConnectionError(str(exc)) from exc
    return conn


def _run_lisp(conn, expr: str) -> None:
    """Send a LISP expression to AutoCAD via SendCommand."""
    conn.send_command(f"{expr}\n")


IEC2_LIBRARY = Path(
    r"C:\Users\Public\Documents\Autodesk\Acade 2023\Libs\iec2"
)

SEMANTIC_SYMBOLS = {
    "contacto normalmente abierto": "VCR21.dwg",
    "contacto na": "VCR21.dwg",
    "contacto no": "VCR21.dwg",

    "contacto normalmente cerrado": "VCR22.dwg",
    "contacto nc": "VCR22.dwg",
}


def _insert_symbol(
    symbol_name: str,
    x: float,
    y: float,
    scale: float,
    rotation: float,
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve a local DWG and insert it synchronously via COM."""
    try:
        x, y, scale, rotation = map(float, (x, y, scale, rotation))
        if not all(math.isfinite(v) for v in (x, y, scale, rotation)) or scale <= 0:
            raise ValueError("Coordinates and rotation must be finite; scale must be positive.")
        key = " ".join(symbol_name.strip().lower().split())
        aliases = {**SEMANTIC_SYMBOLS, "wd_nopen": "VCR21.dwg", "wd_nclose": "VCR22.dwg"}
        filename = aliases.get(key, symbol_name.strip())
        # Accept only a filename from the configured library, never arbitrary paths.
        if not filename or Path(filename).name != filename or any(c in filename for c in '/\\:'):
            raise ValueError("Use a symbol name from the IEC2 library, without a path.")
        resolved = symbol_catalog.resolve(IEC2_LIBRARY, filename)
        symbol_path = Path(resolved["path"])
        if not symbol_path.is_file():
            return {"success": False, "error": f"No existe el símbolo: {symbol_path}"}
        conn = _get_conn()
        from src.tools.project_validation import require_valid_project
        attrs = {k.upper(): v for k, v in (attributes or {}).items()}
        if not (attrs.get('TAG1', '').strip() or attrs.get('TAG2', '').strip()):
            raise ValueError('Se requiere TAG1 o TAG2 explícito para evitar identificadores heredados')
        if any(v.strip() for k, v in attrs.items() if k.startswith('XREF')):
            raise ValueError('Las referencias se generan en el proyecto destino')
        require_valid_project(conn.get_active_document(), [attrs])
        if conn.get_application().GetAcadState().IsQuiescent is False:
            return {
                "success": False,
                "error": "AutoCAD está ocupado. Terminá el comando activo o cerrá el diálogo y reintentá.",
            }
        block = conn.get_model_space().InsertBlock(
            point3d(x, y), str(symbol_path), scale, scale, scale, math.radians(rotation)
        )
        result = {
            "success": True, "symbol": symbol_path.name, "path": str(symbol_path),
            "insertion_point": [x, y], "scale": scale, "rotation": rotation,
            "handle": block.Handle,
        }
        if attributes:
            result["attributes_set"] = set_block_attributes(block, attrs)
            if result["attributes_set"] < len(attributes):
                block.Delete()
                raise RuntimeError('No se pudieron asignar los atributos solicitados; inserción eliminada')
        # Only this instance is changed; source IEC2 files remain read-only.
        for attr in block.GetAttributes():
            if attr.TagString.upper().startswith('XREF'):
                attr.TextString = ''
                attr.Update()
        return result
    except Exception as exc:
        logger.exception("Electrical symbol insertion failed")
        return {"success": False, "error": str(exc)}


def insert_component(
    component_type: str,
    x: float,
    y: float,
    scale: float = 2.0,
    rotation: float = 0.0,
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Insert contacts, coils, pushbuttons, contactors, motors, overloads or timers.

    VCR21.dwg is normally open; VCR22.dwg is normally closed.
    Coordinates are drawing units; rotation is in degrees, scale defaults to 2.
    This inserts a block with attributes, without automatic wire breaking or
    project cross-reference updates.
    """
    result = _insert_symbol(component_type, x, y, scale, rotation, attributes)
    result["component"] = component_type
    return result


def insert_electrical_symbol(
    symbol_name: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    attributes: dict[str, str] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Insert a local IEC2 DWG via COM, e.g. VCR21 or VCR22 (optional .dwg).

    Legacy WD_NOPEN/WD_NCLOSE aliases resolve to VCR21/VCR22. Returns the
    inserted block handle and applies attributes directly to that block.
    Rotation is in degrees. No automatic wire breaking or project updates.
    """
    return _insert_symbol(symbol_name, x, y, scale, rotation, attributes)


def insert_ladder(
    x_start: float,
    y_start: float,
    rung_spacing: float = 25.4,
    rung_count: int = 10,
    voltage: str = "120V",
    phase: str = "1P",
) -> dict[str, Any]:
    """Create a ladder diagram via AutoCAD Electrical's WDLADDER command.

    The command is sent as a LISP string so it runs inside AutoCAD Electrical's
    own environment and respects the current project settings.

    Parameters
    ----------
    x_start, y_start : float
        Origin of the ladder (top-left corner of the first rung).
    rung_spacing : float
        Vertical distance between rungs in drawing units (default 25.4 mm / 1 inch).
    rung_count : int
        Number of rungs to create.
    voltage : str
        Voltage label for the ladder (e.g. ``"120V"``, ``"24VDC"``).
    phase : str
        Phase designation: ``"1P"`` (single) or ``"3P"`` (three-phase).

    Returns
    -------
    dict
        Success/error dict.
    """
    try:
        conn = _get_conn()
        # WDLADDER command syntax (AutoCAD Electrical):
        # Command: WDLADDER
        # Then prompts for: start point, rung spacing, number of rungs, etc.
        # We drive it programmatically via SendCommand with newline-separated answers.
        cmd = (
            f"WDLADDER\n"
            f"{x_start},{y_start}\n"  # insertion point
            f"{rung_spacing}\n"       # rung spacing
            f"{rung_count}\n"         # rung count
            f"{voltage}\n"            # voltage label
            f"{phase}\n"              # phase
            f"\n"                     # accept defaults / end
        )
        conn.send_command(cmd)
        return {
            "success": True,
            "start": [x_start, y_start],
            "rung_spacing": rung_spacing,
            "rung_count": rung_count,
            "voltage": voltage,
            "phase": phase,
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("insert_ladder failed")
        return {"success": False, "error": str(exc)}


def get_symbol_list(category: str = "") -> dict[str, Any]:
    """List actual DWG files in the local IEC2 library; contacts are VCR21/22."""
    try:
        if not IEC2_LIBRARY.is_dir():
            return {"success": False, "error": f"No existe la biblioteca: {IEC2_LIBRARY}"}
        entries = symbol_catalog.inventory(IEC2_LIBRARY)
        names = sorted(e["symbol"] for e in entries)
        cat = category.strip().lower()
        if cat == "contacts":
            names = [n for n in names if n.upper() in ("VCR21", "VCR22")]
        elif cat:
            names = [e["symbol"] for e in entries if symbol_catalog.normalize(cat) in (symbol_catalog.normalize(e["category"]), *map(symbol_catalog.normalize, e["aliases"]))]
        return {
            "success": True, "category": cat or "all", "symbols": names,
            "by_category": {cat or "all": names}, "count": len(names),
            "library": str(IEC2_LIBRARY), "semantic_symbols": SEMANTIC_SYMBOLS,
        }
    except OSError as exc:
        return {"success": False, "error": str(exc)}


def search_symbols(query: str = "", orientation: str = "", category: str = "", limit: int = 50) -> dict[str, Any]:
    """Search local symbols by Spanish names, DWG code or menu description."""
    try:
        if not 1 <= limit <= 500:
            raise ValueError("limit debe estar entre 1 y 500")
        matches = symbol_catalog.search(IEC2_LIBRARY, query, orientation, category)
        return {"success": True, "symbols": matches[:limit], "count": len(matches), "truncated": len(matches) > limit, "library": str(IEC2_LIBRARY)}
    except (OSError, ValueError) as exc:
        return {"success": False, "error": str(exc)}


def set_wire_number(
    wire_number: str,
    x: float,
    y: float,
) -> dict[str, Any]:
    """Place a wire number tag at the given coordinates.

    Uses the AutoCAD Electrical ``WDWNUM`` command to insert the tag so that
    it is properly associated with the wire it overlaps.

    Parameters
    ----------
    wire_number : str
        The wire number string (e.g. ``"101"``, ``"L1"``).
    x, y : float
        Insertion point for the wire number tag.

    Returns
    -------
    dict
        Success/error dict.
    """
    try:
        conn = _get_conn()
        # WDWNUM: Place wire number at a specific location
        cmd = f"WDWNUM\n{x},{y}\n{wire_number}\n\n"
        conn.send_command(cmd)
        return {
            "success": True,
            "wire_number": wire_number,
            "position": [x, y],
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("set_wire_number failed")
        return {"success": False, "error": str(exc)}


def insert_plc_module(
    module_type: str,
    rack: int,
    slot: int,
    x: float,
    y: float,
) -> dict[str, Any]:
    """Insert a PLC I/O module symbol.

    Parameters
    ----------
    module_type : str
        Module type: ``"input"``, ``"output"``, ``"analog_input"``,
        ``"analog_output"``.
    rack : int
        PLC rack number (0-based).
    slot : int
        Slot number within the rack (0-based).
    x, y : float
        Insertion point.

    Returns
    -------
    dict
        Success/error dict.
    """
    _TYPE_MAP = {
        "input": "WD_PLC_IN",
        "output": "WD_PLC_OUT",
        "analog_input": "WD_PLC_AI",
        "analog_output": "WD_PLC_AO",
    }
    symbol = _TYPE_MAP.get(module_type.lower(), "WD_PLC_IN")
    attrs = {
        "RACK": str(rack),
        "SLOT": str(slot),
        "TAG1": f"R{rack:02d}S{slot:02d}",
        "DESC1": f"PLC {module_type.replace('_', ' ').title()}",
    }
    result = insert_electrical_symbol(symbol, x, y, attributes=attrs)
    if result.get("success"):
        result.update({"module_type": module_type, "rack": rack, "slot": slot})
    return result


def create_cross_reference(
    source_tag: str,
    dest_sheet: str,
    dest_ref: str,
) -> dict[str, Any]:
    """Create a cross-reference link between a source component and a destination.

    Uses AutoCAD Electrical's ``WDXREF`` command.

    Parameters
    ----------
    source_tag : str
        TAG1 of the source component (e.g. ``"101CR"``).
    dest_sheet : str
        Destination drawing sheet number (e.g. ``"3"``).
    dest_ref : str
        Reference designation on the destination sheet (e.g. ``"B12"``).

    Returns
    -------
    dict
        Success/error dict.
    """
    try:
        conn = _get_conn()
        from src.tools.project_validation import validate_project
        validation = validate_project(conn.get_active_document())
        if not validation["success"]:
            return {"success": False, "validation": validation, "error": "Validación de proyecto fallida"}
        cmd = f"WDXREF\n{source_tag}\n{dest_sheet}\n{dest_ref}\n\n"
        conn.send_command(cmd)
        return {
            "success": True,
            "source_tag": source_tag,
            "dest_sheet": dest_sheet,
            "dest_ref": dest_ref,
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("create_cross_reference failed")
        return {"success": False, "error": str(exc)}


def edit_component_attributes(
    tag1: str,
    attributes_dict: dict[str, str],
) -> dict[str, Any]:
    """Update attribute values on a component identified by TAG1.

    Searches ModelSpace for a block reference whose TAG1 attribute matches,
    then applies the provided attribute updates.

    Parameters
    ----------
    tag1 : str
        The component's TAG1 value (case-insensitive search).
    attributes_dict : dict[str, str]
        Attribute tag → new value mapping.

    Returns
    -------
    dict
        Success/error dict with the number of attributes updated.
    """
    try:
        conn = _get_conn()
        from src.tools.project_validation import validate_component_update
        validation = validate_component_update(conn.get_active_document(), tag1, attributes_dict)
        if not validation["success"]:
            return {"success": False, "validation": validation, "error": "Validación de proyecto fallida"}
        doc = conn.get_active_document()
        ms = conn.get_model_space()

        target = None
        for i in range(ms.Count):
            try:
                obj = ms.Item(i)
                if obj.ObjectName != "AcDbBlockReference":
                    continue
                attrs = get_block_attributes(obj)
                if attrs.get("TAG1", "").upper() == tag1.upper():
                    target = obj
                    break
            except Exception:
                continue

        if target is None:
            return {
                "success": False,
                "error": f"Component with TAG1='{tag1}' not found in current drawing.",
            }

        updated = set_block_attributes(target, attributes_dict)
        doc.Regen(1)  # acAllViewports
        return {
            "success": True,
            "tag1": tag1,
            "attributes_updated": updated,
            "handle": target.Handle,
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("edit_component_attributes failed")
        return {"success": False, "error": str(exc)}
