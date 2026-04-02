# Requirements Document

## Introduction

OpenHaC (Open Hardware-as-Code) is a Python-based PCB compiler framework that transforms high-level hardware descriptions into manufacturable PCB designs. This document covers five targeted production-readiness improvements identified in a code review: real KiCad schematic generation, live FreeRouting autorouter integration, hardened Module interface validation, net-level ERC checks, and correct SPICE reference designator assignment. Together these changes close the gap between the current prototype state and a pipeline that produces real, usable KiCad schematics, routed PCBs, and valid SPICE netlists.

## Glossary

- **Schematic_Generator**: The module `openhac/compiler/schematic_gen.py` responsible for producing `.kicad_sch` files.
- **Autorouter**: The module `openhac/compiler/autoroute_cli.py` responsible for invoking FreeRouting to produce routed PCB traces.
- **ERC_Engine**: The module `openhac/compiler/rule_check.py` responsible for Electrical Rule Checks.
- **SPICE_Generator**: The module `openhac/compiler/spice_gen.py` responsible for producing `.cir` SPICE netlists.
- **Module_System**: The `Module` and `Interface` classes in `openhac/core/base.py` that define the hardware abstraction layer.
- **KiCad_Schematic**: A `.kicad_sch` file conforming to the KiCad 7/8 S-expression schema, readable and usable by KiCad EDA.
- **S-expression**: The parenthesised text format used by KiCad for schematics and PCB files (e.g. `(symbol ...)`).
- **Symbol_Instance**: A `(symbol ...)` S-expression block inside a `.kicad_sch` file that places a schematic symbol at a specific coordinate.
- **Wire_Segment**: A `(wire (pts (xy ...) (xy ...)))` S-expression that draws an electrical connection line in a KiCad schematic.
- **Power_Flag**: A `PWR_FLAG` symbol required by KiCad ERC on every power net to suppress false "pin not driven" errors.
- **FreeRouting**: An open-source autorouter that accepts DSN (Specctra Design) files and produces SES (Specctra Session) files containing routed traces.
- **DSN_File**: A Specctra Design file (`.dsn`) exported from a KiCad PCB, used as input to FreeRouting.
- **SES_File**: A Specctra Session file (`.ses`) produced by FreeRouting, imported back into KiCad to apply routed traces.
- **Interface**: A named collection of `Net` objects on a `Module` that forms a typed connection point (e.g. `power`, `uart`, `spi`).
- **Required_Interface**: An `Interface` declared on a `Module` that must be connected before the compiler proceeds.
- **Floating_Net**: A `Net` that has fewer than two connected pins, meaning it carries no signal.
- **Unconnected_Pin**: A pin on a `Part` that has not been assigned to any `Net`.
- **ref_prefix**: The SKiDL `Part` attribute (e.g. `'R'`, `'C'`, `'U'`) that defines the correct SPICE reference designator prefix for a component.
- **SKiDL**: The Python netlist library used by OpenHaC to define parts, nets, and circuits.
- **Compiler**: The `Board.compile()` method and the pipeline of sub-modules it orchestrates.

---

## Requirements

### Requirement 1: Real KiCad Schematic Generation

**User Story:** As an electrical engineer, I want `Board.compile()` to produce a valid `.kicad_sch` file with proper symbol instances and wire geometry, so that I can open the schematic directly in KiCad without manual rework.

#### Acceptance Criteria

