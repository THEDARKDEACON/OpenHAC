import logging
import sqlite3
import os
import warnings

logger = logging.getLogger("openhac.db")

_default_db = os.path.join(os.path.dirname(__file__), "openhac.db")
_env_db = (os.environ.get("OPENHAC_DB_PATH") or "").strip()
DB_PATH = os.path.abspath(os.path.expanduser(_env_db)) if _env_db else _default_db
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

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


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create database, apply schema, and run migrations."""
        with sqlite3.connect(self.db_path) as conn:
            with open(SCHEMA_PATH, "r") as f:
                conn.executescript(f.read())
            # Run v2 migration — add parametric columns if they don't exist
            self._migrate_v2(conn)
            self._migrate_v3(conn)
            self._migrate_v4(conn)
            self._migrate_v5_part_alternates_group(conn)
            self._migrate_v6_pinout(conn)
            self._migrate_v7_complete_data(conn)
            self._migrate_v8_vendor_enrich_fields(conn)
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM components WHERE generic_name = ?", (generic_name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_component_by_supplier_sku(self, supplier_sku: str) -> dict | None:
        """Fetch a component by its supplier SKU (e.g. LCSC Cxxxxx)."""
        if not supplier_sku:
            return None
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
            updates["category"] = part_info.category
        if getattr(part_info, "package", None):
            updates["package"] = part_info.package
        if getattr(part_info, "stock", None) is not None:
            try:
                updates["stock"] = int(part_info.stock)
            except Exception:
                pass
        
        # Pinout
        if part_info.pinout:
            updates["pinout_json"] = json.dumps(part_info.pinout)
            updates["pinout_source"] = getattr(part_info, "source_vendor", None) or updates.get("pinout_source") or ""
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
        
        with sqlite3.connect(self.db_path) as conn:
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
    ) -> tuple[dict | None, bool]:
        """Find the best component match using parametric constraints.

        Hard constraints (must match exactly):
            - category, value (if given), package (if given), mpn (if given)

        Soft constraints (may over-spec):
            - voltage_rating: selects ≥ requested
            - power_watts: selects ≥ requested
            - tolerance: exact preferred, falls back to any

        Returns:
            (component_dict, was_soft_fallback)
            component_dict is None if no match found at all.
        """
        with sqlite3.connect(self.db_path) as conn:
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
