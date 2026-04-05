"""Tests for the JIT API Fallback Engine."""

import pytest
from unittest.mock import patch, MagicMock
import json

from openhac.database.api_fallback import (
    fetch_and_map_part,
    OfflineCompilationError,
    _resolve_footprint,
    _infer_category,
    _build_search_query,
)
from openhac.database.lookup_meta import LOOKUP_CONFIDENCE_KEY, CONFIDENCE_HIGH, CONFIDENCE_LOW


class TestFootprintResolution:

    def test_resistor_0805(self):
        assert _resolve_footprint("resistors", "0805") == "Resistor_SMD:R_0805_2012Metric"

    def test_capacitor_0603(self):
        assert _resolve_footprint("capacitors", "0603") == "Capacitor_SMD:C_0603_1608Metric"

    def test_sot223(self):
        assert _resolve_footprint("voltage_regulators", "SOT-223") == "Package_TO_SOT_SMD:SOT-223-3_TabPin2"

    def test_unknown_falls_back_to_generic(self):
        fp = _resolve_footprint("resistors", "3216")
        # Unknown package falls back to generic Package_TO_SOT_SMD
        assert "3216" in fp

    def test_empty_package_fallback(self):
        fp = _resolve_footprint("resistors", "")
        assert fp == "Package_TO_SOT_SMD:SOT-23"


class TestCategoryInference:

    def test_resistor_from_value(self):
        assert _infer_category({"value": "10k"}) == "resistors"

    def test_capacitor_from_value(self):
        assert _infer_category({"value": "100nF"}) == "capacitors"

    def test_voltage_regulator_from_vout(self):
        assert _infer_category({"v_out": 3.3}) == "voltage_regulators"

    def test_connector_from_type(self):
        assert _infer_category({"connector_type": "XT60"}) == "connectors"

    def test_explicit_category(self):
        assert _infer_category({"category": "mosfets"}) == "mosfets"


class TestSearchQueryBuilder:

    def test_value_and_package(self):
        q = _build_search_query({"value": "10k", "package": "0805"})
        assert "10k" in q
        assert "0805" in q

    def test_mpn(self):
        q = _build_search_query({"mpn": "AMS1117-3.3"})
        assert "AMS1117-3.3" in q

    def test_empty_returns_empty(self):
        assert _build_search_query({}) == ""


class TestFetchAndMapPart:

    @patch("openhac.database.api_fallback.urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        """Mock a successful API response."""
        api_response = {
            "components": [{
                "lcsc": 12345,
                "mfr": "RC0805FR-0710KL",
                "package": "0805",
                "description": "10k 1% 0805 Resistor",
                "manufacturer": "Yageo",
                "stock": 50000,
            }]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_and_map_part({"category": "resistors", "value": "10k", "package": "0805"})

        assert result is not None
        assert result["supplier_sku"] == "C12345"
        assert result["kicad_footprint"] == "Resistor_SMD:R_0805_2012Metric"
        assert result["kicad_symbol"] == "Device:R"
        assert result[LOOKUP_CONFIDENCE_KEY] == CONFIDENCE_HIGH

    @patch("openhac.database.api_fallback.urllib.request.urlopen")
    def test_unrelated_first_hit_is_low_confidence(self, mock_urlopen):
        """No query token overlap with mfr/description → first item is weak match (LIB-003)."""
        api_response = {
            "components": [{
                "lcsc": 999,
                "mfr": "OTHERPART",
                "package": "0805",
                "description": "mystery widget",
                "manufacturer": "Acme",
                "stock": 10,
            }]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_and_map_part({"category": "resistors", "value": "ZZZONLY", "package": "0805"})
        assert result is not None
        assert result[LOOKUP_CONFIDENCE_KEY] == CONFIDENCE_LOW

    @patch("openhac.database.api_fallback.urllib.request.urlopen")
    def test_timeout_raises_offline_error(self, mock_urlopen):
        """Network timeout should raise OfflineCompilationError."""
        mock_urlopen.side_effect = TimeoutError("timed out")
        with pytest.raises(OfflineCompilationError, match="Cannot reach"):
            fetch_and_map_part({"category": "resistors", "value": "10k"})

    @patch("openhac.database.api_fallback.urllib.request.urlopen")
    def test_empty_results_returns_none(self, mock_urlopen):
        """Empty API response should return None."""
        api_response = {"components": []}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_response).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_and_map_part({"category": "resistors", "value": "99999ohm"})
        assert result is None

    def test_empty_query_returns_none(self):
        """No query params should return None without hitting API."""
        assert fetch_and_map_part({}) is None


class TestJITHook:
    """Test the parametric_search → JIT API hook integration."""

    @patch("openhac.database.api_fallback.fetch_and_map_part")
    def test_jit_hook_caches_result(self, mock_fetch, tmp_path):
        """When local search fails, JIT fetches and caches."""
        from openhac.database.db_manager import DatabaseManager
        db = DatabaseManager(db_path=str(tmp_path / "jit.db"))

        # Mock the API response
        mock_fetch.return_value = {
            "generic_name": "R_4k7_0603",
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603_1608Metric",
            "manufacturer": "Yageo",
            "mpn": "RC0603FR-074K7L",
            "supplier_sku": "C25900",
            "description": "4.7k 1% 0603 Resistor",
            "category": "resistors",
            "jlc_class": "Basic",
            LOOKUP_CONFIDENCE_KEY: CONFIDENCE_HIGH,
        }

        # First call: JIT kicks in
        result, fallback = db.parametric_search("resistors", value="4k7", package="0603")
        assert result is not None
        assert result["generic_name"] == "R_4k7_0603"
        assert fallback is True
        mock_fetch.assert_called_once()

        # Second call: cached, no API hit
        mock_fetch.reset_mock()
        result2, fallback2 = db.parametric_search("resistors", value="4k7", package="0603")
        assert result2 is not None
        mock_fetch.assert_not_called()
