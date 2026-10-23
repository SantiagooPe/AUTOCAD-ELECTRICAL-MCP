"""Electrical 2023 APIs, documented in the installed ACE_API.chm."""
from src.autocad.lisp import evaluate, quote
from src.autocad.utils import get_block_attributes


def ensure_wire_type(doc, layer="WIRES"):
    name = quote(layer)
    value = evaluate(doc, f'''(progn
      (if (not wd_load) (load "wd_load.lsp")) (wd_load)
      (c:ace_GBL_wd_m 1)
      (if (not (member {name} (c:ace_get_wiretype_list nil)))
        (c:ace_new_wiretype {name} (list "WIRE COLOR" "RED" "WIRENO" "1") nil))
      (if (not (member {name} (c:ace_get_wiretype_list nil)))
        (error "Wire type registration failed"))
      (if (= (last (c:ace_get_wiretype_data {name} nil)) "0")
        (error "Wire type excludes numbering"))
      T)''')
    if value != "T":
        raise RuntimeError("No se verificó el tipo de conductor")
    return {"layer": layer, "registered": True, "numbering_enabled": True}


def update_cross_references(doc, coil_handle, child_handle):
    """Update the current project drawing; require saved project membership."""
    from src.tools.project_validation import require_valid_project
    require_valid_project(doc, allow_incomplete_xrefs=True)
    parent = doc.HandleToObject(coil_handle)
    child = doc.HandleToObject(child_handle)
    pa, ca = get_block_attributes(parent), get_block_attributes(child)
    if not pa.get("TAG1") or pa.get("TAG1") != ca.get("TAG2"):
        raise ValueError("TAG1/TAG2 no coinciden")
    for key in ("FAMILY", "INST", "LOC"):
        if pa.get(key, "") != ca.get(key, ""):
            raise ValueError(f"Identidad padre/hijo distinta: {key}")
    member = evaluate(doc, '''(progn
      (if (not wd_load) (load "wd_load.lsp")) (wd_load)
      (if (> (c:wd_is_cur_dwg_in_proj) 0) T nil))''')
    if member != "T":
        return {"success": False, "status": "requires_project_drawing",
                "error": "Guardar el dibujo e incorporarlo al proyecto activo antes de actualizar referencias"}
    for stage, expression in [
        ('save', '(progn (command "_.QSAVE") T)'),
        ('database', '(progn (wd_pds_flush_active_dwg) (c:ace_update_WFRM2ALL 1) (wd_pds_freshen_project_db (ace_getactiveproject)) T)'),
        # The project utility establishes the DBX update context. Calling
        # wd_xref_doit directly can report false duplicate parents in a
        # multi-drawing project and leave existing XREF text untouched.
        # Only run_xref is enabled: no retag, numbering or setting changes.
        ('xref', '(progn (c:ace_projwide_util_dbx (list (nth (1- (c:wd_is_cur_dwg_in_proj)) (nth 5 (c:wd_proj_wdp_data)))) (list 0 0 1) (list nil nil) nil) T)'),
        ('save_references', '(progn (command "_.QSAVE") T)')]:
        try:
            evaluate(doc, expression, timeout=120)
        except Exception as exc:
            raise RuntimeError(f"{stage}: {exc}") from exc
    pa = get_block_attributes(doc.HandleToObject(coil_handle))
    ca = get_block_attributes(doc.HandleToObject(child_handle))
    def refs(attrs):
        return {k: v for k, v in attrs.items() if k.startswith("XREF") and v.strip()}
    pr, cr = refs(pa), refs(ca)
    # A split-XREF parent must contain the bucket for this child's contact.
    # A stale NO value must not hide a missing NC reference (or vice versa).
    contact = ca.get("CONTACT", "").strip().upper()
    required = "XREF" + contact
    verified = bool(pr and cr) and not any('??' in v for v in [*pr.values(), *cr.values()])
    if contact in ("NO", "NC") and ("XREFNO" in pa or "XREFNC" in pa):
        verified = verified and bool(pa.get(required, "").strip())
    return {"success": verified, "parent_handle": coil_handle,
            "child_handle": child_handle, "parent_references": pr,
            "child_references": cr, "tag": pa.get("TAG1"),
            "status": "updated" if verified else "unverified"}
