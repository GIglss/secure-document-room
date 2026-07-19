#!/usr/bin/env bash
# Lists all live sandboxes with their power state and public host.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

az vm list -g "$SANDBOX_RG" --show-details \
  --query "[].{sandbox: tags.SANDBOX_ID, vm: name, size: hardwareProfile.vmSize, state: powerState, host: tags.PUBLIC_HOST, ip: publicIps}" \
  -o table
