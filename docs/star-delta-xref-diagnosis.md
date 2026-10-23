# Referencias de estrella_triangulo.dwg

El proyecto Curso_AutocadElectricall contenía inversion_giro.dwg y
estrella_triangulo.dwg. Ambos circuitos independientes reutilizan KM1/KM2
con FAMILY=MS e INST/LOC vacíos. La actualización de la base del proyecto
mezclaba esas identidades: por ejemplo KM1 tenía XREFNO
`4-A,??.3- B,??.4-A` y KM2 XREFNO `??.6- B,??.7-A`, aunque KM2
no tiene hijos NO en estrella-triángulo.

En el dibujo se encontraron exactamente estos vínculos:

| Padre | Handle | Familia | Hijos |
|---|---|---|---|
| KM1 | 3B4 | MS | 388 NO |
| KM2 | 41A | MS | 4F1 NC |
| KM3 | 449 | MS | 4CD NC |
| KT1 | 3EA | TD | 47A NC, 4A5 NO |

TAG1/TAG2, FAMILY, INST y LOC coinciden en cada pareja local. KM3 y KT1
no presentan la colisión de identidad observada para KM1/KM2.
No hay que borrar componentes ni cambiar CONTACT o familia.

La reparación `python -m scripts.repair_star_delta_xrefs` crea y activa
un proyecto propio en `artifacts/star-delta-xref-repair/estrella_triangulo.wdp`
que apunta al DWG original. Conserva el proyecto anterior sin editarlo.
Limpia sólo atributos XREF derivados y ejecuta Electrical en este orden:
guardar, actualizar base, regenerar referencias nativas, guardar referencias.
Se repite con las parejas en orden inverso y se comprueba estabilidad,
topología y atributos no XREF idénticos y hashes de toda IEC2 idénticos.
El informe antes/después queda en `verification.json` junto al proyecto.

Al volver al proyecto anterior, las identidades repetidas volverían a
participar en una actualización. Usar el proyecto propio para este circuito.

La regresión unitaria en `tests/test_electrical_native.py` evita declarar
éxito cuando padre o hijo todavía contienen `??`, incluso con referencias
válidas mezcladas en el mismo atributo.
