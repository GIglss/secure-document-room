#!/usr/bin/env bash
# Standby: deallocate the VM. Compute billing stops; disk (~5 EUR/month) and
# the public IP (~3 EUR/month) remain. All engagement data stays on the disk.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "Deallocating $VM_NAME ..."
az vm deallocate -g "$RG" -n "$VM_NAME" -o none
echo "State: $(vm_power_state)"
echo "Resume with ./up.sh"
