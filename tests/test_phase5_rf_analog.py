import pytest

from openhac.rf.geometry import Microstrip, Substrate
from openhac.core.net import Net
from openhac.core.layout_zones import LayoutZone, StarGround
from openhac.core.base import Component
from openhac.core.module import Module
import openhac.core.circuit

@pytest.fixture(autouse=True)
def reset_circuit():
    openhac.core.circuit.reset_default_circuit()

def test_microstrip_impedance_calculation():
    """Verify that a 50-ohm microstrip on 1.6mm FR4 (er=4.4) calculates to roughly 3mm width."""
    sub = Substrate(er=4.4, h_mm=1.6, t_mm=0.035)
    ms = Microstrip(impedance_ohms=50.0, length_mm=10.0)
    
    ms.calculate_geometry(sub)
    
    # Using the IPC-2141 simplified equation, a 50 ohm trace on 1.6mm FR4 is roughly 2.9 - 3.1mm wide.
    assert 2.8 < ms.width_mm < 3.2, f"Expected width around 3.0mm, got {ms.width_mm:.2f}mm"
    
    # Check that points are generated
    assert len(ms.points) == 4
    assert ms.points[0] == (0.0, -ms.width_mm / 2.0)
    
def test_layout_zone_assignment():
    """Verify modules can be assigned to a layout zone."""
    zone = LayoutZone("Analog_Frontend", clearance_mm=2.5)
    mod = Module("ADC_Module")
    
    mod.assign_to(zone)
    
    assert mod.layout_zone == zone
    assert mod in zone.members
    
    manifest_dict = zone.to_manifest_dict()
    assert manifest_dict["name"] == "Analog_Frontend"
    assert manifest_dict["clearance_mm"] == 2.5
    assert "ADC_Module" in manifest_dict["members"]

def test_net_guard_ring_intent():
    """Verify a net can declare a guard ring intent."""
    agnd = Net("AGND")
    adc_input = Net("ADC_IN")
    
    adc_input.wrap_guard_ring(agnd)
    
    assert adc_input.guard_net == agnd

def test_starground_serialization():
    """Verify StarGround serializes correctly for the intent manifest."""
    dgnd = Net("DGND")
    agnd = Net("AGND")
    pwrgnd = Net("PWRGND")
    
    sg = StarGround("Main_Star_Point", nets=[dgnd, agnd, pwrgnd])
    
    manifest_dict = sg.to_manifest_dict()
    assert manifest_dict["name"] == "Main_Star_Point"
    assert "DGND" in manifest_dict["nets"]
    assert "AGND" in manifest_dict["nets"]
    assert "PWRGND" in manifest_dict["nets"]
