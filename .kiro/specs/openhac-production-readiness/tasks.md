# Implementation Plan: OpenHaC Production Readiness

## Overview

Five self-contained improvements to the OpenHaC PCB compiler pipeline, implemented in dependency order: Module interface system first (other modules depend on it), then ERC, SPICE, schematic, and autorouter. Tests live in `tests/`.

## Tasks

- [x] 1. Harden Module interface system (`openhac/core/base.py`)
  - [x] 1.1 Add `required_interfaces` dict, `declare_interface`, and `expose_interface` to `Module`
    - Add `self.required_interfaces: dict[str, Interface] = {}` to `Module.__init__`
    - Implement `declare_interface(name, *nets) -> Interface` that creates an `Interface`, stores it in `required_interfaces`, and returns it
    - Implement `expose_interface(name) -> Interface` that returns the named interface or raises `InterfaceNotFoundError`
    - Add `UnconnectedInterfaceError` and `InterfaceNotFoundError` to the exception hierarchy in `base.py`
    - _Requirements: 3.1, 3.2, 3.5_

  - [ ]* 1.2 Write property test for `declare_interface`/`expose_interface` round-trip
    - **Property 8: declare_interface round-trip**
    - **Validates: Requirements 3.1, 3.2, 3.5**

  - [x] 1.3 Add `DeprecationWarning` on external raw pin access
    - Override `__getitem__` on the component wrapper to inspect the call stack frame and emit `DeprecationWarning` when the caller is outside the owning module's `__init__`
    - _Requirements: 3.8_

  - [ ]* 1.4 Write unit test for `DeprecationWarning` on external pin access
    - Use `warnings.catch_warnings` to assert the warning is emitted when a pin is accessed from outside the module
    - _Requirements: 3.8_

- [x] 2. Update `Board.compile()` to validate required interfaces (`openhac/core/board.py`)
  - [x] 2.1 Add interface validation step before netlist generation
    - After ERC/DRC, iterate all modules; for each interface in `module.required_interfaces`, check that every net has ≥ 2 pins attached
    - Raise `UnconnectedInterfaceError` naming module, interface, and unconnected net if any fail
    - _Requirements: 3.3, 3.4_

  - [ ]* 2.2 Write property test for unconnected required interface raising compile error
    - **Property 9: Unconnected required interface triggers compile error**
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 2.3 Write property test for internal module wiring unaffected by interface system
    - **Property 10: Internal module wiring is unaffected by interface system**
    - **Validates: Requirements 3.7**

- [x] 3. Update stdlib modules to use `declare_interface` (`openhac/stdlib/mcu.py`, `openhac/stdlib/power.py`)
  - [x] 3.1 Migrate `ESP32_WROOM`, `XT60_Input`, and `LDO_5V` to call `declare_interface`
    - Replace raw pin-number public attributes with `declare_interface(...)` calls in each module's `__init__`
    - Preserve all internal pin wiring (e.g. `self.mcu['2'] += self.vcc`) unchanged
    - _Requirements: 3.6, 3.7_

  - [ ]* 3.2 Write unit tests for stdlib module interface registration
    - Assert that `ESP32_WROOM`, `XT60_Input`, and `LDO_5V` each populate `required_interfaces` after construction
    - _Requirements: 3.6_

