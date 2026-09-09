# Fundi MIG — footprint enrichment

Electrical connectivity is ported from the KiCad netlist into
`fundi_mig_controller.py`. **No invented module footprints.**

Fundi source had empty footprints for ~136/157 parts and an empty
`EasyEDA.pretty`; the PCB has zero placed footprints.

## Verified (in `01_verified_packages.json`)

- `ATMEGA2560` → `Package_QFP:TQFP-100_14x14mm_P0.5mm` (was Arduino_Mega module)

Datasheet packages or stock KiCad module footprints only:

- `max485_1_1` → `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
- `max485_1_2` → `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
- `max485_1_3` → `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
- `max485_1_4` → `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
- `1N4007` → `Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal`
- `74HC14` → `Package_DIP:DIP-14_W7.62mm`
- `A1101ELHL` → `Package_TO_SOT_SMD:SOT-23W`
- `AD620` → `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
- `Arduino_Nano` → `Module:Arduino_Nano`
- `BT136-800` → `Package_TO_SOT_THT:TO-220-3_Vertical`
- `C` → `Capacitor_SMD:C_0805_2012Metric`
- `C_Small` → `Capacitor_SMD:C_0805_2012Metric`
- `D_Small` → `Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal`
- `LED` → `LED_THT:LED_D3.0mm`
- `MOC3021M` → `Package_DIP:DIP-6_W7.62mm`
- `PC817` → `Package_DIP:DIP-4_W7.62mm`
- `R` → `Resistor_SMD:R_0805_2012Metric`
- `R_Potentiometer` → `Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical`
- `SW_SPST` → `Button_Switch_THT:SW_PUSH_6mm`
- `Screw_Terminal_01x02` → `TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal`
- `ads1115` → `Package_SO:VSSOP-10_3x3mm_P0.5mm`
- `R_Small` → `Resistor_SMD:R_0805_2012Metric`
- `Arduino_Nano_Every_Socket` → `Module:Arduino_Nano`
- `MAX1044` → `Package_DIP:DIP-8_W7.62mm`

## Needs real footprints (in `02_needs_module_footprints.json`)

These have electrical pinouts but **empty** `kicad_footprint`.
Handoff skips them on the PCB (FAB-003 omit list).
`--production` / fabrication must fail until overlays supply real FPs.

- `max6675_thermocouple_module_1` refs=['U25', 'U44']
- `max6675_thermocouple_module_2` refs=['U21', 'U45']
- `max6675_thermocouple_module_3` refs=['U46']
- `max6675_thermocouple_module_4` refs=['U47']
- `Battery_Cell` refs=['BT1', 'BT2', 'BT3', 'BT5', 'BT4', 'BT6', 'BT7']
- `Motor_AC` refs=['M4']
- `Motor_Servo` refs=['M2']
- `VDC` refs=['V1', 'V3']
- `VSIN` refs=['V2']
- `max6675_thermocouple_module` refs=['U4']

## How to enrich

1. Obtain a real `.kicad_mod` (Mega module, MAX6675 breakout, battery holder, …).
2. Update the matching object in `02_needs_module_footprints.json`:
   set `kicad_footprint` and align `pinout[].num` to pad numbers.
3. Move the row into `01_verified_packages.json` (or leave in 02 once FP is set).
4. Recompile; omitted-ref list must shrink; fab gate must pass.

