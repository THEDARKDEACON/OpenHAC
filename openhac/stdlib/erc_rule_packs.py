"""Named ERC hook bundles (SCH-005) — register multiple ``openhac.stdlib.erc_rules`` checks in one call.

These are **optional** conveniences; equivalent hooks can be registered individually.
"""

from __future__ import annotations

# Discoverable names for manifest / docs (STR-002 / SCH-005).
ERC_RULE_PACK_EXPORTS: tuple[str, ...] = (
    "apply_i2c_pullup_pack",
    "apply_spi_flash_pullup_pack",
    "apply_uart_debug_pullup_pack",
    "apply_hdmi_display_pullup_pack",
    "apply_sd_mmc_pullup_pack",
    "apply_jtag_boundary_pullup_pack",
    "apply_spi_nor_protect_pullup_pack",
    "apply_lin_rs485_re_pullup_pack",
    "apply_can_eth_phy_pullup_pack",
)


def apply_i2c_pullup_pack(board, scl_net, sda_net) -> None:
    """Register **I2C** SCL + SDA pull-up check (single hook, SCH-005)."""
    from openhac.stdlib.erc_rules import i2c_pullup_erc_hook

    board.register_erc_hook(i2c_pullup_erc_hook(sda_net, scl_net))


def apply_spi_flash_pullup_pack(board, cs_n_net, miso_net) -> None:
    """Register **SPI** CS# + MISO pull-up checks common on flash / MCU buses."""
    from openhac.stdlib.erc_rules import spi_cs_pullup_erc_hook, spi_miso_pullup_erc_hook

    board.register_erc_hook(spi_cs_pullup_erc_hook(cs_n_net))
    board.register_erc_hook(spi_miso_pullup_erc_hook(miso_net))


def apply_uart_debug_pullup_pack(board, uart_rx_net, swdio_net) -> None:
    """Register **UART RX** + **SWDIO** pull-up checks (typical bring-up)."""
    from openhac.stdlib.erc_rules import swd_swdio_pullup_erc_hook, uart_rx_pullup_erc_hook

    board.register_erc_hook(uart_rx_pullup_erc_hook(uart_rx_net))
    board.register_erc_hook(swd_swdio_pullup_erc_hook(swdio_net))


def apply_hdmi_display_pullup_pack(board, cec_net, hpd_net) -> None:
    """Register **HDMI CEC** + **HPD** open-drain pull-up checks."""
    from openhac.stdlib.erc_rules import hdmi_cec_pullup_erc_hook, hdmi_hpd_pullup_erc_hook

    board.register_erc_hook(hdmi_cec_pullup_erc_hook(cec_net))
    board.register_erc_hook(hdmi_hpd_pullup_erc_hook(hpd_net))


def apply_sd_mmc_pullup_pack(board, cmd_net, cd_net) -> None:
    """Register **SD/MMC CMD** + **card detect (CD#)** pull-up checks."""
    from openhac.stdlib.erc_rules import sd_cd_pullup_erc_hook, sd_cmd_pullup_erc_hook

    board.register_erc_hook(sd_cmd_pullup_erc_hook(cmd_net))
    board.register_erc_hook(sd_cd_pullup_erc_hook(cd_net))


def apply_jtag_boundary_pullup_pack(board, tms_net, tck_net) -> None:
    """Register **JTAG TMS** + **TCK** pull-up checks (typical boundary-scan / debug header)."""
    from openhac.stdlib.erc_rules import jtag_tck_pullup_erc_hook, jtag_tms_pullup_erc_hook

    board.register_erc_hook(jtag_tms_pullup_erc_hook(tms_net))
    board.register_erc_hook(jtag_tck_pullup_erc_hook(tck_net))


def apply_spi_nor_protect_pullup_pack(board, wp_n_net, hold_n_net) -> None:
    """Register **SPI NOR WP#** + **HOLD#** pull-up checks (typical quad-SPI flash strapping)."""
    from openhac.stdlib.erc_rules import spi_hold_n_pullup_erc_hook, spi_wp_n_pullup_erc_hook

    board.register_erc_hook(spi_wp_n_pullup_erc_hook(wp_n_net))
    board.register_erc_hook(spi_hold_n_pullup_erc_hook(hold_n_net))


def apply_lin_rs485_re_pullup_pack(board, lin_net, re_n_net) -> None:
    """Register **LIN bus** + **RS485 RE#** pull-up checks (common automotive / industrial gateway IO)."""
    from openhac.stdlib.erc_rules import lin_bus_pullup_erc_hook, rs485_re_n_pullup_erc_hook

    board.register_erc_hook(lin_bus_pullup_erc_hook(lin_net))
    board.register_erc_hook(rs485_re_n_pullup_erc_hook(re_n_net))


def apply_can_eth_phy_pullup_pack(board, can_rx_net, eth_phy_int_n_net) -> None:
    """Register **CAN RX** + **Ethernet PHY INT#** pull-up checks (common connected-vehicle / gateway PHY strapping)."""
    from openhac.stdlib.erc_rules import can_rx_pullup_erc_hook, eth_phy_int_n_pullup_erc_hook

    board.register_erc_hook(can_rx_pullup_erc_hook(can_rx_net))
    board.register_erc_hook(eth_phy_int_n_pullup_erc_hook(eth_phy_int_n_net))
