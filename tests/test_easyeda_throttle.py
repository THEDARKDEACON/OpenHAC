"""EasyEDA CAD throttle and 403 circuit breaker (no vendor API keys)."""

from __future__ import annotations

import urllib.error
from io import BytesIO

import pytest

from openhac.database.easyeda_integration import (
    generate_footprint_from_lcsc,
    reset_easyeda_client_state,
    _sleep_for_interval,
    _THROTTLE,
)


@pytest.fixture(autouse=True)
def _reset_easyeda():
    reset_easyeda_client_state()
    yield
    reset_easyeda_client_state()


def test_sleep_for_interval_skips_first_then_waits(monkeypatch):
    monkeypatch.setenv("OPENHAC_EASYEDA_MIN_INTERVAL_S", "1.0")
    slept: list[float] = []
    monkeypatch.setattr(
        "openhac.database.easyeda_integration.time.sleep",
        lambda s: slept.append(s),
    )
    ticks = iter([10.0, 10.2, 11.2])
    monkeypatch.setattr(
        "openhac.database.easyeda_integration.time.monotonic",
        lambda: next(ticks),
    )
    _sleep_for_interval()
    assert slept == []
    _sleep_for_interval()
    assert slept and slept[0] == pytest.approx(0.8)


def test_no_network_skips_easyeda(monkeypatch):
    monkeypatch.setenv("OPENHAC_NO_NETWORK", "1")
    assert generate_footprint_from_lcsc("C7171") == (None, None)


def test_circuit_opens_after_repeated_403(monkeypatch):
    monkeypatch.setenv("OPENHAC_EASYEDA_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("OPENHAC_EASYEDA_MAX_CONSECUTIVE_FAILS", "2")

    class Api:
        def get_cad_data_of_component(self, lcsc_id):
            urllib.request.urlopen("https://easyeda.com/api/products/%s/components" % lcsc_id)
            return {}

    monkeypatch.setattr(
        "openhac.database.easyeda_integration._easyeda_backends",
        lambda: (Api, None, None, None, None),
    )

    def boom(*_a, **_k):
        raise urllib.error.HTTPError(
            "https://easyeda.com/api/products/C1/components",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr("urllib.request.urlopen", boom)

    assert generate_footprint_from_lcsc("C111") == (None, None)
    assert generate_footprint_from_lcsc("C222") == (None, None)
    assert _THROTTLE["open"] is True
    calls = {"n": 0}

    def should_not_run(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("EasyEDA must not be called after the circuit opens")

    monkeypatch.setattr("urllib.request.urlopen", should_not_run)
    assert generate_footprint_from_lcsc("C333") == (None, None)
    assert calls["n"] == 0
