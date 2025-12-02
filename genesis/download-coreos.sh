#!/bin/bash
set -euo pipefail

# Download Fedora CoreOS live ISO
# This is used to create a bootable USB installer

STREAM="stable"
ARCH="x86_64"
COREOS_URL="https://builds.coreos.fedoraproject.org/streams/${STREAM}.json"

echo "Fetching CoreOS ${STREAM} stream metadata..."

# Fetch metadata
METADATA=$(curl -s "${COREOS_URL}")

# Get version
VERSION=$(echo "${METADATA}" | jq -r ".architectures.${ARCH}.artifacts.metal.release")

# Get ISO URL
ISO_URL=$(echo "${METADATA}" | jq -r ".architectures.${ARCH}.artifacts.metal.formats.iso.disk.location")

echo "Latest CoreOS version: ${VERSION}"
echo "ISO URL: ${ISO_URL}"

if [ "${ISO_URL}" = "null" ] || [ -z "${ISO_URL}" ]; then
    echo ""
    echo "Error: Could not find ISO URL"
    echo "Available artifacts:"
    echo "${METADATA}" | jq ".architectures.${ARCH}.artifacts | keys"
    exit 1
fi

# Download ISO
FILENAME="fedora-coreos-${VERSION}-live.${ARCH}.iso"

if [ -f "${FILENAME}" ]; then
    echo ""
    echo "File already exists: ${FILENAME}"
    echo "Skipping download."
else
    echo ""
    echo "Downloading CoreOS ISO (~1GB)..."
    curl -L --progress-bar -o "${FILENAME}" "${ISO_URL}"
    echo ""
    echo "Download complete: ${FILENAME}"
fi

echo ""
echo "✓ CoreOS ISO ready: ${FILENAME}"
echo ""
echo "Next: Generate ignition config with ./generate-ignition.sh"
