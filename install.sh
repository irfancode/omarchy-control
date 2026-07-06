#!/bin/bash
set -e

echo "================================"
echo "  Omarchy Control Installer"
echo "================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Install via the omarchy command
bash "$SCRIPT_DIR/bin/omarchy-install-control"
