#!/usr/bin/env bash
# Show VM power state, URL, and what it's costing right now.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

STATE="$(vm_power_state || echo 'VM not found')"
FQDN="$(deployment_output vmFqdn 2>/dev/null || echo '-')"

echo "Resource group : $RG"
echo "VM             : $VM_NAME ($VM_SIZE)"
echo "Power state    : $STATE"
echo "URL            : https://$FQDN"
case "$STATE" in
  "VM running")
    echo "Cost           : ~0.42 EUR/hour compute + ~8 EUR/month disk/IP/storage" ;;
  "VM deallocated")
    echo "Cost           : compute 0 — only disk + IP + storage (~8 EUR/month)" ;;
  *)
    echo "Cost           : transitional state (stopped-but-not-deallocated still bills compute — run ./down.sh)" ;;
esac
