#!/usr/bin/env bash
# =====================================================================
# Pird AI Video Dubbing - Azure Ubuntu VM Swap Space Setup Script
# Purpose: Allocates a 4 GiB swap file to prevent Out-Of-Memory (OOM) 
#          crashes during large (up to 2 GiB) video transfers and local
#          telegram-bot-api C++ daemon execution on a 1 GiB RAM host.
# =====================================================================

set -euo pipefail

SWAP_FILE="/swapfile"
SWAP_SIZE="4G"

echo "🔍 [1/5] Checking existing swap space..."
if swapon --show | grep -q "^$SWAP_FILE"; then
    echo "✅ Swap file $SWAP_FILE is already active:"
    swapon --show
    free -h
    exit 0
fi

echo "⚙️ [2/5] Creating $SWAP_SIZE swap file at $SWAP_FILE..."
# Fallback to dd if fallocate is not supported or filesystem rejects it
if command -v fallocate >/dev/null 2>&1; then
    sudo fallocate -l "$SWAP_SIZE" "$SWAP_FILE" || sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count=4096 status=progress
else
    sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count=4096 status=progress
fi

echo "🔒 [3/5] Setting secure permissions (600) on $SWAP_FILE..."
sudo chmod 600 "$SWAP_FILE"

echo "🛠️ [4/5] Formatting swap file..."
sudo mkswap "$SWAP_FILE"

echo "🚀 [5/5] Enabling swap space..."
sudo swapon "$SWAP_FILE"

# Persist in /etc/fstab if not already present
if ! grep -q "$SWAP_FILE" /etc/fstab; then
    echo "💾 Persisting swap configuration in /etc/fstab..."
    echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab > /dev/null
fi

echo "🎉 Swap space successfully configured!"
free -h
