#!/bin/bash
set -euo pipefail

# Create bootable USB installer for Fedora CoreOS on macOS
# This script writes the CoreOS live ISO/image to a USB drive

echo "========================================"
echo "Fedora CoreOS USB Installer Creator"
echo "========================================"
echo ""
echo "WARNING: This will ERASE the selected USB drive!"
echo ""

# Find CoreOS image
COREOS_IMAGE=$(ls -t fedora-coreos-*-metal.x86_64.raw.xz 2>/dev/null | head -1)

if [ -z "${COREOS_IMAGE}" ]; then
    echo "Error: No CoreOS image found."
    echo "Please run: ./download-coreos.sh first"
    exit 1
fi

echo "Found CoreOS image: ${COREOS_IMAGE}"
echo ""

# List available disks
echo "Available disks:"
diskutil list external physical

echo ""
echo "Enter the disk identifier (e.g., disk2 or disk4):"
read -r DISK_ID

# Validate disk ID
if [ -z "${DISK_ID}" ]; then
    echo "Error: No disk ID provided"
    exit 1
fi

# Add /dev/ prefix if not present
if [[ ! "${DISK_ID}" =~ ^/dev/ ]]; then
    DISK_PATH="/dev/${DISK_ID}"
else
    DISK_PATH="${DISK_ID}"
    DISK_ID=$(basename "${DISK_PATH}")
fi

# Check if disk exists
if [ ! -e "${DISK_PATH}" ]; then
    echo "Error: Disk ${DISK_PATH} does not exist"
    exit 1
fi

# Show disk info
echo ""
echo "Selected disk:"
diskutil info "${DISK_ID}" | grep -E "Device Node|Media Name|Total Size"

echo ""
echo "WARNING: All data on ${DISK_PATH} will be ERASED!"
echo "Type 'yes' to continue:"
read -r CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Unmounting disk..."
diskutil unmountDisk "${DISK_PATH}" || true

echo ""
echo "Writing CoreOS image to ${DISK_PATH}..."
echo "This will take 5-15 minutes depending on USB speed..."
echo ""

# Decompress and write in one step
xz -dc "${COREOS_IMAGE}" | sudo dd of="${DISK_PATH}" bs=4M status=progress

echo ""
echo "Syncing..."
sync

echo ""
echo "Ejecting disk..."
diskutil eject "${DISK_PATH}"

echo ""
echo "✓ USB installer created successfully!"
echo ""
echo "Next steps:"
echo "1. Insert USB into Odroid HC4"
echo "2. Boot from USB (may need to access boot menu)"
echo "3. Follow installation instructions in README.md"
