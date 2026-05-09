import os
from openhac.core.base import Component, Module, Net
from openhac.core.board import Board

def MockComp(name: str, pin_count: int = 0, pin_dict: dict | None = None, lcsc_id: str | None = None, footprint: str | None = None) -> Component:
    """Helper for complex industrial modules without direct LCSC mapping."""
    if pin_dict is None:
        pin_dict = {str(i): (f"P{i}", "passive") for i in range(1, pin_count + 1)}
    kwargs = {"pins": pin_dict}
    if lcsc_id:
        kwargs["lcsc_id"] = lcsc_id
    if footprint:
        kwargs["footprint"] = footprint
    return Component(name, **kwargs)

class PowerSubsystem(Module):
    """14.8V Traction + Isolated Logic Power Distribution."""
    def __init__(self) -> None:
        super().__init__("Power_Safety")
        self.schematic_layer = 1
        
        # High Voltage Rail
        self.v14v8 = Net("VBAT_14.8V")
        self.gnd_traction = Net("GND_TRACTION") # Traction Star Ground
        
        # 1. Traction Battery (XT60-M)
        self.battery = self.add(MockComp("Turnigy_Graphene_4S_10000mAh", 2, 
                                        footprint="Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical"))
        self.battery["1"] += self.v14v8
        self.battery["2"] += self.gnd_traction
        
        # 2. Main Contactor (Hardware Kill-Switch)
        self.contactor = self.add(MockComp("Albright_SW60_Contactor", 4, 
                                          footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-4-5.08_1x04_P5.08mm_Horizontal"))
        self.v14v8_fused = Net("VBAT_FUSED")
        self.contactor["1"] += self.v14v8
        self.contactor["2"] += self.v14v8_fused
        # Coil driven by safety loop (simplified)
        self.contactor["3"] += Net("KILL_SWITCH_CTRL")
        self.contactor["4"] += self.gnd_traction
        
        # 3. Logic Regulators (Isolated Buck Converters)
        self.v5v_rpi = Net("5V_RPI")
        self.v5v_logic = Net("5V_LOGIC")
        self.gnd_logic = Net("GND_LOGIC") # Isolated Logic Ground
        
        # Regulator 1: RPi 5 Power (SOT-23-5 placeholder)
        self.reg1 = self.add(MockComp("Pololu_D36V50F5_5V_9A", 4, 
                                     footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.reg1["1"] += self.v14v8_fused
        self.reg1["2"] += self.gnd_traction
        self.reg1["3"] += self.v5v_rpi
        self.reg1["4"] += self.gnd_logic
        
        # Regulator 2: MCU & Sensors Power
        self.reg2 = self.add(MockComp("Pololu_D24V60F5_5V_6A", 4, 
                                     footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.reg2["1"] += self.v14v8_fused
        self.reg2["2"] += self.gnd_traction
        self.reg2["3"] += self.v5v_logic
        self.reg2["4"] += self.gnd_logic

class ComputeStack(Module):
    """Avionics Brain (RPi 5) and Brainstem (Teensy 4.1)."""
    def __init__(self) -> None:
        super().__init__("Compute_Avionics")
        self.schematic_layer = 2
        
        self.v5v_rpi = Net("5V_RPI")
        self.v5v_logic = Net("5V_LOGIC")
        self.v3v3 = Net("3V3")
        self.gnd_logic = Net("GND_LOGIC")
        
        # RPi 5 (PinHeader 2x20)
        self.rpi = self.add(MockComp("Raspberry_Pi_5_8GB", 40,
                                     footprint="Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"))
        self.rpi["2"] += self.v5v_rpi
        self.rpi["6"] += self.gnd_logic
        
        # Teensy 4.1 (PinHeader 1x24)
        self.teensy = self.add(MockComp("Teensy_4.1", 24,
                                       footprint="Connector_PinHeader_2.54mm:PinHeader_1x24_P2.54mm_Vertical"))
        # Using numeric pins for power to match header footprint
        self.teensy["24"] += self.v5v_logic # VIN on pin 24
        self.teensy["23"] += self.gnd_logic # GND on pin 23
        
        # Radio Telemetry (1x04 Header)
        self.radio = self.add(MockComp("Holybro_SiK_Radio_V3", 4,
                                      footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.radio["1"] += self.v5v_rpi
        self.radio["2"] += self.gnd_logic
        
        # Power caps
        c = self.add(Component("C_100NF_0402"))
        c["1"] += self.v3v3; c["2"] += self.gnd_logic

class ActuationSystem(Module):
    """Thrusters, Drill Auger, and Z-Axis Stepper."""
    def __init__(self) -> None:
        super().__init__("Actuation_Control")
        self.schematic_layer = 3
        
        self.v14v8_fused = Net("VBAT_FUSED")
        self.gnd_traction = Net("GND_TRACTION")
        self.gnd_logic = Net("GND_LOGIC")
        
        # 1. Thruster ESCs (1x03 Header)
        esc_fp = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
        self.esc_l = self.add(MockComp("BlueRobotics_Basic_30A_ESC", 3, footprint=esc_fp))
        self.esc_r = self.add(MockComp("BlueRobotics_Basic_30A_ESC", 3, footprint=esc_fp))
        for esc in [self.esc_l, self.esc_r]:
            esc["1"] += self.v14v8_fused # V+
            esc["2"] += self.gnd_traction # V-
            
        # 2. Drill ESC (VESC) (1x04 Header)
        self.vesc = self.add(MockComp("Flipsky_FSESC_4.12", 4, 
                                     footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.vesc["1"] += self.v14v8_fused
        self.vesc["2"] += self.gnd_traction
        
        # 3. Z-Axis Stepper Driver (Terminal Block)
        self.tb6600 = self.add(MockComp("TB6600_Stepper_Driver", 6, 
                                       footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-6-5.08_1x06_P5.08mm_Horizontal"))
        self.tb6600["1"] += self.v14v8_fused
        self.tb6600["2"] += self.gnd_traction

class SensorSuite(Module):
    """Perception and Feedback Sensors."""
    def __init__(self) -> None:
        super().__init__("Sensors_Feedback")
        self.schematic_layer = 4
        
        self.v5v_logic = Net("5V_LOGIC")
        self.v3v3 = Net("3V3")
        self.gnd_logic = Net("GND_LOGIC")
        
        # Isolated Analog LDO (SOT-23-5)
        self.analog_ldo = self.add(MockComp("LDO_3V3_Analog", 5, 
                                           footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.analog_ldo["1"] += self.v5v_logic
        self.analog_ldo["2"] += self.gnd_logic
        self.v3v3_analog = Net("3V3_ANALOG")
        self.analog_ldo["5"] += self.v3v3_analog

        # Hall Effect Current Sensor (Isolated)
        from openhac.stdlib.sensors import CurrentSensor
        self.current_sensor = self.add(CurrentSensor(type="hall", range_a=100))
        self.current_sensor.power.vcc += self.v3v3_analog
        self.current_sensor.power.gnd += self.gnd_logic
        
        # IMU BNO085 (1x04 Header)
        self.imu = self.add(MockComp("Adafruit_BNO085_IMU", 4,
                                    footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.imu["1"] += self.v3v3
        self.imu["2"] += self.gnd_logic
        
        # RTK GPS (1x04 Header)
        self.gps = self.add(MockComp("SparkFun_ZED-F9P_RTK", 4,
                                    footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.gps["1"] += self.v3v3
        self.gps["2"] += self.gnd_logic

# -----------------------------------------------------------------------------
# Boat System Integration
# -----------------------------------------------------------------------------
board = Board(size_mm=(200, 150), layers=4, strict=False)

pwr = PowerSubsystem()
brain = ComputeStack()
drive = ActuationSystem()
sens = SensorSuite()

board.add_module(pwr)
board.add_module(brain)
board.add_module(drive)
board.add_module(sens)

# Cross-Module Interconnects (using numeric pins to match header footprints)
# 1. Teensy Controls Thruster ESCs (PWM)
board.connect(brain.teensy["1"], drive.esc_l["3"])
board.connect(brain.teensy["2"], drive.esc_r["3"])

# 2. Teensy Controls Stepper (Opto-Isolated)
board.connect(brain.teensy["3"], drive.tb6600["3"]) # PUL
board.connect(brain.teensy["4"], drive.tb6600["4"]) # DIR
board.connect(brain.teensy["5"], drive.tb6600["5"]) # ENA

# 3. Teensy <-> VESC (UART Telemetry)
board.connect(brain.teensy["6"], drive.vesc["3"]) # TX -> RX
board.connect(brain.teensy["7"], drive.vesc["4"]) # RX -> TX

# 4. Teensy <-> Current Sensor (Analog Feedback)
board.connect(brain.teensy["8"], sens.current_sensor.v_out.vout)

# 5. Teensy <-> IMU (I2C)
board.connect(brain.teensy["9"], sens.imu["3"]) # SCL
board.connect(brain.teensy["10"], sens.imu["4"]) # SDA

# 6. RPi 5 <-> GPS (UART)
board.connect(brain.rpi["8"], sens.gps["3"]) # TX -> RX
board.connect(brain.rpi["10"], sens.gps["4"]) # RX -> TX

# 7. RPi 5 <-> Teensy (High-Level Link)
board.connect(brain.rpi["12"], brain.teensy["11"]) # Pi TX -> Teensy RX
board.connect(brain.rpi["14"], brain.teensy["12"]) # Pi RX -> Teensy TX

# 8. Radio Telemetry to RPi 5
board.connect(brain.radio["3"], brain.rpi["16"]) # Radio TX -> Pi RX
board.connect(brain.radio["4"], brain.rpi["18"]) # Radio RX -> Pi TX
