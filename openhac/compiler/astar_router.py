"""Grid A* leftover router for nets FreeRouting did not finish.

Connects isolated pad islands on the board copper layers with axis-aligned
tracks and vias. SMD pads block only their copper layer so a via can run
under a part. This is a cleanup maze router, not a replacement for FreeRouting.
"""

from __future__ import annotations

import heapq
import logging
import os

logger = logging.getLogger("openhac.astar_router")


def astar_grid(
    blocked: list[list[list[bool]]],
    start: tuple[int, int, int],
    goal: tuple[int, int, int],
    *,
    via_cost: int = 12,
    max_exp: int = 400_000,
) -> list[tuple[int, int, int]] | None:
    """4-connected A* on ``blocked[layer][y][x]``. Coordinates are grid cells."""
    if not blocked:
        return None
    n_layers = len(blocked)
    h = len(blocked[0])
    w = len(blocked[0][0]) if h else 0
    sx, sy, sl = start
    gx, gy, gl = goal
    if not (0 <= sx < w and 0 <= sy < h and 0 <= sl < n_layers):
        return None
    if not (0 <= gx < w and 0 <= gy < h and 0 <= gl < n_layers):
        return None
    if blocked[sl][sy][sx] or blocked[gl][gy][gx]:
        return None

    def heur(x: int, y: int, layer: int) -> int:
        return abs(x - gx) + abs(y - gy) + (0 if layer == gl else via_cost)

    openh: list[tuple[int, int, int, int, int]] = []
    seq = 0
    heapq.heappush(openh, (heur(sx, sy, sl), seq, sx, sy, sl))
    came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {(sx, sy, sl): None}
    gscore = {(sx, sy, sl): 0}
    expansions = 0
    deltas = ((1, 0), (-1, 0), (0, 1), (0, -1))

    while openh and expansions < max_exp:
        _f, _s, x, y, layer = heapq.heappop(openh)
        expansions += 1
        if (x, y, layer) == (gx, gy, gl):
            path: list[tuple[int, int, int]] = []
            cur: tuple[int, int, int] | None = (x, y, layer)
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            path.reverse()
            return path
        g0 = gscore[(x, y, layer)]
        for dx, dy in deltas:
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            if blocked[layer][ny][nx]:
                continue
            ng = g0 + 1
            key = (nx, ny, layer)
            if ng < gscore.get(key, 10**9):
                gscore[key] = ng
                came[key] = (x, y, layer)
                seq += 1
                heapq.heappush(openh, (ng + heur(nx, ny, layer), seq, nx, ny, layer))
        if n_layers > 1:
            for nl in range(n_layers):
                if nl == layer:
                    continue
                if not blocked[nl][y][x]:
                    ng = g0 + via_cost
                    key = (x, y, nl)
                    if ng < gscore.get(key, 10**9):
                        gscore[key] = ng
                        came[key] = (x, y, layer)
                        seq += 1
                        heapq.heappush(openh, (ng + heur(x, y, nl), seq, x, y, nl))
    return None


def _truthy(name: str, default: bool = True) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _to_vec(pcbnew_mod, x: int, y: int):
    try:
        return pcbnew_mod.VECTOR2I(int(x), int(y))
    except Exception:
        return pcbnew_mod.wxPoint(int(x), int(y))


def _pad_xy(pad) -> tuple[int, int]:
    p = pad.GetPosition()
    return int(p.x), int(p.y)


def _union_find(n: int) -> tuple[list[int], callable, callable]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    return parent, find, union


def _net_pads(pcb, net_code: int) -> list:
    pads = []
    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        fps = list(pcb.Footprints())
    for fp in fps:
        for pad in fp.Pads():
            try:
                if int(pad.GetNetCode()) == int(net_code):
                    pads.append(pad)
            except Exception:
                continue
    return pads


def _copper_layer_ids(pcb) -> list[int]:
    names = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
    ids: list[int] = []
    for name in names:
        try:
            lid = int(pcb.GetLayerID(name))
        except Exception:
            continue
        if lid >= 0:
            ids.append(lid)
    if len(ids) >= 2:
        return ids
    try:
        return [int(pcb.GetLayerID("F.Cu")), int(pcb.GetLayerID("B.Cu"))]
    except Exception:
        return []


def _pad_layer_indices(pad, layer_ids: list[int]) -> list[int]:
    """Layers this pad occupies. SMD → front (or back) only; PTH → all copper."""
    hit: list[int] = []
    for i, lid in enumerate(layer_ids):
        try:
            if pad.IsOnLayer(lid):
                hit.append(i)
        except Exception:
            continue
    if hit:
        return hit
    return list(range(len(layer_ids)))


