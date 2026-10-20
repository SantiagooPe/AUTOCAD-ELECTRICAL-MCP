"""Synchronous, error-checked AutoLISP calls through the active document."""
import json
from pathlib import Path
import tempfile
import time
import uuid


def quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def evaluate(doc, expression, timeout=60):
    """Return the printed Lisp value only after the completion receipt exists.

    SendCommand returning is not proof of execution. Errors and timeouts must
    propagate; callers must never report a queued command as verified success.
    """
    path = Path(tempfile.gettempdir()) / f"ace-mcp-{uuid.uuid4().hex}.txt"
    name = "ace_mcp_" + uuid.uuid4().hex
    result_var, file_var = name + '_result', name + '_file'
    command = (
        f'(progn (defun {name} (/ {result_var} {file_var}) '
        f'(setq {result_var} (vl-catch-all-apply (function (lambda () {expression})) nil)) '
        f'(setq {file_var} (open {quote(path.as_posix())} "w")) '
        f'(if (vl-catch-all-error-p {result_var}) '
        f'(progn (write-line "ERROR" {file_var}) (write-line (vl-catch-all-error-message {result_var}) {file_var})) '
        f'(progn (write-line "OK" {file_var}) (write-line (vl-prin1-to-string {result_var}) {file_var}))) '
        f'(close {file_var})) ({name}) (princ))\n'
    )
    deadline = time.monotonic() + 10
    while True:
        try:
            active = doc.GetVariable("CMDACTIVE")
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.3)
    if active:
        raise RuntimeError("AutoCAD tiene un comando activo")
    try:
        doc.SendCommand(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) >= 2:
                    if lines[0] != "OK":
                        raise RuntimeError(lines[1])
                    time.sleep(.5)
                    while time.monotonic() < deadline:
                        try:
                            if doc.Application.GetAcadState().IsQuiescent:
                                break
                        except Exception:
                            pass
                        time.sleep(.2)
                    else:
                        raise TimeoutError("Electrical terminó la llamada pero sigue ocupado")
                    return "\n".join(lines[1:])
            time.sleep(.1)
        raise TimeoutError("Electrical no confirmó la ejecución; revisar el comando activo")
    finally:
        path.unlink(missing_ok=True)
