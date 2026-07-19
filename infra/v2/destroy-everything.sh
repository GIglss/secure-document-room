#!/usr/bin/env bash
# Deletes BOTH Confidant v2 resource groups (control plane + sandboxes).
#
# WARNING: the Key Vault has purge protection enabled. After deletion the
# vault (and its name) stays in soft-deleted state for 90 days and CANNOT be
# purged — the vault name is locked for 90 days. Analytics tables are lost.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

echo "This deletes resource groups '$CORE_RG' and '$SANDBOX_RG' and ALL their contents,"
echo "including the analytics tables. The Key Vault name will be locked for 90 days"
echo "(purge protection). This does NOT touch confidant-rg / confidant-landingpage-rg."
read -r -p "Type 'destroy' to confirm: " CONFIRM
[[ "$CONFIRM" == "destroy" ]] || { echo "Aborted."; exit 1; }

az group delete -n "$SANDBOX_RG" --yes --no-wait || true
az group delete -n "$CORE_RG" --yes --no-wait || true
echo ">> Deletion started (running in background). Check with: az group list -o table"
