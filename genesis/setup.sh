#!/bin/bash
set -euo pipefail

# Genesis Setup - Fedora CoreOS + k3s Kubernetes on Odroids
# Checks prerequisites and guides through setup

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "Genesis - Fedora CoreOS + k3s Setup"
echo "=================================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."
echo ""

MISSING_TOOLS=()

# Check butane (required for generating ignition configs)
if ! command -v butane &> /dev/null; then
    echo "⚠️  butane not found (required for generating ignition configs)"
    echo "   Install with: brew install butane"
    MISSING_TOOLS+=("butane")
else
    echo "✓ butane installed"
fi

# Check jq (required for downloading CoreOS)
if ! command -v jq &> /dev/null; then
    echo "⚠️  jq not found (required for downloading CoreOS)"
    echo "   Install with: brew install jq"
    MISSING_TOOLS+=("jq")
else
    echo "✓ jq installed"
fi

# Check kubectl (recommended)
if ! command -v kubectl &> /dev/null; then
    echo "⚠️  kubectl not found (recommended for cluster management)"
    echo "   Install with: brew install kubectl"
else
    echo "✓ kubectl installed"
fi

echo ""

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo "=================================================="
    echo "Missing required tools: ${MISSING_TOOLS[*]}"
    echo "=================================================="
    echo ""
    echo "Install them with:"
    for tool in "${MISSING_TOOLS[@]}"; do
        echo "  brew install ${tool}"
    done
    echo ""
    exit 1
fi

# Check for SSH key
if [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
    echo "✓ SSH key found: ~/.ssh/id_ed25519.pub"
else
    echo "⚠️  No SSH key found"
    echo "   Generate one with: ssh-keygen -t ed25519"
    echo ""
fi

echo "✓ All prerequisites met!"
echo ""

echo "=================================================="
echo "Next Steps:"
echo "=================================================="
echo ""
echo "1. Download Fedora CoreOS:"
echo "   ./download-coreos.sh"
echo ""
echo "2. Create USB installer:"
echo "   ./create-usb-installer.sh"
echo ""
echo "3. Generate ignition config for first node:"
echo "   export NODE_HOSTNAME=odroid-1"
echo "   ./generate-ignition.sh"
echo "   (automatically uses ~/.ssh/id_ed25519.pub)"
echo ""
echo "4. Boot Odroid from USB and install CoreOS"
echo "   (see README.md for detailed instructions)"
echo ""
echo "5. Repeat for other nodes"
echo ""
echo "6. Bootstrap the k3s cluster:"
echo "   ./bootstrap-cluster.sh"
echo ""
echo "For complete instructions, see: README.md"
echo ""
