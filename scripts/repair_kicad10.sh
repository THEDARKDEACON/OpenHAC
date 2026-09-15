#!/usr/bin/env bash
# Fresh KiCad 10-only install: drop 8/9 PPAs, purge mixed packages, reinstall 10.0.
# Run:  bash scripts/repair_kicad10.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-running with sudo (password required)..."
  exec sudo -E bash "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Removing KiCad 8.0 / 9.0 PPAs (keep 10.0 only)"
rm -f /etc/apt/sources.list.d/kicad-ubuntu-kicad-8_0-releases-noble.sources \
      /etc/apt/sources.list.d/kicad-ubuntu-kicad-9_0-releases-noble.sources \
      /etc/apt/sources.list.d/kicad-ubuntu-kicad-9_0-releases-noble.sources.save

if [[ ! -f /etc/apt/sources.list.d/kicad-ubuntu-kicad-10_0-releases-noble.sources ]]; then
  echo "ERROR: KiCad 10.0 PPA source missing."
  echo "Add it with:  sudo add-apt-repository ppa:kicad/kicad-10.0-releases"
  exit 1
fi

echo "==> Finishing any stuck dpkg configures, then purge KiCad"
dpkg --configure -a || true
apt-get purge -y 'kicad*' || true
apt-get autoremove -y || true

echo "==> apt update"
apt-get update

echo "==> Install KiCad 10.0.x + matching libraries"
apt-get install -y \
  kicad \
  kicad-libraries \
  kicad-footprints \
  kicad-symbols \
  kicad-packages3d \
  kicad-templates \
  kicad-demos

echo "==> Finish triggers / configure"
dpkg --configure -a
apt-get install -f -y

echo
echo "==> Installed packages"
dpkg -l 'kicad*' | grep -E '^ii|^iU|^hi' || true

echo
echo "==> Versions (expect all 10.0.x)"
kicad-cli --version || true
python3 - <<'PY'
import pcbnew
print("pcbnew:", pcbnew.GetBuildVersion())
print("FindPlugin:", hasattr(pcbnew.PCB_IO_MGR, "FindPlugin"))
PY

echo
echo "Done. Optional user cleanup (as your normal user, not root):"
echo "  cp /usr/share/kicad/template/fp-lib-table  ~/.config/kicad/10.0/fp-lib-table"
echo "  cp /usr/share/kicad/template/sym-lib-table ~/.config/kicad/10.0/sym-lib-table"
echo "Then open KiCad once so it migrates KICAD10_* path vars if needed."
