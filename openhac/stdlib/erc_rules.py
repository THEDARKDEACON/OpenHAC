"""Example ERC hooks for :meth:`openhac.core.board.Board.register_erc_hook` (SCH-005).

These are **illustrative** checks only; tune or replace for your design rules.
"""

from __future__ import annotations

_RAIL_NAME_HINTS = ("vcc", "3v3", "5v", "1v8", "2v5", "vdd", "vin", "vbat", "vbus")


def _pins_on_net(net):
    try:
        return list(net.get_pins())
    except Exception:
        try:
            return list(getattr(net, "pins", ()) or ())
        except Exception:
            return []


def _net_name_lower(net) -> str:
    return str(getattr(net, "name", "") or "").lower()


def _looks_like_supply_net(net) -> bool:
    n = _net_name_lower(net)
    return any(n.startswith(p) for p in _RAIL_NAME_HINTS)


def _part_is_resistor_symbol(part) -> bool:
    """KiCad ``Device:R`` is a resistor even when SKiDL uses ref_prefix ``U`` (synthetic symbol)."""
    if str(getattr(part, "ref_prefix", "") or "").upper() == "R":
        return True
    return (getattr(part, "name", None) or "").strip().upper() == "R"


def net_has_resistor_pullup_to_rail(net) -> bool:
    """True if some resistor part connects *net* to a net whose name looks like a supply rail."""
    for pin in _pins_on_net(net):
        part = getattr(pin, "part", None)
        if part is None:
            continue
        if not _part_is_resistor_symbol(part):
            continue
        try:
            part_pins = list(part.pins)
        except Exception:
            continue
        for pp in part_pins:
            if pp is pin:
                continue
            other = getattr(pp, "net", None)
            if other is None or other is net:
                continue
            if _looks_like_supply_net(other):
                return True
    return False


