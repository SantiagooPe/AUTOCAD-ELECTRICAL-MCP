# Circuito marcha-paro con enclavamiento

Tool MCP y dashboard: `create_start_stop_circuit(x=0, y=0, scale=1, coil_tag="KM1")`.

`x,y` indican el centro del pulsador de paro. La escala afecta símbolos y
separaciones. El catálogo semántico resuelve los símbolos verticales:

| Función | Símbolo | Identificador |
|---|---|---|
| Paro NC | VPB12 | TAG1=S0, bornes 11/12 |
| Marcha NA | VPB11 | TAG1=S1, bornes 13/14 |
| Bobina de contactor | VMS1 | TAG1=KM1, bornes A1/A2 |
| Auxiliar NA | VMS21 | TAG2=KM1, FAMILY=MS, bornes 13/14 |

Paro está en serie con el paralelo marcha/auxiliar, seguido por la bobina.
Diez segmentos LINE en WIRES conectan los atributos XnTERM reales de los
bloques; los empalmes son extremos coincidentes. Los extremos superior e
inferior quedan disponibles para alimentación. El resultado devuelve
handles, bornes, conductores y puntos de empalme.

Cada instancia conserva visibles TAG, descripción, bornes y referencias
cruzadas. Oculta metadatos técnicos, incluidos NO/NC de la bobina, sin borrar
sus valores. Se verifica la lectura de los atributos asignados y la igualdad
TAG2/TAG1 y FAMILY entre auxiliar y bobina. Se usa el contacto de contactor
VMS21 junto con la bobina VMS1, sin alterar archivos de la biblioteca.
La visibilidad respeta ATTMODE del dibujo (usar 1 para mostrar atributos
normales; 2 fuerza también la visualización de los invisibles).

El proceso lee IEC2 sin modificar sus DWG. Rechaza identificadores repetidos
S0/S1/KM1; elimina sus propias entidades si ocurre un error.
Los duplicados se comparan sin distinguir mayúsculas y minúsculas, y la
bobina no puede usar S0 o S1 como identificador.
Los bloques importados y la capa pueden permanecer en el dibujo tras un error.
Las entidades se agrupan para deshacer. La configuración Electrical se
inicializa con `c:ace_GBL_wd_m 1`; `c:ace_new_wiretype` registra WIRES si hace
falta y `c:ace_get_wiretype_list` / `c:ace_get_wiretype_data` verifican su
registro y que admite numeración. No basta crear una capa de AutoCAD.

En un dibujo guardado que pertenece al proyecto activo, guarda el dibujo,
sincroniza/reconstruye la base nativa y llama `c:ace_projwide_util_dbx` con
sólo XREF habilitado para el dibujo actual. Guarda las referencias y comprueba
valores no vacíos en padre e hijo, incluido el campo NO/NC correspondiente, y devuelve su lectura
en `cross_references`. No asigna textos XREF inventados. Para un dibujo fuera
del proyecto devuelve `requires_project_drawing`; el circuito queda creado.
Los fallos de actualización se informan separadamente, conservando el circuito.

La tool `update_cross_references(coil_handle, child_handle)` permite repetir
la actualización después de incorporar el dibujo al proyecto. Valida TAG1/TAG2,
FAMILY, INST y LOC antes de modificar la base. Ambas tools esperan confirmación
de ejecución; enviar un comando no se considera una verificación exitosa.

Prueba real reproducible con Electrical 2023 abierto:

```powershell
python -m scripts.test_start_stop_2023
python -m scripts.test_native_2023
```

La prueba llama la tool por MCP en un dibujo temporal, verifica cuatro
bloques, diez conductores, bornes, identificadores, escalas 1/2, ocho
combinaciones de estados y protección contra duplicados. Compara SHA256 de
los cuatro DWG originales antes/después y cierra el dibujo sin guardar,
restaurando el documento previo.

La prueba nativa adicional usa la plantilla IEC instalada y un WDP temporal
con nombre único (Electrical identifica su base scratch por el nombre del
proyecto). Invoca las tools mediante MCP, consulta `c:wd_get_wire_netlst`
para comprobar las conexiones a componentes, inserta un WIRENO real con
`c:wd_putwn`, verifica referencias padre/hijo y su repetición, y compara SHA256
de todos los archivos IEC2. Verifica también el registro de WIRES en un dibujo
vacío. Conserva DWG, WDP y `verification.json` en `artifacts/native-2023/`,
cierra los dibujos de prueba y restaura el proyecto y dibujo anteriores.
Las APIs se consultaron en la ayuda oficial instalada de Electrical 2023:
`Acade/Help/en-US/Help/ACE_API.chm`.
