"""Example ERC hooks for :meth:`openhac.core.board.Board.register_erc_hook` (SCH-005).

These are **illustrative** checks only; tune or replace for your design rules.

The :func:`pullup_erc_hook` factory generates a ``fn(board) -> list[str]`` that
checks whether a given net has a resistor path to a supply-named rail.  All the
protocol-specific helpers (``i2c_pullup_erc_hook``, ``uart_rx_pullup_erc_hook``,
etc.) are thin wrappers around this factory.
"""

from __future__ import annotations

_RAIL_NAME_HINTS = ("vcc", "3v3", "5v", "1v8", "2v5", "vdd", "vin", "vbat", "vbus")


def _pins_on_net(net):
    """Return all pins connected to *net*, spanning both SKiDL and native OpenHaC worlds.

    When a native ``Component`` pin is connected to a SKiDL ``Net`` (cross-world
    connection made via ``Pin.__add__``), the SKiDL Net's internal pin list does
    not record the native pin.  We compensate by also walking native circuit parts
    (from ``openhac.core.circuit.default_circuit``) and collecting any pin whose
    ``.net`` attribute is the *same object* as *net*.
    """
    # Primary: ask the net for its own pin list (works for both SKiDL and native nets)
    try:
        primary = list(net.get_pins())
    except Exception:
        try:
            primary = list(getattr(net, "pins", ()) or ())
        except Exception:
            primary = []

    # Secondary: scan both the SKiDL circuit and the native core circuit for cross-world pins.
    # Native Components register their Parts in openhac.core.circuit.default_circuit, which is
    # SEPARATE from builtins.default_circuit (the SKiDL global circuit).
    seen_ids = {id(p) for p in primary}
    extra = []

    def _scan_parts(parts_iterable):
        for part in parts_iterable:
            pin_iter = []
            try:
                pin_iter = list(part.get_pins())
            except Exception:
                try:
                    raw = part.pins
                    if isinstance(raw, dict):
                        pin_iter = list(raw.values())
                    else:
                        pin_iter = list(raw or [])
                except Exception:
                    pass
            for pin in pin_iter:
                if id(pin) in seen_ids:
                    continue
                if getattr(pin, "net", None) is net:
                    extra.append(pin)
                    seen_ids.add(id(pin))

    # Scan SKiDL global circuit
    try:
        from openhac.circuit import get_default_circuit
        _scan_parts(getattr(get_default_circuit(), "parts", []))
    except Exception:
        pass

    # Scan native OpenHaC core circuit (always present; separate from SKiDL global)
    try:
        from openhac.core.circuit import default_circuit as _native_circuit
        _scan_parts(getattr(_native_circuit, "parts", []))
    except Exception:
        pass

    return primary + extra


def _net_name_lower(net) -> str:
    return str(getattr(net, "name", "") or "").lower()


def _looks_like_supply_net(net) -> bool:
    n = _net_name_lower(net)
    return any(n.startswith(p) for p in _RAIL_NAME_HINTS)


def _part_is_resistor_symbol(part) -> bool:
    """True if *part* is a resistor — works for both SKiDL and native OpenHaC parts."""
    # SKiDL Part: ref_prefix is "R" for resistors
    if str(getattr(part, "ref_prefix", "") or "").upper() == "R":
        return True
    # SKiDL Part: name is "R" (Device:R symbol)
    if (getattr(part, "name", None) or "").strip().upper() == "R":
        return True
    # Native OpenHaC Part: refdes starts with "R"
    refdes = str(getattr(part, "refdes", None) or getattr(part, "ref", "") or "")
    if refdes.upper().startswith("R"):
        return True
    # Native OpenHaC Part: generic_name starts with "R_" (e.g. R_10k_0805)
    gname = str(getattr(part, "generic_name", None) or getattr(part, "value", "") or "")
    if gname.upper().startswith("R_") or gname.upper().startswith("R "):
        return True
    return False


def net_has_resistor_pullup_to_rail(net) -> bool:
    """True if some resistor part connects *net* to a net whose name looks like a supply rail."""
    for pin in _pins_on_net(net):
        part = getattr(pin, "part", None)
        if part is None:
            continue
        if not _part_is_resistor_symbol(part):
            continue
        try:
            raw_pins = part.pins
            if isinstance(raw_pins, dict):
                part_pins = list(raw_pins.values())
            else:
                part_pins = list(raw_pins)
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


# ---------------------------------------------------------------------------
# Generic pull-up hook factory
# ---------------------------------------------------------------------------

def pullup_erc_hook(net, label: str = "signal"):
    """Build ``fn(board) -> list[str]`` that expects *net* to have a pull-up to a supply rail (SCH-005).

    Args:
        net: The net object to check.
        label: Human-readable description for error messages (e.g. "I2C SDA", "UART RX").
    """
    def _hook(board):
        _ = board
        if not net_has_resistor_pullup_to_rail(net):
            return [
                f"{label} net {getattr(net, 'name', '?')!r}: expected a pull-up "
                f"resistor to a supply rail (SCH-005)."
            ]
        return []
    return _hook


def i2c_pullup_erc_hook(sda_net, scl_net):
    """Build ``fn(board)`` that requires pull-up resistors from *sda_net* / *scl_net* to a supply-named net."""
    def _hook(board):
        _ = board
        msgs = []
        if not net_has_resistor_pullup_to_rail(sda_net):
            msgs.append(
                f"I2C SDA net {getattr(sda_net, 'name', '?')!r}: expected a resistor "
                f"to a supply rail (SCH-005)."
            )
        if not net_has_resistor_pullup_to_rail(scl_net):
            msgs.append(
                f"I2C SCL net {getattr(scl_net, 'name', '?')!r}: expected a resistor "
                f"to a supply rail (SCH-005)."
            )
        return msgs
    return _hook


