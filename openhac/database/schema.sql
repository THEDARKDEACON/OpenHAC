CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_name TEXT NOT NULL UNIQUE,
    kicad_symbol TEXT NOT NULL,
    kicad_footprint TEXT NOT NULL,
    manufacturer TEXT,
    mpn TEXT NOT NULL,
    supplier_sku TEXT,
    description TEXT,
    category TEXT,
    attributes_json TEXT,
    tolerance TEXT,
    voltage_rating REAL,
    power_watts REAL,
    jlc_class TEXT DEFAULT 'Basic',
    spice_include TEXT,
    spice_subckt TEXT,
    mouser_sku TEXT,
    digikey_sku TEXT
);

CREATE TABLE IF NOT EXISTS part_alternates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    primary_generic TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 1,
    alternate_mpn TEXT,
    alternate_supplier_sku TEXT,
    note TEXT,
    alternate_group_id TEXT,
    UNIQUE(primary_generic, rank)
);

CREATE TABLE IF NOT EXISTS part_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_name TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 1,
    supplier TEXT NOT NULL,
    supplier_sku TEXT,
    mpn TEXT,
    note TEXT,
    UNIQUE(generic_name, rank)
);
