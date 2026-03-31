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

    def insert_component(self, component_data: dict):
        """Inserts a component into the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            columns = ', '.join(component_data.keys())
            placeholders = ', '.join('?' * len(component_data))
            values = tuple(component_data.values())
            
            cursor.execute(f"INSERT INTO components ({columns}) VALUES ({placeholders})", values)
            conn.commit()
            return cursor.lastrowid