# ---------------------------------------------------------------------------
# Protocol / signal-specific aliases (backward compat)
# ---------------------------------------------------------------------------

def one_wire_pullup_erc_hook(dq_net):
    """1-Wire DQ pull-up check."""
    return pullup_erc_hook(dq_net, "1-Wire DQ")

def uart_rx_pullup_erc_hook(rx_net):
    """UART RX idle-high pull-up check."""
    return pullup_erc_hook(rx_net, "UART RX")

def swd_swdio_pullup_erc_hook(swdio_net):
    """SWD SWDIO pull-up check."""
    return pullup_erc_hook(swdio_net, "SWDIO")

def jtag_tms_pullup_erc_hook(tms_net):
    """JTAG TMS pull-up check."""
    return pullup_erc_hook(tms_net, "JTAG TMS")

def jtag_tck_pullup_erc_hook(tck_net):
    """JTAG TCK pull-up check."""
    return pullup_erc_hook(tck_net, "JTAG TCK")

def can_rx_pullup_erc_hook(rx_net):
    """CAN RX pull-up check."""
    return pullup_erc_hook(rx_net, "CAN RX")

def sd_cmd_pullup_erc_hook(cmd_net):
    """SD/eMMC CMD pull-up check."""
    return pullup_erc_hook(cmd_net, "SD/MMC CMD")

def spi_miso_pullup_erc_hook(miso_net):
    """SPI MISO pull-up check (multi-slave bus hold)."""
    return pullup_erc_hook(miso_net, "SPI MISO")

def spi_cs_pullup_erc_hook(cs_n_net):
    """SPI CS# active-low pull-up check."""
    return pullup_erc_hook(cs_n_net, "SPI CS")

def spi_hold_n_pullup_erc_hook(hold_n_net):
    """SPI HOLD# pull-up check."""
    return pullup_erc_hook(hold_n_net, "SPI HOLD#")

def spi_wp_n_pullup_erc_hook(wp_n_net):
    """SPI WP# (write-protect) pull-up check."""
    return pullup_erc_hook(wp_n_net, "SPI WP#")

def reset_pullup_erc_hook(rst_n_net):
    """Active-low reset pull-up check."""
    return pullup_erc_hook(rst_n_net, "Reset")

def mdio_pullup_erc_hook(mdio_net):
    """MDIO pull-up check."""
    return pullup_erc_hook(mdio_net, "MDIO")

def eth_phy_int_n_pullup_erc_hook(int_n_net):
    """Ethernet PHY INT# open-drain pull-up check."""
    return pullup_erc_hook(int_n_net, "Ethernet PHY INT#")

def rs485_re_n_pullup_erc_hook(re_n_net):
    """RS485 RE# pull-up check."""
    return pullup_erc_hook(re_n_net, "RS485 RE#")

def usb_vbus_sense_pullup_erc_hook(vbus_sense_net):
    """USB VBUS sense pull-up check."""
    return pullup_erc_hook(vbus_sense_net, "USB VBUS sense")

def pcie_wake_n_pullup_erc_hook(wake_n_net):
    """PCIe WAKE# open-drain pull-up check."""
    return pullup_erc_hook(wake_n_net, "PCIe WAKE#")

def rtc_int_n_pullup_erc_hook(int_n_net):
    """RTC INT# pull-up check."""
    return pullup_erc_hook(int_n_net, "RTC INT#")

def lin_bus_pullup_erc_hook(lin_net):
    """LIN bus idle-recessive pull-up check."""
    return pullup_erc_hook(lin_net, "LIN bus")

def power_good_pullup_erc_hook(pgood_net):
    """Power-good open-drain status pull-up check."""
    return pullup_erc_hook(pgood_net, "Power-good")

def i2s_ws_pullup_erc_hook(ws_net):
    """I2S WS (word select / LRCLK) pull-up check."""
    return pullup_erc_hook(ws_net, "I2S WS")

def hdmi_cec_pullup_erc_hook(cec_net):
    """HDMI CEC open-drain pull-up check."""
    return pullup_erc_hook(cec_net, "HDMI CEC")

def hdmi_hpd_pullup_erc_hook(hpd_net):
    """HDMI HPD open-drain pull-up check."""
    return pullup_erc_hook(hpd_net, "HDMI HPD")

def sd_cd_pullup_erc_hook(cd_net):
    """SD card CD# pull-up check."""
    return pullup_erc_hook(cd_net, "SD card CD")

def stepper_dir_pullup_erc_hook(dir_net):
    """Stepper DIR idle level pull-up check."""
    return pullup_erc_hook(dir_net, "Stepper DIR")

def usb_otg_id_pullup_erc_hook(id_net):
    """USB OTG ID pull-up check."""
    return pullup_erc_hook(id_net, "USB OTG ID")

def smbus_alert_pullup_erc_hook(alert_net):
    """SMBus / PMBus ALERT# pull-up check."""
    return pullup_erc_hook(alert_net, "SMBus ALERT")

def sensor_interrupt_pullup_erc_hook(irq_net):
    """Open-drain sensor interrupt (DRDY / INT) pull-up check."""
    return pullup_erc_hook(irq_net, "Sensor interrupt")


# ---------------------------------------------------------------------------
# Structural checks (not pull-up based)
# ---------------------------------------------------------------------------

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
