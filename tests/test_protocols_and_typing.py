"""Unit tests for Phase 2: Strong Protocol, Signal, Domains, and Static ERC (ERC-001 to ERC-003)."""

import pytest

from openhac import (
    AnalogDomain,
    DesignContext,
    DifferentialPair,
    DigitalDomain,
    DomainKind,
    ElectricalDomain,
    ERCDomainMismatchError,
    ERCDriverContentionError,
    ERCFloatingInputError,
    ERCUnconnectedPinError,
    I2C,
    InOut,
    Input,
    JTAG,
    OpenDrain,
    OpenHaCError,
    Output,
    Passive,
    PowerDomain,
    PowerIn,
    PowerOut,
    Protocol,
    ProtocolCompatibilityError,
    Signal,
    SignalDirection,
    SPI,
    SWD,
    UART,
)
from openhac.core.base import Component
from openhac.core.board import Board
from openhac.compiler.rule_check import run_erc


def make_test_component(name: str, pin_type: str = "passive", logic_level: float = 3.3) -> Component:
    """Helper to instantiate a valid component with explicit offline data."""
    return Component(
        name,
        comp_data={
            "generic_name": name,
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603",
            "pins": {"1": ("P1", pin_type), "2": ("P2", "passive")},
        },
        pins={"1": ("P1", pin_type), "2": ("P2", "passive")},
    )


# ---------------------------------------------------------------------------
# Task 2.1: Signal & Protocol Primitives
# ---------------------------------------------------------------------------

class TestSignalPrimitives:

    def test_signal_standalone_generic_syntax(self):
        s_out = Signal[Output]("TX")
        assert s_out.name == "TX"
        assert s_out.direction == SignalDirection.OUTPUT
        assert s_out.direction.is_driver()
        assert not s_out.direction.is_load()

        s_in = Signal[Input]("RX")
        assert s_in.direction == SignalDirection.INPUT
        assert s_in.direction.is_load()
        assert not s_in.direction.is_driver()

    def test_signal_flipping(self):
        s_out = Signal[Output]("MOSI")
        s_flipped = s_out.flipped()
        assert s_flipped.direction == SignalDirection.INPUT

        s_pwr_out = Signal[PowerOut]("VOUT")
        assert s_pwr_out.flipped().direction == SignalDirection.POWER_IN

        s_inout = Signal[InOut]("SDA")
        assert s_inout.flipped().direction == SignalDirection.INOUT


class CustomBus(Protocol):
    clk: Signal[Output] = Signal()
    data: Signal[InOut] = Signal(default_pullup=True)
    ready: Signal[Input] = Signal()


class TestProtocolDefinitionAndBinding:

    def test_protocol_class_introspection(self):
        bus = CustomBus("BUS0")
        assert bus.name == "BUS0"
        assert len(bus) == 3
        assert "clk" in bus
        assert "data" in bus
        assert "ready" in bus

        # Verify signals were instantiated with correct directions
        assert bus.clk.direction == SignalDirection.OUTPUT
        assert bus.data.direction == SignalDirection.INOUT
        assert bus.ready.direction == SignalDirection.INPUT

        # Verify signal net naming in context
        with DesignContext("bus_ctx"):
            bus_scoped = CustomBus("SPI_BUS")
            assert "SPI_BUS_CLK" in bus_scoped.clk.net.name

    def test_protocol_role_inversion(self):
        master_bus = CustomBus("BUS_M")
        slave_bus = master_bus.as_peripheral()

        assert slave_bus.clk.direction == SignalDirection.INPUT
        assert slave_bus.data.direction == SignalDirection.INOUT
        assert slave_bus.ready.direction == SignalDirection.OUTPUT

    def test_protocol_pin_binding(self):
        with DesignContext("bind_ctx"):
            c1 = make_test_component("U1", pin_type="bidirectional")
            bus = CustomBus("BUS1")
            bus.bind(data=c1["1"])
            assert c1["1"] in bus.data.pins


# ---------------------------------------------------------------------------
# Task 2.2: Driver Contention (ERC-001) & Floating Inputs (ERC-002)
# ---------------------------------------------------------------------------

class TestDriverContentionERC001:

    def test_signal_to_signal_driver_contention_raises(self):
        s1 = Signal[Output]("OUT1")
        s2 = Signal[Output]("OUT2")
        with pytest.raises(ERCDriverContentionError) as excinfo:
            s1 += s2
        assert "ERC-001" in str(excinfo.value)
        assert "Driver contention" in str(excinfo.value)

    def test_signal_to_pin_driver_contention_raises(self):
        with DesignContext("driver_pin_ctx"):
            s_out = Signal[Output]("DRIVER")
            c_out = make_test_component("U_OUT", pin_type="output")
            with pytest.raises(ERCDriverContentionError) as excinfo:
                s_out += c_out["1"]
            assert "ERC-001" in str(excinfo.value)

    def test_protocol_master_to_master_contention(self):
        with DesignContext("spi_contention_ctx"):
            m1 = SPI("SPI_M1")
            m2 = SPI("SPI_M2")
            with pytest.raises(ERCDriverContentionError) as excinfo:
                m1 += m2
            assert "ERC-001" in str(excinfo.value)

    def test_protocol_master_to_peripheral_succeeds(self):
        with DesignContext("spi_valid_ctx"):
            master = SPI("SPI_HOST")
            slave = SPI("SPI_DEV").as_peripheral()
            # Output connects to Input (sck, mosi, cs_n) and Input connects to Output (miso)
            master += slave
            assert master.sck.net is slave.sck.net
            assert master.mosi.net is slave.mosi.net
            assert master.miso.net is slave.miso.net

    def test_rule_check_erc_catches_multiple_output_drivers(self):
        board = Board(size_mm=(50, 50))
        with DesignContext("erc_driver_ctx"):
            c1 = make_test_component("U_DRV1", pin_type="output")
            c2 = make_test_component("U_DRV2", pin_type="output")
            # Tie their outputs together
            c1["1"] += c2["1"]
            # Connect passive pins together so unconnected pin check doesn't fire first
            c1["2"] += c2["2"]

            with pytest.raises(ERCDriverContentionError) as excinfo:
                run_erc(board)
            assert "ERC-001" in str(excinfo.value)


