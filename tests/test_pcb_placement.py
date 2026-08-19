"""Unit tests for openhac.compiler.pcb_placement (no KiCad pcbnew required)."""

import pytest

from openhac.compiler.pcb_placement import (
    _pin_covers_footprint_pad,
    collect_skidl_part_positions,
    find_pad_for_pin,
    footprint_search_roots,
    kicad_mod_pad_numbers,
    parse_footprint_id,
    pin_pad_coverage_warnings,
)
from openhac.core.base import Component, Module
from openhac.core.board import Board


def test_place_circuit_applies_rotation_field(monkeypatch, tmp_path):
    """Stretch: OpenHaC_Rotation_Deg on SKiDL part fields is applied to pcbnew footprints when possible."""
    from skidl import Net, Part

    # Minimal fake pcbnew footprint + pcb board.
    class _Fp:
        def __init__(self):
            self.rot_deg = None
            self.path = None

        def SetReference(self, _):
            pass

        def SetValue(self, _):
            pass

        def SetPosition(self, _):
            pass

        def SetPath(self, p):
            self.path = p

        def SetOrientationDegrees(self, d):
            self.rot_deg = float(d)

        def Pads(self):
            return []

    class _Plugin:
        def FootprintLoad(self, *_args, **_kwargs):
            return _Fp()

    class _Pcb:
        def __init__(self):
            self.items = []

        def Add(self, x):
            self.items.append(x)

        def GetNetsByName(self):
            # Net assignment not used in this test.
            return {}

    class _PcbNew:
        class PCB_IO_MGR:
            KICAD_SEXP = 1

            @staticmethod
            def PluginFind(_):
                return _Plugin()

        @staticmethod
        def FromMM(v):
            return int(v * 1_000_000)

        @staticmethod
        def VECTOR2I(x, y):
            return (x, y)

        class KIID_PATH(str):
            pass

        class NETINFO_ITEM:
            def __init__(self, *_args, **_kwargs):
                pass

    # Build circuit with one rotated part.
    n = Net("N")
    p = Part("Device", "R", value="1k", ref="R1", footprint="Resistor_SMD:R_0603_1608Metric")
    p.fields["OpenHaC_Rotation_Deg"] = "45"
    p[1] += n

    # Ensure footprint directory resolver returns something.
    monkeypatch.setattr(
        "openhac.compiler.pcb_placement.resolve_pretty_directory",
        lambda _lib: str(tmp_path),
    )
    monkeypatch.setattr(
        "openhac.compiler.pcb_placement.collect_skidl_part_positions",
        lambda _b: {p: (5.0, 5.0)},
    )

    from openhac.compiler.pcb_placement import place_circuit_on_board

    pcb = _Pcb()

    class _Child:
        part = p

    class _Mod:
        components = [_Child()]

    board = Board(size_mm=(10, 10))
    board._get_all_modules = lambda: [_Mod()]  # type: ignore[method-assign]
    place_circuit_on_board(pcb, board, _PcbNew)
    fps = [x for x in pcb.items if isinstance(x, _Fp)]
    assert fps and fps[0].rot_deg == 45.0
    from openhac.schematic.kicad_links import footprint_schematic_path

    assert str(fps[0].path) == footprint_schematic_path(p, parts=[p])


class TestParseFootprintId:

    def test_valid(self):
        assert parse_footprint_id("Resistor_SMD:R_0805_2012Metric") == (
            "Resistor_SMD",
            "R_0805_2012Metric",
        )

    def test_empty(self):
        assert parse_footprint_id("") is None
        assert parse_footprint_id(None) is None

    def test_no_colon(self):
        assert parse_footprint_id("R_0805") is None


class TestFootprintSearchRoots:

    def test_env_override(self, monkeypatch, tmp_path):
        fp_root = tmp_path / "fp"
        fp_root.mkdir()
        monkeypatch.setenv("KICAD8_FOOTPRINT_DIR", str(fp_root))
        roots = footprint_search_roots()
        assert str(fp_root.resolve()) in roots