- [ ] 4. Checkpoint — ensure interface system tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Extend ERC engine with net-level checks (`openhac/compiler/rule_check.py`)
  - [x] 5.1 Add `ERCFloatingNetError`, `ERCUnconnectedPinError`, and `ERCMissingPowerFlagError` exceptions
    - Define the three new exception classes inheriting from `OpenHaCError`
    - _Requirements: 4.4, 4.5, 4.6_

  - [x] 5.2 Implement `_check_net_level(board)` and integrate into `run_erc`
    - Floating-net check: collect nets with < 2 connected pins
    - Unconnected-pin check: collect pins where `pin.net` is `None` or unassigned, skipping SKiDL `NC` pins
    - Power-flag check: collect power nets (case-insensitive prefix match against `VCC`, `VIN`, `3V3`, `5V`, `GND`, `VBAT`, `VBUS`) with no `PWR_FLAG` connected
    - Collect all violations before raising; use `ExceptionGroup` on Python ≥ 3.11, fallback to concatenated message on older versions
    - Preserve existing `ERCPowerBudgetError` check
    - _Requirements: 4.1, 4.2, 4.3, 4.7, 4.8, 4.9_

  - [ ]* 5.3 Write property test for ERC floating-net detection
    - **Property 11: ERC detects all floating nets**
    - **Validates: Requirements 4.1, 4.4**

  - [ ]* 5.4 Write property test for ERC unconnected-pin detection
    - **Property 12: ERC detects all unconnected pins**
    - **Validates: Requirements 4.2, 4.5, 4.9**

  - [ ]* 5.5 Write property test for ERC missing power-flag detection
    - **Property 13: ERC detects all power nets missing PWR_FLAG**
    - **Validates: Requirements 4.3, 4.6**

  - [ ]* 5.6 Write property test for ERC collecting all violations before raising
    - **Property 14: ERC collects all violations before raising**
    - **Validates: Requirements 4.7**

  - [ ]* 5.7 Write unit tests for ERC edge cases
    - Verify `ERCPowerBudgetError` still raised after net-level checks are added
    - Verify NC pins are excluded from unconnected-pin reporting
    - _Requirements: 4.8, 4.9_

- [x] 6. Fix SPICE reference designator assignment (`openhac/compiler/spice_gen.py`)
  - [x] 6.1 Replace string-matching heuristics with `Part.ref_prefix` lookup
    - Implement ref-prefix resolution: use `part.ref_prefix or 'X'` (emit warning when defaulting to `'X'`)
    - If `part.ref` already starts with `ref_prefix`, use `part.ref` as-is; otherwise prepend `ref_prefix`
    - Remove all `part.description`/`part.value`/`part.name` string matching
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.2 Add net name sanitization
    - Replace spaces, hyphens, and forward slashes in net names with underscores
    - Apply sanitization to all net identifiers in the `.cir` output
    - _Requirements: 5.6_

  - [x] 6.3 Ensure bijective part-to-line output
    - Emit exactly one `.cir` line per part with ≥ 2 connected pins; skip parts with fewer
    - Guard against duplicates by tracking emitted part refs
    - _Requirements: 5.7, 5.8_

  - [ ]* 6.4 Write property test for SPICE ref designator correctness
    - **Property 15: SPICE ref designator uses ref_prefix correctly**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ]* 6.5 Write property test for SPICE net name sanitization
    - **Property 16: SPICE net name sanitization**
    - **Validates: Requirements 5.6**

  - [ ]* 6.6 Write property test for SPICE bijection over connected parts
    - **Property 17: SPICE output is a bijection over connected parts**
    - **Validates: Requirements 5.7, 5.8**

