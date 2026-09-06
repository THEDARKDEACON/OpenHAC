"""LIVE-008: localhost SVG viewer of KiCad's own export (not a symbol renderer).

Serves ``kicad-cli sch export svg`` / optional PCB SVG on 127.0.0.1 and polls
mtime so ``openhac preview --watch`` refreshes without eeschema Reload.
Never runs ``kicad-cli sch erc``.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import os
import shutil
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openhac.core.exceptions import KiCadCliNotFoundError

logger = logging.getLogger("openhac.svg_preview")

_PCB_LAYERS = "F.Cu,F.SilkS,F.Fab,Edge.Cuts"


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def want_preview_browser(*, no_browser: bool = False) -> bool:
    """False when ``--no-browser`` or ``OPENHAC_PREVIEW_NO_BROWSER`` is set."""
    if no_browser:
        return False
    return not _truthy("OPENHAC_PREVIEW_NO_BROWSER")


def open_preview_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception as e:
        logger.warning("Could not open a browser for %s: %s", url, e)
        return False


def file_mtime_ns(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


def preview_index_html(title: str) -> str:
    """Inline viewer page. No CDN. Polls ``/meta.json`` and cache-busts the SVG."""
    safe = html_lib.escape(title or "board")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OpenHaC preview — {safe}</title>
  <style>
    html, body {{ margin: 0; height: 100%; background: #111; color: #ddd;
      font-family: ui-sans-serif, system-ui, sans-serif; }}
    #bar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      padding: 8px 12px; font-size: 13px; background: #1c1c1c; border-bottom: 1px solid #333; }}
    #bar button {{ background: #2a2a2a; color: #ddd; border: 1px solid #444;
      padding: 4px 10px; cursor: pointer; }}
    #bar button.on {{ border-color: #888; background: #333; }}
    #note {{ opacity: 0.75; }}
    #stage {{ height: calc(100% - 42px); overflow: auto; background: #fff; }}
    #stage img {{ display: block; width: 100%; height: auto; }}
  </style>
</head>
<body>
  <div id="bar">
    <strong>OpenHaC preview</strong>
    <span>not ERC-stamped</span>
    <button type="button" id="btn-sch" class="on">Schematic</button>
    <button type="button" id="btn-pcb" hidden>PCB</button>
    <span id="status">waiting</span>
    <span id="note">Save the .py to refresh. Pose is this sheet (same .kicad_sch). Nudge in KiCad, then Save there.</span>
  </div>
  <div id="stage"><img id="pic" alt="preview sheet" src="/sheet.svg"/></div>
  <script>
    const pic = document.getElementById("pic");
    const status = document.getElementById("status");
    const btnSch = document.getElementById("btn-sch");
    const btnPcb = document.getElementById("btn-pcb");
    let which = "sch";
    let lastSch = 0;
    let lastPcb = 0;
    function srcFor(meta) {{
      if (which === "pcb" && meta.has_pcb) {{
        return "/pcb.svg?t=" + meta.pcb_mtime_ns;
      }}
      return "/sheet.svg?t=" + meta.sch_mtime_ns;
    }}
    function apply(meta) {{
      btnPcb.hidden = !meta.has_pcb;
      const t = (which === "pcb" && meta.has_pcb) ? meta.pcb_mtime_ns : meta.sch_mtime_ns;
      const prev = (which === "pcb") ? lastPcb : lastSch;
      if (t && t !== prev) {{
        pic.src = srcFor(meta);
        status.textContent = "updated " + new Date().toLocaleTimeString();
      }}
      lastSch = meta.sch_mtime_ns || lastSch;
      lastPcb = meta.pcb_mtime_ns || lastPcb;
    }}
    async function tick() {{
      try {{
        const r = await fetch("/meta.json", {{ cache: "no-store" }});
        apply(await r.json());
      }} catch (e) {{
        status.textContent = "viewer waiting…";
      }}
    }}
    btnSch.addEventListener("click", () => {{
      which = "sch"; btnSch.classList.add("on"); btnPcb.classList.remove("on"); tick();
    }});
    btnPcb.addEventListener("click", () => {{
      which = "pcb"; btnPcb.classList.add("on"); btnSch.classList.remove("on"); tick();
    }});
    setInterval(tick, 400);
    tick();
  </script>
</body>
</html>
"""


