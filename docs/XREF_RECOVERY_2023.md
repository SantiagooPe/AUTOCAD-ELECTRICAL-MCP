# KM1/KM2 cross-reference recovery (Electrical 2023)

In `inversion_giro.dwg`, KM1 (870) and KM2 (916) use the same VMS1
parent definition, FAMILY=MS, empty INST/LOC, and VMS21/VMS22 children.
KM1's children (820/8ED) carry TAG2=KM1 and CONTACT=NO/NC. KM2's
children (8C9/847) have the equivalent identities. Native COMP records
identify one parent and two children per tag; the other project drawings
contain no additional KM1/KM2 parents.

KM1 initially had empty XREFNO/XREFNC, while both children already
referenced its coil. KM2 retained XREFNO=7-A and XREFNC=%%u3-A%%u,
with generated graphical-reference XData. Existing text alone therefore
did not demonstrate that a new update had run successfully.

The direct `c:wd_xref_doit` path repeatedly left KM1 empty. Electrical's
XREF.BAD reported “Duplicated parent?” for the current drawing's parents,
despite the unique identities in COMP. Saving, rebuilding the database,
changing the DESC-update option and repeating the call did not repair it.
The isolated reversing-circuit test passed, so this was not explained by
the circuit's family or parent/child assignments. The precise internal
reason for the direct API's false duplicate detection is not established.

The documented project-update entry point `c:ace_projwide_util_dbx`,
restricted to the current drawing with `(list 0 0 1)`, regenerated KM1's
references: XREFNO=4-A and XREFNC=%%u6-A%%u. Only the cross-reference
operation is enabled; retagging, wire numbering and drawing-setting
changes are disabled. The production sequence is now save, refresh the
native database, run this XREF update, save, then reread the instances.
No reference text is fabricated or copied from KM2.

Verification also requires the split reference matching the selected
child's CONTACT. A surviving NO reference cannot conceal an empty NC
reference. `scripts/test_xref_recovery_2023.py` clears KM1's split XREFs,
regenerates both parent/child groups, repeats in reverse order, and checks
all component transforms, non-XREF attributes and WIRES endpoints against
the initial snapshot. It writes `artifacts/xref-recovery-2023.json`.

API definitions were checked against the installed
`Acade/Help/en-US/Help/ACE_API.chm`, topics `c:wd_xref_doit` and
`c:ace_projwide_util_dbx`.
