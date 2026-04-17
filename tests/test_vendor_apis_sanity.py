from __future__ import annotations

import base64

from openhac.database.vendor_apis import (
    DigiKeyAPI,
    JLCPCBAPI,
    PartInfo,
    _mouser_search_results_parts,
    _tme_calculate_signature,
    _tme_response_product_list,
)


def test_digikey_parse_product_rohs_status_mapping():
    api = DigiKeyAPI(client_id="x", client_secret="y")
    product = {
        "manufacturer_part_number": "ABC123",
        "manufacturer": {"name": "ACME"},
        "digi_key_part_number": "ACME-ABC123",
        "product_description": "desc",
        "quantity_available": 5,
        "product_url": "https://example.invalid/p",
        "rohs_status": "RoHS Compliant",
        "lead_free": True,
        "category": {"name": "IC"},
        "package_type": {"name": "QFN"},
    }
    info = api._parse_product(product)
    assert isinstance(info, PartInfo)
    assert info.rohs is True


def test_mouser_search_results_parts_accepts_null_search_results():
    assert _mouser_search_results_parts({"SearchResults": None}) == []
    assert _mouser_search_results_parts({"SearchResults": {"Parts": [{"x": 1}]}}) == [{"x": 1}]
    assert _mouser_search_results_parts({}) == []


def test_digikey_api_base_sandbox_env(monkeypatch):
    monkeypatch.setenv("DIGIKEY_USE_SANDBOX", "1")
    monkeypatch.delenv("DIGIKEY_API_BASE", raising=False)
    dk = DigiKeyAPI(client_id="x", client_secret="y")
    assert dk.api_base == "https://sandbox-api.digikey.com"


def test_tme_signature_is_base64_hmac():
    sig = _tme_calculate_signature(
        "POST",
        "https://api.tme.eu/v1/Products/Search.json",
        [("SearchPlain", "STM32"), ("Token", "tok")],
        "mysecret",
    )
    raw = base64.b64decode(sig, validate=True)
    assert len(raw) == 20  # SHA1 digest


def test_tme_response_product_list_null_data():
    assert _tme_response_product_list({"Data": None}) == []
    assert _tme_response_product_list({"Data": {"ProductList": [{"Symbol": "x"}]}}) == [{"Symbol": "x"}]


def test_jlc_parse_smt_list_item_maps_lcsc_fields():
    api = JLCPCBAPI(api_key=None)
    row = {
        "componentCode": "C17513",
        "componentModelEn": "0805W8F1001T5E",
        "componentBrandEn": "UNI-ROYAL",
        "componentTypeEn": "Chip Resistor - Surface Mount",
        "erpComponentName": "1k",
        "stockCount": 100,
        "componentSpecificationEn": "0805",
        "componentPrices": [{"startNumber": 1, "endNumber": 99, "productPrice": 0.01}],
        "dataManualUrl": "https://example.invalid/ds.pdf",
        "lcscGoodsUrl": "https://www.lcsc.com/product-detail/x_C17513.html",
    }
    info = api._parse_smt_list_item(row)
    assert info.supplier_sku == "C17513"
    assert info.mpn == "0805W8F1001T5E"
    assert info.manufacturer == "UNI-ROYAL"
    assert info.stock == 100
    assert info.package == "0805"
    assert info.price_breaks and info.price_breaks[0]["quantity"] == 1


def test_jlc_parse_jlcsearch_item_maps_lcsc_and_stock():
    api = JLCPCBAPI(api_key=None)
    item = {
        "lcsc": 17513,
        "mfr": "RC0805FR-0710KL",
        "package": "0805",
        "description": "10k",
        "stock": 1000,
        "price": '[{"qFrom": 1, "qTo": null, "price": 0.01}]',
        "category": "Resistors",
    }
    info = api._parse_jlcsearch_item(item)
    assert info.supplier_sku == "C17513"
    assert info.stock == 1000
    assert info.mpn == "RC0805FR-0710KL"
    assert len(info.price_breaks) >= 1
