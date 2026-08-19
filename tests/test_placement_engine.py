"""Constructive / net-affinity placement engine."""

from __future__ import annotations

from openhac.compiler.cluster_affinity import discover_cluster_pairs
from openhac.compiler.placement_engine import (
    affinity_order,
    apply_affinity_floorplan,
    connected_components,
    connectivity_order,
    graph_pack_positions,
    is_power_or_nc_net,
    module_signal_nets,
    shelf_pack,
    shared_signal_count,
)
from openhac.core.board import Board
from openhac.core.module import Module


def test_shelf_pack_uses_real_widths_not_max_cell():
    # 10×10 IC + two 2×1 passives in 2 columns: IC on row 0, passives share row 1.
    items = [("ic", 10.0, 10.0), ("a", 2.0, 1.0), ("b", 2.0, 1.0)]
    pos, w, h = shelf_pack(items, gap=1.0, cols=2)
    assert pos["ic"] == (0.0, 0.0)
    # max-cell packing would be 2*10+1 = 21; real widths keep the row to IC+gap+passive.
    assert w < 16.0
    assert h <= 12.0 + 1e-9


def test_module_signal_nets_reads_dict_pins():
    class _Net:
        def __init__(self, name):
            self.name = name

    class _Pin:
        def __init__(self, name):
            self.net = _Net(name)

    class _Part:
        pins = {"1": _Pin("SIG_A"), "2": _Pin("GND")}

    class _Leaf:
        part = _Part()

    m = Module("M0")
    m.components.append(_Leaf())
    nets = module_signal_nets(m)
    assert "SIG_A" in nets
    assert "GND" not in nets


def test_power_nets_are_ignored_for_affinity():
    assert is_power_or_nc_net("GND")
    assert is_power_or_nc_net("3V3")
    assert is_power_or_nc_net("VBUS_5V")
    assert is_power_or_nc_net("VIN_24V")
    assert is_power_or_nc_net("NC")
    assert not is_power_or_nc_net("SIG_A")
    assert not is_power_or_nc_net("N_BRIDGE")


def test_affinity_order_groups_shared_signal_nets():
    hub, a, b, iso = Module("M0"), Module("M1"), Module("M2"), Module("M3")
    for m, w in ((hub, 40), (a, 30), (b, 8), (iso, 12)):
        m.width, m.height = w, w
    nets = {
        id(hub): {"N0", "N1", "N2"},
        id(a): {"N0", "N1"},
        id(b): {"N2", "N3"},
        id(iso): {"N9"},
    }
    order = affinity_order([iso, b, a, hub], nets)
    assert order[0] is hub  # largest
    assert order[1] is a  # shares two nets with hub


def test_affinity_floorplan_shrinks_outline(monkeypatch):
    monkeypatch.setenv("OPENHAC_MODULE_CLEARANCE_MM", "2")
    monkeypatch.setenv("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", "2")
    b = Board(size_mm=(400, 400))
    a, c = Module("A"), Module("B")
    a.width = a.height = 10
    c.width = c.height = 10
    b.modules = [a, c]
    b.all_modules = [a, c]
    b.constraints = []
    assert apply_affinity_floorplan(b)
    assert a.placed_x is not None and c.placed_x is not None
    max_r = max(a.placed_x + a.width, c.placed_x + c.width)
    max_b = max(a.placed_y + a.height, c.placed_y + c.height)
    assert max_r <= 30
    assert max_b <= 30
    assert b.size_mm[0] <= 40
    assert b.size_mm[1] <= 40


def _edge_sep(pos, a, b) -> float:
    ax, ay = pos[id(a)]
    bx, by = pos[id(b)]
    dx = max(0.0, max(ax - (bx + b.width), bx - (ax + a.width)))
    dy = max(0.0, max(ay - (by + b.height), by - (ay + a.height)))
    if dx > 0 and dy > 0:
        return dx + dy
    return max(dx, dy) if (dx > 0 or dy > 0) else 0.0


def _center(pos, m):
    x, y = pos[id(m)]
    return (x + m.width / 2.0, y + m.height / 2.0)


def test_connectivity_order_prefers_degree_over_area():
    hub, leaf = Module("M_hub"), Module("M_leaf")
    hub.width = hub.height = 8
    leaf.width = leaf.height = 30
    extra = Module("M_b")
    extra.width = extra.height = 8
    nets = {
        id(hub): {"N0", "N1"},
        id(leaf): {"N0"},
        id(extra): {"N1"},
    }
    order = connectivity_order([leaf, extra, hub], nets)
    assert order[0] is hub


def test_graph_pack_star_puts_leaves_on_hub_not_isolate():
    hub = Module("M0")
    leaves = [Module(f"L{i}") for i in range(3)]
    iso = Module("Z")
    hub.width = hub.height = 20
    iso.width = iso.height = 8
    for m in leaves:
        m.width = m.height = 10
    nets = {
        id(hub): {"N0", "N1", "N2"},
        id(leaves[0]): {"N0"},
        id(leaves[1]): {"N1"},
        id(leaves[2]): {"N2"},
        id(iso): set(),
    }
    mods = [iso, leaves[2], hub, leaves[0], leaves[1]]
    pos, order = graph_pack_positions(mods, nets, gap=2.0)
    assert order[0] is hub
    comps = connected_components(mods, nets)
    assert any(hub in g and iso not in g for g in comps)
    leaf_sep = [_edge_sep(pos, hub, m) for m in leaves]
    assert max(leaf_sep) <= 2.0 + 1e-6
    assert _edge_sep(pos, hub, iso) > max(leaf_sep) + 1e-6


def test_graph_pack_chain_keeps_middle_between_ends():
    a, mid, c = Module("A"), Module("B"), Module("C")
    for m in (a, mid, c):
        m.width = m.height = 10
    nets = {
        id(a): {"N0"},
        id(mid): {"N0", "N1"},
        id(c): {"N1"},
    }
    pos, order = graph_pack_positions([c, a, mid], nets, gap=2.0)
    assert order[0] is mid
    ca, cb, cc = _center(pos, a), _center(pos, mid), _center(pos, c)
    def _manh(p, q):
        return abs(p[0] - q[0]) + abs(p[1] - q[1])

    assert _manh(ca, cc) > _manh(ca, cb)
    assert _manh(ca, cc) > _manh(cb, cc)


def test_graph_pack_empty_signal_sets_are_separate_components():
    a, b = Module("P0"), Module("P1")
    a.width = a.height = 10
    b.width = b.height = 10
    nets = {id(a): set(), id(b): set()}
    comps = connected_components([a, b], nets)
    assert len(comps) == 2
    pos, _order = graph_pack_positions([a, b], nets, gap=2.0)
    assert pos[id(a)] != pos[id(b)]


def test_shared_signal_count_is_symmetric():
    a, b = Module("A"), Module("B")
    nets = {id(a): {"N0", "N1"}, id(b): {"N1", "N2"}}
    assert shared_signal_count(a, b, nets) == 1
    assert shared_signal_count(b, a, nets) == 1


def test_unrelated_modules_are_not_clustered_by_name():
    board = Board(size_mm=(80, 80))
    core, other = Module("AlphaCore"), Module("CeBias")
    board.add_module(core)
    board.add_module(other)
    assert discover_cluster_pairs(board) == []
