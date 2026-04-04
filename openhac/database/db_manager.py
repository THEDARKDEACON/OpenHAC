import sqlite3
import os
import warnings

DB_PATH = os.path.join(os.path.dirname(__file__), "openhac.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Columns added in schema v2 (Phase 2 — Parametric Abstraction)
_V2_COLUMNS = {
    "tolerance": "TEXT",
    "voltage_rating": "REAL",
    "power_watts": "REAL",
    "jlc_class": "TEXT DEFAULT 'Basic'",
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
            conn.commit()

    @staticmethod
    def _migrate_v2(conn):
        """Add parametric columns to an existing components table (idempotent)."""
        cursor = conn.execute("PRAGMA table_info(components)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _V2_COLUMNS.items():
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

    def insert_component(self, component_data: dict, ignore_duplicate: bool = False):
        """Inserts a component into the database.

        Args:
            component_data: dict of column -> value.
            ignore_duplicate: if True, use INSERT OR IGNORE.

        Returns:
            lastrowid on insert, or None if the row was ignored.
        """
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

                print(
                    f"\033[96m[INFO]\033[0m Part not found locally. "
                    f"Searching live supply chain..."
                )
                new_part = fetch_and_map_part(query_params)
                if new_part:
                    self.insert_component(new_part, ignore_duplicate=True)
                    return new_part, True
            except Exception as exc:
                # JIT failed — this is non-fatal, return None
                import warnings as _w
                _w.warn(
                    f"JIT API fallback failed: {exc}",
                    UserWarning,
                    stacklevel=2,
                )

            return None, False
