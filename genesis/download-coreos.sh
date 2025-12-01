#!/bin/bash
set -euo pipefail

# Download Fedora CoreOS x86_64 (AMD64) image
# This script downloads the latest stable CoreOS image for x86_64/AMD64 architecture

STREAM="stable"
ARCH="x86_64"  # AMD64/Intel architecture
COREOS_URL="https://builds.coreos.fedoraproject.org/streams/${STREAM}.json"

echo "Fetching CoreOS ${STREAM} stream metadata..."

# Get latest version info
DOWNLOAD_URL=$(curl -s "${COREOS_URL}" | \
  jq -r ".architectures.${ARCH}.artifacts.metal.formats.raw.disk.location")

VERSION=$(curl -s "${COREOS_URL}" | jq -r ".architectures.${ARCH}.artifacts.metal.release")

echo "Latest CoreOS version: ${VERSION}"
echo "Download URL: ${DOWNLOAD_URL}"

# Download if not already present
FILENAME="fedora-coreos-${VERSION}-metal.${ARCH}.raw.xz"

if [ -f "${FILENAME}" ]; then
    echo "File already exists: ${FILENAME}"
    echo "Skipping download."
else
    echo "Downloading CoreOS image..."
    curl -L -o "${FILENAME}" "${DOWNLOAD_URL}"
    echo "Download complete: ${FILENAME}"
fi

# Also download the signature for verification
SIG_URL="${DOWNLOAD_URL}.sig"
if [ ! -f "${FILENAME}.sig" ]; then
    echo "Downloading signature..."
    curl -L -o "${FILENAME}.sig" "${SIG_URL}"
fi

echo ""
echo "CoreOS image ready: ${FILENAME}"
echo "You can now run: ./create-usb-installer.sh"

