import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "openhac.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # Create database and apply schema if it doesn't exist
        with sqlite3.connect(self.db_path) as conn:
            with open(SCHEMA_PATH, "r") as f:
                conn.executescript(f.read())
            conn.commit()

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
            component_data: dict of column -> value. Unknown keys (e.g. category,
                attributes_json) are included automatically; missing optional keys
                are simply omitted.
            ignore_duplicate: if True, use INSERT OR IGNORE so duplicate
                generic_name rows are silently skipped.

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
        """Search components by generic_name or description substring, optionally filtered by category.

        Args:
            query: substring to match against generic_name or description (case-insensitive).
            category: if provided, restrict results to this category value.
            limit: maximum number of rows to return.

        Returns:
            list of component dicts.
        """
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
