"""
KiCad XML Netlist Generator

Generates KiCad-compatible XML netlist format from native Circuit/Part/Net objects.
"""

import logging
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

logger = logging.getLogger("openhac.netlist")


def generate_netlist(circuit, filepath: str | Path) -> Path:
    """Generate KiCad XML netlist from a Circuit or CircuitIR object.
    
    Args:
        circuit: A Circuit or CircuitIR object.
        filepath: Output path for the .net file
        
    Returns:
        Path to the generated netlist file
    """
    filepath = Path(filepath)
    
    from openhac.ir.circuit_ir import CircuitIR
    if isinstance(circuit, CircuitIR):
        cir = circuit
    else:
        from openhac.compiler.elaborator import elaborate
        cir = elaborate(circuit)
    
    # Create root element
    root = Element("export")
    root.set("version", "D")
    
    # Design info
    design = SubElement(root, "design")
    source = SubElement(design, "source")
    source.text = cir.name
    date = SubElement(design, "date")
    date.text = "today"
    tool = SubElement(design, "tool")
    tool.text = "OpenHaC CircuitIR Netlist Generator"
    
    # Components (parts)
    components = SubElement(root, "components")
    for comp_node in cir.components.values():
        comp = SubElement(components, "comp")
        comp.set("ref", comp_node.refdes)
        
        value = SubElement(comp, "value")
        value.text = comp_node.value or ""
        
        footprint = SubElement(comp, "footprint")
        footprint.text = comp_node.footprint or ""
        
        # Add any additional fields
        for key, val in (comp_node.attributes or {}).items():
            if val:
                field = SubElement(comp, "field")
                field.set("name", key)
                field.text = str(val)
    
    # Nets
    nets = SubElement(root, "nets")
    net_code = 1
    for net_node in cir.nets.values():
        if not net_node.connected_pin_paths:
            continue
            
        net_elem = SubElement(nets, "net")
        net_elem.set("code", str(net_code))
        net_elem.set("name", net_node.name)
        net_code += 1
        
        # Add all connected pins
        for pin_path in net_node.connected_pin_paths:
            if "." in pin_path:
                ref, pin = pin_path.rsplit(".", 1)
                node = SubElement(net_elem, "node")
                node.set("ref", ref)
                node.set("pin", pin)
    
    # Convert to pretty-printed XML
    xml_string = tostring(root, encoding="unicode")
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent="  ")
    
    # Write to file
    filepath.write_text(pretty_xml, encoding="utf-8")
    logger.info(f"Generated netlist: {filepath}")
    
    return filepath
