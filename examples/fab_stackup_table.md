# Fab drawing — layer stackup table (template)

Use this table on a fabrication drawing or paste into CM documentation. Values are **placeholders**; replace with your vendor stackup (see also `docs/fab_stackup_jlc_example.json` for a machine-readable example).

After `openhac compile`, check `{project}.openhac-fab-handoff.md` when you used `Board.declare_stackup_reference(...)` — it lists recorded paths and optional per-reference notes (MFG-003 / PCB-004).

| Layer | Material | Thickness (mm) | Dk @ 1 GHz | Df @ 1 GHz | Copper (oz) |
|-------|----------|----------------|------------|------------|-------------|
| L1 (F.Cu) | — | — | — | — | 1 |
| Prepreg | FR4 | 0.10 | 4.2 | 0.018 | — |
| L2 (In1.Cu) | — | — | — | — | 1 |
| Core | FR4 | 1.00 | 4.5 | 0.020 | — |
| L3 (In2.Cu) | — | — | — | — | 1 |
| Prepreg | FR4 | 0.10 | 4.2 | 0.018 | — |
| L4 (B.Cu) | — | — | — | — | 1 |

**Total thickness (nominal):** 1.60 mm  

**Notes:** Impedance targets (if any), surface finish, solder mask color, IPC-6012 class.

(MFG-003 handoff — PDF plot from KiCad remains manual.)