def _pad_start_layer(pad, layer_ids: list[int]) -> int:
    idxs = _pad_layer_indices(pad, layer_ids)
    return int(idxs[0]) if idxs else 0


def _fill_rect(blocked: list[list[list[bool]]], layer: int, x0: int, y0: int, x1: int, y1: int) -> None:
    h = len(blocked[0])
    w = len(blocked[0][0])
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    xa = max(0, xa)
    ya = max(0, ya)
    xb = min(w - 1, xb)
    yb = min(h - 1, yb)
    row = blocked[layer]
    for y in range(ya, yb + 1):
        line = row[y]
        for x in range(xa, xb + 1):
            line[x] = True


def _cell(ox: int, oy: int, cell: int, x_iu: int, y_iu: int) -> tuple[int, int]:
    return (int(x_iu - ox) // cell, int(y_iu - oy) // cell)


def choose_grid_cell_iu(
    width_iu: int,
    height_iu: int,
    *,
    min_cell: int,
    max_cells: int,
    layers: int = 2,
) -> int:
    """Grow cell size until ``gw * gh * layers`` fits in *max_cells*."""
    width_iu = max(1, int(width_iu))
    height_iu = max(1, int(height_iu))
    cell = max(1, int(min_cell))
    max_cells = max(256, int(max_cells))
    layers = max(1, int(layers))
    for _ in range(24):
        gw = max(2, width_iu // cell + 2)
        gh = max(2, height_iu // cell + 2)
        if gw * gh * layers <= max_cells:
            return cell
        cell = max(cell + 1, int(cell * 1.4))
    return cell


def _env_float_local(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def route_leftover_nets(pcb_path: str, *, pcbnew_mod=None) -> int:
    """Route remaining pad islands. Returns number of track/via items added."""
    if not _truthy("OPENHAC_ASTAR_LEFTOVER", default=False):
        return 0
    if pcbnew_mod is None:
        try:
            import pcbnew as pcbnew_mod  # type: ignore
        except Exception as e:
            logger.debug("A* leftover: pcbnew unavailable: %s", e)
            return 0

    pcb = pcbnew_mod.LoadBoard(str(pcb_path))
    try:
        bb = pcb.GetBoardEdgesBoundingBox()
        board_l, board_t = int(bb.GetLeft()), int(bb.GetTop())
        board_r, board_b = int(bb.GetRight()), int(bb.GetBottom())
        bw, bh = abs(int(bb.GetWidth())), abs(int(bb.GetHeight()))
    except Exception:
        logger.warning("A* leftover: no Edge.Cuts bbox")
        return 0
    if bw <= 0 or bh <= 0:
        return 0

    min_cell = max(int(pcbnew_mod.FromMM(_env_float_local("OPENHAC_ASTAR_GRID_MM", 0.2))), int(pcbnew_mod.FromMM(0.1)))
    max_cells = _env_int_local("OPENHAC_ASTAR_MAX_CELLS", 800_000)
    margin_iu = int(pcbnew_mod.FromMM(_env_float_local("OPENHAC_ASTAR_WINDOW_MM", 25.0)))

    try:
        ds = pcb.GetDesignSettings()
        track_w = int(ds.GetCurrentTrackWidth())
        clearance = int(ds.GetSmallestClearanceValue()) if hasattr(ds, "GetSmallestClearanceValue") else int(
            pcbnew_mod.FromMM(0.15)
        )
        via_dia = int(ds.GetCurrentViaSize()) if hasattr(ds, "GetCurrentViaSize") else int(pcbnew_mod.FromMM(0.8))
    except Exception:
        track_w = int(pcbnew_mod.FromMM(0.2))
        clearance = int(pcbnew_mod.FromMM(0.15))
        via_dia = int(pcbnew_mod.FromMM(0.8))
    inflate = max(clearance + track_w // 2, int(pcbnew_mod.FromMM(0.15)))

    layer_ids = _copper_layer_ids(pcb)
    if len(layer_ids) < 2:
        logger.warning("A* leftover: need F.Cu and B.Cu")
        return 0
    n_layers = len(layer_ids)
    layer_index = {int(lid): i for i, lid in enumerate(layer_ids)}

    def raster_window(ox: int, oy: int, gw: int, gh: int, cell: int, skip_net: int) -> list[list[list[bool]]]:
        blocked = [[[False] * gw for _ in range(gh)] for _ in range(n_layers)]
        for ly in range(n_layers):
            for x in range(gw):
                blocked[ly][0][x] = True
                blocked[ly][gh - 1][x] = True
            for y in range(gh):
                blocked[ly][y][0] = True
                blocked[ly][y][gw - 1] = True
        for fp in pcb.GetFootprints():
            for pad in fp.Pads():
                try:
                    if int(pad.GetNetCode()) == int(skip_net):
                        continue
                    pbb = pad.GetBoundingBox()
                    x0, y0 = _cell(ox, oy, cell, int(pbb.GetLeft()) - inflate, int(pbb.GetTop()) - inflate)
                    x1, y1 = _cell(ox, oy, cell, int(pbb.GetRight()) + inflate, int(pbb.GetBottom()) + inflate)
                    for ly in _pad_layer_indices(pad, layer_ids):
                        _fill_rect(blocked, ly, x0, y0, x1, y1)
                except Exception:
                    continue
        for tr in pcb.GetTracks():
            try:
                cls = tr.__class__.__name__.upper()
                netc = int(tr.GetNetCode())
                if netc == int(skip_net):
                    continue
                if "VIA" in cls:
                    pos = tr.GetPosition()
                    r = max(via_dia // 2 + inflate, inflate)
                    x0, y0 = _cell(ox, oy, cell, int(pos.x) - r, int(pos.y) - r)
                    x1, y1 = _cell(ox, oy, cell, int(pos.x) + r, int(pos.y) + r)
                    for ly in range(n_layers):
                        _fill_rect(blocked, ly, x0, y0, x1, y1)
                    continue
                a, b = tr.GetStart(), tr.GetEnd()
                half = max(int(tr.GetWidth()) // 2 + inflate, inflate)
                x0, y0 = _cell(ox, oy, cell, min(int(a.x), int(b.x)) - half, min(int(a.y), int(b.y)) - half)
                x1, y1 = _cell(ox, oy, cell, max(int(a.x), int(b.x)) + half, max(int(a.y), int(b.y)) + half)
                ly = layer_index.get(int(tr.GetLayer()), 0)
                _fill_rect(blocked, ly, x0, y0, x1, y1)
            except Exception:
                continue
        return blocked

    added = 0
    max_paths = _env_int_local("OPENHAC_ASTAR_MAX_PATHS", 1500)
    try:
        nets = pcb.GetNetsByName()
        net_items = list(nets.items()) if hasattr(nets, "items") else [(n, nets[n]) for n in nets]
    except Exception:
        logger.warning("A* leftover: cannot iterate nets")
        return 0

    try:
        from openhac.compiler.placement_engine import is_power_or_nc_net
    except Exception:
        is_power_or_nc_net = lambda _n: False  # noqa: E731

    skip_names = {"", "unconnected", "__noconnect"}
    for name, ni in net_items:
        if added >= max_paths:
            break
        nname = str(name or "")
        if nname.lower() in skip_names or is_power_or_nc_net(nname):
            continue
        try:
            code = int(ni.GetNetCode())
        except Exception:
            continue
        if code <= 0:
            continue
        pads = _net_pads(pcb, code)
        if len(pads) < 2:
            continue
        pts = [_pad_xy(p) for p in pads]
        _, find, union = _union_find(len(pts))
        same_tracks = []
        try:
            for tr in pcb.GetTracks():
                if int(tr.GetNetCode()) != code:
                    continue
                if "VIA" in tr.__class__.__name__.upper():
                    pos = tr.GetPosition()
                    same_tracks.append((int(pos.x), int(pos.y)))
                else:
                    a, b = tr.GetStart(), tr.GetEnd()
                    same_tracks.append((int(a.x), int(a.y)))
                    same_tracks.append((int(b.x), int(b.y)))
        except Exception:
            same_tracks = []
        join_r2 = (int(pcbnew_mod.FromMM(0.6))) ** 2
        for i, (px, py) in enumerate(pts):
            for tx, ty in same_tracks:
                if (px - tx) ** 2 + (py - ty) ** 2 <= join_r2:
                    for j, (qx, qy) in enumerate(pts):
                        if i >= j:
                            continue
                        if (qx - tx) ** 2 + (qy - ty) ** 2 <= join_r2:
                            union(i, j)
        roots = {find(i) for i in range(len(pts))}
        if len(roots) <= 1:
            continue

        reps = {}
        for i in range(len(pts)):
            reps.setdefault(find(i), []).append(i)
        keys = list(reps.keys())
        home = keys[0]
        for other in keys[1:]:
            if added >= max_paths:
                break
            best: tuple[int, int] | None = None
            best_d = 10**18
            for i in reps[home]:
                for j in reps[other]:
                    d = abs(pts[i][0] - pts[j][0]) + abs(pts[i][1] - pts[j][1])
                    if d < best_d:
                        best_d = d
                        best = (i, j)
            if best is None:
                continue
            i, j = best
            ax, ay = pts[i]
            bx, by = pts[j]
            ox = max(board_l, min(ax, bx) - margin_iu)
            oy = max(board_t, min(ay, by) - margin_iu)
            wx = min(board_r, max(ax, bx) + margin_iu) - ox
            wy = min(board_b, max(ay, by) + margin_iu) - oy
            if wx <= 0 or wy <= 0:
                continue
            cell = choose_grid_cell_iu(
                wx, wy, min_cell=min_cell, max_cells=max_cells, layers=n_layers
            )
            gw = max(4, wx // cell + 2)
            gh = max(4, wy // cell + 2)
            blocked = raster_window(ox, oy, gw, gh, cell, code)
            s = _cell(ox, oy, cell, ax, ay)
            g = _cell(ox, oy, cell, bx, by)
            sl = _pad_start_layer(pads[i], layer_ids)
            gl = _pad_start_layer(pads[j], layer_ids)
            start = (
                max(1, min(gw - 2, s[0])),
                max(1, min(gh - 2, s[1])),
                max(0, min(n_layers - 1, sl)),
            )
            goal = (
                max(1, min(gw - 2, g[0])),
                max(1, min(gh - 2, g[1])),
                max(0, min(n_layers - 1, gl)),
            )
            blocked[start[2]][start[1]][start[0]] = False
            blocked[goal[2]][goal[1]][goal[0]] = False
            path = astar_grid(blocked, start, goal, via_cost=14)
            if not path:
                logger.info("A* leftover: no path for net %s (%s islands)", nname, len(keys))
                continue
            n_add = _emit_path(pcb, pcbnew_mod, path, ox, oy, cell, layer_ids, code, track_w, via_dia)
            added += n_add
            union(i, j)
            for idx in reps[other]:
                union(idx, reps[home][0])
            logger.info("A* leftover: routed island on net %s (+%s items)", nname, n_add)

    if added:
        try:
            conn = pcb.GetConnectivity()
            if hasattr(conn, "RecalculateRatsnest"):
                conn.RecalculateRatsnest()
        except Exception:
            pass
        pcbnew_mod.SaveBoard(str(pcb_path), pcb)
        logger.info("A* leftover: saved %s with %s new items", pcb_path, added)
    return added


def _env_int_local(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(float(raw))
    except ValueError:
        return int(default)


def _emit_path(
    pcb,
    pcbnew_mod,
    path: list[tuple[int, int, int]],
    ox: int,
    oy: int,
    cell: int,
    layer_ids: list,
    net_code: int,
    track_w: int,
    via_dia: int,
) -> int:
    """Turn grid path into PCB_TRACK / PCB_VIA items. Returns count added."""
    if len(path) < 2:
        return 0
    added = 0

    def iu(cx: int, cy: int) -> tuple[int, int]:
        return ox + cx * cell + cell // 2, oy + cy * cell + cell // 2

    i = 0
    while i < len(path) - 1:
        x0, y0, l0 = path[i]
        x1, y1, l1 = path[i + 1]
        if l0 != l1:
            via = pcbnew_mod.PCB_VIA(pcb)
            via.SetNetCode(int(net_code))
            vx, vy = iu(x0, y0)
            via.SetPosition(_to_vec(pcbnew_mod, vx, vy))
            try:
                via.SetWidth(int(via_dia))
            except Exception:
                pass
            pcb.Add(via)
            added += 1
            i += 1
            continue
        j = i + 1
        dx = x1 - x0
        dy = y1 - y0
        while j + 1 < len(path) and path[j + 1][2] == l0:
            nx, ny, nl = path[j + 1]
            if nl != l0:
                break
            if dx == 0 and nx == x0:
                j += 1
                continue
            if dy == 0 and ny == y0:
                j += 1
                continue
            break
        ax, ay = iu(path[i][0], path[i][1])
        bx, by = iu(path[j][0], path[j][1])
        tr = pcbnew_mod.PCB_TRACK(pcb)
        tr.SetNetCode(int(net_code))
        tr.SetWidth(int(track_w))
        tr.SetLayer(layer_ids[l0] if l0 < len(layer_ids) else layer_ids[0])
        tr.SetStart(_to_vec(pcbnew_mod, ax, ay))
        tr.SetEnd(_to_vec(pcbnew_mod, bx, by))
        pcb.Add(tr)
        added += 1
        i = j
    return added
