from __future__ import annotations

from openhac.compiler.pcb_fit import (
    count_footprint_bbox_overlap_pairs,
    pcb_fit_violations_from_pcbnew_board,
)


class _FakeBBox:
    def __init__(self, x: int, y: int, w: int, h: int):
        self._x = int(x)
        self._y = int(y)
        self._w = int(w)
        self._h = int(h)

    def GetX(self) -> int:
        return self._x

    def GetY(self) -> int:
        return self._y

    def GetWidth(self) -> int:
        return self._w

    def GetHeight(self) -> int:
        return self._h


class _FakeFootprint:
    def __init__(self, ref: str, bbox: _FakeBBox):
        self._ref = str(ref)
        self._bbox = bbox

    def GetReference(self) -> str:
        return self._ref

    def GetBoundingBox(self) -> _FakeBBox:
        return self._bbox


class _FakePcb:
    def __init__(self, edge_bbox: _FakeBBox, footprints: list[_FakeFootprint]):
        self._edge_bbox = edge_bbox
        self._fps = list(footprints)

    def GetBoardEdgesBoundingBox(self) -> _FakeBBox:
        return self._edge_bbox

    def GetFootprints(self):
        return list(self._fps)


class _FakePcbnew:
    @staticmethod
    def FromMM(mm: float) -> int:
        # Arbitrary internal units for tests
        return int(round(float(mm) * 1000.0))


class _FakeBoard:
    def __init__(self, keepouts: list[dict] | None = None):
        self._keepout_rect_intents = keepouts or []


def test_pcb_fit_flags_footprint_outside_outline_bbox() -> None:
    pcb = _FakePcb(
        edge_bbox=_FakeBBox(0, 0, 100_000, 50_000),
        footprints=[
            _FakeFootprint("U1", _FakeBBox(10_000, 10_000, 5_000, 5_000)),
            _FakeFootprint("U2", _FakeBBox(99_000, 10_000, 5_000, 5_000)),  # spills past right edge
        ],
    )
    board = _FakeBoard()
    viols = pcb_fit_violations_from_pcbnew_board(pcb, board, pcbnew_mod=_FakePcbnew, margin_mm=0.0)
    assert any("U2" in v and "outside" in v.lower() for v in viols)
    assert not any("U1" in v and "outside" in v.lower() for v in viols)


def test_count_footprint_bbox_overlap_pairs_detects_overlap() -> None:
    pcb = _FakePcb(
        edge_bbox=_FakeBBox(0, 0, 100_000, 100_000),
        footprints=[
            _FakeFootprint("U1", _FakeBBox(10_000, 10_000, 5_000, 5_000)),
            _FakeFootprint("U2", _FakeBBox(12_000, 10_000, 5_000, 5_000)),
        ],
    )
    assert count_footprint_bbox_overlap_pairs(pcb, _FakePcbnew, clearance_mm=0.0) == 1


def test_count_footprint_bbox_overlap_pairs_clearance_separates() -> None:
    pcb = _FakePcb(
        edge_bbox=_FakeBBox(0, 0, 100_000, 100_000),
        footprints=[
            _FakeFootprint("U1", _FakeBBox(10_000, 10_000, 5_000, 5_000)),
            _FakeFootprint("U2", _FakeBBox(16_000, 10_000, 5_000, 5_000)),
        ],
    )
    assert count_footprint_bbox_overlap_pairs(pcb, _FakePcbnew, clearance_mm=0.0) == 0


def test_pcb_fit_flags_fp_fp_bbox_overlap_when_enabled() -> None:
    pcb = _FakePcb(
        edge_bbox=_FakeBBox(0, 0, 100_000, 100_000),
        footprints=[
            _FakeFootprint("U1", _FakeBBox(10_000, 10_000, 5_000, 5_000)),
            _FakeFootprint("U2", _FakeBBox(12_000, 10_000, 5_000, 5_000)),
        ],
    )
    board = _FakeBoard()
    viols = pcb_fit_violations_from_pcbnew_board(
        pcb,
        board,
        pcbnew_mod=_FakePcbnew,
        margin_mm=0.0,
        check_fp_overlap=True,
        fp_overlap_clearance_mm=0.0,
    )
    assert any("overlap" in v.lower() and "U1" in v for v in viols)


def test_pcb_fit_flags_footprint_overlapping_keepout_rect() -> None:
    pcb = _FakePcb(
        edge_bbox=_FakeBBox(0, 0, 100_000, 100_000),
        footprints=[
            _FakeFootprint("U1", _FakeBBox(10_000, 10_000, 5_000, 5_000)),
        ],
    )
    board = _FakeBoard(
        keepouts=[
            {"x_mm": 9.0, "y_mm": 9.0, "w_mm": 5.0, "h_mm": 5.0, "layers": ["F.Cu"], "purpose": "placement"}
        ]
    )
    viols = pcb_fit_violations_from_pcbnew_board(pcb, board, pcbnew_mod=_FakePcbnew, margin_mm=0.0)
    assert any("keepout_rect" in v for v in viols)