1. WHEN `export_schematic=True` is passed to `Board.compile()`, THE Schematic_Generator SHALL write a `.kicad_sch` file whose top-level S-expression is `(kicad_sch (version 20231120) ...)`.
2. THE Schematic_Generator SHALL emit one `(symbol ...)` S-expression instance for every `Part` in `default_circuit.parts`, including the part's `lib_id`, a unique `uuid`, and an `(at x y angle)` placement.
3. THE Schematic_Generator SHALL assign non-overlapping grid-aligned `(at x y)` coordinates to each Symbol_Instance, using a minimum spacing of 10 schematic units between adjacent symbols.
4. WHEN two pins on different parts share the same `Net`, THE Schematic_Generator SHALL emit `(wire (pts (xy x1 y1) (xy x2 y2)))` Wire_Segment S-expressions connecting those pins.
5. THE Schematic_Generator SHALL emit one `(label ...)` S-expression for every net that has more than two connected pins, using the net's name as the label text, so that complex nets remain readable.
6. IF `default_circuit` is unavailable at generation time, THEN THE Schematic_Generator SHALL raise a `SchematicGenerationError` with a descriptive message rather than silently producing an empty or text-only file.
7. THE Schematic_Generator SHALL NOT emit bare `(text ...)` nodes as substitutes for Symbol_Instance S-expressions.
8. WHEN the output `.kicad_sch` file is opened in KiCad 7 or KiCad 8, THE Schematic_Generator SHALL produce a file that KiCad loads without parse errors.

---

### Requirement 2: FreeRouting Autorouter Integration

**User Story:** As a PCB designer, I want `Board.compile()` to invoke the real FreeRouting autorouter via its CLI jar, so that the output `.kicad_pcb` contains fully routed copper traces rather than an unrouted ratsnest.

#### Acceptance Criteria

1. WHEN `auto_route=True` is passed to `Board.compile()` and a `.kicad_pcb` file exists, THE Autorouter SHALL export a DSN_File from the PCB using the KiCad Python scripting API or `kicad-cli`.
2. WHEN a DSN_File has been produced, THE Autorouter SHALL invoke the FreeRouting CLI jar via `subprocess` with the DSN_File as input and a target SES_File path as output.
3. WHEN FreeRouting completes successfully and a SES_File is present, THE Autorouter SHALL import the SES_File back into the `.kicad_pcb` using the KiCad Python scripting API or `kicad-cli`.
4. IF the FreeRouting jar is not found at the configured path, THEN THE Autorouter SHALL raise a `FreeRoutingNotFoundError` with the expected jar path, rather than silently succeeding.
5. IF the FreeRouting subprocess exits with a non-zero return code, THEN THE Autorouter SHALL raise a `AutorouterFailedError` containing the subprocess stderr output.
6. IF the SES_File is not produced after FreeRouting completes, THEN THE Autorouter SHALL raise a `AutorouterFailedError` indicating that no SES output was generated.
7. THE Autorouter SHALL accept a configurable `freerouting_jar_path` parameter, defaulting to the value of the `FREEROUTING_JAR` environment variable when set.
8. THE Autorouter SHALL log the FreeRouting subprocess stdout to the console in real time so that routing progress is visible to the user.

---

### Requirement 3: Hardened Module Interface System

**User Story:** As a hardware developer, I want Modules to expose only named Interfaces and for the Compiler to validate that all required interfaces are connected, so that raw pin-number access is eliminated and connection errors are caught before netlist generation.

#### Acceptance Criteria

1. THE Module_System SHALL provide a `declare_interface(name, *nets)` method on `Module` that registers an `Interface` as a required connection point and stores it in a `required_interfaces` dict.
2. WHEN a `Module` subclass calls `declare_interface(...)`, THE Module_System SHALL add that interface to `self.required_interfaces` keyed by name.
3. WHEN `Board.compile()` is called, THE Compiler SHALL iterate over all modules and verify that every interface in `module.required_interfaces` has been connected (i.e. its nets each have at least two pins attached).
4. IF any required interface on any module has an unconnected net, THEN THE Compiler SHALL raise an `UnconnectedInterfaceError` naming the module, the interface, and the unconnected net before any netlist or schematic output is written.
5. THE Module_System SHALL provide an `expose_interface(name)` method on `Module` that returns the named `Interface` object, raising `InterfaceNotFoundError` if the name does not exist.
6. THE stdlib modules (`ESP32_WROOM`, `XT60_Input`, `LDO_5V`) SHALL be updated to use `declare_interface(...)` instead of exposing raw pin-number assignments as public attributes.
7. THE Module_System SHALL preserve backward compatibility so that internal pin-number wiring within a module's `__init__` (e.g. `self.mcu['2'] += self.vcc`) continues to work unchanged.
8. WHEN a user attempts to access a module's internal part directly via a raw pin number from outside the module (e.g. `mcu.mcu['21']`), THE Module_System SHALL emit a `DeprecationWarning` indicating that direct pin access is discouraged in favour of named interfaces.

