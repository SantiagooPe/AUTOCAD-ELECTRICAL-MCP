# Gestión automática de proyectos

MCP y agente web exponen `create_project`, `create_project_drawing`,
`register_project_drawing` y `rebuild_project`.

Crear primero un WDP con ruta nueva y `settings_from` apuntando a un WDP
Electrical válido (por defecto el activo). Se copian sólo líneas de
configuración, sin miembros. La activación se verifica consultando Electrical.
Crear hojas con rutas DWG nuevas y una plantilla DWT Electrical explícita.
`expected_project` permite impedir que una operación se ejecute después de
un cambio de proyecto. `section` y `description` permiten separar potencia
y mando sin separar el espacio de identificadores.

El registro usa la API nativa `c:ace_add_dwg_to_project`, comprueba la ruta
completa y es idempotente. Rechaza nombres de archivo repetidos y dibujos
ajenos con TAGs o referencias: la migración de circuitos requiere un flujo
explícito posterior. Un fallo tras crear un archivo conserva el archivo para
inspección; no implica que haya sido registrado ni revierte el WDP.

Antes de generar circuitos se reutiliza el inventario completo del proyecto,
incluyendo hojas abiertas. Una hoja cerrada bloquea la inserción por cobertura
incompleta. TAG1 debe ser único dentro de INST/LOC, incluso entre familias y
dentro de un lote nuevo. Los hijos se relacionan por TAG, INST, LOC y FAMILY.
Las inserciones individuales requieren TAG explícito y rechazan XREF heredado.
Las referencias de cada instancia nueva se limpian sin modificar IEC2.

El control de wires comprueba LINE nativa, capa registrada y numeración
habilitada. No puede inferir que una geometría en cualquier capa arbitraria
pretendía ser un conductor. La numeración existente sigue siendo la primitiva
Electrical utilizada por los circuitos.

`rebuild_project` permite XREF incompleto, pero bloquea otros conflictos,
guarda las hojas del proyecto y reutiliza las APIs de actualización de base
y referencias de Electrical. No retaguea ni renumera. Valida nuevamente al
terminar. El análisis de texto XREF detecta ausencia y marcadores de error;
no demuestra por sí solo que cualquier texto antiguo no vacío sea correcto.

Regresión aislada: `python -m unittest tests.test_project_management tests.test_project_validation`.
Ensayo real: `python -m scripts.test_project_management_2023`, con Electrical
2023 abierto e inactivo. Conserva evidencia en `artifacts/project-management-2023`.

Verificado el 23/10/2026 en Electrical `24.2s`: WDP temporal con hojas
`control.dwg` y `power.dwg`, registro idempotente, marcha-paro con XREF nativo,
rechazo de inserción duplicada sin agregar entidades, regeneración del proyecto
y validación final de dos hojas sin incidencias. Los hashes SHA-256 de toda
IEC2 coincidieron antes y después y se restauró el contexto previo al ensayo.
Evidencia: `artifacts/project-management-2023/a9b10563/report.json`.
