"""Offline IEC2 inventory with Autodesk menu provenance and Spanish aliases."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).with_name("iec2_catalog.json")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(re.sub(r"[^\w]+", " ", "".join(c for c in text if not unicodedata.combining(c))).split())


# Generic names deliberately return alternatives where a choice affects function.
CONCEPTS = [
    ("CR21", "contacto normalmente abierto", ["contacto NA", "contacto NO", "NA", "NO", "WD_NOPEN"], "contacts"),
    ("CR22", "contacto normalmente cerrado", ["contacto NC", "NC", "WD_NCLOSE"], "contacts"),
    ("CR1", "bobina de relé", ["bobina", "rele", "relay coil"], "coils"),
    ("PB11", "pulsador NA", ["pulsador normalmente abierto", "pulsador", "push button"], "pushbuttons"),
    ("PB12", "pulsador NC", ["pulsador normalmente cerrado", "pulsador", "push button"], "pushbuttons"),
    ("MS1", "bobina de contactor", ["contactor", "motor starter"], "contactors"),
    ("MO12", "motor monofásico", ["motor", "motor 1 fase"], "motors"),
    ("MO13", "motor trifásico", ["motor", "motor 3 fases"], "motors"),
    ("OL1", "relé térmico unipolar", ["rele termico", "sobrecarga", "thermal overload"], "overloads"),
    ("TD1N", "temporizador a la conexión", ["temporizador", "timer", "temporizador on delay"], "timers"),
    ("TD1F", "temporizador a la desconexión", ["temporizador", "timer", "temporizador off delay"], "timers"),
]


def inventory(library: Path) -> list[dict]:
    """Only return files present now; unknown DWGs remain explicitly unclassified."""
    if not library.is_dir():
        raise FileNotFoundError(f"No existe la biblioteca: {library}")
    metadata = json.loads(DATA.read_text(encoding="utf-8"))["symbols"]
    result = []
    for path in sorted(library.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.suffix.casefold() != ".dwg":
            continue
        code = path.stem.upper()
        entry = dict(metadata.get(code, {}))
        entry.update(symbol=code, filename=path.name, path=str(path), orientation={"H": "horizontal", "V": "vertical"}.get(code[:1], "unspecified"))
        entry.setdefault("category", "unclassified")
        entry.setdefault("aliases", [])
        for stem, label, aliases, category in CONCEPTS:
            if code in ("H" + stem, "V" + stem):
                entry.update(label=label, aliases=[label, *aliases], category=category)
        result.append(entry)
    return result


def search(library: Path, query: str = "", orientation: str = "", category: str = "") -> list[dict]:
    orientation = normalize(orientation)
    if orientation not in ("", "horizontal", "vertical"):
        raise ValueError("orientation debe ser horizontal o vertical")
    q = normalize(query)
    entries = inventory(library)
    entries = [e for e in entries if (not orientation or e["orientation"] == orientation) and (not category or normalize(e["category"]) == normalize(category))]
    if not q:
        return entries
    exact = [e for e in entries if q in [normalize(e["symbol"]), normalize(e["filename"]), *map(normalize, e["aliases"])]]
    if exact:
        return exact
    return [e for e in entries if all(t in normalize(" ".join([e["symbol"], e.get("label", ""), e.get("description", ""), *e["aliases"]])).split() for t in q.split())]


def resolve(library: Path, query: str) -> dict:
    # Preserve existing vertical defaults; explicit H/V codes override orientation.
    matches = search(library, query)
    exact_code = [e for e in matches if normalize(query) in (normalize(e["symbol"]), normalize(e["filename"]))]
    if exact_code:
        return exact_code[0]
    matches = [e for e in matches if e["orientation"] == "vertical"]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError("Nombre ambiguo; elegí un símbolo: " + ", ".join(f'{e["symbol"]} ({e.get("label", e.get("description", ""))})' for e in matches))
    raise ValueError(f"Símbolo no encontrado: {query}")