- [ ] 7. Checkpoint — ensure ERC and SPICE tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Rewrite schematic generator (`openhac/compiler/schematic_gen.py`)
  - [x] 8.1 Add `SchematicGenerationError` and internal data structures
    - Define `SchematicGenerationError` in the exception hierarchy
    - Define `PartPlacement` dataclass with `part`, `x`, `y`, `uuid` fields
    - _Requirements: 1.6_

  - [x] 8.2 Implement `_assign_grid_positions` and `_emit_symbol_instance`
    - `_assign_grid_positions(parts)`: row-major scan, 10-unit cell spacing, returns `dict[Part, tuple[float, float]]`
    - `_emit_symbol_instance(f, part, x, y, uuid_str)`: writes `(symbol ...)` block with `lib_id`, `uuid`, and `(at x y angle)`
    - _Requirements: 1.2, 1.3_

  - [x] 8.3 Implement `_emit_wire` and `_emit_net_label`
    - `_emit_wire(f, x1, y1, x2, y2)`: writes `(wire (pts (xy x1 y1) (xy x2 y2)))` block
    - `_emit_net_label(f, net_name, x, y)`: writes `(label ...)` block; called only for nets with > 2 pins
    - _Requirements: 1.4, 1.5_

  - [x] 8.4 Implement `generate_schematic` top-level function
    - Write `(kicad_sch (version 20231120) ...)` header
    - Call `_assign_grid_positions`, emit all symbol instances, wires, and labels
    - Raise `SchematicGenerationError` if `default_circuit` is unavailable
    - Emit zero `(text ...)` placeholder nodes
    - _Requirements: 1.1, 1.6, 1.7, 1.8_

  - [ ]* 8.5 Write property test for schematic S-expression header
    - **Property 1: Schematic file has correct S-expression header**
    - **Validates: Requirements 1.1**

  - [ ]* 8.6 Write property test for symbol instance count
    - **Property 2: Symbol instance count matches part count**
    - **Validates: Requirements 1.2**

  - [ ]* 8.7 Write property test for non-overlapping grid-aligned placements
    - **Property 3: Symbol placements are non-overlapping and grid-aligned**
    - **Validates: Requirements 1.3**

  - [ ]* 8.8 Write property test for wire segments on shared-net pins
    - **Property 4: Shared-net pins produce wire segments**
    - **Validates: Requirements 1.4**

  - [ ]* 8.9 Write property test for net label count
    - **Property 5: Multi-pin nets produce net labels**
    - **Validates: Requirements 1.5**

  - [ ]* 8.10 Write property test for absence of text placeholder nodes
    - **Property 6: No bare text nodes in place of symbols**
    - **Validates: Requirements 1.7**

  - [ ]* 8.11 Write unit test for `SchematicGenerationError` on missing circuit
    - Assert `SchematicGenerationError` is raised with a descriptive message when `default_circuit` is unavailable
    - _Requirements: 1.6_

- [x] 9. Rewrite autorouter integration (`openhac/compiler/autoroute_cli.py`)
  - [x] 9.1 Add `FreeRoutingNotFoundError` and `AutorouterFailedError` exceptions
    - Define both exception classes inheriting from `OpenHaCError`
    - _Requirements: 2.4, 2.5, 2.6_

  - [x] 9.2 Implement jar-path resolution and DSN export
    - Resolve jar path: explicit parameter → `FREEROUTING_JAR` env var → raise `FreeRoutingNotFoundError`
    - Export DSN via `kicad-cli pcb export-dsn` using `subprocess.run`
    - _Requirements: 2.1, 2.4, 2.7_

  - [x] 9.3 Implement FreeRouting subprocess invocation with real-time stdout streaming
    - Invoke `java -jar <jar> -input <dsn> -output <ses>` via `subprocess.Popen`
    - Stream stdout line-by-line to console in real time
    - Raise `AutorouterFailedError` with stderr on non-zero exit code
    - _Requirements: 2.2, 2.5, 2.8_

  - [x] 9.4 Implement SES verification and import
    - Check SES file exists after FreeRouting completes; raise `AutorouterFailedError` if absent
    - Import SES via `kicad-cli pcb import-ses`
    - _Requirements: 2.3, 2.6_

  - [ ]* 9.5 Write property test for jar path resolution from environment variable
    - **Property 7: Autorouter jar path resolution from environment**
    - **Validates: Requirements 2.7**

  - [ ]* 9.6 Write unit tests for autorouter subprocess flow
    - Mock `subprocess.Popen` and `subprocess.run` to verify correct CLI commands are assembled for DSN export, FreeRouting invocation, and SES import
    - Assert `FreeRoutingNotFoundError` when jar is missing
    - Assert `AutorouterFailedError` on non-zero exit code and on missing SES output
    - _Requirements: 2.4, 2.5, 2.6_

- [ ] 10. Final checkpoint — ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Property tests use Hypothesis (`pip install hypothesis`), configured with `@settings(max_examples=100)`
- Each property test comment must include the tag: `# Feature: openhac-production-readiness, Property N: <property_text>`
- Tasks are ordered by dependency: interface system → board validation → stdlib → ERC → SPICE → schematic → autorouter
- All new exceptions inherit from `OpenHaCError` (base exception in `openhac/core/base.py`)