def one_wire_pullup_erc_hook(dq_net):
    """Build ``fn(board)`` that requires a pull-up resistor from *dq_net* to a supply-named net (1-Wire, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(dq_net):
            msgs.append(
                f"1-Wire DQ net {getattr(dq_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def uart_rx_pullup_erc_hook(rx_net):
    """Build ``fn(board)`` that expects *rx_net* to have a pull-up to a supply-named net (idle-high UART RX, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(rx_net):
            msgs.append(
                f"UART RX net {getattr(rx_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def swd_swdio_pullup_erc_hook(swdio_net):
    """Build ``fn(board)`` expecting **SWDIO** to have a pull-up (many debug connectors leave SWDIO open-drain, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(swdio_net):
            msgs.append(
                f"SWDIO net {getattr(swdio_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def jtag_tms_pullup_erc_hook(tms_net):
    """Build ``fn(board)`` expecting **TMS** to have a pull-up (idle-high / shared JTAG buses, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(tms_net):
            msgs.append(
                f"JTAG TMS net {getattr(tms_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def jtag_tck_pullup_erc_hook(tck_net):
    """Build ``fn(board)`` expecting **TCK** to have a pull-up to a supply rail (idle strapping, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(tck_net):
            msgs.append(
                f"JTAG TCK net {getattr(tck_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def can_rx_pullup_erc_hook(rx_net):
    """Build ``fn(board)`` expecting **CAN RX** (post-transceiver MCU side, open-drain / shared) to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(rx_net):
            msgs.append(
                f"CAN RX net {getattr(rx_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def sd_cmd_pullup_erc_hook(cmd_net):
    """Build ``fn(board)`` expecting **CMD** to have a pull-up (SD/eMMC open-drain command line, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(cmd_net):
            msgs.append(
                f"SD/MMC CMD net {getattr(cmd_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def spi_miso_pullup_erc_hook(miso_net):
    """Build ``fn(board)`` expecting **MISO** to have a pull-up (multi-slave SPI / bus-hold, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(miso_net):
            msgs.append(
                f"SPI MISO net {getattr(miso_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def i2c_pullup_erc_hook(sda_net, scl_net):
    """Build ``fn(board)`` that requires pull-up resistors from *sda_net* / *scl_net* to a supply-named net."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(sda_net):
            msgs.append(
                f"I2C SDA net {getattr(sda_net, 'name', '?')!r}: expected a resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        if not net_has_resistor_pullup_to_rail(scl_net):
            msgs.append(
                f"I2C SCL net {getattr(scl_net, 'name', '?')!r}: expected a resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def reset_pullup_erc_hook(rst_n_net):
    """Build ``fn(board)`` for active-low reset: resistor to a supply rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(rst_n_net):
            msgs.append(
                f"Reset net {getattr(rst_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def mdio_pullup_erc_hook(mdio_net):
    """Build ``fn(board)`` expecting MDIO to have a pull-up to a supply-looking rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(mdio_net):
            msgs.append(
                f"MDIO net {getattr(mdio_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def spi_cs_pullup_erc_hook(cs_n_net):
    """Build ``fn(board)`` that expects an active-low CS net to have a resistor to a supply-looking rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(cs_n_net):
            msgs.append(
                f"SPI CS net {getattr(cs_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def spi_hold_n_pullup_erc_hook(hold_n_net):
    """Build ``fn(board)`` expecting **SPI HOLD#** (active-low, often shared on flash) to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(hold_n_net):
            msgs.append(
                f"SPI HOLD# net {getattr(hold_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def spi_wp_n_pullup_erc_hook(wp_n_net):
    """Build ``fn(board)`` expecting **SPI WP#** (write-protect, active-low on NOR flash) to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(wp_n_net):
            msgs.append(
                f"SPI WP# net {getattr(wp_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def eth_phy_int_n_pullup_erc_hook(int_n_net):
    """Build ``fn(board)`` expecting **Ethernet PHY INT#** (open-drain) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(int_n_net):
            msgs.append(
                f"Ethernet PHY INT# net {getattr(int_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def rs485_re_n_pullup_erc_hook(re_n_net):
    """Build ``fn(board)`` expecting **RS485 RE#** (receiver enable, active-low) to have a defined idle level via pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(re_n_net):
            msgs.append(
                f"RS485 RE# net {getattr(re_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def usb_vbus_sense_pullup_erc_hook(vbus_sense_net):
    """Build ``fn(board)`` expecting a **USB VBUS sense** (open-drain / divider tap) net to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(vbus_sense_net):
            msgs.append(
                f"USB VBUS sense net {getattr(vbus_sense_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def pcie_wake_n_pullup_erc_hook(wake_n_net):
    """Build ``fn(board)`` expecting **PCIe WAKE#** (open-drain) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(wake_n_net):
            msgs.append(
                f"PCIe WAKE# net {getattr(wake_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def rtc_int_n_pullup_erc_hook(int_n_net):
    """Build ``fn(board)`` expecting **RTC INT#** (open-drain alarm / tick) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(int_n_net):
            msgs.append(
                f"RTC INT# net {getattr(int_n_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def lin_bus_pullup_erc_hook(lin_net):
    """Build ``fn(board)`` expecting **LIN** (single-wire) to have a pull-up to a rail (idle-recessive, SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(lin_net):
            msgs.append(
                f"LIN bus net {getattr(lin_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def power_good_pullup_erc_hook(pgood_net):
    """Build ``fn(board)`` expecting a **power-good** / open-drain status net to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(pgood_net):
            msgs.append(
                f"Power-good net {getattr(pgood_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(open-drain output; SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def i2s_ws_pullup_erc_hook(ws_net):
    """Build ``fn(board)`` expecting **I2S WS** (word select / LRCLK) to have a pull-up when multi-slave / idle (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(ws_net):
            msgs.append(
                f"I2S WS net {getattr(ws_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def hdmi_cec_pullup_erc_hook(cec_net):
    """Build ``fn(board)`` expecting **HDMI CEC** (open-drain) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(cec_net):
            msgs.append(
                f"HDMI CEC net {getattr(cec_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def hdmi_hpd_pullup_erc_hook(hpd_net):
    """Build ``fn(board)`` expecting **HDMI HPD** (hot-plug detect, open-drain) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(hpd_net):
            msgs.append(
                f"HDMI HPD net {getattr(hpd_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def sd_cd_pullup_erc_hook(cd_net):
    """Build ``fn(board)`` expecting **SD card CD#** (card detect, often open-drain) to have a pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(cd_net):
            msgs.append(
                f"SD card CD net {getattr(cd_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def stepper_dir_pullup_erc_hook(dir_net):
    """Build ``fn(board)`` expecting a **stepper DIR** (direction) input to have a defined idle level via pull-up (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(dir_net):
            msgs.append(
                f"Stepper DIR net {getattr(dir_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def usb_otg_id_pullup_erc_hook(id_net):
    """Build ``fn(board)`` expecting **USB OTG ID** to have a pull-up when host/device strapping matters (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(id_net):
            msgs.append(
                f"USB OTG ID net {getattr(id_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def smbus_alert_pullup_erc_hook(alert_net):
    """Build ``fn(board)`` expecting **SMBus / PMBus ALERT#** (open-drain) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(alert_net):
            msgs.append(
                f"SMBus ALERT net {getattr(alert_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def sensor_interrupt_pullup_erc_hook(irq_net):
    """Build ``fn(board)`` expecting an **open-drain interrupt** (DRDY / INT) to have a pull-up to a rail (SCH-005)."""

    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(irq_net):
            msgs.append(
                f"Sensor interrupt net {getattr(irq_net, 'name', '?')!r}: expected a pull-up resistor to a supply rail "
                f"(open-drain output; SCH-005 example rule; see openhac.stdlib.erc_rules)."
            )
        return msgs

    return _hook


def missing_footprint_erc_hook(board):
    """``fn(board)`` that flags SKiDL parts with an empty footprint (SCH-005 example).

    Skips typical schematic-only power symbols (``power`` lib / ``PWR_FLAG``).
    """
    _ = board
    try:
        from openhac.circuit import get_default_circuit
    except Exception:
        return []

    try:
        circuit = get_default_circuit()
    except Exception:
        return []

    msgs: list[str] = []
    for part in circuit.parts:
        fp = str(getattr(part, "footprint", "") or "").strip()
        if fp:
            continue
        lib = str(getattr(part, "lib", "") or getattr(part, "lib_id", "") or "")
        name = str(getattr(part, "name", "") or "").strip().upper()
        if lib == "power" or name == "PWR_FLAG":
            continue
        ref = getattr(part, "ref", "?")
        msgs.append(
            f"Part {ref!r} has no footprint (SCH-005 example rule; see openhac.stdlib.erc_rules)."
        )
    return msgs
