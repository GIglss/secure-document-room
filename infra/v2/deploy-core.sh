#!/usr/bin/env bash
# Deploys/updates the Confidant v2 control plane. Idempotent — safe to re-run.
# Creates confidant-core-rg + confidant-sandboxes-rg and everything in main.bicep.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

DEPLOYER_IP="${DEPLOYER_IP:-$(curl -fsS https://api.ipify.org || true)}"
echo ">> Deploying Confidant v2 control plane to $LOCATION (deployer IP for debug SSH: ${DEPLOYER_IP:-<none>})"

az deployment sub create \
  --name "confidant-v2-core-$(date +%Y%m%d%H%M%S)" \
  --location "$LOCATION" \
  --template-file "$SCRIPT_DIR/main.bicep" \
  --parameters location="$LOCATION" deployerIp="$DEPLOYER_IP" \
  --query "{state: properties.provisioningState, outputs: properties.outputs}" -o json

echo ">> Done. Run ./status.sh to inspect."
