# Contactos IEC2 en AutoCAD Electrical 2023

La configuración local usa `AutoCAD.Application.24.2`. Los símbolos se buscan en
`C:\Users\Public\Documents\Autodesk\Acade 2023\Libs\iec2`.

La herramienta `insert_component` acepta:

- `contacto normalmente abierto`, `contacto NA`, `contacto NO`: `VCR21.dwg`.
- `contacto normalmente cerrado`, `contacto NC`: `VCR22.dwg`.

Reiniciá el servidor MCP o reconectalo desde Codex para cargar los cambios.
Con un dibujo abierto y AutoCAD sin comandos ni diálogos activos, pedí:

> Insertá un contacto normalmente abierto en x=100, y=100, escala 2, rotación 0 usando insert_component.

> Insertá un contacto normalmente cerrado en x=150, y=100 usando insert_component.

Ambas herramientas devuelven `success`, el archivo usado y el `handle` del bloque.
`insert_component` usa escala 2 por defecto. `insert_electrical_symbol` acepta
`VCR21`, `VCR22`, sus nombres con `.dwg`, y los alias `WD_NOPEN`/`WD_NCLOSE`;
su escala predeterminada es 1 para conservar la interfaz anterior.
La rotación se expresa en grados y las coordenadas en unidades del dibujo.
`attributes` permite asignar atributos existentes, por ejemplo `{"TAG2": "K1"}`;
si alguno no se actualiza, el resultado incluye una advertencia.

Se usa COM `ModelSpace.InsertBlock`, sin `ACET-INSERT-BLOCK`. Esto inserta el
bloque con sus atributos; no ejecuta el corte de cables, el enlace con bobinas,
ni las actualizaciones de referencias del proyecto Electrical.

## Pruebas

Suite sin AutoCAD: `python -m pytest -m "not integration" -q`.

Prueba real: `python -m scripts.test_contacts_2023`. Con AutoCAD Electrical 2023
en reposo, crea un dibujo temporal, invoca ambos contactos mediante MCP, comprueba
nombre de bloque, posición y escala, y cierra ese dibujo sin guardarlo.

Verificación real completada: AutoCAD COM `24.2s (LMS Tech)`, contactos
`VCR21` en `(0, 0, 0)` y `VCR22` en `(50, 0, 0)`, ambos con escala 2.
Las dos llamadas MCP devolvieron `success: true` y sus handles. El dibujo
temporal se cerró sin guardar. La prueba espera a que termine la inicialización
del dibujo antes de insertar para evitar rechazos transitorios de COM.
