#!/usr/bin/env bash
# Hard-deletes one sandbox (VM + NIC + public IP + OS disk).
# Usage: ./destroy-sandbox.sh <sandbox-id>
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SANDBOX_ID="${1:?usage: destroy-sandbox.sh <sandbox-id>}"
VM="vm-confidant-$SANDBOX_ID"

echo ">> Deleting $VM (VM deletion cascades NIC + OS disk via deleteOption) ..."
az vm delete -g "$SANDBOX_RG" -n "$VM" --yes --force-deletion true || echo "   (VM not found)"

# NIC/PIP cleanup in case cascade didn't apply (e.g. VM already gone).
az network nic delete -g "$SANDBOX_RG" -n "nic-$VM" 2>/dev/null || true
az network public-ip delete -g "$SANDBOX_RG" -n "pip-$VM" 2>/dev/null || true

echo ">> Sandbox '$SANDBOX_ID' destroyed."
