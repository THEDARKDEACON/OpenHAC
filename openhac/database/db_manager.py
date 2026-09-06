import logging
import sqlite3
import os
import warnings

logger = logging.getLogger("openhac.db")

_default_db = os.path.join(os.path.dirname(__file__), "openhac.db")
# Packaged catalog. Live ``OPENHAC_DB_PATH`` is read in :func:`resolve_db_path` (CODE-002).
DB_PATH = os.path.abspath(_default_db)
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def resolve_db_path(db_path=None) -> str:
    """Catalog file for this process: explicit path, then env, then packaged DB."""
    if db_path is not None and str(db_path).strip():
        return os.path.abspath(os.path.expanduser(str(db_path)))
    env = (os.environ.get("OPENHAC_DB_PATH") or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.abspath(os.path.expanduser(str(DB_PATH)))

# Columns added in schema v2 (Phase 2 — Parametric Abstraction)
_V2_COLUMNS = {
    "tolerance": "TEXT",
    "voltage_rating": "REAL",
    "power_watts": "REAL",
    "jlc_class": "TEXT DEFAULT 'Basic'",
    "spice_include": "TEXT",
    "mouser_sku": "TEXT",
    "digikey_sku": "TEXT",
}

_V3_COLUMNS = {
    "spice_subckt": "TEXT",
}

# Columns added in schema v6 (Pinout storage for SKiDL removal)
_V6_COLUMNS = {
    "pinout_json": "TEXT",  # JSON array of pin objects: [{"num": "1", "name": "VIN", "type": "power"}, ...]
    "symbol_data": "TEXT",  # KiCad symbol data for schematic generation
}

# Columns added in schema v7 (Complete component data - Phase 3)
_V7_COLUMNS = {
    # Thermal characteristics
    "thermal_json": "TEXT",  # JSON: {"r_theta_ja": 45.0, "max_tj": 125, "max_power": 0.5}
    # Package dimensions (mm)
    "package_length_mm": "REAL",
    "package_width_mm": "REAL",
    "package_height_mm": "REAL",
    "lead_pitch_mm": "REAL",
    # Lifecycle and compliance
    "lifecycle_status": "TEXT",  # Active, NRND, Obsolete, Preview
    "compliance_flags": "TEXT",  # Comma-separated: RoHS,REACH,AEC-Q100,MIL-STD
    # Supply chain
    "lead_time_days": "INTEGER",
    "moq": "INTEGER",  # Minimum order quantity
    # Alternative parts
    "alternative_mpns": "TEXT",  # JSON array of equivalent MPNs
    # Simulation models
    "spice_model_path": "TEXT",
    "ibis_model_path": "TEXT",
    # Manufacturer info
    "manufacturer_info_json": "TEXT",  # JSON: {"location": "CN", "certs": ["ISO9001"]}
    # Application info
    "typical_applications": "TEXT",  # Comma-separated reference design names
    # Documentation links
    "datasheet_url": "TEXT",
    "product_url": "TEXT",
    # Provenance / audit
    "pinout_source": "TEXT",  # e.g. digikey|jlcpcb|seed_file|manual
    "enriched_at_utc": "TEXT",  # ISO8601
    # Footprint verification / resolution (KiCad install-specific)
    "footprint_verified": "INTEGER",  # 1/0
    "footprint_resolved": "TEXT",  # normalized Library:Name when auto-resolved
    "footprint_notes": "TEXT",  # warnings / ambiguity notes
}

# Columns added in schema v8 (vendor enrich persistence)
_V8_COLUMNS = {
    "package": "TEXT",  # vendor package / case code (e.g. SOT-23, 0603)
    "stock": "INTEGER",  # distributor stock level when APIs expose it
}
# Columns added in schema v9 (3D Model Automation)
_V9_COLUMNS = {
    "model_3d_url": "TEXT",  # Remote URL (e.g. EasyEDA UUID or direct link)
    "model_3d_local": "TEXT", # Local filesystem path
}

# Catalog depth + 3D provenance (CAT-009 / 3D-001)
_V11_COLUMNS = {
    "catalog_tier": "TEXT",  # verified | warehouse
    "model_3d_sha256": "TEXT",
    "model_3d_license": "TEXT",
    "model_3d_source": "TEXT",  # kicad_lib | easyeda | overlay | manufacturer
}

_MANAGER_BY_PATH: dict[str, "DatabaseManager"] = {}


def reset_database_managers() -> None:
    """Close cached catalog connections (tests / db-path switches)."""
    for mgr in list(_MANAGER_BY_PATH.values()):
        cx = getattr(mgr, "_cx", None)
        if cx is not None:
            try:
                cx.close()
            except Exception:
                pass
            mgr._cx = None
        mgr._ready = False
    _MANAGER_BY_PATH.clear()


def get_database_manager(db_path: str | None = None) -> "DatabaseManager":
    """Process-wide DatabaseManager for *db_path* (PERF-002)."""
    return DatabaseManager(db_path=db_path)


def _norm_param_token(v: str | None) -> str:
    return str(v or "").strip().lower().replace(" ", "")


def _split_generic_value_package(generic_name: str) -> tuple[str, str]:
    parts = [p for p in str(generic_name or "").split("_") if p]
    if len(parts) >= 3:
        return _norm_param_token("_".join(parts[1:-1])), _norm_param_token(parts[-1])
    if len(parts) == 2:
        return _norm_param_token(parts[1]), ""
    return "", ""



def _normalize_sensor_category_for_db(
    category: str,
    *,
    mpn: str | None = None,
    generic_name: str | None = None,
) -> str:
    """Map motion/sensor catalog labels to ``ic`` for consistent refdes (U*) and metadata."""
    gn_u = str(generic_name or "").strip().upper()
    mpn_u = str(mpn or "").strip().upper()
    if gn_u == "CAN_TJA1051" or "TJA1051" in mpn_u:
        return "ic"
    if gn_u.startswith("XTAL_"):
        return "crystals"
    cl = str(category or "").strip().lower()
    if any(m in cl for m in ("accelerometer", "gyroscope", "barometer", "magnetometer")):
        return "ic"
    return str(category or "").strip()


class DatabaseManager:
    def __new__(cls, db_path=None):
        path = resolve_db_path(db_path)
        inst = _MANAGER_BY_PATH.get(path)
        if inst is not None and getattr(inst, "_ready", False):
            return inst
        if inst is None:
            inst = super().__new__(cls)
            _MANAGER_BY_PATH[path] = inst
        return inst

    def __init__(self, db_path=None):
        if getattr(self, "_ready", False):
            return
        self.db_path = resolve_db_path(db_path)
        self._cx = None
        self._init_db()
        self._ready = True

    def _connect(self):
        if self._cx is None:
            self._cx = sqlite3.connect(self.db_path, check_same_thread=False)
            self._cx.row_factory = sqlite3.Row
            try:
                self._cx.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
        return self._cx

    class _Tx:
        def __init__(self, mgr: "DatabaseManager"):
            self.mgr = mgr

        def __enter__(self):
            return self.mgr._connect()

        def __exit__(self, et, ev, tb):
            cx = self.mgr._cx
            if cx is None:
                return False
            if et is None:
                cx.commit()
            else:
                try:
                    cx.rollback()
                except sqlite3.Error:
                    pass
            return False

    def _tx(self):
        return DatabaseManager._Tx(self)

    def _init_db(self):
        """Create database, apply schema, and run migrations."""
        conn = self._connect()
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        self._migrate_v2(conn)
        self._migrate_v3(conn)
        self._migrate_v4(conn)
        self._migrate_v5_part_alternates_group(conn)
        self._migrate_v6_pinout(conn)
        self._migrate_v7_complete_data(conn)
        self._migrate_v8_vendor_enrich_fields(conn)
        self._migrate_v9_3d_models(conn)
        self._migrate_v10_indexes_and_dedupe(conn)
        self._migrate_v11_catalog_depth(conn)
        conn.commit()

    @staticmethod
    def _migrate_v2(conn):
        """Add parametric columns to an existing components table (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V2_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v3(conn):
        """Add SIM-001 columns (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V3_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v9_3d_models(conn):
        """Add 3D model columns (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V9_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v11_catalog_depth(conn):
        """CAT-009 / 3D-001: catalog_tier + 3D provenance (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V11_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v10_indexes_and_dedupe(conn):
        """PERF-001/003: indexes, catalog dedupe, value_norm backfill."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(components)").fetchall()}
        if not existing:
            return
        if "value_norm" not in existing:
            try:
                conn.execute("ALTER TABLE components ADD COLUMN value_norm TEXT")
                existing.add("value_norm")
            except sqlite3.OperationalError:
                pass
        pkg_expr = "COALESCE(package,'')" if "package" in existing else "''"
        vn_expr = "COALESCE(value_norm,'')" if "value_norm" in existing else "''"
        pin_expr = "length(COALESCE(pinout_json,''))" if "pinout_json" in existing else "0"
        rows = conn.execute(
            f"SELECT id, generic_name, {pkg_expr}, {vn_expr}, {pin_expr} FROM components"
        ).fetchall()
        best: dict[str, tuple[int, int]] = {}
        for row in rows:
            cid, gn, pkg, vn, pin_len = (
                int(row[0]),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                int(row[4] or 0),
            )
            prev = best.get(gn)
            if prev is None or pin_len > prev[1] or (pin_len == prev[1] and cid > prev[0]):
                best[gn] = (cid, pin_len)
            if not vn or not pkg:
                val, pkg_g = _split_generic_value_package(gn)
                updates = []
                params: list = []
                if not vn and val and "value_norm" in existing:
                    updates.append("value_norm=?")
                    params.append(val)
                if not pkg and pkg_g and "package" in existing:
                    updates.append("package=?")
                    params.append(pkg_g)
                if updates:
                    params.append(cid)
                    conn.execute(f"UPDATE components SET {', '.join(updates)} WHERE id=?", params)
        keep = {v[0] for v in best.values()}
        if keep and len(keep) < len(rows):
            dead = [int(r[0]) for r in rows if int(r[0]) not in keep]
            for i in range(0, len(dead), 400):
                chunk = dead[i : i + 400]
                q = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM components WHERE id IN ({q})", chunk)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(components)").fetchall()}
        index_sql = []
        if "generic_name" in existing:
            index_sql.append(
                "CREATE INDEX IF NOT EXISTS idx_components_generic_name ON components(generic_name)"
            )
        if "category" in existing:
            index_sql.append(
                "CREATE INDEX IF NOT EXISTS idx_components_category ON components(category)"
            )
        if "supplier_sku" in existing:
            index_sql.append(
                "CREATE INDEX IF NOT EXISTS idx_components_supplier_sku ON components(supplier_sku)"
            )
        if "mpn" in existing:
            index_sql.append("CREATE INDEX IF NOT EXISTS idx_components_mpn ON components(mpn)")
        if "value_norm" in existing and "package" in existing:
            index_sql.append(
                "CREATE INDEX IF NOT EXISTS idx_components_value_pkg ON components(value_norm, package)"
            )
        for sql in index_sql:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        if "generic_name" in existing:
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_components_generic_name_unique ON components(generic_name)"
                )
            except sqlite3.Error:
                pass

    @staticmethod
    def _migrate_v4(conn):
        """LIB-001: ``part_offers`` for ranked distributor rows (idempotent)."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS part_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generic_name TEXT NOT NULL,
                rank INTEGER NOT NULL DEFAULT 1,
                supplier TEXT NOT NULL,
                supplier_sku TEXT,
                mpn TEXT,
                note TEXT,
                UNIQUE(generic_name, rank)
            )
            """
        )

    @staticmethod
    def _migrate_v5_part_alternates_group(conn):
        """LIB-002: optional ``alternate_group_id`` on ``part_alternates`` (idempotent)."""
        cur = conn.execute("PRAGMA table_info(part_alternates)")
        existing = {row[1] for row in cur.fetchall()}
        if "alternate_group_id" not in existing:
            conn.execute("ALTER TABLE part_alternates ADD COLUMN alternate_group_id TEXT")

    @staticmethod
    def _migrate_v6_pinout(conn):
        """SKiDL-001: Add pinout and symbol data columns for native netlist generation (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V6_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v7_complete_data(conn):
        """DATA-001: Add thermal, dimensions, lifecycle, compliance, and supply chain data (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V7_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _migrate_v8_vendor_enrich_fields(conn):
        """Add package/stock used by ``update_component_from_vendor`` (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V8_COLUMNS.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE components ADD COLUMN {col_name} {col_def}")

    def get_component(self, generic_name: str) -> dict:
        """Fetches a component by its generic name."""
        from openhac.database.catalog_fixups import merge_catalog_fixup

        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Prefer rows with pinout/symbol data when duplicates exist (bad sync/INSERT OR IGNORE).
            cursor.execute(
                """
                SELECT * FROM components WHERE generic_name = ?
                ORDER BY length(COALESCE(pinout_json, '')) DESC,
                         length(COALESCE(symbol_data, '')) DESC,
                         id DESC
                LIMIT 1
                """,
                (generic_name,),
            )
            row = cursor.fetchone()
            if row:
                from openhac.database.catalog_coverage import stamp_spice_registry_on_row

                return stamp_spice_registry_on_row(merge_catalog_fixup(dict(row)))
            return None

    @staticmethod
    def catalog_grade(row: dict | None) -> str:
        """CAT-001 completeness grade: ``compile_ready`` or ``warehouse``."""
        from openhac.database.catalog_coverage import catalog_grade as _grade

        return _grade(row)

    def get_component_by_supplier_sku(self, supplier_sku: str) -> dict | None:
        """Fetch a component by its supplier SKU (e.g. LCSC Cxxxxx)."""
        if not supplier_sku:
            return None
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM components WHERE supplier_sku = ?", (supplier_sku,))
            row = cur.fetchone()
            return dict(row) if row else None

    def insert_component(self, component_data: dict, ignore_duplicate: bool = False):
        """Inserts a component into the database.

        Args:
            component_data: dict of column -> value.
            ignore_duplicate: if True, use INSERT OR IGNORE.

        Returns:
            lastrowid on insert, or None if the row was ignored.
        """
        from openhac.database.lookup_meta import strip_openhac_internal_fields

        component_data = strip_openhac_internal_fields(dict(component_data))
        if not component_data.get("value_norm"):
            val, pkg_g = _split_generic_value_package(str(component_data.get("generic_name") or ""))
            if val:
                component_data["value_norm"] = val
            if pkg_g and not component_data.get("package"):
                component_data["package"] = pkg_g
        with self._tx() as conn:
            cursor = conn.cursor()
            columns = ', '.join(component_data.keys())
            placeholders = ', '.join('?' * len(component_data))
            values = tuple(component_data.values())
            verb = "INSERT OR IGNORE" if ignore_duplicate else "INSERT"
            cursor.execute(
                f"{verb} INTO components ({columns}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            return cursor.lastrowid if cursor.rowcount > 0 else None

    def update_component_fields(self, generic_name: str, updates: dict) -> bool:
        """Update arbitrary component columns for an existing row (best-effort).

        Returns True if an UPDATE was executed with at least one field.
        """
        if not generic_name:
            return False
        updates = dict(updates or {})
        updates.pop("generic_name", None)
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [generic_name]
        with self._tx() as conn:
            conn.execute(f"UPDATE components SET {set_clause} WHERE generic_name = ?", params)
            conn.commit()
        return True

    @staticmethod
    def _jit_db_write_is_strict() -> bool:
        v = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
        if v == "fabrication":
            return True
        strict = (os.environ.get("OPENHAC_STRICT_DB_WRITES") or "").strip().lower()
        if strict in ("1", "true", "yes", "on"):
            return True
        return False

    class DatabaseWriteError(RuntimeError):
        pass

    def safe_insert_component(
        self,
        component_data: dict,
        *,
        ignore_duplicate: bool = True,
        strict: bool | None = None,
        warn_prefix: str = "DB insert failed",
    ) -> bool:
        """Insert a component with unified strict vs warn semantics.

        - strict=True: raise DatabaseWriteError on failure
        - strict=False: emit UserWarning on failure and return False
        - strict=None: choose based on env (fabrication => strict)
        """
        import warnings as _w

        strict_eff = self._jit_db_write_is_strict() if strict is None else bool(strict)
        try:
            self.insert_component(component_data, ignore_duplicate=ignore_duplicate)
            return True
        except Exception as exc:
            if strict_eff:
                raise self.DatabaseWriteError(f"{warn_prefix}: {exc}") from exc
            _w.warn(f"{warn_prefix}: {exc}", UserWarning, stacklevel=2)
            return False

    def list_part_alternates(self, primary_generic: str) -> list[dict]:
        """Return ranked alternate offers for a primary ``generic_name`` (LIB-002)."""
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT rank, alternate_mpn, alternate_supplier_sku, note, alternate_group_id "
                "FROM part_alternates WHERE primary_generic = ? ORDER BY rank ASC",
                (primary_generic,),
            )
            return [dict(row) for row in cur.fetchall()]

    def list_part_offers(self, generic_name: str) -> list[dict]:
        """Return ranked distributor offers for a ``generic_name`` (LIB-001)."""
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT rank, supplier, supplier_sku, mpn, note FROM part_offers "
                "WHERE generic_name = ? ORDER BY rank ASC",
                (generic_name,),
            )
            return [dict(row) for row in cur.fetchall()]

    def insert_part_offer(self, data: dict, ignore_duplicate: bool = False) -> int | None:
        """Insert one offer row; *data* must include ``generic_name``, ``supplier``, and ``rank``."""
        row = dict(data)
        with self._tx() as conn:
            cursor = conn.cursor()
            columns = ", ".join(row.keys())
            placeholders = ", ".join("?" * len(row))
            values = tuple(row.values())
            verb = "INSERT OR IGNORE" if ignore_duplicate else "INSERT"
            cursor.execute(
                f"{verb} INTO part_offers ({columns}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            return cursor.lastrowid if cursor.rowcount > 0 else None

    def insert_part_alternate(self, data: dict, ignore_duplicate: bool = False) -> int | None:
        """Insert one alternate row; *data* must include ``primary_generic`` and ``rank``."""
        row = dict(data)
        with self._tx() as conn:
            cursor = conn.cursor()
            columns = ", ".join(row.keys())
            placeholders = ", ".join("?" * len(row))
            values = tuple(row.values())
            verb = "INSERT OR IGNORE" if ignore_duplicate else "INSERT"
            cursor.execute(
                f"{verb} INTO part_alternates ({columns}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            return cursor.lastrowid if cursor.rowcount > 0 else None

    def search_components(self, query: str = None, category: str = None, limit: int = 50) -> list[dict]:
        """Search components by generic_name or description substring."""
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            conditions = []
            params: list = []

            if query:
                conditions.append("(generic_name LIKE ? OR description LIKE ?)")
                like = f"%{query}%"
                params.extend([like, like])

            if category:
                conditions.append("category = ?")
                params.append(category)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            cursor.execute(
                f"SELECT * FROM components {where} LIMIT ?",
                params,
            )
            return [dict(row) for row in cursor.fetchall()]

    def audit_data_integrity(self, generic_names: list[str]) -> list[str]:
        """Audit existing database records for a list of components.
        
        Checks for:
        1. Missing local 3D model files (if a path is set).
        2. 'Poisoned' footprints (e.g. complex modules mapped to generic resistors).
        3. Missing critical pinout metadata.
        
        Returns:
            List of generic_names that failed the audit and should be re-enriched.
        """
        failed = []
        for gn in generic_names:
            row = self.get_component(gn)
            if not row:
                continue
            
            # Check 1: 3D Model Existence
            m3d = row.get("model_3d_local")
            if m3d and not os.path.isfile(m3d):
                logger.warning("Audit: 3D model for %s missing on disk: %s", gn, m3d)
                failed.append(gn)
                continue
            
            # Check 2: Footprint Sanity (Heuristic)
            fp = str(row.get("kicad_footprint") or "").lower()
            cat = str(row.get("category") or "").lower()
            
            # If a Pi/Teensy/Module is mapped to a tiny resistor, it's poisoned
            poison_keywords = ["raspberry", "teensy", "compute", "module", "esp32", "stm32"]
            if any(k in gn.lower() for k in poison_keywords) or cat in ("ic", "module"):
                if "0805" in fp or "0603" in fp or "0402" in fp or "resistor" in fp:
                    logger.warning("Audit: Component %s has suspicious footprint: %s", gn, fp)
                    failed.append(gn)
                    continue
            
            # Check 3: Pinout coverage if strictly required
            if not row.get("pinout_json") and cat in ("ic", "module", "connector"):
                # Basic connectors might be okay, but complex ones need pinouts
                pass 

        return list(set(failed))

    def update_component_from_vendor(self, generic_name: str, part_info) -> bool:
        """Update component with enriched data from vendor APIs.
        
        Args:
            generic_name: The component's generic_name in the database
            part_info: PartInfo object from vendor APIs containing V7 data
            
        Returns:
            True if update successful, False otherwise
        """
        import json
        
        updates = {}

        # Core docs / links
        if getattr(part_info, "datasheet_url", None):
            updates["datasheet_url"] = part_info.datasheet_url
        if getattr(part_info, "product_url", None):
            updates["product_url"] = part_info.product_url

        # Refresh basic descriptive fields when present (helps docs + BOM quality).
        if getattr(part_info, "manufacturer", None):
            updates["manufacturer"] = part_info.manufacturer
        if getattr(part_info, "mpn", None):
            updates["mpn"] = part_info.mpn
        if getattr(part_info, "supplier_sku", None):
            updates["supplier_sku"] = part_info.supplier_sku
        if getattr(part_info, "description", None):
            updates["description"] = part_info.description
        if getattr(part_info, "category", None):
            updates["category"] = _normalize_sensor_category_for_db(
                str(part_info.category),
                mpn=getattr(part_info, "mpn", None),
                generic_name=generic_name,
            )
        if getattr(part_info, "package", None):
            updates["package"] = part_info.package
        if getattr(part_info, "stock", None) is not None:
            try:
                updates["stock"] = int(part_info.stock)
            except Exception:
                pass
        
        # Pinout (CAT-004: never persist numeric-only IC / MCU / regulator tables)
        if part_info.pinout:
            from openhac.database.pin_policy import should_store_vendor_pinout

            cat = str(
                getattr(part_info, "category", None)
                or updates.get("category")
                or ""
            )
            if should_store_vendor_pinout(
                part_info.pinout, category=cat, generic_name=generic_name
            ):
                updates["pinout_json"] = json.dumps(part_info.pinout)
                src = getattr(part_info, "source_vendor", None) or updates.get("pinout_source") or ""
                updates["pinout_source"] = src
                updates["catalog_tier"] = "verified"
            else:
                logger.warning(
                    "CAT-004: hard-skip numeric-only pinout for %s (category=%s); not stored",
                    generic_name,
                    cat,
                )
        try:
            from datetime import timezone
            updates["enriched_at_utc"] = part_info.last_updated.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        
        # Thermal data
        if part_info.thermal_data:
            updates["thermal_json"] = json.dumps(part_info.thermal_data)
        
        # Package dimensions
        if part_info.package_dimensions:
            pd = part_info.package_dimensions
            if pd.get("length"):
                updates["package_length_mm"] = pd["length"]
            if pd.get("width"):
                updates["package_width_mm"] = pd["width"]
            if pd.get("height"):
                updates["package_height_mm"] = pd["height"]
        
        # Lifecycle and compliance
        if part_info.lifecycle_status:
            updates["lifecycle_status"] = part_info.lifecycle_status
        if part_info.compliance_flags:
            updates["compliance_flags"] = ",".join(part_info.compliance_flags)
        
        # Supply chain
        if part_info.lead_time_days:
            updates["lead_time_days"] = part_info.lead_time_days
        
        # Alternative MPNs
        if part_info.alternative_mpns:
            updates["alternative_mpns"] = json.dumps(part_info.alternative_mpns)
        
        # Manufacturer info
        if part_info.manufacturer_info:
            updates["manufacturer_info_json"] = json.dumps(part_info.manufacturer_info)
        
        if not updates:
            return False
        
        # Build UPDATE query
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [generic_name]
        
        with self._tx() as conn:
            conn.execute(
                f"UPDATE components SET {set_clause} WHERE generic_name = ?",
                params
            )
            conn.commit()
            
        logger.info(f"Updated {generic_name} with vendor data: {list(updates.keys())}")
        return True

    # ------------------------------------------------------------------
    # Parametric Query Engine (Phase 2)
    # ------------------------------------------------------------------

    def parametric_search(
        self,
        category: str,
        *,
        value: str = None,
        package: str = None,
        tolerance: str = None,
        voltage_rating: float = None,
        power_watts: float = None,
        v_out: float = None,
        min_current: float = None,
        connector_type: str = None,
        pin_count: int = None,
        family: str = None,
        mpn: str = None,
        limit: int = 10,
        **kwargs,
    ) -> tuple[dict | None, bool]:
        """Find the best component match using parametric constraints.

        Hard constraints (must match exactly):
            - category, value (if given), package (if given), mpn (if given)
            - Any additional kwargs (exact match in generic_name or description)

        Soft constraints (may over-spec):
            - voltage_rating: selects ≥ requested
            - power_watts: selects ≥ requested
            - tolerance: exact preferred, falls back to any

        Returns:
            (component_dict, was_soft_fallback)
            component_dict is None if no match found at all.
        """
        with self._tx() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # --- Build query with hard constraints ---
            hard_conditions = ["category = ?"]
            hard_params: list = [category]

            if value:
                hard_conditions.append("generic_name LIKE ?")
                hard_params.append(f"%{value}%")

            if package:
                hard_conditions.append("(generic_name LIKE ? OR kicad_footprint LIKE ?)")
                hard_params.extend([f"%{package}%", f"%{package}%"])

            if mpn:
                hard_conditions.append("(mpn LIKE ? OR generic_name LIKE ?)")
                hard_params.extend([f"%{mpn}%", f"%{mpn}%"])

            if connector_type:
                hard_conditions.append("(generic_name LIKE ? OR description LIKE ?)")
                hard_params.extend([f"%{connector_type}%", f"%{connector_type}%"])

            if family:
                hard_conditions.append("(mpn LIKE ? OR generic_name LIKE ? OR description LIKE ?)")
                hard_params.extend([f"%{family}%", f"%{family}%", f"%{family}%"])

            # Add any extra parametric kwargs as fuzzy description/name matches
            for key, val in kwargs.items():
                if val is not None:
                    hard_conditions.append("(generic_name LIKE ? OR description LIKE ?)")
                    hard_params.extend([f"%{val}%", f"%{val}%"])

            if v_out is not None:
                # For voltage regulators: look for the output voltage in the name
                v_str = str(round(v_out, 1))
                if v_out == int(v_out):
                    v_str = str(int(v_out))
                hard_conditions.append("(generic_name LIKE ? OR description LIKE ?)")
                hard_params.extend([f"%{v_str}V%", f"%{v_str}%"])

            hard_where = " AND ".join(hard_conditions)

            # --- Phase 1: Exact match (hard + soft constraints) ---
            soft_conditions = []
            soft_params = []

            if voltage_rating is not None:
                soft_conditions.append("voltage_rating >= ?")
                soft_params.append(voltage_rating)

            if power_watts is not None:
                soft_conditions.append("power_watts >= ?")
                soft_params.append(power_watts)

            if tolerance is not None:
                soft_conditions.append("tolerance = ?")
                soft_params.append(tolerance)

            # Try exact match first
            if soft_conditions:
                full_where = f"{hard_where} AND {' AND '.join(soft_conditions)}"
                full_params = hard_params + soft_params + [limit]
            else:
                full_where = hard_where
                full_params = hard_params + [limit]

            order_by = "ORDER BY CASE WHEN jlc_class = 'Basic' THEN 0 ELSE 1 END ASC"

            vn = _norm_param_token(value) if value else ""
            pkg_n = str(package or "").strip()
            if vn or pkg_n:
                idx_cond = ["category = ?"]
                idx_params: list = [category]
                if vn:
                    idx_cond.append("value_norm = ?")
                    idx_params.append(vn)
                if pkg_n:
                    idx_cond.append("package = ?")
                    idx_params.append(pkg_n)
                cursor.execute(
                    f"SELECT * FROM components WHERE {' AND '.join(idx_cond)} {order_by} LIMIT ?",
                    idx_params + [limit],
                )
                rows = cursor.fetchall()
                if rows:
                    return dict(rows[0]), False

            cursor.execute(
                f"SELECT * FROM components WHERE {full_where} {order_by} LIMIT ?",
                full_params,
            )
            rows = cursor.fetchall()

            if rows:
                return dict(rows[0]), False

            # --- Phase 2: Soft fallback (drop soft constraints) ---
            fallback_params = hard_params + [limit]
            cursor.execute(
                f"SELECT * FROM components WHERE {hard_where} {order_by} LIMIT ?",
                fallback_params,
            )
            rows = cursor.fetchall()

            if rows:
                return dict(rows[0]), True

            # --- Phase 3: Broader fallback (relax value matching) ---
            if value:
                # Try just the category + basic value prefix
                broad_conditions = ["category = ?"]
                broad_params_list: list = [category]
                # Extract numeric portion from value for fuzzy matching
                import re
                numeric = re.sub(r'[^0-9.]', '', value)
                if numeric:
                    broad_conditions.append("generic_name LIKE ?")
                    broad_params_list.append(f"%{numeric}%")
                if package:
                    broad_conditions.append("(generic_name LIKE ? OR kicad_footprint LIKE ?)")
                    broad_params_list.extend([f"%{package}%", f"%{package}%"])

                broad_where = " AND ".join(broad_conditions)
                broad_params_list.append(limit)
                cursor.execute(
                    f"SELECT * FROM components WHERE {broad_where} {order_by} LIMIT ?",
                    broad_params_list,
                )
                rows = cursor.fetchall()
                if rows:
                    return dict(rows[0]), True

            # --- Phase 4: JIT API Fallback ---
            # Component not found locally — try the live supply chain API
            try:
                from openhac.database.enrich import network_allowed as _net_ok
            except Exception:
                _net_ok = lambda: False  # noqa: E731 — fail closed (FAB-010)
            if not _net_ok():
                return None, False
            try:
                from openhac.database.api_fallback import fetch_and_map_part

                query_params = {
                    "category": category,
                    "value": value,
                    "package": package,
                    "mpn": mpn,
                    "family": family,
                    "connector_type": connector_type,
                    "v_out": v_out,
                }
                # Strip None values
                query_params = {k: v for k, v in query_params.items() if v is not None}

                logger.info(
                    "Part not found locally. Searching live supply chain..."
                )
                new_part = fetch_and_map_part(query_params)
                if new_part:
                    self.safe_insert_component(
                        new_part,
                        ignore_duplicate=True,
                        warn_prefix="JIT DB insert failed",
                    )
                    return new_part, True
            except Exception as exc:
                if isinstance(exc, self.DatabaseWriteError):
                    raise
                # JIT failed — this is non-fatal, return None
                import warnings as _w
                _w.warn(
                    f"JIT API fallback failed: {exc}",
                    UserWarning,
                    stacklevel=2,
                )

            return None, False
