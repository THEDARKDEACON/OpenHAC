from openhac.database.db_manager import DatabaseManager
import json

db = DatabaseManager()
row = db.get_component("ACS758LCB-100B")
if row:
    print(json.dumps(dict(row), indent=2))
else:
    print("Not found")
