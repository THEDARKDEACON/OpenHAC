"""AABB footprint legalizer — geometry only, no board-class tables."""

from __future__ import annotations

from openhac.compiler.legalize import legalize_aabbs, overlap_pairs


def test_legalize_separates_two_stacked_boxes():
    pos, w, h = legalize_aabbs(
        [("a", 0.0, 0.0, 10.0, 10.0), ("b", 0.0, 0.0, 10.0, 10.0)],
        gap=2.0,
        margin=1.0,
    )
    boxes = {k: (pos[k][0], pos[k][1], 10.0, 10.0) for k in pos}
    assert overlap_pairs(boxes, 2.0) == 0
    assert pos["a"] != pos["b"]
    assert w >= 10 + 2 + 10 + 1
    assert h >= 10 + 1


def test_legalize_separates_many_coincident_boxes():
    items = [(i, 0.0, 0.0, 8.0, 8.0) for i in range(9)]
    pos, _w, _h = legalize_aabbs(items, gap=1.0, margin=0.0, rounds=400)
    boxes = {k: (pos[k][0], pos[k][1], 8.0, 8.0) for k in pos}
    assert overlap_pairs(boxes, 1.0) == 0
    assert len(pos) == 9


def test_legalize_does_not_collapse_already_legal_pack():
    items = [
        ("a", 0.0, 0.0, 10.0, 10.0),
        ("b", 13.0, 0.0, 10.0, 10.0),
    ]
    pos, _w, _h = legalize_aabbs(items, gap=2.0, margin=0.0)
    dx = abs(pos["a"][0] - pos["b"][0])
    dy = abs(pos["a"][1] - pos["b"][1])
    assert dx >= 12.0 or dy >= 12.0
    boxes = {k: (pos[k][0], pos[k][1], 10.0, 10.0) for k in pos}
    assert overlap_pairs(boxes, 2.0) == 0


def test_legalize_grows_outline_instead_of_clamping():
    # Four 20×20 boxes stacked cannot fit in a 30×30 outline; legalizer must grow.
    # Growth is shrink-wrapped to the pack, not a sparse origin-push.
    items = [(i, 5.0, 5.0, 20.0, 20.0) for i in range(4)]
    pos, w, h = legalize_aabbs(items, gap=2.0, margin=2.0)
    boxes = {k: (pos[k][0], pos[k][1], 20.0, 20.0) for k in pos}
    assert overlap_pairs(boxes, 2.0) == 0
    assert w > 30.0 or h > 30.0
    assert min(xy[0] for xy in pos.values()) >= 2.0 - 1e-9
    assert min(xy[1] for xy in pos.values()) >= 2.0 - 1e-9
    # 2×2 of 20 mm + gap 2 + margins: ~46 mm, not a 4-long strip (~90 mm).
    assert max(w, h) < 70.0
    assert w * h < 70.0 * 70.0


def test_legalize_keeps_neighborhood_of_slight_overlap():
    # Two boxes already in a floorplan neighborhood: nudge, do not teleport.
    items = [
        ("a", 80.0, 20.0, 10.0, 10.0),
        ("b", 88.0, 20.0, 10.0, 10.0),
    ]
    pos, w, h = legalize_aabbs(items, gap=2.0, margin=2.0)
    boxes = {k: (pos[k][0], pos[k][1], 10.0, 10.0) for k in pos}
    assert overlap_pairs(boxes, 2.0) == 0
    mid = (pos["a"][0] + pos["b"][0]) / 2.0
    assert mid > 70.0
    assert abs(pos["a"][1] - 20.0) < 1.0
    assert abs(pos["b"][1] - 20.0) < 1.0
    assert abs(pos["a"][0] - pos["b"][0]) < 20.0
    assert w < 120.0
    assert h < 40.0


