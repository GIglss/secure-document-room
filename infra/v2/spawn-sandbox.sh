#!/usr/bin/env bash
# Spawns one client sandbox VM from the latest gallery image.
# Usage: ./spawn-sandbox.sh <sandbox-id>   (lowercase letters, digits, hyphens)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SANDBOX_ID="${1:?usage: spawn-sandbox.sh <sandbox-id>}"
if ! [[ "$SANDBOX_ID" =~ ^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$ ]]; then
  echo "sandbox-id must be lowercase alphanumeric/hyphens (3-40 chars)" >&2; exit 1
fi

# Debug SSH key (NSG only allows SSH from the deployer IP anyway).
SSH_KEY_FILE="${SSH_KEY_FILE:-$HOME/.ssh/confidant_sandbox}"
[[ -f "$SSH_KEY_FILE.pub" ]] || ssh-keygen -t ed25519 -N '' -f "$SSH_KEY_FILE" -C confidant-sandbox >/dev/null

STORAGE_NAME="$(core_storage_account)"
DES="$(des_id)"

# Per-sandbox backend SECRET_KEY — generated fresh at spawn time, delivered
# only via cloud-init customData (never baked into the gallery image).
SECRET_KEY="$(openssl rand -hex 32)"

# Verification-email credentials, fetched at spawn time from the shared ACS
# resource (confidant-acs in confidant-landingpage-rg). Sender address is the
# DoNotReply@ address of the AzureManaged domain on the confidant-email
# service (confidant-rg). Both are optional: if the lookup fails the sandbox
# still works, with the email step disabled (backend treats empty as unset).
ACS_RG="confidant-landingpage-rg"
ACS_NAME="confidant-acs"
EMAIL_RG="confidant-rg"
EMAIL_SERVICE="confidant-email"
ACS_CONNECTION_STRING="$(az communication list-key -n "$ACS_NAME" -g "$ACS_RG" \
  --query primaryConnectionString -o tsv 2>/dev/null || true)"
ACS_SENDER_DOMAIN="$(az communication email domain list \
  --email-service-name "$EMAIL_SERVICE" -g "$EMAIL_RG" \
  --query "[?domainManagement=='AzureManaged'].mailFromSenderDomain | [0]" \
  -o tsv 2>/dev/null || true)"
ACS_SENDER_ADDRESS=""
[[ -n "$ACS_SENDER_DOMAIN" ]] && ACS_SENDER_ADDRESS="DoNotReply@$ACS_SENDER_DOMAIN"
if [[ -z "$ACS_CONNECTION_STRING" || -z "$ACS_SENDER_ADDRESS" ]]; then
  echo "WARN: ACS lookup incomplete — sandbox will run with email verification disabled." >&2
fi

echo ">> Spawning sandbox '$SANDBOX_ID' ($VM_SIZE, osDiskMode=$OS_DISK_MODE) ..."
PARAMS_FILE="$(mktemp)"
trap 'rm -f "$PARAMS_FILE"' EXIT
# Secrets go through a parameters file (not argv) so they never appear in `ps`.
python3 - "$PARAMS_FILE" <<EOF
import json, sys
params = {
    "sandboxId": {"value": "$SANDBOX_ID"},
    "coreRgName": {"value": "$CORE_RG"},
    "coreStorageAccountName": {"value": "$STORAGE_NAME"},
    "vmSize": {"value": "$VM_SIZE"},
    "osDiskMode": {"value": "$OS_DISK_MODE"},
    "diskEncryptionSetId": {"value": "$DES"},
    "sshPublicKey": {"value": open("$SSH_KEY_FILE.pub").read().strip()},
    "secretKey": {"value": "$SECRET_KEY"},
    "acsConnectionString": {"value": """$ACS_CONNECTION_STRING"""},
    "acsSenderAddress": {"value": "$ACS_SENDER_ADDRESS"},
}
json.dump({
    "\$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": params,
}, open(sys.argv[1], "w"))
EOF
az deployment group create \
  --resource-group "$SANDBOX_RG" \
  --name "sandbox-$SANDBOX_ID" \
  --template-file "$SCRIPT_DIR/sandbox.bicep" \
  --parameters "@$PARAMS_FILE" \
  --query "properties.outputs" -o json

echo ""
echo ">> Sandbox up: https://confidant-$SANDBOX_ID.$LOCATION.cloudapp.azure.com"
