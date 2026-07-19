#!/usr/bin/env bash
# Wake the engagement: start the VM. Containers restart automatically.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "Starting $VM_NAME ..."
az vm start -g "$RG" -n "$VM_NAME" -o none
FQDN="$(deployment_output vmFqdn)"
echo "State: $(vm_power_state)"
echo "URL:   https://$FQDN  (allow ~1-2 min for containers to come up)"
