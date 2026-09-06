# Release checklist (SW-004)

Use this before tagging a hardware release or sending artifacts to a CM.

- Phase-1 context: [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md)
- Phase-2 fabrication gates: [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) (track [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md))
- Schematic sign-off (optional EE stamp): [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (`--schematic-signoff`)
- SPICE sign-off (optional analog physics gate): [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md) (`--spice-signoff`)
- Scope / non-goals: [SCOPE.md](./SCOPE.md)

1. **Toolchain** — Record KiCad version, `kicad-cli --version`, Python version, and OpenHaC version (`openhac --version`).
2. **Catalog** — Prefer a populated offline DB (`sync` / `seed`). Avoid one-off JIT parts for fabrication. Use `OPENHAC_NO_NETWORK=1` for release builds (**FAB-010**).
3. **Compile (fabrication target)** — When Phase-2 gates are implemented, prefer:

```bash
OPENHAC_NO_NETWORK=1 openhac compile board.py \
  --name proj \
  --production \
  --compile-goal fabrication \
  --strict-footprint-pads \
  --require-verified-parts \
  --no-schematic \
  -o dist/proj \
  --zip-release \
  --release-tag vX.Y.Z
```

**Gate validation (no physical board):** known-good fixture + negatives:

```bash
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py
# With KiCad/pcbnew (CI layout job):
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_fab_gates.py --require-layout
# Full ERC → PCB DRC → Gerbers (needs FreeRouting + Java):
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_production.py --require-all --fetch-freerouting
```

Fixture: [`tests/fixtures/fab_golden_board.py`](../../tests/fixtures/fab_golden_board.py) (also [`examples/fab_golden_resistor_bridge.py`](../../examples/fab_golden_resistor_bridge.py)).

Until Phase-2 FAB gates landed, prefer explicit `--compile-goal fabrication`, `--strict-footprint-pads`, and `--require-verified-parts` with `--production`. Prefer `--no-schematic` for fab packages; preview connectivity with `openhac preview` (KiCad SVG, **SSO-012**) or Hardware IR JSON. Cytoscape webview is deprecated (**FAB-041**). Full software claim is the **2R golden** only: `python3 scripts/ci_validate_production.py --require-all --fetch-freerouting` (see [PRODUCTION_VALIDATION.md](./PRODUCTION_VALIDATION.md), **FAB-051**).

Advanced board capabilities (**ABC-***): see [ADVANCED_BOARD_CAPABILITIES_SPEC.md](./ADVANCED_BOARD_CAPABILITIES_SPEC.md). Complex multi-IC route subset: `ci_validate_complex_boards.py --place --route --route-subset esp32c3_usb,rs485_node`.

### Headless CI recipe (no pcbnew required)

- **Toolchain check**: `openhac doctor --strict-headless --json`
- **Compile (logic-only)**: `openhac --db-path /path/to/openhac.db compile board.py --skip-layout --deterministic -o out/`
- **Notes**: `--skip-layout` avoids `pcbnew`; `--deterministic` enables byte-stable artifacts suitable for golden comparisons; `--db-path` keeps CI isolated from developer machines. Add `--require-verified-parts` and `OPENHAC_NO_NETWORK=1`. Logic-only compiles do **not** satisfy the fabrication claim.

4. **Manifest** — Confirm `*.openhac-manifest.json` lists expected outputs and hashes. When present, review **fab_audit** (**FAB-032**): omitted footprints, enrich failures, pad warnings, unrouted nets, PCB DRC, network policy. Archive with `--zip-release`.
5. **Schematic ERC** — Optional unless `--schematic-signoff`. Preview (`openhac preview`) never runs `kicad-cli sch erc`. Prefer native ERC + KiCad SVG preview for connectivity; stamp with `--schematic-signoff`.
6. **PCB DRC** — For fabrication: ensure KiCad PCB DRC ran clean (**FAB-022**). Do not ship with unrouted nets unless explicitly waived and recorded.
7. **Fab** — `openhac export fab dist/proj/proj.kicad_pcb -o dist/proj/fab --zip` (optional `--ipc2581`). Attach stackup notes from [examples/fab_stackup_table.md](../../examples/fab_stackup_table.md) / [fab_stackup_jlc_example.json](./fab_stackup_jlc_example.json). Refuse export if omitted footprints remain (**FAB-003**).
8. **Review** — SI/PI/EMC remain manual per [SCOPE.md](./SCOPE.md). Autoroute is assistive only (**PCB-007**).
9. **SPICE (optional)** — Analog physics stamp is **not** implied by `--production`. When required:

```bash
OPENHAC_NO_NETWORK=1 openhac simulate board.py \
  --spice-signoff \
  --spice-vendor-dir /path/to/vendor-libs \
  --require-vendor-models \
  -o dist/proj
```

Vendor `.lib` files are **not** in git (`OPENHAC_SPICE_VENDOR_DIR`). Kirchhoff-only boards (R/C/L + declared rails) do not need vendor models. See [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md).
