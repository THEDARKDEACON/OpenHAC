from __future__ import annotations


class _Part:
    def __init__(self, ref: str):
        self.ref = ref
        self.value = "10k"
        self.fields = {}
        self.footprint = "Resistor_SMD:R_0805_2012Metric"


class _Circuit:
    def __init__(self, parts):
        self.parts = parts


def test_bom_csv_is_stable_across_part_insertion_order(tmp_path, monkeypatch):
    from openhac.compiler import netlist_gen

    # Avoid SKiDL netlist emission; we only care about BOM stability here.
    monkeypatch.setattr(netlist_gen, "generate_netlist", lambda file_: None, raising=True)

    out1 = tmp_path / "a.csv"
    out2 = tmp_path / "b.csv"

    c1 = _Circuit([_Part("U2"), _Part("R10"), _Part("R2"), _Part("U10"), _Part("R1")])
    c2 = _Circuit([_Part("R1"), _Part("U10"), _Part("R2"), _Part("R10"), _Part("U2")])

    monkeypatch.setattr(netlist_gen, "get_default_circuit", lambda: c1, raising=True)
    netlist_gen.generate_logic_and_bom(str(tmp_path / "a.net"), bom_path=str(out1))

    monkeypatch.setattr(netlist_gen, "get_default_circuit", lambda: c2, raising=True)
    netlist_gen.generate_logic_and_bom(str(tmp_path / "b.net"), bom_path=str(out2))

    assert out1.read_bytes() == out2.read_bytes()

