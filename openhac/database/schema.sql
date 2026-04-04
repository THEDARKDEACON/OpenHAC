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
    jlc_class TEXT DEFAULT 'Basic'
);
