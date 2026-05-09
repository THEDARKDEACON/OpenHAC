-- OpenHaC component catalog schema (v8)
-- This file reflects the current full schema including all migrations (v1–v8).
-- db_manager.py applies these same columns via idempotent ALTER TABLE migrations
-- for existing databases, so this file and the migrations stay in sync.

CREATE TABLE IF NOT EXISTS components (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Core identity
    generic_name         TEXT NOT NULL UNIQUE,
    kicad_symbol         TEXT NOT NULL,
    kicad_footprint      TEXT NOT NULL,
    manufacturer         TEXT,
    mpn                  TEXT NOT NULL,
    supplier_sku         TEXT,
    description          TEXT,
    category             TEXT,
    attributes_json      TEXT,
    -- v2: Parametric fields
    tolerance            TEXT,
    voltage_rating       REAL,
    power_watts          REAL,
    jlc_class            TEXT DEFAULT 'Basic',
    spice_include        TEXT,
    mouser_sku           TEXT,
    digikey_sku          TEXT,
    -- v3: SIM-001 SPICE subcircuit
    spice_subckt         TEXT,
    -- v6: Pinout storage (SKiDL-native netlist)
    pinout_json          TEXT,   -- JSON array: [{"num": "1", "name": "VIN", "type": "power"}, ...]
    symbol_data          TEXT,   -- KiCad symbol data for schematic generation
    -- v7: Complete component data (Phase 3)
    thermal_json         TEXT,   -- JSON: {"r_theta_ja": 45.0, "max_tj": 125, "max_power": 0.5}
    package_length_mm    REAL,
    package_width_mm     REAL,
    package_height_mm    REAL,
    lead_pitch_mm        REAL,
    lifecycle_status     TEXT,   -- Active | NRND | Obsolete | Preview
    compliance_flags     TEXT,   -- Comma-separated: RoHS,REACH,AEC-Q100,MIL-STD
    lead_time_days       INTEGER,
    moq                  INTEGER,
    alternative_mpns     TEXT,   -- JSON array of equivalent MPNs
    spice_model_path     TEXT,
    ibis_model_path      TEXT,
    manufacturer_info_json TEXT, -- JSON: {"location": "CN", "certs": ["ISO9001"]}
    typical_applications TEXT,   -- Comma-separated reference design names
    datasheet_url        TEXT,
    product_url          TEXT,
    pinout_source        TEXT,   -- digikey | jlcpcb | seed_file | manual
    enriched_at_utc      TEXT,   -- ISO8601
    footprint_verified   INTEGER, -- 1 = verified against local KiCad lib, 0 = unverified
    footprint_resolved   TEXT,   -- normalized Library:Name when auto-resolved
    footprint_notes      TEXT,   -- warnings / ambiguity notes
    -- v8: Vendor enrich persistence
    package              TEXT,   -- vendor package / case code (e.g. SOT-23, 0603)
    stock                INTEGER -- distributor stock level
);

CREATE TABLE IF NOT EXISTS part_alternates (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    primary_generic      TEXT NOT NULL,
    rank                 INTEGER NOT NULL DEFAULT 1,
    alternate_mpn        TEXT,
    alternate_supplier_sku TEXT,
    note                 TEXT,
    alternate_group_id   TEXT,
    UNIQUE(primary_generic, rank)
);

CREATE TABLE IF NOT EXISTS part_offers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_name         TEXT NOT NULL,
    rank                 INTEGER NOT NULL DEFAULT 1,
    supplier             TEXT NOT NULL,
    supplier_sku         TEXT,
    mpn                  TEXT,
    note                 TEXT,
    UNIQUE(generic_name, rank)
);
