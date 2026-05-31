# OpenHaC: Long-Term Architectural Roadmap

This document captures the strategic recommendations for scaling OpenHaC (Hardware as Code) from its current monolithic architecture into a robust, enterprise-grade Hardware Compiler. These recommendations address the core bottlenecks of stability, collaboration, and scalability.

---

## 1. The Core Philosophy: "The Unix Philosophy for Hardware"
Currently, OpenHaC is tightly coupled to the internal mechanics of KiCad (specifically the C++ SWIG bindings) and attempts to handle component lookup, schematic drawing, auto-routing, and physics injection all in one breath. 

**The Pivot:** OpenHaC should act strictly as a **Frontend Compiler**. Its only job should be executing the Python hardware definitions, resolving the modules/interfaces, and outputting a standardized **Hardware Intermediate Representation (IR)** (e.g., a rich JSON manifest or standardized Netlist with constraints). 

Downstream tasks should be handled by independent **Backend Plugins**:
* `openhac-kicad-bridge`: Applies the IR constraints to a `.kicad_pcb` file.
* `openhac-autorouter`: Wraps external AI or topological routers.
* `openhac-docs`: Generates interactive WebViews for human review.

---

## 2. Decoupling the Schematic Generator
**The Problem:** Algorithmically generating a static, 2D visual schematic (`.kicad_sch`) is an NP-Hard graph drawing problem. It causes the vast majority of test regressions (overlapping wires, coordinate math errors) and provides low ROI since the Python code is the true source of truth.

**The Solution:**
1. **Deprecate Default Generation:** Make `.kicad_sch` generation an optional, legacy plugin rather than the default critical path.
2. **Interactive WebViews:** Replace static schematics with interactive, web-based graph explorers (using libraries like Cytoscape.js or React Flow). This allows engineers to search, filter, and hierarchically zoom through massive hardware systems (similar to how cloud infrastructure or FPGA logic is debugged today).

---

## 3. Ecosystem Scalability: The "pip" for Hardware
To allow OpenHaC to scale across global engineering teams, hardware modules must be treated exactly like software libraries.
* **Hermetic Modules:** Move away from SKiDL's global `default_circuit` state. A `Module` should be completely isolated and strictly namespaced, preventing reference designator collisions in massive multi-board systems (e.g., an autonomous vehicle).
* **Package Management:** Enable users to publish validated modules (like an `ESP32_WiFi_Node`) as standard Python packages that others can simply `pip install` and instantiate on their own boards.

---

## 4. Validation Scalability: CI/CD for Hardware
If hardware is code, it must be testable like code. Before a board is ever routed, the compilation pipeline should run automated electrical and logical assertions.
* Build a headless Design Rule Check (DRC) API that runs entirely in memory against the IR.
* Allow users to write standard `pytest` assertions against their hardware (e.g., `assert board.get_total_current() < 5.0_Amps` or `assert mcu.spi.is_fully_connected()`).
* This enables Continuous Integration (CI) in GitHub Actions, catching floating pins and thermal budget violations on pull requests *before* the design reaches KiCad.

---

## 5. Intelligent Supply Chain Caching
Component lookups (LCSC/EasyEDA APIs) are slow and rate-limited. 
* Implement a robust, local SQLite-based caching layer for component metadata that can be shared across a team or committed to the repository (akin to a `package-lock.json`). 
* This ensures that compiling a massive board takes milliseconds rather than minutes and remains deterministic even if a vendor's API goes offline.

---
*Documented on 2026-05-31 following the stabilization of the OpenHaC v1 Schematic Pipeline.*
