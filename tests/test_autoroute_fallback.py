from __future__ import annotations

from openhac.compiler.autoroute_cli import fallback_route_with_pcbnew


class _NetInfo:
    def __init__(self, name: str, code: int):
        self._name = name
        self._code = int(code)

    def GetNetCode(self) -> int:
        return self._code


class _Pad:
    def __init__(self, net_code: int, pos: tuple[int, int]):
        self._net_code = int(net_code)
        self._pos = pos

    def GetNetCode(self) -> int:
        return self._net_code

    def GetPosition(self):
        return self._pos


class _Fp:
    def __init__(self, pads):
        self._pads = pads

    def Pads(self):
        return list(self._pads)


class _DesignSettings:
    def GetCurrentTrackWidth(self):
        return 111


class _Board:
    def __init__(self, nets: dict[str, _NetInfo], fps):
        self._nets = nets
        self._fps = fps
        self._added_tracks = []

    def GetNetsByName(self):
        return self._nets

    def GetFootprints(self):
        return list(self._fps)

    def GetDesignSettings(self):
        return _DesignSettings()

    def Add(self, t):
        self._added_tracks.append(t)


class _Track:
    def __init__(self, board):
        self.net = None
        self.layer = None
        self.width = None
        self.a = None
        self.b = None

    def SetNetCode(self, n: int):
        self.net = int(n)

    def SetWidth(self, w: int):
        self.width = int(w)

    def SetLayer(self, l):
        self.layer = l

    def SetStart(self, a):
        self.a = a

    def SetEnd(self, b):
        self.b = b


class _FakePcbNew:
    F_Cu = 0
    B_Cu = 31

    def __init__(self, board):
        self._board = board

    def LoadBoard(self, _):
        return self._board

    def SaveBoard(self, *_args, **_kwargs):
        return None

    def PCB_TRACK(self, board):
        return _Track(board)


def test_fallback_route_respects_no_autoroute_nets(monkeypatch):
    # Net codes.
    nets = {"GND": _NetInfo("GND", 1), "3V3": _NetInfo("3V3", 2)}
    # Two footprints, each has pads on both nets.
    pads = [
        _Pad(1, (0, 0)),
        _Pad(1, (10, 0)),
        _Pad(2, (0, 10)),
        _Pad(2, (10, 10)),
    ]
    board = _Board(nets=nets, fps=[_Fp(pads)])
    pcbnew = _FakePcbNew(board)

    # Patch the module-level pcbnew import inside autoroute_cli.
    monkeypatch.setitem(__import__("sys").modules, "pcbnew", pcbnew)

    fallback_route_with_pcbnew("dummy.kicad_pcb", no_autoroute_nets=["3V3"])

    # Only GND should have tracks added.
    assert board._added_tracks
    assert all(t.net == 1 for t in board._added_tracks)

