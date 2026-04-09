from __future__ import annotations

from openhac.compiler.ngspice_runner import parse_ngspice_log


def test_parse_ngspice_log_counts_error_warning_lines() -> None:
    txt = "warning: foo\nERROR: bad\nok\nWarn: bar\n"
    s = parse_ngspice_log(txt)
    assert s["error_line_count"] == 1
    assert s["warning_line_count"] == 2

