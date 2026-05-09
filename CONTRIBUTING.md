# Contributing to OpenHaC

Thank you for considering contributing to OpenHaC! This document covers the
development setup, code organization, and contribution workflow.

## Development Setup

### Prerequisites
- Python 3.11+
- KiCad 8 or 9 (`kicad-cli` on PATH for full pipeline)
- FreeRouting JAR (optional, for automated PCB routing)

### Quick Start

```bash
# Clone and install in editable mode with dev dependencies
git clone https://github.com/THEDARKDEACON/OpenHAC.git
cd OpenHAC
pip install -e ".[dev]"

# Verify your toolchain
openhac doctor

# Seed the component database
openhac seed
```

### Environment Variables

Copy `.env.example` to `.env` and set at minimum:
- `KICAD8_SYMBOL_DIR` — path to KiCad symbol libraries
- `KICAD8_FOOTPRINT_DIR` — path to KiCad footprint libraries
- `OPENHAC_DB_PATH` — path to the SQLite catalog (default: `openhac/database/openhac.db`)

Run `openhac doctor --print-env` to auto-detect typical paths.

## Code Organization

```
openhac/
├── core/                    # Foundational types
│   ├── base.py              # Component class + backward-compat re-exports
│   ├── board.py             # Board (top-level container, compile entry point)
│   ├── compile_context.py   # Per-compile contextvars state
│   ├── compile_profile.py   # Named strictness presets (dev/handoff/production/fabrication)
│   ├── exceptions.py        # All OpenHaCError subclasses
│   ├── interface.py         # Interface class (named signal groups)
│   ├── module.py            # Module class (logical component groupings)
│   ├── net.py               # Native Net/Bus (replaces SKiDL)
│   ├── part.py              # Native Part/Pin (replaces SKiDL)
│   ├── pin_resolution.py    # Pin resolution pipeline (explicit → DB → fallback)
│   └── refdes.py            # Reference designator prefix logic
│
├── compiler/                # Compile pipeline phases
│   ├── compile_pipeline.py  # Phase orchestration
│   ├── rule_check.py        # ERC/DRC engine
│   ├── schematic_gen.py     # .kicad_sch generation
│   ├── pcb_placement.py     # Z3-based PCB placement
│   └── ...                  # Other pipeline stages
│
├── database/                # SQLite catalog management
│   ├── db_manager.py        # DatabaseManager class
│   ├── sync_jlc.py          # JLC/LCSC catalog synchronization
│   └── enrich.py            # Vendor API enrichment
│
├── stdlib/                  # Standard library modules
│   ├── power.py             # Buck converters, LDOs
│   ├── erc_rules.py         # Pull-up / decoupling ERC hooks
│   └── ...
│
├── cli.py                   # CLI entry point
└── cli_env_context.py       # env_scope() context manager
```

## Running Tests

```bash
# Full suite
python -m pytest tests/ -x -q

# Specific area
python -m pytest tests/test_erc*.py -v
python -m pytest tests/test_compile*.py -v

# With coverage
python -m pytest tests/ --cov=openhac --cov-report=html
```

## Adding New Components to the Database

### Via Catalog Sync
```bash
openhac sync --categories "Resistors,Capacitors"
```

### Via Seed File
```bash
openhac seed  # loads bundled seed data
```

### Via Vendor Enrichment
```bash
openhac database enrich --skus-file parts.json --vendor jlcpcb
```

## Adding New ERC Rules

ERC hooks are functions with the signature `fn(board) -> list[str]`. Register
them on a board via `board.register_erc_hook(fn)`:

```python
from openhac.stdlib.erc_rules import pullup_erc_hook

# Factory for standard pull-up checks
hook = pullup_erc_hook(my_net, label="I2C SDA")
board.register_erc_hook(hook)
```

See `openhac/stdlib/erc_rules.py` for the full catalog of built-in hooks.

## Compile Profiles

Instead of setting 15+ individual strictness flags, use named profiles:

```python
board = Board(profile="fabrication")  # strictest — all gates enabled
board = Board(profile="handoff")      # reviewable outputs, implicit pins OK
```

Or via CLI:
```bash
openhac compile --compile-goal fabrication example.py
openhac compile --production example.py
```

## PR Checklist

- [ ] All existing tests pass (`python -m pytest tests/ -x -q`)
- [ ] New features have corresponding tests
- [ ] No new `mypy` errors in `openhac/core/`
- [ ] Docstrings on public functions/classes
- [ ] `openhac doctor` still passes
- [ ] If touching the compile pipeline, verify with an example:
      `openhac compile examples/autonomous_boat_system.py --skip-layout -o /tmp/test`