class TestFloatingInputsERC002:

    def test_strict_erc_catches_floating_input(self):
        board = Board(size_mm=(50, 50))
        board.strict_mode = True
        with DesignContext("floating_ctx"):
            c_in = make_test_component("U_IN", pin_type="input")

            with pytest.raises(Exception) as excinfo:
                run_erc(board)

            err = excinfo.value
            sub_errs = getattr(err, "exceptions", [err])
            err_text = "\n".join(str(e) for e in sub_errs)
            assert "ERC-002" in err_text or "Floating input" in err_text


# ---------------------------------------------------------------------------
# Task 2.3: Electrical Domains & Compatibility (ERC-003)
# ---------------------------------------------------------------------------

class TestElectricalDomainsERC003:

    def test_domain_constructors(self):
        pwr = PowerDomain(3.3, max_current_a=1.5)
        assert pwr.kind == DomainKind.POWER
        assert pwr.nominal_voltage == 3.3
        assert pwr.max_current_a == 1.5

        dig = DigitalDomain(1.8)
        assert dig.kind == DomainKind.DIGITAL_LOGIC
        assert dig.nominal_voltage == 1.8

        diff = DifferentialPair(100.0, standard="LVDS")
        assert diff.kind == DomainKind.DIFFERENTIAL
        assert diff.impedance_target_ohms == 100.0

    def test_domain_voltage_mismatch_signal_connection(self):
        sig_5v = Signal[Output]("SIG_5V", domain=DigitalDomain(5.0))
        sig_1v8 = Signal[Input]("SIG_1V8", domain=DigitalDomain(1.8))

        with pytest.raises(ERCDomainMismatchError) as excinfo:
            sig_5v += sig_1v8
        assert "ERC-003" in str(excinfo.value)
        assert "Digital logic level mismatch" in str(excinfo.value)

    def test_domain_power_rail_voltage_mismatch(self):
        rail_5v = Signal[PowerOut]("VBUS", domain=PowerDomain(5.0))
        rail_3v3 = Signal[PowerOut]("VCC_3V3", domain=PowerDomain(3.3))

        with pytest.raises(ERCDriverContentionError):
            rail_5v += rail_3v3

    def test_compatible_domains_connect_cleanly(self):
        sig_3v3_out = Signal[Output]("OUT_3V3", domain=DigitalDomain(3.3))
        sig_3v3_in = Signal[Input]("IN_3V3", domain=DigitalDomain(3.3))
        sig_3v3_out += sig_3v3_in
        assert sig_3v3_out.net is sig_3v3_in.net


# ---------------------------------------------------------------------------
# Standard Protocol Library Checks
# ---------------------------------------------------------------------------

class TestStandardProtocols:

    def test_i2c_protocol(self):
        i2c_master = I2C("I2C0")
        i2c_slave = I2C("SENSOR_I2C")
        i2c_master += i2c_slave
        assert i2c_master.scl.net is i2c_slave.scl.net
        assert i2c_master.sda.net is i2c_slave.sda.net

    def test_uart_protocol(self):
        uart_host = UART("UART0")
        uart_dev = UART("GPS_UART").as_peripheral()
        uart_host += uart_dev
        assert uart_host.tx.net is uart_dev.tx.net
        assert uart_host.rx.net is uart_dev.rx.net

    def test_swd_protocol(self):
        swd_host = SWD("DEBUG_PROBE")
        swd_target = SWD("MCU_SWD").as_target()
        swd_host += swd_target
        assert swd_host.swdio.net is swd_target.swdio.net
        assert swd_host.swclk.net is swd_target.swclk.net

    def test_jtag_protocol(self):
        jtag_host = JTAG("JTAG_MASTER")
        jtag_target = JTAG("FPGA_JTAG").as_target()
        jtag_host += jtag_target
        assert jtag_host.tck.net is jtag_target.tck.net
        assert jtag_host.tdi.net is jtag_target.tdi.net
        assert jtag_host.tdo.net is jtag_target.tdo.net

    def test_incompatible_protocol_connection_raises(self):
        i2c = I2C("I2C_BUS")
        spi = SPI("SPI_BUS")
        with pytest.raises(ProtocolCompatibilityError) as excinfo:
            i2c += spi
        assert "no overlapping signal names" in str(excinfo.value)
