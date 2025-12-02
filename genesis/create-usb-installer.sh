#!/bin/bash
set -euo pipefail

# Create a bootable Fedora CoreOS USB installer
# This writes the standard CoreOS live ISO to USB

echo "=== Fedora CoreOS USB Installer Creator ==="
echo ""

# Find ISO file
ISO_FILES=(fedora-coreos-*-live.x86_64.iso)

if [ ! -e "${ISO_FILES[0]}" ]; then
    echo "Error: No CoreOS ISO found."
    echo ""
    echo "Please run ./download-coreos.sh first to download the ISO."
    exit 1
fi

# Select ISO if multiple exist
ISO_FILE=""
if [ ${#ISO_FILES[@]} -eq 1 ]; then
    ISO_FILE="${ISO_FILES[0]}"
else
    echo "Multiple ISOs found:"
    for i in "${!ISO_FILES[@]}"; do
        echo "  $((i+1)). ${ISO_FILES[$i]}"
    done
    echo ""
    read -p "Select ISO (1-${#ISO_FILES[@]}): " selection
    ISO_FILE="${ISO_FILES[$((selection-1))]}"
fi

echo "Selected ISO: ${ISO_FILE}"
echo ""

# List available disks
echo "Available disks:"
if [[ "$OSTYPE" == "darwin"* ]]; then
    diskutil list
    echo ""
    read -p "Enter disk identifier (e.g., disk2): " DISK
    DEVICE="/dev/${DISK}"
    
    # Unmount if mounted
    diskutil unmountDisk "${DEVICE}" 2>/dev/null || true
    
    echo ""
    echo "⚠️  WARNING: This will ERASE ALL DATA on ${DEVICE}"
    read -p "Type 'YES' to confirm: " confirm
    
    if [ "${confirm}" != "YES" ]; then
        echo "Cancelled."
        exit 1
    fi
    
    echo ""
    echo "Writing ISO to ${DEVICE}..."
    sudo dd if="${ISO_FILE}" of="${DEVICE}" bs=1m status=progress
    
    echo ""
    echo "Syncing..."
    sudo sync
    
    echo ""
    echo "Ejecting ${DEVICE}..."
    diskutil eject "${DEVICE}"
    
else
    lsblk -d -o NAME,SIZE,TYPE,MOUNTPOINT
    echo ""
    read -p "Enter device (e.g., /dev/sdb): " DEVICE
    
    echo ""
    echo "⚠️  WARNING: This will ERASE ALL DATA on ${DEVICE}"
    read -p "Type 'YES' to confirm: " confirm
    
    if [ "${confirm}" != "YES" ]; then
        echo "Cancelled."
        exit 1
    fi
    
    # Unmount if mounted
    sudo umount "${DEVICE}"* 2>/dev/null || true
    
    echo ""
    echo "Writing ISO to ${DEVICE}..."
    sudo dd if="${ISO_FILE}" of="${DEVICE}" bs=4M status=progress conv=fsync
    
    echo ""
    echo "Syncing..."
    sudo sync
fi

echo ""
echo "✓ USB installer created successfully!"
echo ""
echo "This USB can be reused for all nodes."
echo ""
echo "Next steps:"
echo "  1. Generate ignition configs: ./generate-ignition.sh <hostname>"
echo "  2. Start HTTP server: python3 -m http.server 8080"
echo "  3. Boot from USB and install (see README.md)"
