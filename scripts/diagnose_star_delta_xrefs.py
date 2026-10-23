"""Read-only live diagnosis of the star/delta drawing and project context."""
import json
from src.autocad.connection import get_connection
from src.autocad.lisp import evaluate
from scripts.test_xref_recovery_2023 import snapshot

def main():
    doc = get_connection().get_active_document()
    assert doc.Name.lower() == 'estrella_triangulo.dwg', doc.Name
    print(json.dumps(snapshot(doc)[1], indent=2))
    print(evaluate(doc, '''(progn (if (not wd_load) (load "wd_load.lsp"))
      (wd_load) (list (ace_getactiveproject) (c:wd_proj_wdp_data)))'''))

if __name__ == '__main__':
    main()
