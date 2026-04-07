from __future__ import annotations


class _Part:
    def __init__(self, lab: str):
        self.fields = {"OpenHaC_JIT_Confidence": lab}


class _Circuit:
    def __init__(self, parts):
        self.parts = parts


def test_jit_confidence_histogram_is_sorted(monkeypatch):
    from openhac.compiler import compile_manifest

    c = _Circuit([_Part("low"), _Part("high"), _Part("medium"), _Part("")])
    monkeypatch.setattr(compile_manifest, "get_default_circuit", lambda: c, raising=False)

    # Call private helper directly; it must be stable for manifest determinism.
    h = compile_manifest._jit_confidence_histogram_from_circuit()
    assert list(h.keys()) == sorted(h.keys())

