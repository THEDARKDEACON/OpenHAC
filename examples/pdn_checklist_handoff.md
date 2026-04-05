# PDN / decap handoff (SIG-003)

Core OpenHaC does **not** size or place decoupling capacitors automatically. Use this checklist when closing power integrity before fab:

- **Rails:** List every supply net, nominal voltage, and max transient / ripple budget (from your regulator and load datasheets).
- **Target impedance:** For each rail, note a rough Z_target vs frequency band if you use that method; otherwise document “by inspection + lab measure.”
- **Cap budget:** Per IC or rail region, record bulk vs ceramic mix, total µF per rail, and any mandatory part numbers (low-ESL ceramics at the package).
- **Return path:** Confirm ground reference under fast edges (diff pairs, clocks) and that pour/split strategy matches **`net_roles`** / **`net_merge_hints`** in the manifest and `.openhac-pcb-routing-handoff.json`.
- **Measurement:** Plan scope points or test pads for rail noise; align with **`require_test_point_on_nets`** / DRC if you enabled them.

Attach completed tables to your CM or SI review package alongside **`declare_stackup_reference`** outputs and fab stackup docs.
