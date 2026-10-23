"""Project management tools for AutoCAD Electrical MCP Server.

Provides MCP tools for querying project info, listing drawings, opening/closing
drawings, and running project-wide synchronisation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.autocad.connection import get_connection, AutoCADConnectionError

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


# ---------------------------------------------------------------------------
# MCP Tool functions
# ---------------------------------------------------------------------------

def get_project_info() -> dict[str, Any]:
    """Return information about the currently active AutoCAD Electrical project.

    Queries Electrical's authoritative active WDP and its drawing membership,
    along with the separately listed open documents.

    Returns
    -------
    dict
        Project name, path, and list of drawings.
    """
    try:
        conn = _get_conn()
        app = conn.get_application()
        doc = conn.get_active_document()

        from src.tools.project_management import context
        state = context(doc)
        project_path = state['project']
        project_name = Path(project_path).stem

        drawings: list[str] = []
        for i in range(app.Documents.Count):
            try:
                d = app.Documents.Item(i)
                drawings.append(d.Name)
            except Exception:
                pass

        return {
            "success": True,
            "project_name": project_name,
            "project_path": project_path,
            "project_drawings": state["drawings"],
            "active_drawing": doc.Name,
            "active_drawing_path": doc.FullName,
            "open_drawings": drawings,
            "open_drawing_count": len(drawings),
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("get_project_info failed")
        return {"success": False, "error": str(exc)}


def list_drawings() -> dict[str, Any]:
    """List all drawings currently open in AutoCAD.

    Returns sheet numbers (parsed from drawing names if they follow the
    AutoCAD Electrical naming convention) along with save state.

    Returns
    -------
    dict
        ``{"success": True, "drawings": [...], "count": N}``
    """
    try:
        conn = _get_conn()
        app = conn.get_application()

        drawings: list[dict[str, Any]] = []
        for i in range(app.Documents.Count):
            try:
                d = app.Documents.Item(i)
                # AutoCAD Electrical typically names drawings like "Sheet_01.dwg"
                name = d.Name
                sheet_num = ""
                for part in name.replace("_", " ").split():
                    if part.isdigit():
                        sheet_num = part
                        break
                drawings.append({
                    "name": name,
                    "full_path": d.FullName,
                    "sheet_number": sheet_num,
                    "saved": d.Saved,
                    "active": (d.Name == app.ActiveDocument.Name),
                })
            except Exception:
                pass

        return {
            "success": True,
            "drawings": drawings,
            "count": len(drawings),
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("list_drawings failed")
        return {"success": False, "error": str(exc)}


def open_drawing(sheet_number_or_name: str) -> dict[str, Any]:
    """Open exactly one member of the active WDP; reject ambiguous sheet names."""
    try:
        import ntpath
        from src.tools.project_management import context, resolve_drawing, retry_com
        from src.tools.project_validation import path_key
        app = _get_conn().get_application()
        state = context(app.ActiveDocument)
        path = resolve_drawing(state['drawings'], sheet_number_or_name)
        for i in range(app.Documents.Count):
            doc = app.Documents.Item(i)
            if path_key(doc.FullName) == path_key(path):
                retry_com(lambda: doc.Activate())
                return dict(success=True, drawing=doc.Name, path=path, action='activated')
        doc = app.Documents.Open(path)
        if path_key(retry_com(lambda: doc.FullName)) != path_key(path):
            raise RuntimeError('AutoCAD abrió un dibujo distinto del solicitado')
        return dict(success=True, drawing=ntpath.basename(path), path=path, action='opened')
    except Exception as exc:
        return dict(success=False, error=str(exc))



def close_drawing(save: bool = True) -> dict[str, Any]:
    """Close the currently active drawing.

    Parameters
    ----------
    save : bool
        When ``True`` (default), save the drawing before closing.

    Returns
    -------
    dict
        Success/error dict.
    """
    try:
        conn = _get_conn()
        doc = conn.get_active_document()
        name = doc.Name
        if save:
            doc.Save()
        doc.Close(save)
        return {
            "success": True,
            "drawing": name,
            "saved": save,
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("close_drawing failed")
        return {"success": False, "error": str(exc)}


def sync_project() -> dict[str, Any]:
    """Run a project-wide update/synchronisation via AutoCAD Electrical.

    Sends the ``WDSYNCH`` command which re-numbers wires, updates cross-
    references, and refreshes all project data across all drawings.

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
        conn.send_command("WDSYNCH\n\n")
        return {
            "success": True,
            "message": "WDSYNCH project synchronisation command sent.",
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("sync_project failed")
        return {"success": False, "error": str(exc)}


def get_active_drawing() -> dict[str, Any]:
    """Return information about the currently active drawing.

    Returns
    -------
    dict
        Drawing name, full path, saved state, and entity count.
    """
    try:
        conn = _get_conn()
        doc = conn.get_active_document()
        ms = conn.get_model_space()

        entity_count = 0
        try:
            entity_count = ms.Count
        except Exception:
            pass

        return {
            "success": True,
            "name": doc.Name,
            "full_path": doc.FullName,
            "saved": doc.Saved,
            "entity_count": entity_count,
            "read_only": doc.ReadOnly if hasattr(doc, "ReadOnly") else False,
        }
    except AutoCADConnectionError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("get_active_drawing failed")
        return {"success": False, "error": str(exc)}