def test_legalize_does_not_pull_legal_pack_to_origin():
    items = [
        ("a", 80.0, 10.0, 10.0, 10.0),
        ("b", 93.0, 10.0, 10.0, 10.0),
    ]
    pos, _w, _h = legalize_aabbs(items, gap=2.0, margin=2.0)
    assert abs(pos["a"][0] - 80.0) < 1e-6
    assert abs(pos["b"][0] - 93.0) < 1e-6
    boxes = {k: (pos[k][0], pos[k][1], 10.0, 10.0) for k in pos}
    assert overlap_pairs(boxes, 2.0) == 0


def test_legalize_coincident_pile_stays_compact():
    items = [(i, 0.0, 0.0, 8.0, 8.0) for i in range(9)]
    pos, w, h = legalize_aabbs(items, gap=1.0, margin=0.0, rounds=400)
    boxes = {k: (pos[k][0], pos[k][1], 8.0, 8.0) for k in pos}
    assert overlap_pairs(boxes, 1.0) == 0
    # 3×3 grid is ~26 mm; origin-push staircase is ~80 mm on both axes.
    assert max(w, h) < 45.0
    assert w * h < 45.0 * 45.0


def test_overlap_pairs_counts_gap_violation():
    boxes = {
        "a": (0.0, 0.0, 10.0, 10.0),
        "b": (10.5, 0.0, 10.0, 10.0),
    }
    assert overlap_pairs(boxes, 0.0) == 0
    assert overlap_pairs(boxes, 1.0) == 1


class _BBox:
    def __init__(self, l, t, w, h):
        self._l, self._t, self._w, self._h = l, t, w, h

    def GetLeft(self):
        return self._l

    def GetTop(self):
        return self._t

    def GetRight(self):
        return self._l + self._w

    def GetBottom(self):
        return self._t + self._h

    def GetWidth(self):
        return self._w

    def GetHeight(self):
        return self._h


class _Pos:
    def __init__(self, x, y):
        self.x = int(x)
        self.y = int(y)


class _Fp:
    def __init__(self, ref: str, x: int, y: int, w: int, h: int):
        self._ref = ref
        self._x, self._y, self._w, self._h = x, y, w, h

    def GetReference(self):
        return self._ref

    def GetBoundingBox(self, *_args):
        return _BBox(self._x, self._y, self._w, self._h)

    def GetPosition(self):
        return _Pos(self._x, self._y)

    def SetPosition(self, p):
        if isinstance(p, tuple):
            self._x, self._y = int(p[0]), int(p[1])
        else:
            self._x, self._y = int(p.x), int(p.y)


class _Pcb:
    def __init__(self, fps):
        self._fps = list(fps)
        self.added = []

    def GetFootprints(self):
        return list(self._fps)

    def GetLayerID(self, _name):
        return 44

    def GetDrawings(self):
        return []

    def Remove(self, _d):
        return None

    def Add(self, obj):
        self.added.append(obj)


class _Pn:
    SHAPE_T_SEGMENT = 0

    class PCB_SHAPE:
        def __init__(self, _pcb):
            pass

        def SetShape(self, *_a):
            pass

        def SetStart(self, *_a):
            pass

        def SetEnd(self, *_a):
            pass

        def SetLayer(self, *_a):
            pass

        def SetWidth(self, *_a):
            pass

    @staticmethod
    def FromMM(v):
        return int(round(float(v) * 1000.0))

    @staticmethod
    def ToMM(v):
        return float(v) / 1000.0

    @staticmethod
    def VECTOR2I(x, y):
        return _Pos(x, y)


def test_legalize_placed_footprints_separates_and_grows_outline():
    from openhac.compiler.pcb_postprocess import legalize_placed_footprints

    # Two 10 mm squares stacked at origin (IU = 0.001 mm).
    fps = [_Fp("U1", 0, 0, 10_000, 10_000), _Fp("U2", 0, 0, 10_000, 10_000)]
    pcb = _Pcb(fps)
    board = type("B", (), {"size_mm": (20.0, 20.0)})()
    stats = legalize_placed_footprints(pcb, _Pn, board, gap_mm=2.0, margin_mm=1.0)
    assert stats["overlaps"] == 0
    assert stats["moved"] >= 1
    assert board.size_mm[0] >= 23.0 or board.size_mm[1] >= 23.0
    assert len(pcb.added) >= 4

