#!/usr/bin/env bash
# Shared config for the Confidant ops scripts. Override via environment.
set -euo pipefail

export RG="${RG:-rg-confidant}"
export LOCATION="${LOCATION:-westeurope}"
export VM_NAME="${VM_NAME:-vm-confidant}"
export DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-confidant}"
export SSH_KEY="${SSH_KEY:-$HOME/.ssh/confidant_vm}"
export ADMIN_USER="${ADMIN_USER:-azureuser}"

# Chosen from subscription quota at design time (see OPERATIONS.md):
# no NCASv3_T4 (GPU) quota in westeurope/spaincentral/francecentral -> CPU.
export VM_SIZE="${VM_SIZE:-Standard_D8s_v6}"
export GPU="${GPU:-false}"
export LOCAL_LLM_MODEL_DEFAULT="${LOCAL_LLM_MODEL_DEFAULT:-qwen3:4b}"

deployment_output() { # deployment_output <outputName>
  az deployment group show -g "$RG" -n "$DEPLOYMENT_NAME" \
    --query "properties.outputs.$1.value" -o tsv
}

ensure_ssh_key() {
  if [ ! -f "$SSH_KEY" ]; then
    echo "Generating SSH key at $SSH_KEY"
    ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "confidant-vm" -q
  fi
}

vm_power_state() {
  az vm get-instance-view -g "$RG" -n "$VM_NAME" \
    --query "instanceView.statuses[?starts_with(code,'PowerState/')].displayStatus | [0]" -o tsv
}
