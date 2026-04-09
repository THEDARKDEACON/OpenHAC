from __future__ import annotations

from openhac.compiler.pcb_metrics import compute_pcb_metrics


class _FakeTrack:
    pass


class _FakeVia:
    pass


class _FakePcb:
    def __init__(self):
        self._tracks = [_FakeTrack(), _FakeTrack(), _FakeVia()]
        self._fps = [object(), object()]
        self._nets = {"N1": object(), "N2": object()}

    def GetTracks(self):
        return list(self._tracks)

    def GetFootprints(self):
        return list(self._fps)

    def GetNetsByName(self):
        return dict(self._nets)


class _FakePcbnew:
    @staticmethod
    def LoadBoard(_path: str):
        return _FakePcb()


def test_compute_pcb_metrics_counts_tracks_vias_footprints_nets(tmp_path) -> None:
    m = compute_pcb_metrics(tmp_path / "x.kicad_pcb", pcbnew_mod=_FakePcbnew)
    # Via detection is class-name based; _FakeVia should be counted as via.
    assert m["track_count"] == 2
    assert m["via_count"] == 1
    assert m["footprint_count"] == 2
    assert m["net_count"] == 2

