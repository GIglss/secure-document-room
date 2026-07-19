#!/usr/bin/env bash
# Nuke EVERYTHING: the whole rg-confidant resource group, including the
# durable insights table and ACS email. Irreversible.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "This deletes the ENTIRE resource group '$RG':"
az resource list -g "$RG" --query "[].{name:name, type:type}" -o table || true
echo
read -r -p "Type the resource group name ('$RG') to confirm deletion: " CONFIRM
[ "$CONFIRM" = "$RG" ] || { echo "Aborted."; exit 1; }

az group delete -n "$RG" --yes
echo "Resource group '$RG' deleted."
