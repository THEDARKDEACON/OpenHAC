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
    """Generate KiCad XML netlist from circuit.
    
    Args:
        circuit: The Circuit object containing parts and nets
        filepath: Output path for the .net file
        
    Returns:
        Path to the generated netlist file
    """
    filepath = Path(filepath)
    
    # Create root element
    root = Element("export")
    root.set("version", "D")
    
    # Design info
    design = SubElement(root, "design")
    source = SubElement(design, "source")
    source.text = circuit.name
    date = SubElement(design, "date")
    date.text = "today"
    tool = SubElement(design, "tool")
    tool.text = "OpenHaC Native Netlist Generator"
    
    # Components (parts)
    components = SubElement(root, "components")
    for part in circuit.parts:
        comp = SubElement(components, "comp")
        comp.set("ref", part.refdes)
        
        value = SubElement(comp, "value")
        value.text = part.value or ""
        
        footprint = SubElement(comp, "footprint")
        footprint.text = part.footprint or ""
        
        # Add any additional fields
        for key, val in (part.fields or {}).items():
            if val:
                field = SubElement(comp, "field")
                field.set("name", key)
                field.text = str(val)
    
    # Nets
    nets = SubElement(root, "nets")
    for net in circuit.get_nets():
        if not net.is_connected():
            continue
            
        net_elem = SubElement(nets, "net")
        net_elem.set("code", str(net.code or 0))
        net_elem.set("name", net.name or f"Net-{net.code}")
        
        # Add all connected pins
        for pin in net.pins:
            node = SubElement(net_elem, "node")
            node.set("ref", pin.part.refdes if pin.part else "?")
            node.set("pin", pin.number)
    
    # Convert to pretty-printed XML
    xml_string = tostring(root, encoding="unicode")
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent="  ")
    
    # Write to file
    filepath.write_text(pretty_xml, encoding="utf-8")
    logger.info(f"Generated netlist: {filepath}")
    
    return filepath