---

### Requirement 4: Net-Level Electrical Rule Check

**User Story:** As a hardware engineer, I want the ERC to check for floating nets, unconnected pins, and missing power flags on power nets, so that electrical errors are caught at compile time rather than discovered after fabrication.

#### Acceptance Criteria

1. WHEN `run_erc(board)` is called, THE ERC_Engine SHALL inspect every `Net` in `default_circuit.nets` and report any net that has fewer than two connected pins as a Floating_Net violation.
2. WHEN `run_erc(board)` is called, THE ERC_Engine SHALL inspect every `Pin` on every `Part` in `default_circuit.parts` and report any pin whose `net` attribute is `None` or unassigned as an Unconnected_Pin violation.
3. WHEN `run_erc(board)` is called, THE ERC_Engine SHALL identify every net whose name starts with a power-net prefix (e.g. `VCC`, `VIN`, `3V3`, `5V`, `GND`) and verify that at least one `PWR_FLAG` symbol is connected to that net.
4. IF any Floating_Net violations are found, THEN THE ERC_Engine SHALL raise an `ERCFloatingNetError` listing all offending net names.
5. IF any Unconnected_Pin violations are found, THEN THE ERC_Engine SHALL raise an `ERCUnconnectedPinError` listing all offending part references and pin numbers.
6. IF any power net is missing a Power_Flag, THEN THE ERC_Engine SHALL raise an `ERCMissingPowerFlagError` listing all offending net names.
7. THE ERC_Engine SHALL continue collecting all violations across all three checks before raising, so that a single compile run reports all ERC errors at once rather than stopping at the first.
8. THE ERC_Engine SHALL preserve the existing power-budget check (`ERCPowerBudgetError`) and run it alongside the new net-level checks.
9. WHERE a net is explicitly marked as intentionally unconnected using SKiDL's `NC` (no-connect) mechanism, THE ERC_Engine SHALL exclude that pin from Unconnected_Pin reporting.

---

### Requirement 5: Correct SPICE Reference Designator Assignment

**User Story:** As a simulation engineer, I want SPICE netlists to use each component's authoritative `ref_prefix` from SKiDL rather than string-matching heuristics, so that SPICE simulators parse the netlist correctly without manual correction.

#### Acceptance Criteria

1. WHEN generating a SPICE netlist, THE SPICE_Generator SHALL read the `ref_prefix` attribute from each SKiDL `Part` object to determine the correct SPICE reference designator prefix.
2. THE SPICE_Generator SHALL use the `Part.ref` value directly as the SPICE instance identifier when `Part.ref` already begins with the correct `ref_prefix`, without prepending an additional prefix.
3. WHEN `Part.ref` does not begin with the part's `ref_prefix`, THE SPICE_Generator SHALL prepend `ref_prefix` to `Part.ref` to form the SPICE identifier.
4. THE SPICE_Generator SHALL NOT use string matching on `Part.description`, `Part.value`, or `Part.name` to infer the reference designator prefix.
5. WHEN a `Part` has a `ref_prefix` of `None` or an empty string, THE SPICE_Generator SHALL default to `'X'` as the prefix and emit a warning to stdout identifying the part reference.
6. THE SPICE_Generator SHALL sanitize net names for SPICE compatibility by replacing spaces, hyphens, and forward slashes with underscores.
7. WHEN the generated `.cir` file is parsed by a SPICE simulator (e.g. ngspice), THE SPICE_Generator SHALL produce a file where every component line begins with a valid SPICE element identifier (a single letter followed by alphanumeric characters).
8. FOR ALL parts in `default_circuit.parts` that have at least two connected pins, THE SPICE_Generator SHALL include exactly one corresponding line in the `.cir` output — no duplicates and no omissions.
