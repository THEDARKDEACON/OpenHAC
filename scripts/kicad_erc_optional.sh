#!/usr/bin/env bash
# Optional KiCad schematic ERC (SCH-003 helper). Requires kicad-cli on PATH.
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: $0 path/to/board.kicad_sch [extra kicad-cli args...]" >&2
  exit 2
fi
sch="$1"
shift
out="${sch%.kicad_sch}.erc.rpt"
exec kicad-cli sch erc -o "$out" "$sch" "$@"
