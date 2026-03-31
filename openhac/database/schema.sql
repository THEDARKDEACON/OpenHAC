CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generic_name TEXT NOT NULL,
    kicad_symbol TEXT NOT NULL,
    kicad_footprint TEXT NOT NULL,
    manufacturer TEXT,
    mpn TEXT NOT NULL,
    supplier_sku TEXT,
    description TEXT
);
