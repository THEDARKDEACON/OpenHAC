from __future__ import annotations


class _Net:
    def __init__(self, name: str):
        self.name = name


class _Pin:
    def __init__(self, net):
        self.net = net


class _Part:
    def __init__(self, ref: str, include: str | None = None):
        self.ref = ref
        self.ref_prefix = "R"
        self.value = "10k"
        self.name = "R"
        self.fields = {}
        if include:
            self.fields["Spice_Include"] = include
        self.pins = [_Pin(_Net("N1")), _Pin(_Net("GND"))]


class _Circuit:
    def __init__(self, parts):
        self.parts = parts


def test_spice_is_stable_across_part_insertion_order(tmp_path, monkeypatch):
    from openhac.compiler import spice_gen

    out1 = tmp_path / "a.cir"
    out2 = tmp_path / "b.cir"

    c1 = _Circuit([_Part("R10", include="a.lib"), _Part("R2", include="b.lib"), _Part("R1", include="a.lib")])
    c2 = _Circuit([_Part("R1", include="a.lib"), _Part("R2", include="b.lib"), _Part("R10", include="a.lib")])

    monkeypatch.setattr(spice_gen, "get_default_circuit", lambda: c1, raising=False)
    spice_gen.generate_spice(str(out1), analysis_lines=[".op"])

    monkeypatch.setattr(spice_gen, "get_default_circuit", lambda: c2, raising=False)
    spice_gen.generate_spice(str(out2), analysis_lines=[".op"])

    assert out1.read_bytes() == out2.read_bytes()

