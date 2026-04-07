from collections import defaultdict
from skidl import Pin, Part, Alias, SchLib, SKIDL, TEMPLATE

from skidl.pin import pin_types

SKIDL_lib_version = '0.0.1'

__main__ = SchLib(tool=SKIDL).add_parts(*[
        Part(**{ 'name':'FUSE_2A_1206', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'FUSE_2A_1206'}), 'ref_prefix':'F', 'fplist':None, 'footprint':'Fuse:Fuse_1206_3216Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'TVS_SMBJ26A', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'TVS_SMBJ26A'}), 'ref_prefix':'D', 'fplist':None, 'footprint':'Diode_SMD:D_SMB', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='A',func=pin_types.UNSPEC),
            Pin(num='2',name='K',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'PMOS_AO3401A', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'PMOS_AO3401A'}), 'ref_prefix':'Q', 'fplist':None, 'footprint':'Package_TO_SOT_SMD:SOT-23', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='G',func=pin_types.UNSPEC),
            Pin(num='2',name='S',func=pin_types.UNSPEC),
            Pin(num='3',name='D',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'BUCK_IC', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'BUCK_IC'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VIN',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SW',func=pin_types.UNSPEC),
            Pin(num='4',name='BST',func=pin_types.UNSPEC),
            Pin(num='5',name='FB',func=pin_types.UNSPEC),
            Pin(num='6',name='EN',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'LDO_3V3', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'LDO_3V3'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_TO_SOT_SMD:SOT-23-5', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='IN',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='OUT',func=pin_types.UNSPEC),
            Pin(num='4',name='EN',func=pin_types.UNSPEC),
            Pin(num='5',name='NC',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'L_2R2_SHIELD', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'L_2R2_SHIELD'}), 'ref_prefix':'L', 'fplist':None, 'footprint':'Inductor_SMD:L_6.3x6.3_H3', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_SHUNT_10m_2512', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_SHUNT_10m_2512'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_2512_6332Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'NTC_10K_0603', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'NTC_10K_0603'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_VBAT_47u_1210', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_VBAT_47u_1210'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_1210_3225Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_VBAT_1u_0603', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_VBAT_1u_0603'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_5V_22u_0805', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_5V_22u_0805'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0805_2012Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_3V3_22u_0805', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_3V3_22u_0805'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0805_2012Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_3V3_100n_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_3V3_100n_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_BUCK_BST_10N_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_BUCK_BST_10N_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_5V_SW', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_5V_SW'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_VBAT_FUSED', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_VBAT_FUSED'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_VBAT_PROT', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_VBAT_PROT'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_5V_SENSE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_5V_SENSE'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_NTC_NODE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_NTC_NODE'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'MCU_FC_CORE_QFP64', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'MCU_FC_CORE_QFP64'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_QFP:LQFP-64_10x10mm_P0.5mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='3V3',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='NRST',func=pin_types.UNSPEC),
            Pin(num='4',name='BOOT0',func=pin_types.UNSPEC),
            Pin(num='5',name='SWDIO',func=pin_types.UNSPEC),
            Pin(num='6',name='SWCLK',func=pin_types.UNSPEC),
            Pin(num='7',name='USB_DP',func=pin_types.UNSPEC),
            Pin(num='8',name='USB_DM',func=pin_types.UNSPEC),
            Pin(num='9',name='I2C_SCL',func=pin_types.UNSPEC),
            Pin(num='10',name='I2C_SDA',func=pin_types.UNSPEC),
            Pin(num='11',name='SPI_SCK',func=pin_types.UNSPEC),
            Pin(num='12',name='SPI_MOSI',func=pin_types.UNSPEC),
            Pin(num='13',name='SPI_MISO',func=pin_types.UNSPEC),
            Pin(num='14',name='UART_TX',func=pin_types.UNSPEC),
            Pin(num='15',name='UART_RX',func=pin_types.UNSPEC),
            Pin(num='16',name='GPIO1',func=pin_types.UNSPEC),
            Pin(num='17',name='GPIO2',func=pin_types.UNSPEC),
            Pin(num='18',name='GPIO3',func=pin_types.UNSPEC),
            Pin(num='19',name='GPIO4',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'XTAL_8MHz_3225', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'XTAL_8MHz_3225'}), 'ref_prefix':'Y', 'fplist':None, 'footprint':'Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC),
            Pin(num='3',name='3',func=pin_types.UNSPEC),
            Pin(num='4',name='4',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'USB_C_16P_HEADER', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'USB_C_16P_HEADER'}), 'ref_prefix':'J', 'fplist':None, 'footprint':'Connector_PinHeader_2.54mm:PinHeader_1x16_P2.54mm_Vertical', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='P1',func=pin_types.UNSPEC),
            Pin(num='2',name='P2',func=pin_types.UNSPEC),
            Pin(num='3',name='P3',func=pin_types.UNSPEC),
            Pin(num='4',name='P4',func=pin_types.UNSPEC),
            Pin(num='5',name='P5',func=pin_types.UNSPEC),
            Pin(num='6',name='P6',func=pin_types.UNSPEC),
            Pin(num='7',name='P7',func=pin_types.UNSPEC),
            Pin(num='8',name='P8',func=pin_types.UNSPEC),
            Pin(num='9',name='P9',func=pin_types.UNSPEC),
            Pin(num='10',name='P10',func=pin_types.UNSPEC),
            Pin(num='11',name='P11',func=pin_types.UNSPEC),
            Pin(num='12',name='P12',func=pin_types.UNSPEC),
            Pin(num='13',name='P13',func=pin_types.UNSPEC),
            Pin(num='14',name='P14',func=pin_types.UNSPEC),
            Pin(num='15',name='P15',func=pin_types.UNSPEC),
            Pin(num='16',name='P16',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'SWD_10PIN_1.27', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'SWD_10PIN_1.27'}), 'ref_prefix':'J', 'fplist':None, 'footprint':'Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='P1',func=pin_types.UNSPEC),
            Pin(num='2',name='P2',func=pin_types.UNSPEC),
            Pin(num='3',name='P3',func=pin_types.UNSPEC),
            Pin(num='4',name='P4',func=pin_types.UNSPEC),
            Pin(num='5',name='P5',func=pin_types.UNSPEC),
            Pin(num='6',name='P6',func=pin_types.UNSPEC),
            Pin(num='7',name='P7',func=pin_types.UNSPEC),
            Pin(num='8',name='P8',func=pin_types.UNSPEC),
            Pin(num='9',name='P9',func=pin_types.UNSPEC),
            Pin(num='10',name='P10',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'QSPI_FLASH_SOIC8', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'QSPI_FLASH_SOIC8'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VCC',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCK',func=pin_types.UNSPEC),
            Pin(num='4',name='MOSI',func=pin_types.UNSPEC),
            Pin(num='5',name='MISO',func=pin_types.UNSPEC),
            Pin(num='6',name='CS',func=pin_types.UNSPEC),
            Pin(num='7',name='HOLD',func=pin_types.UNSPEC),
            Pin(num='8',name='WP',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'MICROSD_9P_HEADER', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'MICROSD_9P_HEADER'}), 'ref_prefix':'J', 'fplist':None, 'footprint':'Connector_PinHeader_2.54mm:PinHeader_1x09_P2.54mm_Vertical', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='P1',func=pin_types.UNSPEC),
            Pin(num='2',name='P2',func=pin_types.UNSPEC),
            Pin(num='3',name='P3',func=pin_types.UNSPEC),
            Pin(num='4',name='P4',func=pin_types.UNSPEC),
            Pin(num='5',name='P5',func=pin_types.UNSPEC),
            Pin(num='6',name='P6',func=pin_types.UNSPEC),
            Pin(num='7',name='P7',func=pin_types.UNSPEC),
            Pin(num='8',name='P8',func=pin_types.UNSPEC),
            Pin(num='9',name='P9',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'CAN_TRANSCEIVER_SOIC8', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'CAN_TRANSCEIVER_SOIC8'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VCC',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='TXD',func=pin_types.UNSPEC),
            Pin(num='4',name='RXD',func=pin_types.UNSPEC),
            Pin(num='5',name='CANH',func=pin_types.UNSPEC),
            Pin(num='6',name='CANL',func=pin_types.UNSPEC),
            Pin(num='7',name='STB',func=pin_types.UNSPEC),
            Pin(num='8',name='WAKE',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'LED_STATUS_0603', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'LED_STATUS_0603'}), 'ref_prefix':'D', 'fplist':None, 'footprint':'LED_SMD:LED_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='A',func=pin_types.UNSPEC),
            Pin(num='2',name='K',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LED_1K_0603', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LED_1K_0603'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'BUZZER_SMT', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'BUZZER_SMT'}), 'ref_prefix':'BZ', 'fplist':None, 'footprint':'Buzzer_Beeper:Buzzer_12x9.5RM7.6', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='+',func=pin_types.UNSPEC),
            Pin(num='2',name='-',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_BOOT0_100K_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_BOOT0_100K_0402'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_NRST_100N_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_NRST_100N_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'USB_ESD_ARRAY', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'USB_ESD_ARRAY'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_TO_SOT_SMD:SOT-23-6', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='DP',func=pin_types.UNSPEC),
            Pin(num='2',name='DM',func=pin_types.UNSPEC),
            Pin(num='3',name='VBUS',func=pin_types.UNSPEC),
            Pin(num='4',name='GND',func=pin_types.UNSPEC),
            Pin(num='5',name='X1',func=pin_types.UNSPEC),
            Pin(num='6',name='X2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_USB_DP_22R_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_USB_DP_22R_0402'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_USB_DM_22R_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_USB_DM_22R_0402'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SWDIO', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SWDIO'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SWCLK', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SWCLK'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_GPIO1', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_GPIO1'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_GPIO2', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_GPIO2'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_GPIO3', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_GPIO3'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_GPIO4', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_GPIO4'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_BUZZER_DRV', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_BUZZER_DRV'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_CAN_TXD', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_CAN_TXD'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_CAN_RXD', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_CAN_RXD'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_CANH', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_CANH'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_CANL', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_CANL'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SPI_CS_FLASH', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SPI_CS_FLASH'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_UART_TX', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_UART_TX'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_UART_RX', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_UART_RX'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_USB_DP_EDGE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_USB_DP_EDGE'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_USB_DM_EDGE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_USB_DM_EDGE'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'IMU_ICM42688', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'IMU_ICM42688'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-14_3.9x8.7mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCK',func=pin_types.UNSPEC),
            Pin(num='4',name='MOSI',func=pin_types.UNSPEC),
            Pin(num='5',name='MISO',func=pin_types.UNSPEC),
            Pin(num='6',name='CS',func=pin_types.UNSPEC),
            Pin(num='7',name='INT1',func=pin_types.UNSPEC),
            Pin(num='8',name='INT2',func=pin_types.UNSPEC),
            Pin(num='9',name='RST',func=pin_types.UNSPEC),
            Pin(num='10',name='AUX1',func=pin_types.UNSPEC),
            Pin(num='11',name='AUX2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'MAG_LIS3MDL', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'MAG_LIS3MDL'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCL',func=pin_types.UNSPEC),
            Pin(num='4',name='SDA',func=pin_types.UNSPEC),
            Pin(num='5',name='INT',func=pin_types.UNSPEC),
            Pin(num='6',name='CS',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'BARO_BMP388', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'BARO_BMP388'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCL',func=pin_types.UNSPEC),
            Pin(num='4',name='SDA',func=pin_types.UNSPEC),
            Pin(num='5',name='INT',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'AIRSPEED_MS4525', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'AIRSPEED_MS4525'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCL',func=pin_types.UNSPEC),
            Pin(num='4',name='SDA',func=pin_types.UNSPEC),
            Pin(num='5',name='EOC',func=pin_types.UNSPEC),
            Pin(num='6',name='X1',func=pin_types.UNSPEC),
            Pin(num='7',name='X2',func=pin_types.UNSPEC),
            Pin(num='8',name='X3',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'RF_TRANSCEIVER_QFN32', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'RF_TRANSCEIVER_QFN32'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_QFP:LQFP-32_7x7mm_P0.8mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCK',func=pin_types.UNSPEC),
            Pin(num='4',name='MOSI',func=pin_types.UNSPEC),
            Pin(num='5',name='MISO',func=pin_types.UNSPEC),
            Pin(num='6',name='CS',func=pin_types.UNSPEC),
            Pin(num='7',name='IRQ',func=pin_types.UNSPEC),
            Pin(num='8',name='RST',func=pin_types.UNSPEC),
            Pin(num='9',name='ANT',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'OSD_MAX7456', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'OSD_MAX7456'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCK',func=pin_types.UNSPEC),
            Pin(num='4',name='MOSI',func=pin_types.UNSPEC),
            Pin(num='5',name='MISO',func=pin_types.UNSPEC),
            Pin(num='6',name='CS',func=pin_types.UNSPEC),
            Pin(num='7',name='VIN',func=pin_types.UNSPEC),
            Pin(num='8',name='VOUT',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'BLACKBOX_FRAM_SOIC8', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'BLACKBOX_FRAM_SOIC8'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='VDD',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='SCL',func=pin_types.UNSPEC),
            Pin(num='4',name='SDA',func=pin_types.UNSPEC),
            Pin(num='5',name='WP',func=pin_types.UNSPEC),
            Pin(num='6',name='X1',func=pin_types.UNSPEC),
            Pin(num='7',name='X2',func=pin_types.UNSPEC),
            Pin(num='8',name='X3',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_I2C_SCL_2K2_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_I2C_SCL_2K2_0402'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_I2C_SDA_2K2_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_I2C_SDA_2K2_0402'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_IMU_100N_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_IMU_100N_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_BARO_100N_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_BARO_100N_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_RF_1U_0603', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_RF_1U_0603'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'ANT_ESD_SOT23_6', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'ANT_ESD_SOT23_6'}), 'ref_prefix':'U', 'fplist':None, 'footprint':'Package_TO_SOT_SMD:SOT-23-6', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='IN',func=pin_types.UNSPEC),
            Pin(num='2',name='GND',func=pin_types.UNSPEC),
            Pin(num='3',name='X1',func=pin_types.UNSPEC),
            Pin(num='4',name='X2',func=pin_types.UNSPEC),
            Pin(num='5',name='X3',func=pin_types.UNSPEC),
            Pin(num='6',name='X4',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_VIDEO_IN', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_VIDEO_IN'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_VIDEO_OUT', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_VIDEO_OUT'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_ANT_NODE', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_ANT_NODE'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SPI_CS_IMU', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SPI_CS_IMU'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SPI_CS_OSD', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SPI_CS_OSD'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'R_LOAD_SPI_CS_RF', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'R_LOAD_SPI_CS_RF'}), 'ref_prefix':'R', 'fplist':None, 'footprint':'Resistor_SMD:R_0603_1608Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'TP_AGND', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'TP_AGND'}), 'ref_prefix':'TP', 'fplist':None, 'footprint':'TestPoint:TestPoint_Pad_D1.0mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'TP_DGND', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'TP_DGND'}), 'ref_prefix':'TP', 'fplist':None, 'footprint':'TestPoint:TestPoint_Pad_D1.0mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'C_AGND_DGND_1N_0402', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'C_AGND_DGND_1N_0402'}), 'ref_prefix':'C', 'fplist':None, 'footprint':'Capacitor_SMD:C_0402_1005Metric', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC),
            Pin(num='2',name='2',func=pin_types.UNSPEC)] }),
        Part(**{ 'name':'PWR_FLAG', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'PWR_FLAG'}), 'ref_prefix':'PWR', 'fplist':None, 'footprint':'TestPoint:TestPoint_Pad_D1.0mm', 'keywords':None, 'description':'', 'datasheet':None, 'pins':[
            Pin(num='1',name='1',func=pin_types.UNSPEC)] })])