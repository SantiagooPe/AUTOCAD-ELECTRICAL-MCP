# Electrical primitives

`src.tools.electrical_primitives` operates on an explicit AutoCAD document;
callers own the connection, undo scope, and project selection.

- `insert_iec_component`: resolve a read-only catalog DWG, insert a reference,
  apply and verify instance attributes. Rotation is in degrees. Optional
  vertical terminal validation uses the actual WCS XnTERM attributes.
- `create_electrical_wires`: validate WCS segments and create LINE entities on
  a registered Electrical wire type with numbering enabled. This preserves
  the existing Electrical network recognition, rather than just drawing on an
  arbitrary layer. `register_type=False` requires prior `ensure_wire_type`.
- `number_wire`: assign a number by wire handle through synchronous `wd_putwn`.
  Raises when Electrical does not confirm completion.
- `associate_parent_child`: copy TAG1 to TAG2 and FAMILY/INST/LOC to the child
  reference, or validate an existing association with `assign=False`.
- `update_cross_references`: reuse the native project/database update and
  verified parent/child XREF attributes. An unsaved/non-project drawing
  returns `requires_project_drawing`.

Insertion and wire creation accept a `created` journal. Entities enter it
immediately, before attribute/layer operations can fail. Compound callers
must delete journal entries in reverse order on failure. Without a journal,
these primitives remove their own partially created entities.

`create_start_stop_circuit` keeps its public signature, layout, response,
legacy TAG/FAMILY validation policy, rollback, and nonfatal XREF errors.
Numbering is available independently; the circuit does not add number tags.
IEC2 files and block definitions are never edited.

`create_reversing_circuit(x=0, y=0, scale=1)` composes nine IEC2 references:
common S0 NC, S1/S2 NO, KM1/KM2 coils, their NO holding contacts, and the
opposite coil's NC interlock in each branch. It reuses these same primitives;
the bus is split at every branch connection. Seven Electrical networks are
numbered 101..107 with `number_wire`, and all four parent/child XREF pairs are
updated and checked. S0/S1/S2/KM1/KM2 must be unused in the drawing.

The return includes `assembled`, `wire_numbers`, and `cross_references`.
`success=True` requires numbering and all XREF checks to pass. For a drawing
outside the active project, geometry is retained with `assembled=True` and
`success=False`; save/add it to a project and retry the reported finalization
operations by handle. Insertion/wiring failures roll back newly created
entities. This is the control circuit; power poles are outside its scope.

Run `python -m scripts.test_reversing_2023` with Electrical 2023 open to test
the MCP tool in a separate temporary project/drawing. It checks 32 contact
states, native netlists, seven wire numbers, four XREF associations, duplicate
protection and SHA256 of every IEC2 file, then restores the original drawing
and project. Evidence is retained under `artifacts/reversing-2023/`.

Offline regressions: `python -m unittest tests.test_electrical_primitives
 tests.test_start_stop tests.test_electrical_native` (one command line).
The full offline suite uses `python -m pytest -m "not integration"`.
`scripts/test_native_2023.py` additionally verifies actual Electrical networks,
native numbering, cross-references, and unchanged IEC2 hashes in an isolated
live project. It requires AutoCAD Electrical 2023 and is not an offline test.