class TestCollectSkidlPartPositions:

    def test_places_components_under_module(self, tmp_db, monkeypatch):
        _, dm = tmp_db
        dm.insert_component(
            {
                "generic_name": "R_10k_0805",
                "kicad_symbol": "Device:R",
                "kicad_footprint": "Resistor_SMD:R_0805_2012Metric",
                "manufacturer": "",
                "mpn": "X",
                "description": "",
            }
        )

        class M(Module):
            def __init__(self):
                super().__init__("M1")
                self.placed_x = 20
                self.placed_y = 30
                with monkeypatch.context() as m:
                    m.setattr(Component, "db", dm)
                    self.c = self.add(Component("R_10k_0805"))

        board = Board(size_mm=(100, 100))
        board.all_modules = [M()]
        pos = collect_skidl_part_positions(board)
        assert len(pos) == 1
        (x, y) = next(iter(pos.values()))
        assert x == 20.0 and y == 30.0


class TestKicadModPadNumbers:
    def test_quoted_and_numeric_pad_tokens(self):
        body = (
            '(footprint "X" '
            '(pad "1" smd roundrect (at 0 0) (size 1 1) (layers F.Cu)) '
            "(pad 2 smd rect (at 1 0) (size 1 1) (layers F.Cu)))"
        )
        assert kicad_mod_pad_numbers(body) == {"1", "2"}


def test_find_pad_for_pin_name_and_led_alias():
    import os

    pytest.importorskip("pcbnew")
    import pcbnew

    p = "/usr/share/kicad/footprints/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod"
    if not os.path.isfile(p):
        pytest.skip("KiCad stock footprints not at expected path")
    plug = pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    fp = plug.FootprintLoad(os.path.dirname(p), "R_0603_1608Metric")
    assert find_pad_for_pin(fp, "1", None) is not None
    assert find_pad_for_pin(fp, "3", "1") is not None  # wrong num, name matches pad 1
    # LED-style A/K → 1/2 when only numeric pads exist
    assert find_pad_for_pin(fp, "9", "A") is not None
    assert find_pad_for_pin(fp, "9", "K") is not None


class TestPinPadCoverageWarnings:
    def test_warns_when_pin_net_has_no_matching_pad(self, tmp_path, monkeypatch):
        import openhac.core  # noqa: F401
        from skidl import Net, Part

        root = tmp_path / "fp"
        pretty = root / "Resistor_Test.pretty"
        pretty.mkdir(parents=True)
        (pretty / "R2.kicad_mod").write_text(
            '(footprint "R2" '
            '(pad "1" smd roundrect (at 0 0) (size 1 1) (layers F.Cu F.Mask F.Paste)))',
            encoding="utf-8",
        )
        monkeypatch.setenv("KICAD8_FOOTPRINT_DIR", str(root))
        monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")

        n = Net("N")
        r = Part("Device", "R", value="1k", ref="RX", footprint="Resistor_Test:R2")
        r[1] += n
        r[2] += n

        from openhac.circuit import get_default_circuit

        msgs = pin_pad_coverage_warnings(get_default_circuit())
        assert any("RX" in m and "2" in m and "pad" in m.lower() for m in msgs)


def test_pin_covers_footprint_pad_usb_typec_synonyms():
    pads = {"D+", "D-", "GND", "VBUS", "A6", "A7", "CC1", "CC2", "A1", "B1"}
    assert _pin_covers_footprint_pad("", "DP", pads)
    assert _pin_covers_footprint_pad("", "DM", pads)
    assert _pin_covers_footprint_pad("", "CC1", pads)
    assert _pin_covers_footprint_pad("99", "VBUS", pads)


def test_footprint_pack_bbox_excludes_silk_text():
    from openhac.compiler.pcb_placement import _footprint_pack_bbox, _module_pack_cols

    class _Box:
        def __init__(self, w):
            self._w = w

        def GetWidth(self):
            return self._w

    class _Fp:
        def GetBoundingBox(self, *args):
            if args == (False, False):
                return _Box(3_010_000)
            if not args:
                return _Box(14_917_000)
            raise TypeError("unexpected")

    bb = _footprint_pack_bbox(_Fp())
    assert bb.GetWidth() == 3_010_000
    assert _module_pack_cols(6) == 3
    assert _module_pack_cols(1) == 1
