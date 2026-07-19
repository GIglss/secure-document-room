#!/usr/bin/env bash
# Shared config for Confidant v2 infra scripts.
set -euo pipefail

export SUBSCRIPTION_ID="0f94670d-1eff-45a0-a2f8-8215eb135886"
export LOCATION="${LOCATION:-westeurope}"
export CORE_RG="confidant-core-rg"
export SANDBOX_RG="confidant-sandboxes-rg"
export VM_SIZE="${VM_SIZE:-Standard_E4s_v6}"
# Persistent | EphemeralNvme (use with Standard_E4ds_v6) | EphemeralCache
export OS_DISK_MODE="${OS_DISK_MODE:-Persistent}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

az account set --subscription "$SUBSCRIPTION_ID"

core_storage_account() {
  az storage account list -g "$CORE_RG" \
    --query "[?starts_with(name, 'stconfcore')].name | [0]" -o tsv
}

des_id() {
  az resource show -g "$CORE_RG" \
    --resource-type Microsoft.Compute/diskEncryptionSets \
    -n des-confidant-gallery --query id -o tsv
}
