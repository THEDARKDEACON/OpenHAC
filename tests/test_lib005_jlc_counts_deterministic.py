from __future__ import annotations


class _Part:
    def __init__(self, cls: str):
        self.fields = {"JLC_Class": cls}


class _Circuit:
    def __init__(self, parts):
        self.parts = parts


def test_jlc_class_line_counts_are_sorted(monkeypatch):
    from openhac.compiler import rule_check

    c = _Circuit([_Part("extended"), _Part("basic"), _Part(""), _Part("basic")])
    monkeypatch.setattr(rule_check, "get_default_circuit", lambda: c, raising=False)
    d = rule_check.jlc_class_line_counts_from_circuit()
    assert list(d.keys()) == sorted(d.keys())

