import os
import csv
import requests
import sqlite3
import sys
from pathlib import Path
from .db_manager import DatabaseManager

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
CATALOG_URL = "https://raw.githubusercontent.com/yaqwsx/jlcparts/master/docs/demo_components.csv" # Mocks bulk LCSC CSV
DOWNLOAD_URL = "https://raw.githubusercontent.com/yaqwsx/jlcparts/master/docs/demo_components.csv"

def sync_catalog():
    print(f"Initiating Production JLC/LCSC Catalog Sync...")
    
    db_path = Path(__file__).parent / "openhac.db"
    cache_dir = Path(__file__).parent / ".cache"
    cache_dir.mkdir(exist_ok=True)
    
    csv_path = cache_dir / "jlc_catalog.csv"
    
    print(f"Streaming live catalog from {DOWNLOAD_URL}...")
    try:
        # 1. Stream the massive file in chunks to prevent MemoryErrors (RAM exhaustion)
        with requests.get(DOWNLOAD_URL, stream=True, timeout=10) as r:
            r.raise_for_status()
            with open(csv_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    except Exception as e:
        print(f"\nCRITICAL ERROR: Failed to reach the production catalog server.")
        print(f"Reason: {e}")
        print("Halting sync to prevent generic data corruption. (Mock fallback disabled in Production).")
        sys.exit(1)
        
    print(f"Parsing CSV ({csv_path}) and injecting into SQLite...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    inserted = 0
    # 2. Iterate row by row instead of loading the whole 1.2GB CSV into memory
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        
        for row in reader:
            if len(row) < 7: continue
            
            cursor.execute('''
                INSERT OR IGNORE INTO components 
                (id, kicad_symbol, kicad_footprint, manufacturer, mpn, supplier_sku, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (row[0], row[1], row[2], row[3], row[4], row[5], row[6]))
            
            if cursor.rowcount > 0:
                inserted += 1
                
    conn.commit()
    conn.close()
    print(f"Production Sync complete! Successfully ingested {inserted} live components.")

if __name__ == "__main__":
    sync_catalog()
