from __future__ import annotations

from dataclasses import dataclass

from openhac.compiler.pcb_postprocess import (
    apply_copper_pour_intents,
    apply_keepout_rect_intents,
    apply_mounting_hole_intents,
    apply_net_tie_intents,
)


class _FakeNetInfo:
    def __init__(self, name: str, code: int):
        self._name = name
        self._code = int(code)

    def GetNetCode(self) -> int:  # KiCad API shape
        return self._code


class _FakeZone:
    def __init__(self, pcb):
        self.pcb = pcb
        self.net = None
        self.layer = None
        self.polys = []

    def SetNet(self, ni):
        self.net = ni

    def SetLayer(self, lid: int):
        self.layer = int(lid)

    def AddPolygon(self, poly):
        # Accept either a list of points or a SHAPE_LINE_CHAIN-like object.
        pts = getattr(poly, "_pts", None)
        if pts is None:
            pts = list(poly)
        self.polys.append(list(pts))

    def SetIsRuleArea(self, v: bool):
        self.is_rule = bool(v)

    def SetDoNotAllowTracks(self, v: bool):
        self.no_tracks = bool(v)

    def SetDoNotAllowVias(self, v: bool):
        self.no_vias = bool(v)

    def SetDoNotAllowCopperPour(self, v: bool):
        self.no_pour = bool(v)

    def SetDoNotAllowFootprints(self, v: bool):
        self.no_fps = bool(v)


class _FakeFootprint:
    def __init__(self):
        self.ref = None
        self.val = None
        self.pos = None

    def SetReference(self, r: str):
        self.ref = r

    def SetValue(self, v: str):
        self.val = v

    def SetPosition(self, p):
        self.pos = p

    def Pads(self):
        return getattr(self, "_pads", [])


class _FakePad:
    def __init__(self, name: str):
        self._name = str(name)
        self.net = None

    def GetPadName(self):
        return self._name

    def GetNumber(self):
        return self._name

    def SetNet(self, ni):
        self.net = ni


class _FakeBoard:
    def __init__(self):
        self.added = []
        self._layer_ids = {"F.Cu": 0, "B.Cu": 31}
        self._nets = {"GND": _FakeNetInfo("GND", 1), "3V3": _FakeNetInfo("3V3", 2)}

    def GetLayerID(self, name: str) -> int:
        return int(self._layer_ids[name])

    def GetNetsByName(self):
        return self._nets

    def Add(self, obj):
        self.added.append(obj)


class _FakePcbNew:
    ZONE = _FakeZone

    class SHAPE_LINE_CHAIN:
        def __init__(self):
            self._pts = []
            self._closed = False

        def Append(self, p):
            self._pts.append(p)

        def SetClosed(self, v: bool):
            self._closed = bool(v)

    @staticmethod
    def FromMM(v: float) -> int:
        return int(round(float(v) * 1_000_000))

    @staticmethod
    def VECTOR2I(x: int, y: int):
        return (int(x), int(y))

    @staticmethod
    def FootprintLoad(pretty_dir: str, fp_name: str):
        # We only care that something truthy is returned.
        fp = _FakeFootprint()
        fp._pads = [_FakePad("1"), _FakePad("2")]
        return fp


@dataclass
class _FakeOpenHaCBoard:
    size_mm: tuple[float, float] = (40.0, 30.0)
    _copper_pour_intents: list[dict] | None = None
    _mounting_hole_intents: list[dict] | None = None


def test_apply_copper_pour_intents_adds_zone(monkeypatch):
    pcb = _FakeBoard()
    board = _FakeOpenHaCBoard(
        _copper_pour_intents=[{"net": "GND", "layer": "B.Cu", "purpose": "ground"}]
    )

    added = apply_copper_pour_intents(pcb, board, _FakePcbNew)
    assert added == 1
    assert any(isinstance(x, _FakeZone) for x in pcb.added)
    z = next(x for x in pcb.added if isinstance(x, _FakeZone))
    assert z.layer == 31
    assert z.net.GetNetCode() == 1
    assert z.polys and len(z.polys[0]) == 4


def test_apply_mounting_hole_intents_adds_footprint(monkeypatch):
    # Avoid depending on host footprint paths in unit tests.
    monkeypatch.setattr(
        "openhac.compiler.pcb_postprocess.resolve_pretty_directory",
        lambda _: "/tmp/MountingHole.pretty",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_postprocess.os.listdir",
        lambda _: {"MountingHole_3.2mm_M3.kicad_mod"},
    )

    pcb = _FakeBoard()
    board = _FakeOpenHaCBoard(
        _mounting_hole_intents=[{"x_mm": 2.5, "y_mm": 2.5, "diameter_mm": 2.2, "note": "M2"}]
    )

    added = apply_mounting_hole_intents(pcb, board, _FakePcbNew)
    assert added == 1
    fp = next(x for x in pcb.added if isinstance(x, _FakeFootprint))
    assert fp.ref == "H1"
    assert fp.pos is not None


def test_apply_keepout_rect_intents_adds_rule_area():
    pcb = _FakeBoard()
    board = _FakeOpenHaCBoard(
        _copper_pour_intents=[],
        _mounting_hole_intents=[],
    )
    board._keepout_rect_intents = [
        {"x_mm": 1.0, "y_mm": 2.0, "w_mm": 5.0, "h_mm": 6.0, "layers": ["F.Cu"], "purpose": "placement"}
    ]
    added = apply_keepout_rect_intents(pcb, board, _FakePcbNew)
    assert added == 1
    z = next(x for x in pcb.added if isinstance(x, _FakeZone))
    assert getattr(z, "is_rule", False) is True
    assert getattr(z, "no_fps", False) is True


def test_apply_net_tie_intents_adds_footprint_and_sets_pad_nets(monkeypatch):
    monkeypatch.setattr(
        "openhac.compiler.pcb_postprocess.resolve_pretty_directory",
        lambda _: "/tmp/NetTie.pretty",
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_postprocess.os.listdir",
        lambda _: {"NetTie-2_SMD_Pad2.0mm.kicad_mod"},
    )
    pcb = _FakeBoard()
    board = _FakeOpenHaCBoard(
        _copper_pour_intents=[],
        _mounting_hole_intents=[],
    )
    board._net_tie_intents = [
        {"net_a": "GND", "net_b": "3V3", "footprint": "NetTie:NetTie-2_SMD_Pad2.0mm", "x_mm": 3.0, "y_mm": 4.0}
    ]
    added = apply_net_tie_intents(pcb, board, _FakePcbNew)
    assert added == 1
    fp = next(x for x in pcb.added if isinstance(x, _FakeFootprint))
    pads = fp.Pads()
    assert pads[0].net.GetNetCode() == 1
    assert pads[1].net.GetNetCode() == 2

