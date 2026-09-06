"""LIVE-008: localhost SVG viewer of KiCad export (no ERC, no symbol renderer)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from openhac.compiler.kicad_sch_svg import find_exported_svg
from openhac.compiler.svg_preview import (
    SvgPreviewServer,
    file_mtime_ns,
    preview_index_html,
    want_preview_browser,
)


def test_find_exported_svg_prefers_stem(tmp_path: Path):
    (tmp_path / "other.svg").write_text("<svg/>", encoding="utf-8")
    wanted = tmp_path / "demo.svg"
    wanted.write_text("<svg id='demo'/>", encoding="utf-8")
    assert find_exported_svg(tmp_path, "demo") == wanted


def test_want_preview_browser_env(monkeypatch):
    monkeypatch.delenv("OPENHAC_PREVIEW_NO_BROWSER", raising=False)
    assert want_preview_browser(no_browser=False) is True
    assert want_preview_browser(no_browser=True) is False
    monkeypatch.setenv("OPENHAC_PREVIEW_NO_BROWSER", "1")
    assert want_preview_browser(no_browser=False) is False


def test_preview_html_is_self_contained():
    page = preview_index_html('board"x')
    assert "ERC-stamped" in page
    assert "/meta.json" in page
    assert "/sheet.svg" in page
    assert "<script src=" not in page
    assert "board&quot;x" in page


def test_svg_preview_server_serves_sheet(tmp_path: Path):
    sch = tmp_path / "sheet.svg"
    sch.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>', encoding="utf-8")
    pcb = tmp_path / "board.svg"
    pcb.write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>', encoding="utf-8")
    srv = SvgPreviewServer(title="demo")
    srv.update(sch_svg=sch, pcb_svg=pcb)
    url = srv.start()
    try:
        html = urlopen(url, timeout=3).read().decode("utf-8")
        assert "not ERC-stamped" in html
        sheet = urlopen(url + "sheet.svg", timeout=3).read()
        assert b"<svg" in sheet
        meta = json.loads(urlopen(url + "meta.json", timeout=3).read())
        assert meta["has_pcb"] is True
        assert meta["sch_mtime_ns"] == file_mtime_ns(sch)
        t0 = meta["sch_mtime_ns"]
        sch.write_text(sch.read_text(encoding="utf-8") + " ", encoding="utf-8")
        meta2 = json.loads(urlopen(url + "meta.json", timeout=3).read())
        assert meta2["sch_mtime_ns"] != t0
        pcb_body = urlopen(url + "pcb.svg", timeout=3).read()
        assert b"circle" in pcb_body
        try:
            urlopen(url + "nope", timeout=3)
            raise AssertionError("expected 404")
        except HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_svg_preview_never_runs_erc():
    from openhac.compiler import svg_preview

    src = Path(svg_preview.__file__).read_text(encoding="utf-8")
    assert 'kicad_cli, "sch", "erc"' not in src
    assert '"pcb"' in src and "export" in src and "svg" in src
