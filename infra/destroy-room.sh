#!/usr/bin/env bash
# End of engagement: DESTROY the sandbox VM and all client data on it
# (documents, vector DB, SQLite, chat). KEEPS the storage account (anonymized
# insights table) and ACS email so they survive for the next engagement.
# Re-provision a fresh room later with ./provision.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "This PERMANENTLY DESTROYS the VM '$VM_NAME' and all engagement data on it:"
echo "  - VM + OS disk (documents, Chroma vectors, SQLite DB, chat history)"
echo "  - NIC + public IP (the FQDN is released)"
echo "It KEEPS: storage account (insights table) and ACS email service."
read -r -p "Type 'destroy' to continue: " CONFIRM
[ "$CONFIRM" = "destroy" ] || { echo "Aborted."; exit 1; }

# OS disk and NIC are set to deleteOption=Delete in bicep, so deleting the VM
# removes them too. The public IP is deleted explicitly afterwards.
echo "Deleting VM (with OS disk and NIC)..."
az vm delete -g "$RG" -n "$VM_NAME" --yes -o none

echo "Deleting public IP..."
az network public-ip delete -g "$RG" -n pip-confidant

# Belt-and-braces: remove any leftover disk/NIC if deleteOption didn't apply.
for DISK in $(az disk list -g "$RG" --query "[?contains(name, '$VM_NAME')].name" -o tsv); do
  echo "Deleting leftover disk $DISK..."
  az disk delete -g "$RG" -n "$DISK" --yes -o none
done
if az network nic show -g "$RG" -n nic-confidant >/dev/null 2>&1; then
  echo "Deleting leftover NIC..."
  az network nic delete -g "$RG" -n nic-confidant
fi

echo "Room destroyed. Insights table and ACS email were preserved."
