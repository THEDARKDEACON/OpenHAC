from __future__ import annotations


def _ns(**kwargs):
    # Keep it simple; argparse.Namespace would also work.
    class _NS:
        pass

    o = _NS()
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


def test_doctor_strict_headless_only_requires_kicad_cli(monkeypatch, capsys):
    from openhac import cli

    def _which(name: str):
        if name == "kicad-cli":
            return None
        if name == "pcbnew":
            return None
        if name == "java":
            return None
        return None

    monkeypatch.setattr(cli.shutil, "which", _which, raising=True)
    monkeypatch.setattr(cli.os.path, "isfile", lambda p: False, raising=True)

    args = _ns(
        db_path=None,
        as_json=True,
        strict=False,
        strict_headless=True,
        strict_layout=False,
        strict_config=False,
        strict_routing=False,
        print_env=False,
    )
    try:
        cli.cmd_doctor(args)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert int(e.code) == 2
    out = capsys.readouterr().out
    assert "kicad-cli" in out


def test_doctor_strict_layout_only_requires_pcbnew(monkeypatch, capsys):
    from openhac import cli

    import importlib

    real_import_module = importlib.import_module

    def _which(name: str):
        if name == "kicad-cli":
            return None
        if name == "pcbnew":
            return None
        if name == "java":
            return None
        return None

    monkeypatch.setattr(cli.shutil, "which", _which, raising=True)
    monkeypatch.setattr(cli.os.path, "isfile", lambda p: False, raising=True)
    # Simulate pcbnew import failure.
    def _imp(name: str):
        if name == "pcbnew":
            raise ImportError("no pcbnew")
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", _imp, raising=True)

    args = _ns(
        db_path=None,
        as_json=True,
        strict=False,
        strict_headless=False,
        strict_layout=True,
        strict_config=False,
        strict_routing=False,
        print_env=False,
    )
    try:
        cli.cmd_doctor(args)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert int(e.code) == 2
    out = capsys.readouterr().out
    # strict-layout should complain about pcbnew, but not require kicad-cli
    assert "pcbnew" in out


def test_doctor_strict_config_only_requires_config(monkeypatch, capsys):
    from openhac import cli

    # Tools present, but config absent.
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}", raising=True)
    monkeypatch.setattr(cli.os.path, "isfile", lambda p: False, raising=True)
    monkeypatch.delenv("KICAD8_SYMBOL_DIR", raising=False)
    monkeypatch.delenv("KICAD8_FOOTPRINT_DIR", raising=False)
    monkeypatch.delenv("OPENHAC_KICAD_SYMBOL_DIRS", raising=False)

    args = _ns(
        db_path=None,
        as_json=True,
        strict=False,
        strict_headless=False,
        strict_layout=False,
        strict_config=True,
        strict_routing=False,
        print_env=False,
    )
    try:
        cli.cmd_doctor(args)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert int(e.code) == 2
    out = capsys.readouterr().out
    assert "sym-lib-table-or-KICAD*_SYMBOL_DIR" in out or "sym-lib-table" in out


def test_doctor_strict_routing_requires_java_and_jar(monkeypatch, capsys):
    from openhac import cli

    monkeypatch.setattr(cli.shutil, "which", lambda name: None, raising=True)
    monkeypatch.setenv("FREEROUTING_JAR", "/nope/freerouting.jar")
    monkeypatch.setattr(cli.os.path, "isfile", lambda p: False, raising=True)

    args = _ns(
        db_path=None,
        as_json=True,
        strict=False,
        strict_headless=False,
        strict_layout=False,
        strict_config=False,
        strict_routing=True,
        print_env=False,
    )
    try:
        cli.cmd_doctor(args)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert int(e.code) == 2
    out = capsys.readouterr().out
    assert "java" in out
    assert "freerouting_jar_exists" in out or "FREEROUTING_JAR" in out


def test_doctor_candidate_lists_are_sorted_and_deduped(monkeypatch):
    from openhac import cli
    import json
    import contextlib
    import io

    # Make sure we get deterministic candidate lists even if cwd/config paths overlap.
    monkeypatch.setattr(cli.os, "getcwd", lambda: "/tmp", raising=True)
    monkeypatch.setattr(cli.os.path, "isfile", lambda p: False, raising=True)
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/bin/x", raising=True)

    args = _ns(
        db_path=None,
        as_json=True,
        strict=False,
        strict_headless=False,
        strict_layout=False,
        print_env=False,
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_doctor(args)
    data = json.loads(buf.getvalue())
    fp = data.get("fp_lib_table_candidates") or []
    sym = data.get("sym_lib_table_candidates") or []
    assert fp == sorted(fp)
    assert sym == sorted(sym)
    assert len(fp) == len(set(fp))
    assert len(sym) == len(set(sym))
