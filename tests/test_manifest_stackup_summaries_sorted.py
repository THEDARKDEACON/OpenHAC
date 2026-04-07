from __future__ import annotations


def test_stackup_json_summaries_sorted_by_path(tmp_path):
    from openhac.compiler.compile_manifest import _stackup_json_summaries
    from openhac.core.board import Board

    a = tmp_path / "b.json"
    b = tmp_path / "a.json"
    a.write_text('{"layers": []}', encoding="utf-8")
    b.write_text('{"layers": []}', encoding="utf-8")

    board = Board(size_mm=(10.0, 10.0))
    board.declare_stackup_reference(str(a), role="fab")
    board.declare_stackup_reference(str(b), role="si")

    out = _stackup_json_summaries(board)
    paths = [d["path"] for d in out]
    assert paths == sorted(paths)

