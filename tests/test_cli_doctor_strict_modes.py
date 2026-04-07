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
        strict_headless=False,
        strict_layout=True,
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
