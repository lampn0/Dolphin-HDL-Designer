#!/usr/bin/env bash
# =============================================================================================
# Build the Linux (CentOS Stream 9) release of HDLDesigner with PyInstaller.
#
#     bash resources/scripts/build_linux.sh
#
# Run from anywhere: paths are taken relative to this script. Needs the packages of
# requirements.txt and PyInstaller (pip install pyinstaller) in the active Python.
# Result: dist/HDLDesigner/ and dist/HDLDesigner-<version>-linux-x64.tar.gz
# =============================================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"     # repository root
cd "$ROOT"

# version of the release: __version__ of src/version.py
VERSION="$(python3 -c "import sys; sys.path.insert(0, 'src'); import version; print(version.__version__)")"

# build the folder distribution (work files in build/, result in dist/HDLDesigner)
pyinstaller --noconfirm --distpath dist --workpath build resources/scripts/HDLDesigner.spec

# pack it for distribution
tar -C dist -czf "dist/HDLDesigner-${VERSION}-linux-x64.tar.gz" HDLDesigner
echo "Built dist/HDLDesigner-${VERSION}-linux-x64.tar.gz"
