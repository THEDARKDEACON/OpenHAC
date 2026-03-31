# OpenHaC (Open Hardware-as-Code)

OpenHaC is a general-purpose, open-source Python compiler that translates declarative, object-oriented code into physically routed circuit boards and procurable Bills of Materials (BOM).

## Vision & Objective

The core directive of OpenHaC is to eliminate the need for GUI-based PCB layout tools during the standard design phase. The system natively bridges logical intent (using `SKiDL`), real-world procurable supply chains (via a local `SQLite` database), and geometric physical layouts (using the `KiCad` Python API). Every generic component requested in the Python code automatically resolves to a real Manufacturer Part Number (MPN) upon compilation.

## Architecture

OpenHaC operates on a strict 3-Tier Model ensuring clean abstraction constraints:

### 1. Tier 1: Parametric Translation Engine (`openhac/database/`)
The single source of truth for the physical reality of the board. All hardware code requests generic components (e.g., `R_10k_0805`), and the local DB dynamically queries its schema to map them to specific `KiCad` footprints and real-world MPNs from suppliers like LCSC or Yageo.
- **Live Catalog Sync (`sync_jlc.py`)**: Automatically download and cache realtime structural snapshots of the JLCPCB/LCSC global distributor catalogs using memory-safe HTTP Chunked Streaming. This creates a lightning-fast localized SQLite DB without relying on rate-limited internet APIs.

### 2. Tier 2: Core Abstraction Engine (`openhac/core/` & `openhac/stdlib/`)
The front-facing API that wraps raw `SKiDL` pins in intuitive Object-Oriented patterns.
- `Component`: Overloads dictionary mapping to seamlessly instantiate KiCad paths and inject SKU/MPN definitions directly into SKiDL metadata.
- `Module`: Collects hardware components logically and tracks Physics constraints (`max_current_draw_ma`, `height`, `width`).
- `Board`: Manages the overall logic tree, routing rules, and invokes the compiler pipelines.

### 3. Tier 3: Compilation Engine (`openhac/compiler/`)
The compiler runtime translates abstract objects into physical manufacturing files across multiple advanced phases:
- **Hardware Physics Validations (ERC & DRC)**: 
  - **Power Budgeting**: Scans all node branches for theoretical `max_current_draw` and cross-evaluates it against power supply source limits. Compilations on logically overloaded or shorted circuits are immediately halted.
  - **IPC-2152 Traces**: Calculates mandatory trace width geometries based on node amperage loads to prevent thermal failure.
- **SMT Spatial Constraint Solver**: Uses Microsoft's `z3-solver` to mathematically prove non-overlapping placement coordinates based on user-defined algebraic rules (e.g. keeping hot components structurally isolated).
- **Geometric Layout Compiler**: Utilizes `pcbnew` (KiCad API) to map solved coordinates and board constraints to the copper CAD.
- **SPICE Simulation Engine**: Call `.simulate()` to bypass the physical geometry entirely and output declarative python graphs directly into industry-standard `.cir` SPICE files for evaluating AC/DC transient responses.
- **Legacy EDA Interoperability**: Passing `export_schematic=True` synthesizes `.kicad_sch` (2D Visual Schematics) and `.kicad_pro` wrappers directly from the Python objects, guaranteeing 100% downstream compatibility with electrical engineers using the traditional KiCad 8.0/9.0 Desktop Suite.

## Features at a Glance
- **Headless Execution**: Compiles everything exclusively from the Python command line without ever starting the KiCad layout GUI.
- **Hardware-as-Code Declarations**: Clean, explicit layout interfaces mimicking declarative UI frameworks.
- **Zero-Cost Supply Chain Integrity**: Injects strict LCSC Manufacturer Part Numbers (MPNs) directly into your exported `.csv` BOMs for seamless JLCPCB ordering.
- **Graceful Fallbacks**: Automatically generates synthetic SKiDL dummy parts upon missing local KiCad footprint libraries for use in headless CI/CD integration pipelines.

## Getting Started

1. **Install Requirements**:
   Ensure you have SKiDL, python 3.12, and KiCad installed (alongside its Python bindings).
   ```bash
   pip install -e .
   ```

2. **Seed Local Database**:
   Establish your initial catalog of procurable MPNs.
   ```bash
   python -m openhac.database.seed_data
   ```

3. **Compiler Demonstration**:
   Design your circuit via a declarative Python file (`build.py`) representing an ultimate acceptance integration test.
   ```bash
   python build.py
   ```
   *Expected outputs*: `iot_node.net`, `iot_node.csv`, and `iot_node.kicad_pcb` seamlessly materialized without GUI intervention.
