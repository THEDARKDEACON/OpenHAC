# OpenHaC software architecture (maintainer notes)

This document captures **cross-cutting software design** that complements numbered items in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md).

## Compile context (no global `Component` stomp)

- **`Board.__init__` does not set** `Component.require_kicad_symbols` or `Component.strict_jit_lookups`. Sequential `Board(...)` constructions in one process no longer flip class-wide behavior.
- **`openhac.core.compile_context`**: `Board.compile` / `Board.simulate` install an `OpenHaCCompileContext` (contextvars) for **allow-risky** resolution during those calls.
- **Host board on modules**: `Board.add_module` stamps `_openhac_host_board` on the module subtree. **`Module.add_part("Generic")`** constructs a `Component` with `parent_module=self` so **`board.strict_kicad` / `strict_jit_lookups`** apply **during** `Component.__init__`. Plain `module.add(Component(...))` still runs `Component.__init__` before the module link exists; for strict-at-construction behavior, prefer **`add_part`** or pass **`parent_module=`** (keyword-only).
- **CLI** still may set **`Component` class attributes** before executing the user script (legacy path); it also copies **`--strict-kicad` / `--production` / `--strict-jit`** onto the **`board` instance** before `board.compile(...)`.

## Hardware tree iteration

- **`Module.__iter__`** yields direct children. **ERC/DRC** walks use `for child in module:` instead of hard-coding only the attribute name `components` on internal walks (subclasses can override `__iter__` for alternate storage).

## Compile pipeline

- **`openhac.compiler.compile_pipeline`**: ordered phases (`CompileState`, `DEFAULT_COMPILE_PHASES`) invoked from `Board.compile`. Easier to test and to swap phases later.

## Schematic pin order

- **`schematic_gen`**: non-numeric pin numbers use an **alphanumeric natural key** (e.g. **A2** before **A10**) to reduce crossing-wire risk from arbitrary ordering.

## JIT / API matching

- **`api_fallback._query_matches_item`**: optional **category slug** alignment when the API returns category metadata; **word-boundary** matching on description tokens (length ≥ 3) to reduce false positives from unrelated phrases.

## Power net naming (SCH-004)

- **`Board(power_net_prefixes=(...))`** extends default prefix heuristics alongside **`declare_power_rail`**.

## “Next 30 tickets” (batch stance)

Full **Done** closure of every **Partial** row in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) remains a **multi-phase** program. This change set advances **architecture + SCH-001/SCH-004/LIB-003/LIB-004** ergonomics; remaining IDs are updated in the status table, not all marked complete.
