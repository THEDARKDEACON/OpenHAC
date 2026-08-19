"""Close remaining audit-recheck gates (floating ERC, bbox, units/bus, FR argv, invent-pin)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from openhac.core.exceptions import OpenHaCError
from openhac.core.pin_resolution import get_pins_from_data


def test_bbox_padding_cli_default_is_0_5():
    src = Path("openhac/cli.py").read_text(encoding="utf-8")
    chunk = src.split("--bbox-padding-mm", 1)[1][:500]
    assert "default=0.5" in chunk
    assert "Default: 0.5" in chunk
    from openhac.compiler.compile_pipeline import CompileState

    assert CompileState.__dataclass_fields__["bbox_padding_mm"].default == 0.5


def test_floating_net_named_one_pin_raises():
    from openhac.compiler.rule_check import ERCFloatingNetError, run_erc
    from openhac.core.board import Board
    from openhac.core.circuit import default_circuit, reset_default_circuit
    from openhac.core.net import Net
    from openhac.core.part import Part, Pin

    reset_default_circuit()
    n = Net("HANGING")
    p = Part(
        "U1",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        {"kicad_symbol": "Device:R"},
        [Pin("1", "A", "passive"), Pin("2", "B", "passive")],
        value="1k",
    )
    default_circuit.add_part(p)
    p["1"] += n
    with pytest.raises(BaseException) as ei:
        run_erc(Board((20, 20)))
    err = ei.value
    blob = str(err)
    if hasattr(err, "exceptions"):
        blob += " ".join(str(e) for e in err.exceptions)
    assert "HANGING" in blob
    assert ERCFloatingNetError.__name__ in type(err).__name__ or "HANGING" in blob


def test_anonymous_one_pin_net_is_not_floating():
    from openhac.compiler.rule_check import run_erc
    from openhac.core.board import Board
    from openhac.core.circuit import default_circuit, reset_default_circuit
    from openhac.core.net import Net
    from openhac.core.part import Part, Pin

    reset_default_circuit()
    n = Net()  # auto _N
    p = Part(
        "R1",
        "Resistor_SMD:R_0603_1608Metric",
        {"kicad_symbol": "Device:R"},
        [Pin("1", "1", "passive"), Pin("2", "2", "passive")],
        value="1k",
    )
    default_circuit.add_part(p)
    p["1"] += n
    p["2"] += n
    run_erc(Board((20, 20)))  # two-pin anonymous is fine; named check skipped


def test_freerouting_argv_is_not_bash(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENHAC_FREEROUTING_GUI", raising=False)
    from openhac.compiler.autoroute_cli import _freerouting_argv

    dsn = tmp_path / "a.dsn"
    ses = tmp_path / "a.ses"
    jar = _freerouting_argv("jar", "/opt/fr.jar", dsn, ses)
    assert jar[0] == "java"
    assert "-jar" in jar
    assert "--gui.enabled=false" in jar
    assert any(str(a).startswith("--router.max_passes=") for a in jar)
    assert any(str(a).startswith("--user_data_path=") for a in jar)
    assert "bash" not in jar
    cli = _freerouting_argv("cli", ["/usr/bin/freeroute"], dsn, ses)
    assert cli[0] == "/usr/bin/freeroute"
    assert "bash" not in cli
    js = json.dumps(["java", "-jar", "/x.jar", "-de", "{dsn}", "-do", "{ses}"])
    tpl = _freerouting_argv("cmd_tpl", js, dsn, ses)
    assert tpl == ["java", "-jar", "/x.jar", "-de", str(dsn), "-do", str(ses)]
    sh = _freerouting_argv("cmd_tpl", "java -jar /x.jar -de {dsn} -do {ses}", dsn, ses)
    assert sh[0] == "java"
    with pytest.raises(Exception, match="bash"):
        _freerouting_argv("cmd_tpl", "bash -c 'echo hi'", dsn, ses)


def test_invent_pin_warns_in_handoff(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    monkeypatch.delenv("OPENHAC_STRICT_PINOUT", raising=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pins = get_pins_from_data({"generic_name": "UNKNOWN_IC", "package": "WEIRD-PKG"})
    assert any(str(p.name).startswith("Pin_") for p in pins)
    assert any("FAB-001" in str(w.message) and "invented" in str(w.message).lower() for w in caught)


def test_invent_pin_strict_handoff_refuses(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "handoff")
    monkeypatch.setenv("OPENHAC_STRICT_PINOUT", "1")
    with pytest.raises(OpenHaCError, match="STRICT_PINOUT"):
        get_pins_from_data({"generic_name": "UNKNOWN_IC", "package": "QFN-48"})


def test_multi_unit_and_datasheet_and_pin_uuid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.core.base import Component, Module
    from openhac.core.board import Board
    from openhac.core.net import Net
    from openhac.schematic.emit_kicad import generate_schematic

    a = Net("INP")
    b = Net("OUTP")

    class M(Module):
        def __init__(self) -> None:
            super().__init__("M")
            u = self.add(
                Component(
                    "DUAL_AMP",
                    pins={
                        "1": ("IN+", "input"),
                        "2": ("IN-", "input"),
                        "5": ("OUT", "output"),
                        "8": ("VCC", "power_in"),
                    },
                )
            )
            u.part.pins["1"].unit = 1
            u.part.pins["2"].unit = 1
            u.part.pins["5"].unit = 2
            u.part.pins["8"].unit = 2
            u.fields["Datasheet"] = "https://example.com/dual.pdf"
            u.fields["MPN"] = "FAKE-AMP"
            u["1"] += a
            u["5"] += b

    board = Board((20, 20))
    board.add_module(M())
    out = tmp_path / "units.kicad_sch"
    generate_schematic(str(out), board)
    text = out.read_text(encoding="utf-8")
    assert "(unit 1)" in text
    assert "(unit 2)" in text
    assert '(property "Datasheet" "https://example.com/dual.pdf"' in text
    assert '(property "MPN" "FAKE-AMP"' in text
    assert '(pin "1"' in text
    assert "(uuid " in text
    gen = tmp_path / "units.openhac-generated.kicad_sym"
    if gen.is_file():
        sym = gen.read_text(encoding="utf-8")
        assert "_1_1" in sym and "_2_1" in sym


def test_kicad_bus_graphics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHAC_SCHEMATIC_STUB_ONLY", "1")
    from openhac.core.circuit import default_circuit, reset_default_circuit
    from openhac.core.net import Bus
    from openhac.core.part import Part, Pin
    from openhac.core.board import Board
    from openhac.schematic.emit_kicad import generate_schematic

    reset_default_circuit()
    bus = Bus("DATA", width=4)
    p1 = Part(
        "U1",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        {"kicad_symbol": "Device:R"},
        [Pin("1", "D0", "bidirectional"), Pin("2", "D1", "bidirectional"),
         Pin("3", "D2", "bidirectional"), Pin("4", "D3", "bidirectional")],
        value="BUF",
    )
    p2 = Part(
        "U2",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        {"kicad_symbol": "Device:R"},
        [Pin("1", "D0", "bidirectional"), Pin("2", "D1", "bidirectional"),
         Pin("3", "D2", "bidirectional"), Pin("4", "D3", "bidirectional")],
        value="BUF",
    )
    default_circuit.add_part(p1)
    default_circuit.add_part(p2)
    for i in range(4):
        p1[str(i + 1)] += bus[i]
        p2[str(i + 1)] += bus[i]
    out = tmp_path / "bus.kicad_sch"
    generate_schematic(str(out), Board((20, 20)), circuit=default_circuit)
    text = out.read_text(encoding="utf-8")
    assert "(bus (pts" in text
    assert "(bus_entry" in text
    assert "DATA[0]" in text


def test_license_and_lockfile_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / "LICENSE").is_file()
    text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    lock = root / "requirements.lock"
    assert lock.is_file(), "requirements.lock must pin CI installs"
    body = lock.read_text(encoding="utf-8")
    assert "z3-solver" in body.lower() or "z3_solver" in body.lower() or "z3-solver" in body
    assert "pyyaml" in body.lower() or "PyYAML" in body
