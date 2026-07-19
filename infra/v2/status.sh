#!/usr/bin/env bash
# Shows control-plane health and live sandboxes.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

echo "== Control plane ($CORE_RG) =="
az resource list -g "$CORE_RG" --query "[].{name: name, type: type}" -o table 2>/dev/null \
  || { echo "(core RG not found — run ./deploy-core.sh)"; exit 0; }

echo ""
echo "== Function app =="
FUNC="$(az functionapp list -g "$CORE_RG" --query "[0].{name: name, state: state, host: defaultHostName}" -o table 2>/dev/null)"
echo "${FUNC:-<none>}"

echo ""
echo "== Gallery image versions (sandboxes need >= 1) =="
az sig image-version list -g "$CORE_RG" --gallery-name confidant_gallery \
  --gallery-image-definition confidant-sandbox -o table 2>/dev/null || echo "(none yet)"

echo ""
echo "== Sandboxes ($SANDBOX_RG) =="
"$SCRIPT_DIR/list-sandboxes.sh"
