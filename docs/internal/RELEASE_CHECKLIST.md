# Release checklist (SW-004)

Use this before tagging a hardware release or sending artifacts to a CM.

- Phase-1 context: [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md)
- Phase-2 fabrication gates: [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md) (track [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md))
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
```

Fixture: [`tests/fixtures/fab_golden_board.py`](../../tests/fixtures/fab_golden_board.py) (also [`examples/fab_golden_resistor_bridge.py`](../../examples/fab_golden_resistor_bridge.py)).

Until **FAB-030** lands, pass `--compile-goal fabrication`, `--strict-footprint-pads`, and `--require-verified-parts` explicitly even with `--production`. Prefer `--no-schematic` and review connectivity via webview/IR (**FAB-040**, **FAB-041**).

### Headless CI recipe (no pcbnew required)

- **Toolchain check**: `openhac doctor --strict-headless --json`
- **Compile (logic-only)**: `openhac --db-path /path/to/openhac.db compile board.py --skip-layout --deterministic -o out/`
- **Notes**: `--skip-layout` avoids `pcbnew`; `--deterministic` enables byte-stable artifacts suitable for golden comparisons; `--db-path` keeps CI isolated from developer machines. Add `--require-verified-parts` and `OPENHAC_NO_NETWORK=1`. Logic-only compiles do **not** satisfy the fabrication claim.

4. **Manifest** — Confirm `*.openhac-manifest.json` lists expected outputs and hashes. When present, review **fab_audit** (**FAB-032**): omitted footprints, enrich failures, pad warnings, unrouted nets, PCB DRC, network policy. Archive with `--zip-release`.
5. **Schematic ERC** — Optional. Only if you exported a schematic: `openhac compile … --kicad-erc` (optional `--kicad-erc-json`). Prefer native ERC + webview for connectivity review.
6. **PCB DRC** — For fabrication: ensure KiCad PCB DRC ran clean (**FAB-022**). Do not ship with unrouted nets unless explicitly waived and recorded.
7. **Fab** — `openhac export fab dist/proj/proj.kicad_pcb -o dist/proj/fab --zip` (optional `--ipc2581`). Attach stackup notes from [examples/fab_stackup_table.md](../../examples/fab_stackup_table.md) / [fab_stackup_jlc_example.json](./fab_stackup_jlc_example.json). Refuse export if omitted footprints remain (**FAB-003**).
8. **Review** — SI/PI/EMC remain manual per [SCOPE.md](./SCOPE.md). Autoroute is assistive only (**PCB-007**).
