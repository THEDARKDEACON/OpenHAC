import os
from openhac.core.base import Component, Module, Net
from openhac.core.board import Board

def RealComp(name: str, lcsc_id: str, footprint: str = None) -> Component:
    kwargs = {"lcsc_id": lcsc_id}
    if footprint: kwargs["footprint"] = footprint
    return Component(name, **kwargs)

def MockComp(name: str, pin_count: int = 0, pin_dict: dict | None = None, lcsc_id: str | None = None, footprint: str | None = None) -> Component:
    if pin_dict is None:
        pin_dict = {str(i): (f"P{i}", "passive") for i in range(1, pin_count + 1)}
    kwargs = {"pins": pin_dict}
    if footprint: kwargs["footprint"] = footprint
    return Component(name, **kwargs)

def PowerFlag(net: Net):
    flag = Component("PWR_FLAG", pins={"1": ("p1", "power_out")}, footprint="")
    flag["1"] += net
    return flag

class PowerSubsystem(Module):
    def __init__(self) -> None:
        super().__init__("Power_Safety")
        
        self.v14v8 = Net("VBAT_14.8V"); self.v14v8.set_current(60.0)
        self.gnd_traction = Net("GND_TRACTION"); self.gnd_traction.set_current(60.0)
        self.gnd_logic = Net("GND_LOGIC"); self.gnd_logic.set_current(5.0)
        
        # FIX 3: The Star Ground Net Tie
        # This physically bridges the noisy traction ground to the quiet logic ground at ONE point.
        self.star_ground = self.add(MockComp("NetTie_2Pad", 2, footprint="NetTie:NetTie-2_SMD_Pad0.5mm"))
        self.star_ground["1"] += self.gnd_traction
        self.star_ground["2"] += self.gnd_logic
        
        self.battery = self.add(MockComp("Turnigy_Graphene_4S", 2, footprint="Connector_AMASS:AMASS_XT90-S_1x02_P15.50mm_Vertical"))
        self.battery["1"] += self.v14v8; self.battery["2"] += self.gnd_traction
        
        self.main_fuse = self.add(MockComp("Fuse_100A_Maxi_Blade", 2, footprint="Fuse:Fuseholder_Cylinder-5x20mm_Schurter_0031_8201_Horizontal_Open"))
        
        self.v14v8_fused = Net("VBAT_FUSED"); self.v14v8_fused.set_current(60.0)
        self.main_fuse["1"] += self.v14v8; self.main_fuse["2"] += self.v14v8_fused
        self.v14v8_switched = Net("VBAT_SWITCHED"); self.v14v8_switched.set_current(60.0)
        self.v14v8_pre_contact = Net("VBAT_PRE_CONTACT"); self.v14v8_pre_contact.set_current(60.0)
        
        self.contactor = self.add(MockComp("Albright_SW60_Contactor", 4, footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-4-5.08_1x04_P5.08mm_Horizontal"))
        
        self.contactor["1"] += self.v14v8_pre_contact
        self.contactor["2"] += self.v14v8_switched
        self.contactor["3"] += self.v14v8_fused 
        
        # FIX 1: Component Vaporization (Heavy Duty MOSFET & Schottky Diode)
        self.mosfet = self.add(MockComp("IRLR2905_Power_MOSFET", 3, footprint="Package_TO_SOT_SMD:TO-252-2")) # 42A continuous rating
        self.kill_switch_logic = Net("KILL_SWITCH_LOGIC_3V3")
        self.mosfet["1"] += self.kill_switch_logic # Gate
        self.mosfet["2"] += self.contactor["4"]    # Drain
        self.mosfet["3"] += self.gnd_traction      # Source
        
        self.flyback = self.add(MockComp("SS34_Schottky", 2, footprint="Diode_SMD:D_SMC")) # 3A rating for violent inductive kickback
        self.flyback["1"] += self.contactor["4"]   
        self.flyback["2"] += self.v14v8_fused      

        self.v5v_rpi = Net("5V_RPI"); self.v5v_rpi.set_current(5.0)
        self.v5v_logic = Net("5V_LOGIC"); self.v5v_logic.set_current(3.0)
        
        self.reg1 = self.add(MockComp("Pololu_D36V50F5_5V_9A", pin_dict={
            "1": ("VIN", "power_in"), "2": ("GND", "power_in"),
            "3": ("VOUT", "power_out"), "4": ("GND", "power_out")
        }, footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.reg1["1"] += self.v14v8_fused; self.reg1["2"] += self.gnd_traction
        self.reg1["3"] += self.v5v_rpi; self.reg1["4"] += self.gnd_logic
        
        self.reg2 = self.add(MockComp("Pololu_D24V60F5_5V_6A", pin_dict={
            "1": ("VIN", "power_in"), "2": ("GND", "power_in"),
            "3": ("VOUT", "power_out"), "4": ("GND", "power_out")
        }, footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.reg2["1"] += self.v14v8_fused; self.reg2["2"] += self.gnd_traction
        self.reg2["3"] += self.v5v_logic; self.reg2["4"] += self.gnd_logic

        # FIX 2: Resolving the "Ghost" 3.3V Rail natively in the Power Subsystem
        self.v3v3_analog = Net("3V3_ANALOG"); self.v3v3_analog.set_current(0.5)
        self.reg3v3 = self.add(MockComp("AP2112K-3.3_LDO", 5, footprint="Package_TO_SOT_SMD:SOT-23-5"))
        self.reg3v3["1"] += self.v5v_logic # VIN
        self.reg3v3["2"] += self.gnd_logic # GND
        self.reg3v3["5"] += self.v3v3_analog # VOUT

        # NEW: 1.5KE18CA Bidirectional TVS for Inductive Load Dump Protection
        self.tvs = self.add(MockComp("1.5KE18CA_TVS", 2, footprint="Diode_THT:D_DO-201AD_P15.24mm_Horizontal"))
        self.tvs["1"] += self.v14v8_switched; self.tvs["2"] += self.gnd_traction

        # NEW: UVLO Divider (10k / 2.2k) for Battery Monitoring
        self.uvlo_r1 = self.add(MockComp("R_10k_UVLO", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.uvlo_r2 = self.add(MockComp("R_2.2k_UVLO", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.vbat_sense = Net("VBAT_SENSE_3V3"); self.vbat_sense.set_current(0.1)
        self.uvlo_r1["1"] += self.v14v8_fused; self.uvlo_r1["2"] += self.vbat_sense
        self.uvlo_r2["1"] += self.vbat_sense; self.uvlo_r2["2"] += self.gnd_logic


class ComputeStack(Module):
    def __init__(self) -> None:
        super().__init__("Compute_Avionics")
        self.v5v_rpi = Net("5V_RPI")
        self.v5v_logic = Net("5V_LOGIC")
        self.gnd_logic = Net("GND_LOGIC")
        self.v3v3_analog = Net("3V3_ANALOG")
        
        self.rpi = self.add(MockComp("Raspberry_Pi_5_8GB", 40, lcsc_id="C2114620", footprint="Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"))
        self.rpi["2"] += self.v5v_rpi; self.rpi["4"] += self.v5v_rpi; self.rpi["6"] += self.gnd_logic

        # NEW: Graceful Shutdown Pushbutton (IP68)
        self.shutdown_btn = self.add(MockComp("Shutdown_Button", 2, footprint="Button_Switch_THT:SW_PUSH_6mm"))
        self.btn_pullup = self.add(MockComp("R_10k_BTN", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.shutdown_sig = Net("SHUTDOWN_SIGNAL")
        self.shutdown_btn["1"] += self.shutdown_sig; self.shutdown_btn["2"] += self.gnd_logic
        self.btn_pullup["1"] += self.shutdown_sig; self.btn_pullup["2"] += self.v3v3_analog
        
        self.teensy = self.add(MockComp("Teensy_4.1", 48, lcsc_id="C2344710", footprint="Connector_PinHeader_2.54mm:PinHeader_2x24_P2.54mm_Vertical"))
        self.teensy["24"] += self.v5v_logic; self.teensy["48"] += self.gnd_logic
        
        self.gps = self.add(MockComp("NEO-M9N", pin_dict={
            "23": ("VCC", "power_in"),
            "24": ("GND", "ground"),
            "21": ("TX", "output"),
            "20": ("RX", "input")
        }, footprint="easyeda_generated:GPSM-SMD_24P-L16.0-W12.2-P1.10-BL"))
        self.gps_uart = self.declare_interface("gps_uart", tx=self.gps["21"], rx=self.gps["20"])
        
        self.nvme = self.add(MockComp("NVMe_M2_Base", 4, footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical")) # Simplified PCIe header
        self.nvme["1"] += self.v5v_rpi; self.nvme["2"] += self.gnd_logic
        
        self.radio = self.add(MockComp("Holybro_SiK_Radio", 4, footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.radio["1"] += self.v5v_rpi; self.radio["2"] += self.gnd_logic

        self.rc_rx = self.add(MockComp("ELRS_Micro_Receiver", 4, footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.rc_rx["1"] += self.v5v_logic; self.rc_rx["2"] += self.gnd_logic
        self.rc_rx_tx = Net("RC_UART_TX"); self.rc_rx_rx = Net("RC_UART_RX")
        self.rc_rx["3"] += self.rc_rx_tx; self.rc_rx["4"] += self.rc_rx_rx


class ActuationSystem(Module):
    def __init__(self) -> None:
        super().__init__("Actuation_Control")
        self.v14v8_switched = Net("VBAT_SWITCHED")
        self.gnd_traction = Net("GND_TRACTION")
        self.v5v_logic = Net("5V_LOGIC")
        self.v3v3_analog = Net("3V3_ANALOG")
        self.gnd_logic = Net("GND_LOGIC")
        
        esc_fp = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
        self.esc_l = self.add(MockComp("BlueRobotics_ESC", 3, footprint=esc_fp)); self.esc_l["1"] += self.v14v8_switched; self.esc_l["2"] += self.gnd_traction
        self.esc_r = self.add(MockComp("BlueRobotics_ESC", 3, footprint=esc_fp)); self.esc_r["1"] += self.v14v8_switched; self.esc_r["2"] += self.gnd_traction
        self.vesc = self.add(MockComp("Flipsky_FSESC", 4, footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical")); self.vesc["1"] += self.v14v8_switched; self.vesc["2"] += self.gnd_traction
        
        self.tb6600 = self.add(MockComp("TB6600_Stepper_Driver", 6, footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-6-5.08_1x06_P5.08mm_Horizontal"))
        self.tb6600["1"] += self.v14v8_switched; self.tb6600["2"] += self.gnd_traction

        # UPDATED: 74AHCT125 Quad Buffer for high-drive Level Shifting
        self.shifter = self.add(MockComp("74AHCT125_Shifter", 14, footprint="Package_SO:TSSOP-14_4.4x5mm_P0.65mm"))
        self.shifter["14"] += self.v5v_logic # VCC
        self.shifter["7"] += self.gnd_logic  # GND
        
        self.teensy_pul = Net("TEENSY_PUL_3V3")
        self.teensy_dir = Net("TEENSY_DIR_3V3")
        self.teensy_ena = Net("TEENSY_ENA_3V3")
        
        self.tb6600_pul = Net("TB6600_PUL_5V")
        self.tb6600_dir = Net("TB6600_DIR_5V")
        self.tb6600_ena = Net("TB6600_ENA_5V")
        
        # 74AHCT125 Pinout: 1=OE1, 2=A1, 3=Y1...
        # We tie OEs to GND to enable buffers
        self.shifter["1"] += self.gnd_logic; self.shifter["2"] += self.teensy_pul; self.shifter["3"] += self.tb6600_pul
        self.shifter["4"] += self.gnd_logic; self.shifter["5"] += self.teensy_dir; self.shifter["6"] += self.tb6600_dir
        self.shifter["10"] += self.gnd_logic; self.shifter["9"] += self.teensy_ena; self.shifter["8"] += self.tb6600_ena
        
        # Connect the 5V shifted signals to the TB6600
        self.tb6600["3"] += self.tb6600_pul
        self.tb6600["4"] += self.tb6600_dir
        self.tb6600["5"] += self.tb6600_ena

        # Limit Switches
        self.limit_top = self.add(MockComp("Limit_Switch_Top", 3, footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
        self.limit_bot = self.add(MockComp("Limit_Switch_Bot", 3, footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
        for sw in [self.limit_top, self.limit_bot]: sw["1"] += self.v5v_logic; sw["2"] += self.gnd_logic
        self.sig_lim_top = Net("LIMIT_TOP_SIG"); self.limit_top["3"] += self.sig_lim_top
        self.sig_lim_bot = Net("LIMIT_BOT_SIG"); self.limit_bot["3"] += self.sig_lim_bot


class SensorSuite(Module):
    def __init__(self) -> None:
        super().__init__("Sensors_Feedback")
        self.v5v_logic = Net("5V_LOGIC")
        self.v3v3_analog = Net("3V3_ANALOG")
        self.gnd_logic = Net("GND_LOGIC")
        
        # Current Sensor (Fast Kill)
        from openhac.stdlib.sensors import CurrentSensor
        self.current_sensor = self.add(CurrentSensor(type="hall", range_a=100))
        self.current_sensor.power.vcc += self.v3v3_analog # Clean 3.3V Analog for Hall sensor
        self.current_sensor.power.gnd += self.gnd_logic
        self.current_sensor.ip_pos += Net("VBAT_FUSED")
        self.current_sensor.ip_neg += Net("VBAT_PRE_CONTACT")
        
        # Thermistor (Slow Kill)
        self.thermistor = self.add(MockComp("NTC_10K_Probe", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.therm_pullup = self.add(MockComp("R_10k", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.temp_sense_net = Net("AUGER_TEMP_ANALOG")
        self.thermistor["1"] += self.gnd_logic; self.thermistor["2"] += self.temp_sense_net
        self.therm_pullup["1"] += self.temp_sense_net; self.therm_pullup["2"] += self.v3v3_analog
        
        # IMU with I2C Pullups
        self.imu = self.add(MockComp("Adafruit_BNO085_IMU", 4, footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"))
        self.imu_scl = Net("I2C_SCL"); self.imu_sda = Net("I2C_SDA")
        self.imu["1"] += self.v3v3_analog; self.imu["2"] += self.gnd_logic
        self.imu["3"] += self.imu_scl; self.imu["4"] += self.imu_sda
        
        self.r_pu_scl = self.add(MockComp("R_4.7k", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.r_pu_scl["1"] += self.v3v3_analog; self.r_pu_scl["2"] += self.imu_scl
        self.r_pu_sda = self.add(MockComp("R_4.7k", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.r_pu_sda["1"] += self.v3v3_analog; self.r_pu_sda["2"] += self.imu_sda

        # FIX 5: High-Power Payload Terminals (Bypassing the Pi 5 USB limits)
        self.oakd_pwr = self.add(MockComp("OAK_D_Pro_Power", 2, footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal"))
        self.oakd_pwr["1"] += self.v5v_logic; self.oakd_pwr["2"] += self.gnd_logic
        
        self.sonar_pwr = self.add(MockComp("Ping_Sonar_Power", 2, footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"))
        self.sonar_pwr["1"] += self.v5v_logic; self.sonar_pwr["2"] += self.gnd_logic

        # Leak Sensor & Status LED
        self.leak_sensor = self.add(MockComp("Hull_Water_Probe", 2, footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"))
        self.leak_sig = Net("LEAK_DETECT_SIG")
        self.leak_sensor["1"] += self.gnd_logic; self.leak_sensor["2"] += self.leak_sig
        self.leak_pullup = self.add(MockComp("R_10k", 2, footprint="Resistor_SMD:R_0603_1608Metric"))
        self.leak_pullup["1"] += self.leak_sig; self.leak_pullup["2"] += self.v3v3_analog

        self.status_led = self.add(MockComp("WS2812B_Strobe_Mast", 3, footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
        self.status_led["1"] += self.v5v_logic; self.status_led["2"] += self.gnd_logic
        self.led_data = Net("STATUS_LED_DATA"); self.status_led["3"] += self.led_data

# -----------------------------------------------------------------------------
# System Integration
# -----------------------------------------------------------------------------
board = Board(size_mm=(None), layers=6, strict=False)

pwr = PowerSubsystem()
brain = ComputeStack()
drive = ActuationSystem()
sens = SensorSuite()

board.declared_supply_voltages_v = {
    "3V3_ANALOG": 3.3,
    "5V_LOGIC": 5.0, 
    "5V_RPI": 5.0, 
    "VBAT_14.8V": 14.8
}
for mod in [pwr, brain, drive, sens]: 
    board.add_module(mod)

# Control Interconnects (Teensy 4.1 Pinout per Specification)
board.connect(brain.teensy["1"], drive.esc_l["3"]) # PWM Thruster L
board.connect(brain.teensy["2"], drive.esc_r["3"]) # PWM Thruster R

# Stepper controls via Level Shifter
board.connect(brain.teensy["3"], drive.teensy_pul) # Level Shifted Stepper PUL
board.connect(brain.teensy["4"], drive.teensy_dir) # Level Shifted Stepper DIR
board.connect(brain.teensy["5"], drive.teensy_ena) # Level Shifted Stepper ENA

board.connect(brain.teensy["6"], drive.vesc["3"]) # UART2 TX -> VESC RX
board.connect(brain.teensy["7"], drive.vesc["4"]) # UART2 RX -> VESC TX

# Analog Feedback
board.connect(brain.teensy["8"], sens.current_sensor.v_out.vout) # A0: Current Sense
board.connect(brain.teensy["20"], sens.temp_sense_net) # A1: Thermistor
board.connect(brain.teensy["23"], pwr.vbat_sense)      # A9: UVLO Monitoring

# Digital IO & Comms
board.connect(brain.teensy["9"], sens.imu["3"])  # SCL
board.connect(brain.teensy["10"], sens.imu["4"]) # SDA

board.connect(brain.teensy["13"], pwr.kill_switch_logic) # Kill Switch Trigger

board.connect(brain.teensy["14"], brain.rc_rx_tx)
board.connect(brain.teensy["15"], brain.rc_rx_rx)

board.connect(brain.teensy["16"], drive.sig_lim_top)
board.connect(brain.teensy["17"], drive.sig_lim_bot)
board.connect(brain.teensy["18"], sens.leak_sig)
board.connect(brain.teensy["19"], sens.led_data)

# GPS Connection (UART7 on Teensy 4.1: pins 28, 29)
board.connect(brain.teensy["28"], brain.gps["20"]) # Teensy TX (28) -> GPS RX (20)
board.connect(brain.teensy["29"], brain.gps["21"]) # Teensy RX (29) -> GPS TX (21)

# NVMe Connection (Simplified PCIe breakout on available GPIOs)
board.connect(brain.rpi["37"], brain.nvme["3"])
board.connect(brain.rpi["38"], brain.nvme["4"])

# Pi 5 Telemetry Link (UART5 on Teensy 4.1)
board.connect(brain.teensy["21"], brain.rpi["8"])  # Teensy RX5 -> Pi TX (GPIO 14)
board.connect(brain.teensy["22"], brain.rpi["10"]) # Teensy TX5 -> Pi RX (GPIO 15)

# ERC Power Flags
PowerFlag(pwr.v14v8)
PowerFlag(pwr.v14v8_fused)
PowerFlag(pwr.v14v8_switched)
PowerFlag(pwr.v14v8_pre_contact)
PowerFlag(pwr.v5v_rpi)
PowerFlag(pwr.v5v_logic)
PowerFlag(pwr.v3v3_analog)
PowerFlag(pwr.gnd_traction)
PowerFlag(pwr.gnd_logic)

# Final NC Termination
for mod in [pwr, brain, drive, sens]:
    mod.nc_unused_pins()

if __name__ == "__main__":
    print("\n[5/5] Compiling Board and Generating Web View...")
    board.compile(project_name="autonomous_boat")
    
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    out_html = os.path.join(docs_dir, "boat_system_view.html")
    
    board.export_webview(out_html)
    print(f"\n✅ Compilation successful! View the interactive graph at:\n   {os.path.abspath(out_html)}")