#!/usr/bin/env bash
# Provision the Confidant engagement environment: resource group, storage
# (durable insights table), ACS email, and the sandbox VM. Idempotent —
# re-running updates in place.
#
# Usage: ./provision.sh
# Env overrides: RG, LOCATION, VM_SIZE, GPU=true (also sets SCSI + GPU cloud-init)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

ensure_ssh_key

MY_IP="$(curl -fsS https://api.ipify.org)"
echo "Deployer public IP (SSH allowlist): $MY_IP"

DISK_CONTROLLER="NVMe"
if [ "$GPU" = "true" ]; then
  DISK_CONTROLLER="SCSI"   # T4 GPU SKUs are not NVMe-capable
fi

echo "Creating resource group $RG in $LOCATION..."
az group create -n "$RG" -l "$LOCATION" -o none

echo "Deploying bicep (VM size: $VM_SIZE, gpu: $GPU)..."
az deployment group create \
  -g "$RG" \
  -n "$DEPLOYMENT_NAME" \
  -f "$SCRIPT_DIR/main.bicep" \
  -p vmSize="$VM_SIZE" \
     gpu="$GPU" \
     diskControllerType="$DISK_CONTROLLER" \
     adminUsername="$ADMIN_USER" \
     sshPublicKey="$(cat "$SSH_KEY.pub")" \
     allowedSshSourcePrefix="$MY_IP/32" \
  -o none

echo
echo "=== Deployment outputs ==="
az deployment group show -g "$RG" -n "$DEPLOYMENT_NAME" \
  --query "properties.outputs" -o json | python3 -c "
import json, sys
for k, v in json.load(sys.stdin).items():
    print(f'{k:22s} {v[\"value\"]}')"

echo
echo "Next: ./deploy-app.sh  (builds and starts the app on the VM)"
