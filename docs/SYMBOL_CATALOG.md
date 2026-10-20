# Catálogo semántico IEC2

El inventario se generó a partir de los 3.317 DWG locales de AutoCAD Electrical
2023 y las descripciones de `ACE_IEC_MENU.DAT` de Autodesk. No se modifican los
DWG ni se requiere AutoCAD para buscar. Los archivos sin descripción del menú
se conservan sin atribuirles una función por su nombre.

`search_symbols(query, orientation="", category="", limit=50)` permite buscar
por nombre español, descripción inglesa o código. Devuelve ruta, nombre real,
orientación, categoría y procedencia de la descripción cuando está disponible.
`count` cuenta todas las coincidencias; `truncated` indica si se aplicó el límite.
Los archivos eliminados dejan de aparecer y los nuevos se inventarían como
no clasificados. Las variantes H equivalentes al menú V indican esa inferencia
en `source`; no se analizaron las geometrías internas del DWG.

| Nombre | Símbolo vertical |
| --- | --- |
| contacto NA / NO | VCR21 |
| contacto NC | VCR22 |
| bobina / bobina de relé | VCR1 |
| pulsador NA / NC | VPB11 / VPB12 |
| contactor / bobina de contactor | VMS1 |
| motor monofásico / trifásico | VMO12 / VMO13 |
| relé térmico / relé térmico unipolar | VOL1 |
| temporizador a la conexión / desconexión | VTD1N / VTD1F |

`insert_component` e `insert_electrical_symbol` usan la misma resolución.
Los nombres semánticos mantienen orientación vertical; un código H explícito
selecciona la variante horizontal. Los nombres genéricos motor, pulsador y
temporizador devuelven un error con alternativas para no elegir una función
arbitrariamente. No se ignoran palabras desconocidas ni se corrigen errores
tipográficos durante la inserción. Contactor representa su bobina, no un
conjunto completo de contactos. Relé térmico representa un polo de sobrecarga.
La inserción COM no corta cables ni actualiza referencias de proyecto.

El inventario portable está en `src/tools/iec2_catalog.json`. Se regenera con
`scripts/build_symbol_catalog.py`, pasando biblioteca, menú y archivo de salida.
Las pruebas están en `tests/test_symbol_catalog.py`; se ejecutan junto con las
regresiones existentes mediante `pytest tests -m "not integration"`.
