# OpenHaC — Live KiCad artwork overlay (LIVE)

**Purpose:** Normative contract for treating saved KiCad files as an **artwork overlay** on top of the native circuit graph. Python remains the HDL. KiCad on disk is geometry (symbol/footprint pose, then user wires/tracks/zones) merged on emit and used as the freeze path when you compile after polishing.

**Audience:** Core maintainers implementing live preview, schematic/PCB emit, and freeze compile.

**Status:** Normative. Progress tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (LIVE table). Product scope: [SCOPE.md](./SCOPE.md). EE stamp remains [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (**SSO-***).

**Relationship:** Does **not** reopen closed FAB/PERF/SSO rows. Preview still never runs `kicad-cli sch erc` (**SSO-012**). ERC stays `--schematic-signoff` (**SSO-040**).

---

## Product lock

- **Electrical source of truth:** native circuit / `Board` (Python). Adding or rewiring parts happens in the `.py`.
- **Artwork overlay:** the live `.kicad_sch` / `.kicad_pcb` (and sibling sheets) after the user **Saves in KiCad**. That overlay is the last saved edit of the editables before compile.
- **Not a second HDL:** KiCad connectivity that disagrees with the graph **fails compile** (parity). It does not win.
- **Preview is not a stamp:** `openhac preview` never runs `kicad-cli sch erc`.
- **No pcbnew daemon:** do not keep `SaveBoard` in-process as a live server (SIGSEGV). Write files; KiCad **Reload**.

KiCad does not push unsaved GUI state to disk. Overlay is always **last saved file**. Workflow: nudge in KiCad → **Save** → (optional) save `.py` → watcher merges → **File → Revert** or close/reopen the sheet (KiCad 9 often never prompts Reload while the editor holds a lock).

```
board.py → native circuit → emit (merge overlay) → build/live/*.kicad_pro
                ↑                                         │
                │                                         ▼
         compile (netlist/BOM/gates)              KiCad GUI Reload
                ↑                                         │
         parity: graph vs KiCad nets                      │ Save
                └──────── overlay (saved files) ←─────────┘
```

## Two modes (same overlay)

**Live (watcher)** — `openhac preview --kicad --watch` (optional `--pcb`): on `.py` save, reset circuit, re-import, emit with **merge**. New refdes get auto layout; surviving refdes keep KiCad x/y/rot; dropped refdes disappear.

**Freeze compile** — user stops the watcher, polishes in KiCad, then `openhac compile … --keep-kicad-artwork`: electrical artifacts from the graph; **do not clobber** merged artwork; run parity + optional ERC. Escape hatch: `--regenerate-artwork` (full rewrite, ignore overlay).

Default when live files exist: **merge**. Explicit regenerate is opt-in.

---

## LIVE-001 — Overlay schema

Primary capture is **parse of saved KiCad files**, not a second HDL.

Optional JSON sidecar (`{project}.openhac-kicad-artwork.json`) may mirror the same records for tooling; emit and merge must still work if only `.kicad_sch` / `.kicad_pcb` exist.

**Keys:** stable **symbol UUID** (`symbol_instance_uuid` / sheet instance `(uuid …)`), then **refdes** (`R1`, `U2`, …). KiCad 9 Save often rewrites `Reference` to `R?` / `C?`; UUID is the merge key. File-level `(symbol_instances …)` is not enough — emit per-symbol `(instances (project … (path "/{sheet-uuid}" (reference "R1"))))` so KiCad 9 keeps annotation.

**Records:**

| Kind | Fields |
|------|--------|
| Schematic symbol | `ref`, `x`, `y`, `rot` (degrees), `unit`, `uuid` |
| PCB footprint | `ref`, `x`, `y`, `rot` (degrees) |
| PCB copper | tracks (`start`, `end`, `width`, `layer`, `net` name), vias, zones |
| Schematic artwork | wires, labels, sheet-level graphics (polyline/rectangle/text) |

**Drop policy:** overlay objects whose refdes or net is **absent from the graph** are not resurrected (no `R99` from KiCad-only drawing; no copper for a vanished net).

**Sidecar schema id:** `openhac.kicad_artwork.v1`.

---

## LIVE-002 — Schematic symbol pose

Keep symbol `(at x y rot)` / `(unit N)` from the saved `.kicad_sch`.

Merge in `openhac/schematic/layout.py` `_assign_positions`: auto-place new refs; overlay pose wins for surviving UUID/refdes. Do **not** 50-mil-snap overlay coordinates (user placement is exact). KiCad 9 unannotated `R?` still matches by symbol UUID.

Parsers live in `openhac/compiler/kicad_artwork.py` (next to the wire/label regexes already in `openhac/schematic/parity.py`).

---

## LIVE-003 — PCB footprint pose

Keep footprint `(at x y rot)` from the saved `.kicad_pcb`.

Apply in `place_circuit_on_board` **after** Z3/grid packing so matching refs are not left at solver coords. Overlay `(at)` is the KiCad footprint origin (skip courtyard top-left compensation for those refs).

If **every** placeable ref has overlay coords, skip Z3. New refs still get grid/Z3; overlay refs win afterward.

Do not run the footprint legalizer on overlay refs (user placement must not be shoved).

---

## LIVE-004 — PCB copper overlay

Re-apply **tracks, vias, zones** from the previous `.kicad_pcb` onto the new board for nets that **still exist** in the graph. Drop copper whose net vanished.

Net match is by **net name** (remap KiCad net numbers on splice). `--keep-kicad-artwork` skips autoroute so FreeRouting does not clobber user copper. Default merge skips autoroute only when the overlay already contains tracks/vias/zones.

---

## LIVE-005 — Schematic artwork overlay

Keep user **wires / labels / graphics** when the graph still has that net. New connectivity is still emitted from the IR.

**Conflict policy:** graph pins win. Orphan wires (endpoints not on a surviving net) are dropped. A user wire whose endpoints sit on pins of **two different graph nets** is a parity failure (LIVE-006), not a silent short.

---

## LIVE-006 — Freeze compile

CLI (mutually exclusive):

- `--keep-kicad-artwork` — require overlay files; merge; skip destructive rewrite of pose/copper; still write netlist/BOM/manifest; **require** graph↔overlay connectivity parity.
- `--regenerate-artwork` — ignore overlay (today’s full rewrite).

Env: `OPENHAC_KEEP_KICAD_ARTWORK`, `OPENHAC_REGENERATE_ARTWORK`.

Fabrication **or** an explicit `--keep-kicad-artwork` with **missing/empty overlay** → error, not a silent empty board.

Parity: reuse `openhac/schematic/parity.py` for IR↔graph when schematic is emitted; additionally fail closed if overlay wires/labels short distinct graph nets. PCB net names on kept copper must exist in the graph (vanished nets dropped, not resurrected).

---

## LIVE-007 — Live PCB on watch

`openhac preview --kicad --watch --pcb` runs **place-only**: schematic + layout, **no** FreeRouting, **no** ERC (`kicad-cli sch erc` stays off). Debounce the watcher (PCB emit is slower). Same merge as live schematic. Not fab.

Compile profile: `preview_pcb`.

---

## LIVE-008 — SVG viewer on watch

`openhac preview --watch` starts a **127.0.0.1** page that shows `kicad-cli sch export svg` of the written `.kicad_sch` and reloads when the Python script is saved. Optional `--pcb` adds a PCB SVG tab. This is a **view**, not an editor and not a second symbol renderer. Pose edits stay in KiCad (Save → overlay). `--no-browser` prints the URL only.

Never runs `kicad-cli sch erc`.

---

## Out of scope

- KiCad plugin / **schematic** IPC hot-reload (KiCad 11). PCB revert via IPC is **LIVE-010** in [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md) (best-effort; missing socket is not an error).
- Round-trip: drawing a **new part** in eeschema does not add a `Component()` in Python.
- In-process pcbnew watcher / `SaveBoard` daemon.
- Replacing `--schematic-signoff` with live preview.

---

## Acceptance (CI)

- Merge: two-resistor board, overlay moves `R1`, emit keeps `R1` xy; `R2` auto if new.
- KiCad 9: overlay `Reference "R?"` plus matching symbol UUID still keeps xy; emit writes per-symbol `(instances … (path "/{sheet-uuid}"))`.
- Drop: overlay has `R99` not in the graph → not resurrected.
- Parity fail: overlay adds a wire that shorts two graph nets → compile non-zero.
- Preview still has no `sch erc` in `openhac/compiler/kicad_sch_svg.py` or `openhac/compiler/svg_preview.py`.
- LIVE-008: localhost viewer serves `/sheet.svg` and `/meta.json`; no `sch erc`.
- Fabrication + missing overlay + `--keep-kicad-artwork` → error.
