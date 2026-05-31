"""
comms.py — Communication and interface controller wrappers.

Includes USB-Serial bridges, Ethernet controllers, and CAN-bus transceivers.
"""
from openhac.core.base import Component, Module
from openhac.core.net import Net, Bus

class USBSerialBridge(Module):
    """USB-to-UART bridge (CH340G/C compatible)."""
    def __init__(self, mpn: str = "CH340C"):
        super().__init__(f"USB_UART_{mpn}")
        self.ic = self.add(Component(mpn))
        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        self.tx = Net("TX")
        self.rx = Net("RX")
        
        # Semantic mapping
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd
        self.ic["TX"] += self.tx
        self.ic["RX"] += self.rx
        
        # USB D+/D- semantic lookup
        self.ic["D+"] += Net("USB_DP")
        self.ic["D-"] += Net("USB_DN")

        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.uart = self.declare_interface("uart", tx=self.tx, rx=self.rx)
        self.usb = self.declare_interface("usb", dp=self.ic["D+"], dn=self.ic["D-"])

class EthernetController(Module):
    """W5500 SPI-to-Ethernet Controller."""
    def __init__(self):
        super().__init__("W5500_Ethernet")
        self.ic = self.add(Component("W5500"))
        self.vcc = Net("3V3")
        self.gnd = Net("GND")
        
        # Power
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd
        
        # SPI Interface (Semantic)
        self.ic["MOSI"] += Net("MOSI")
        self.ic["MISO"] += Net("MISO")
        self.ic["SCLK"] += Net("SCLK")
        self.ic["CS"]   += Net("nCS")
        
        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.spi = self.declare_interface("spi", mosi=self.ic["MOSI"], miso=self.ic["MISO"], 
                                         sclk=self.ic["SCLK"], cs=self.ic["CS"])

class CANTransceiver(Module):
    """CAN-bus transceiver (TJA1051 or similar)."""
    def __init__(self, mpn: str = "TJA1051T"):
        super().__init__(f"CAN_{mpn}")
        self.ic = self.add(Component(mpn))
        self.vcc = Net("VCC")
        self.gnd = Net("GND")
        
        self.ic["VCC"] += self.vcc
        self.ic["GND"] += self.gnd
        self.ic["TX"] += Net("CAN_TX")
        self.ic["RX"] += Net("CAN_RX")
        
        self.ic["CANH"] += Net("CAN_H")
        self.ic["CANL"] += Net("CAN_L")
        
        self.power = self.declare_interface("power", self.vcc, self.gnd)
        self.mcu_side = self.declare_interface("mcu", tx=self.ic["TX"], rx=self.ic["RX"])
        self.bus_side = self.declare_interface("bus", high=self.ic["CANH"], low=self.ic["CANL"])
