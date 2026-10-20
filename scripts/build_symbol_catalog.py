"""Rebuild the portable inventory from a local IEC2 directory and Autodesk menu."""
import argparse
import json
import re
from pathlib import Path


def build(library: Path, menu: Path) -> dict:
    descriptions = {}
    section = ""
    for line in menu.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.startswith("IEC:"):
            section = line
        fields = line.split("|")
        if len(fields) != 3 or line.startswith(";"):
            continue
        code = fields[2].strip().upper()
        if not re.fullmatch(r"[HV][A-Z0-9_\-]+", code):
            continue
        descriptions[code] = {"description": fields[0], "menu_section": section, "source": menu.name}
        descriptions.setdefault(("H" if code[0] == "V" else "V") + code[1:], {**descriptions[code], "source": menu.name + " (orientation counterpart)"})
    symbols = {}
    for path in sorted(library.glob("*.dwg"), key=lambda p: p.name.casefold()):
        symbols[path.stem.upper()] = {"filename": path.name, **descriptions.get(path.stem.upper(), {})}
    return {"library": str(library), "menu": str(menu), "count": len(symbols), "symbols": symbols}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("menu", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(args.library, args.menu), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
