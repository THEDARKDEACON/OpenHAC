"""
KiCad Schematic Generator

Creates .kicad_sch files from native Circuit/Part/Net objects.
"""

import logging
from pathlib import Path

logger = logging.getLogger("openhac.schematic")


class SchematicWriter:
    """Generates KiCad schematic files."""
    
    def write(self, circuit, filepath: str | Path) -> Path:
        """Write schematic to file.
        
        Args:
            circuit: The Circuit object
            filepath: Output path for the .kicad_sch file
            
        Returns:
            Path to the generated schematic file
        """
        filepath = Path(filepath)
        
        # Generate s-expression format
        lines = self._generate_sch(circuit)
        
        # Write to file
        filepath.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Generated schematic: {filepath}")
        
        return filepath
    
    def _generate_sch(self, circuit) -> list[str]:
        """Generate s-expression lines for schematic."""
        lines = [
            "(kicad_sch (version 20211123) (generator \"OpenHaC\")",
            "  (paper \"A4\")",
            "",
            "  (lib_symbols",
        ]
        
        # Add symbols for each part type
        symbols_added = set()
        for part in circuit.parts:
            symbol_name = self._get_symbol_name(part)
            if symbol_name not in symbols_added:
                lines.extend(self._generate_symbol(symbol_name, part))
                symbols_added.add(symbol_name)
        
        lines.append("  )")
        lines.append("")
        
        # Add component instances
        for i, part in enumerate(circuit.parts):
            x = 50 + (i % 10) * 25
            y = 50 + (i // 10) * 25
            lines.extend(self._generate_component(part, x, y))
        
        # Add wires for nets
        for net in circuit.get_nets():
            if len(net.pins) >= 2:
                lines.extend(self._generate_net_wires(net))
        
        lines.append(")")
        
        return lines
    
    def _get_symbol_name(self, part) -> str:
        """Get symbol name from part."""
        # Try to extract from footprint or use generic
        fp = part.footprint or ""
        if "Resistor" in fp or part.value and part.refdes.startswith("R"):
            return "Device:R"
        elif "Capacitor" in fp or part.value and part.refdes.startswith("C"):
            return "Device:C"
        elif "Inductor" in fp or part.value and part.refdes.startswith("L"):
            return "Device:L"
        else:
            return f"Device:IC"
    
    def _generate_symbol(self, name: str, part) -> list[str]:
        """Generate symbol definition."""
        return [
            f"    (symbol \"{name}\" (pin_numbers hide) (pin_names hide)",
            "      (property \"Reference\" \"${REFERENCE}\" (id 0))",
            "      (property \"Value\" \"${VALUE}\" (id 1))",
            "    )",
        ]
    
    def _generate_component(self, part, x: int, y: int) -> list[str]:
        """Generate component instance."""
        symbol = self._get_symbol_name(part)
        lines = [
            f"  (symbol (lib_id \"{symbol}\") (at {x} {y} 0)",
            f"    (property \"Reference\" \"{part.refdes}\" (at {x} {y-5} 0))",
            f"    (property \"Value\" \"{part.value or ''}\" (at {x} {y+5} 0))",
        ]
        
        # Add pins
        for pin in part.get_pins():
            lines.append(f"    (pin \"{pin.number}\" (at {x+10} {y} 0))")
        
        lines.append("  )")
        lines.append("")
        
        return lines
    
    def _generate_net_wires(self, net) -> list[str]:
        """Generate wires for a net."""
        lines = []
        pins = list(net.pins)
        
        # Simple wire between consecutive pins
        for i in range(len(pins) - 1):
            # In a real implementation, we'd calculate positions
            # For now, just placeholder
            pass
        
        return lines
