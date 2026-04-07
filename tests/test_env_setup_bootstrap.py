from __future__ import annotations


def test_bootstrap_environment_sets_default_symbol_and_footprint_env(monkeypatch, tmp_path):
    from openhac.core import env_setup

    sym = tmp_path / "symbols"
    fp = tmp_path / "footprints"
    sym.mkdir()
    fp.mkdir()

    # Force resolver to pick our symbol path without relying on OS paths.
    monkeypatch.setenv("KICAD8_SYMBOL_DIR", str(sym))
    monkeypatch.delenv("OPENHAC_KICAD_SYMBOL_DIRS", raising=False)
    monkeypatch.delenv("KICAD9_FOOTPRINT_DIR", raising=False)
    monkeypatch.delenv("KICAD8_FOOTPRINT_DIR", raising=False)
    monkeypatch.delenv("KICAD_FOOTPRINT_DIR", raising=False)

    # Pretend a common footprint path exists by intercepting os.path.isdir.
    real_isdir = env_setup.os.path.isdir

    def _isdir(p: str) -> bool:
        if p == "/usr/share/kicad/footprints":
            return True
        return real_isdir(p)

    monkeypatch.setattr(env_setup.os.path, "isdir", _isdir, raising=True)

    env_setup._bootstrapped = False
    env_setup.bootstrap_environment()

    assert (env_setup.os.environ.get("KICAD8_SYMBOL_DIR") or "").endswith("symbols")
    assert env_setup.os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS") is not None
    assert env_setup.os.environ.get("KICAD8_FOOTPRINT_DIR") == "/usr/share/kicad/footprints"

