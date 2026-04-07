from __future__ import annotations


class _Net:
    def __init__(self, name: str):
        self.name = name


class _Pin:
    def __init__(self, num: str, net):
        self.num = num
        self.net = net


class _Part:
    def __init__(self, ref: str, footprint: str, pins):
        self.ref = ref
        self.footprint = footprint
        self.pins = pins


class _Circuit:
    def __init__(self, parts):
        self.parts = parts


def test_pin_pad_coverage_warnings_are_sorted(monkeypatch):
    from openhac.compiler import pcb_placement

    # Force pad set to a known small set so warnings are deterministic.
    monkeypatch.setattr(pcb_placement, "footprint_pad_numbers_from_library", lambda lib, fp: {"1"}, raising=True)

    gnd = _Net("GND")
    p1 = _Part("R2", "Lib:FP", [_Pin("2", gnd), _Pin("1", gnd)])
    p2 = _Part("R1", "Lib:FP", [_Pin("2", gnd), _Pin("1", gnd)])

    c = _Circuit([p1, p2])
    msgs = pcb_placement.pin_pad_coverage_warnings(c)
    assert msgs == sorted(msgs)

