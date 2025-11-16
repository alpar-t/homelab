#!/bin/bash

# Genesis Setup - Talos Kubernetes on Odroids
# Prepares for USB-based installation

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "Genesis - Talos Kubernetes Setup"
echo "=================================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v talosctl &> /dev/null; then
    echo "⚠️  talosctl not found"
    echo "Install with: brew install siderolabs/tap/talosctl"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ talosctl installed"
fi
echo ""

echo "Setup ready!"
echo ""
echo "=================================================="
echo "Next Steps:"
echo "=================================================="
echo ""
echo "1. Create USB installer:"
echo "   ./create-usb-installer.sh"
echo ""
echo "2. Boot each Odroid from USB and install Talos"
echo ""
echo "3. Generate cluster configuration:"
echo "   talosctl gen config mycluster https://192.168.1.10:6443 \\"
echo "     --output-dir talos-config/"
echo ""
echo "4. Follow README.md for complete installation steps"
echo ""
echo "For detailed instructions, see README.md"
echo ""