def export_pcb_preview_svg(
    pcb_path: str | os.PathLike[str],
    dest: str | os.PathLike[str],
) -> Path:
    """Place-only board picture via ``kicad-cli pcb export svg`` (not ERC)."""
    pcb = Path(pcb_path)
    if not pcb.is_file():
        raise FileNotFoundError(f"pcb not found: {pcb}")
    kicad_cli = shutil.which("kicad-cli")
    if not kicad_cli:
        raise KiCadCliNotFoundError(
            "kicad-cli not found on PATH. Install KiCad to export preview SVG."
        )
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        kicad_cli,
        "pcb",
        "export",
        "svg",
        "--mode-single",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
        "--page-size-mode",
        "2",
        "--layers",
        _PCB_LAYERS,
        "--output",
        str(out),
        str(pcb),
    ]
    logger.info("LIVE-008 preview PCB SVG (not ERC): %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        detail = ((r.stderr or "") + (r.stdout or "")).strip()[:800]
        raise RuntimeError(f"kicad-cli pcb export svg failed (rc={r.returncode}): {detail}")
    if not out.is_file():
        raise RuntimeError(f"kicad-cli pcb export svg produced no file at {out}")
    return out


class _PreviewHandler(BaseHTTPRequestHandler):
    server: Any  # _PreviewHttpd

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug("%s - " + fmt, self.address_string(), *args)

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_path(self, path: Path | None, content_type: str) -> None:
        if path is None or not path.is_file():
            self.send_error(404, "not found")
            return
        data = path.read_bytes()
        self._send(200, content_type, data)

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        state: SvgPreviewServer = self.server.preview
        if route in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", preview_index_html(state.title).encode("utf-8"))
            return
        if route == "/meta.json":
            payload = {
                "title": state.title,
                "has_pcb": bool(state.pcb_svg and state.pcb_svg.is_file()),
                "sch_mtime_ns": file_mtime_ns(state.sch_svg),
                "pcb_mtime_ns": file_mtime_ns(state.pcb_svg),
            }
            self._send(200, "application/json", json.dumps(payload).encode("utf-8"))
            return
        if route == "/sheet.svg":
            self._send_path(state.sch_svg, "image/svg+xml")
            return
        if route == "/pcb.svg":
            self._send_path(state.pcb_svg, "image/svg+xml")
            return
        self.send_error(404, "not found")


class _PreviewHttpd(ThreadingHTTPServer):
    preview: SvgPreviewServer


class SvgPreviewServer:
    """Loopback HTTP server for the latest schematic (and optional PCB) SVG."""

    def __init__(self, *, title: str) -> None:
        self.title = title or "board"
        self.sch_svg: Path | None = None
        self.pcb_svg: Path | None = None
        self._httpd: _PreviewHttpd | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def update(self, *, sch_svg: Path | None = None, pcb_svg: Path | None = None) -> None:
        if sch_svg is not None:
            self.sch_svg = Path(sch_svg)
        if pcb_svg is not None:
            self.pcb_svg = Path(pcb_svg)

    def start(self) -> str:
        if self._httpd is not None:
            return self.url
        httpd = _PreviewHttpd(("127.0.0.1", 0), _PreviewHandler)
        httpd.preview = self
        self._httpd = httpd
        host, port = httpd.server_address[:2]
        self.url = f"http://{host}:{port}/"
        t = threading.Thread(target=httpd.serve_forever, name="openhac-svg-preview", daemon=True)
        self._thread = t
        t.start()
        logger.info("LIVE-008 SVG viewer at %s", self.url)
        return self.url

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        self._httpd = None
        httpd.shutdown()
        httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.url = ""
