
## Validación previa del proyecto Electrical

La herramienta `validate_project` (MCP y web) inspecciona el proyecto activo y
entrega `success`, `complete`, `issues`, `project` y `drawing_count`. Cada
incidencia identifica el dibujo y los handles cuando corresponde. Los handles
se interpretan dentro de su dibujo. No ejecuta reparaciones ni modifica cables,
componentes, posiciones, conexiones o topologías.

Los tres creadores de circuitos ejecutan este control antes de registrar tipos de
wire, abrir el grupo de deshacer o insertar entidades. También se aplica antes
de editar atributos, crear referencias y sincronizar el proyecto. Las ediciones
comprueban además el estado propuesto: cambiar un TAG no puede introducir un
padre duplicado ni dejar hijos huérfanos. Un fallo devuelve `success: false` con
el informe en `validation` (los creadores conservan su formato de error).

Códigos de diagnóstico:

| Código | Significado |
| --- | --- |
| `duplicate_tag` | Más de un TAG1 con igual TAG, INST, LOC y FAMILY, o un TAG1 propuesto que ya existe en esa INST/LOC. |
| `ambiguous_parent` | Un TAG2 tiene varios padres con la misma identidad. |
| `child_without_parent` | No hay un TAG1 con el TAG2, INST, LOC y FAMILY del hijo. |
| `incomplete_cross_reference` | Falta XREF de padre/hijo, contiene `??`, o falta la referencia NO/NC correspondiente en un padre con XREF separado. |
| `unregistered_wire` | Un conductor inventariado usa una capa ausente en los tipos Electrical registrados. |
| `drawing_outside_project` | El dibujo activo o inventariado no pertenece al WDP activo. |
| `drawing_not_inspected` | Una hoja del proyecto está cerrada. |
| `incomplete_project_inventory` | La cobertura del proyecto es incompleta. |
| `inspection_failed` | No se pudo leer el proyecto o una entidad; no se autoriza la operación. |
| `ambiguous_update_target` | La edición no identifica exactamente un componente del dibujo activo. |

La identidad normaliza espacios exteriores y mayúsculas. Varios contactos TAG2
con el mismo TAG son válidos. Las rutas se comparan completas con normalización
Windows: un nombre de archivo coincidente en otra carpeta no prueba pertenencia.

El WDP se obtiene mediante `ace_getactiveproject` y sus hojas mediante
`c:wd_proj_wdp_data`; no se elige un WDP por proximidad en el disco. Abrí todas las
hojas del proyecto antes de validar. El control activa temporalmente cada hoja
abierta para consultar sus tipos de wire y restaura la hoja original incluso
ante un error. No abre ni guarda hojas automáticamente. Si hay hojas cerradas,
bloquea la operación e informa la cobertura pendiente.

Se inventarían LINEs en `WIRES` y en capas de wire registradas. Una línea genérica
en una capa personalizada no registrada no permite inferir si representa un wire:
esa intención no se deduce de la geometría. El análisis XREF verifica presencia,
marcadores de error y buckets NO/NC; no garantiza que texto no vacío esté actualizado.

La actualización nativa de XREF permite **únicamente** referencias incompletas
para poder repararlas. Mantiene bloqueados duplicados, ambigüedad, hijos huérfanos,
wires no registrados, dibujos externos y cobertura incompleta. Los algoritmos de
trazado, enclavamiento y numeración de los circuitos no se modificaron.

Regresiones sin AutoCAD:

```text
python -m unittest tests.test_project_validation tests.test_start_stop tests.test_reversing tests.test_star_delta tests.test_electrical_native tests.test_electrical_primitives -q
```

Las pruebas de composición aíslan el control previo para seguir verificando las
mismas geometrías y estados de contacto. Las pruebas del control verifican por
separado que un rechazo ocurre antes de toda inserción, registro o comando de
actualización. La comprobación con una instalación real de Electrical sigue
siendo necesaria para verificar sus APIs y los datos del proyecto concreto.
