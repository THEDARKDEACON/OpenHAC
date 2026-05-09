# Release checklist (SW-004)

Use this before tagging a hardware release or sending artifacts to a CM. Complement [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md).

1. **Toolchain** — Record KiCad version, `kicad-cli --version`, Python version, and OpenHaC version (`openhac --version`).
2. **Catalog** — Prefer a populated DB (`sync` / `seed`); avoid one-off JIT parts for production, or use `openhac compile --production` / strict flags.
3. **Compile** — Run full compile (or `OPENHAC_SKIP_LAYOUT=1` only for logic CI). Use `-o DIR` and optional `--release-tag vX.Y.Z`, `--build-profile production`, `--zip-release`.

### Headless CI recipe (no pcbnew required)

- **Toolchain check**: `openhac doctor --strict-headless --json`
- **Compile (logic-only)**: `openhac --db-path /path/to/openhac.db compile board.py --skip-layout --deterministic -o out/`
- **Notes**: `--skip-layout` avoids `pcbnew`; `--deterministic` enables byte-stable artifacts suitable for golden comparisons; `--db-path` keeps CI isolated from developer machines. For a “no unverified/JIT parts” gate, add `--require-verified-parts`.
4. **Manifest** — Confirm `*.openhac-manifest.json` lists all expected outputs and hashes; archive with `--zip-release` or your own process.
5. **Schematic ERC** — With KiCad installed: `openhac compile … --kicad-erc` (optional `--kicad-erc-json`). Parse reports via `openhac.compiler.kicad_erc_report.summarize_kicad_erc_report` in CI (SCH-003).
6. **Fab** — `openhac export fab …` (optional `--ipc2581`). Attach stackup notes from [examples/fab_stackup_table.md](../examples/fab_stackup_table.md) / [fab_stackup_jlc_example.json](./fab_stackup_jlc_example.json).
7. **Review** — DRC/ERC clean in KiCad for golden designs; SI/PI/EMC remain manual per [SCOPE.md](./SCOPE.md).
