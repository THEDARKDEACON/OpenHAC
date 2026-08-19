from __future__ import annotations

from openhac.compiler.astar_router import astar_grid, choose_grid_cell_iu
from openhac.compiler.autoroute_cli import parse_freerouting_unrouted


def test_parse_freerouting_unrouted():
    line = "Auto-router pass #10 on board 'abc' was completed in 0.79 seconds with the score of 982.58 (4 unrouted)"
    assert parse_freerouting_unrouted(line) == 4
    assert parse_freerouting_unrouted("nope") is None
    assert parse_freerouting_unrouted("score of 893.50 (61 unrouted).") == 61


def test_astar_grid_finds_axis_path():
    w, h = 12, 8
    blocked = [[[False] * w for _ in range(h)] for _ in range(2)]
    for x in range(w):
        blocked[0][0][x] = blocked[0][h - 1][x] = True
        blocked[1][0][x] = blocked[1][h - 1][x] = True
    for y in range(h):
        blocked[0][y][0] = blocked[0][y][w - 1] = True
        blocked[1][y][0] = blocked[1][y][w - 1] = True
    path = astar_grid(blocked, (1, 1, 0), (10, 6, 0))
    assert path is not None
    assert path[0] == (1, 1, 0)
    assert path[-1] == (10, 6, 0)


def test_astar_grid_uses_via_around_wall():
    w, h = 10, 6
    blocked = [[[False] * w for _ in range(h)] for _ in range(2)]
    for y in range(h):
        blocked[0][y][5] = True  # wall on F.Cu
    path = astar_grid(blocked, (1, 2, 0), (8, 2, 0), via_cost=3)
    assert path is not None
    assert any(layer == 1 for _x, _y, layer in path)


def test_choose_grid_cell_iu_coarsens_large_board():
    # 229 mm × 155 mm at 0.2 mm → ~1.1e6 cells × 2 layers, over an 800k cap.
    nm = 1_000_000
    min_cell = int(0.2 * nm)
    cell = choose_grid_cell_iu(229 * nm, 155 * nm, min_cell=min_cell, max_cells=800_000)
    gw = 229 * nm // cell + 2
    gh = 155 * nm // cell + 2
    assert gw * gh * 2 <= 800_000
    assert cell >= min_cell


def test_astar_grid_vias_to_inner_layer():
    """SMD walls on F.Cu must not block In1.Cu — that was the leftover-router miss."""
    w, h, n = 12, 8, 4
    blocked = [[[False] * w for _ in range(h)] for _ in range(n)]
    for ly in range(n):
        for x in range(w):
            blocked[ly][0][x] = blocked[ly][h - 1][x] = True
        for y in range(h):
            blocked[ly][y][0] = blocked[ly][y][w - 1] = True
    for y in range(h):
        blocked[0][y][5] = True  # F.Cu wall; inner layers stay open
    path = astar_grid(blocked, (1, 3, 0), (10, 3, 0), via_cost=3)
    assert path is not None
    assert any(layer >= 1 for _x, _y, layer in path)


def test_freerouting_child_env_sets_stop_pass_no(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHAC_FREEROUTING_MAX_PASSES", "12")
    monkeypatch.delenv("OPENHAC_FREEROUTING_GUI", raising=False)
    from openhac.compiler.autoroute_cli import (
        _freerouting_argv,
        _freerouting_child_env,
        _prepare_freerouting_user_dir,
    )

    dsn = tmp_path / "board.dsn"
    dsn.write_text("dsn\n", encoding="utf-8")
    user = _prepare_freerouting_user_dir(dsn)
    env = _freerouting_child_env(user)
    assert env["FREEROUTING__ROUTER__STOP_PASS_NO"] == "12"
    assert env["FREEROUTING__ROUTER__MAX_PASSES"] == "12"
    assert env["FREEROUTING__ROUTER__OPTIMIZER__ENABLED"] == "false"
    cfg = (user / "freerouting.json").read_text(encoding="utf-8")
    assert '"max_passes": 12' in cfg
    argv = _freerouting_argv("jar", "/opt/fr.jar", dsn, tmp_path / "board.ses")
    assert any(str(a).startswith("--user_data_path=") for a in argv)
    assert "--gui.enabled=false" in argv
    assert env["FREEROUTING__GUI__ENABLED"] == "false"


def test_freerouting_gui_env_enables_window(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHAC_FREEROUTING_GUI", "1")
    monkeypatch.delenv("OPENHAC_FREEROUTING_TIMEOUT_S", raising=False)
    from openhac.compiler.autoroute_cli import (
        _freerouting_argv,
        _freerouting_child_env,
        _freerouting_plateau_passes,
        _freerouting_subprocess_timeout,
        _prepare_freerouting_user_dir,
    )

    dsn = tmp_path / "board.dsn"
    dsn.write_text("dsn\n", encoding="utf-8")
    user = _prepare_freerouting_user_dir(dsn)
    env = _freerouting_child_env(user)
    argv = _freerouting_argv("jar", "/opt/fr.jar", dsn, tmp_path / "board.ses")
    assert "--gui.enabled=true" in argv
    assert env["FREEROUTING__GUI__ENABLED"] == "true"
    cfg = (user / "freerouting.json").read_text(encoding="utf-8")
    import json as _json

    assert _json.loads(cfg)["gui"]["enabled"] is True
    assert _freerouting_subprocess_timeout() is None
    assert _freerouting_plateau_passes() == 0
