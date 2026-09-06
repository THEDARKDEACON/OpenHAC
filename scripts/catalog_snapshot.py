"""CAT-014: maintainer catalog snapshot (sync + coverage JSON).

Not a user compile phase. Not invoked by ``--production``. User CI must not
require live jlcsearch — this script is optional and network-gated.

Usage:
    python scripts/catalog_snapshot.py -o build/catalog_coverage.json
    python scripts/catalog_snapshot.py --skip-sync -o build/catalog_coverage.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Maintainer job: optional JLC sync then catalog coverage JSON (CAT-014)."
    )
    p.add_argument(
        "-o",
        "--output",
        default="catalog_coverage.json",
        help="Coverage JSON path (schema openhac.catalog_coverage.v1)",
    )
    p.add_argument("--skip-sync", action="store_true", help="Do not call jlcsearch; coverage only")
    p.add_argument("--include-extended", action="store_true", help="Pass through to openhac sync")
    p.add_argument("--max-per-category", type=int, default=500, help="Cap per typed category")
    p.add_argument("--db-path", default=None, help="SQLite catalog path")
    args = p.parse_args(argv)

    if args.db_path:
        os.environ["OPENHAC_DB_PATH"] = str(args.db_path)

    from openhac.database.enrich import network_allowed

    if not args.skip_sync:
        if not network_allowed():
            print(
                "catalog_snapshot: network denied (OPENHAC_NO_NETWORK / fabrication); "
                "skipping sync. Use --skip-sync for coverage-only.",
                file=sys.stderr,
            )
        else:
            from openhac.database.sync_jlc import sync_catalog

            n = sync_catalog(
                verbose=True,
                include_extended=bool(args.include_extended),
                max_per_category=int(args.max_per_category),
            )
            print(f"catalog_snapshot: synced {n} new rows", file=sys.stderr)

    from openhac.database.catalog_coverage import collect_catalog_coverage, write_coverage_json
    from openhac.database.db_manager import DatabaseManager

    db = DatabaseManager()
    report = collect_catalog_coverage(db)
    dest = write_coverage_json(report, args.output)
    print(json.dumps({"wrote": str(dest), "compile_ready": report["compile_ready"], "warehouse": report["warehouse"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
