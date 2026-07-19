#!/usr/bin/env bash
# Build & (re)deploy the app onto the sandbox VM.
#   - tars the repo (minus junk), scp to VM, extracts into /opt/confidant
#   - first deploy: generates /opt/confidant/.env (random SECRET_KEY, FQDN,
#     Azure Tables endpoint, ACS connection string + sender). Preserved after.
#   - docker compose up -d --build (adds GPU override if nvidia-smi present)
#
# Usage: ./deploy-app.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib.sh"

ensure_ssh_key
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

FQDN="$(deployment_output vmFqdn)"
STORAGE_ACCOUNT="$(deployment_output storageAccountName)"
TABLE_ENDPOINT="$(deployment_output tableEndpoint)"
ACS_NAME="$(deployment_output acsName)"
ACS_SENDER="$(deployment_output acsSenderAddress)"
HOST="$ADMIN_USER@$FQDN"

STATE="$(vm_power_state || true)"
if [ "$STATE" != "VM running" ]; then
  echo "VM is '$STATE' — starting it first..."
  az vm start -g "$RG" -n "$VM_NAME" -o none
fi

echo "Packaging repo..."
TARBALL="$(mktemp -t confidant-app.XXXXXX).tar.gz"
trap 'rm -f "$TARBALL"' EXIT
tar -czf "$TARBALL" -C "$REPO_DIR" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='backend/uploads' \
  --exclude='backend/data' \
  --exclude='*.db' \
  --exclude='.next' \
  --exclude='confidant landing page' \
  backend frontend infra docker-compose.prod.yml docker-compose.gpu.yml

echo "Uploading to $HOST:/opt/confidant ..."
scp "${SSH_OPTS[@]}" "$TARBALL" "$HOST:/tmp/confidant-app.tar.gz"
ssh "${SSH_OPTS[@]}" "$HOST" "tar -xzf /tmp/confidant-app.tar.gz -C /opt/confidant && rm /tmp/confidant-app.tar.gz"

# --- .env: create once, preserve afterwards -------------------------------
if ssh "${SSH_OPTS[@]}" "$HOST" "test -f /opt/confidant/.env"; then
  echo "/opt/confidant/.env exists — preserving it."
else
  echo "First deploy: generating /opt/confidant/.env"
  SECRET_KEY="$(openssl rand -hex 32)"
  ACS_CONN="$(az communication list-key --name "$ACS_NAME" -g "$RG" --query primaryConnectionString -o tsv)"
  ENV_FILE="$(mktemp -t confidant-env.XXXXXX)"
  cat > "$ENV_FILE" <<EOF
PUBLIC_HOST=$FQDN
PUBLIC_ORIGIN=https://$FQDN
SECRET_KEY=$SECRET_KEY
LOCAL_LLM_MODEL=$LOCAL_LLM_MODEL_DEFAULT
# Insights: VM managed identity has Storage Table Data Contributor on this account.
AZURE_TABLES_ENDPOINT=$TABLE_ENDPOINT
# Fallback (uncomment to use key auth instead of managed identity):
# AZURE_TABLES_CONNECTION_STRING=
ACS_CONNECTION_STRING=$ACS_CONN
ACS_SENDER_ADDRESS=$ACS_SENDER
EOF
  scp "${SSH_OPTS[@]}" "$ENV_FILE" "$HOST:/opt/confidant/.env"
  ssh "${SSH_OPTS[@]}" "$HOST" "chmod 600 /opt/confidant/.env"
  rm -f "$ENV_FILE"
fi

# --- build & start ----------------------------------------------------------
COMPOSE_FILES="-f docker-compose.prod.yml"
if ssh "${SSH_OPTS[@]}" "$HOST" "command -v nvidia-smi >/dev/null 2>&1"; then
  echo "GPU detected on VM — including docker-compose.gpu.yml"
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.gpu.yml"
fi

echo "Building and starting containers (first build takes several minutes)..."
ssh "${SSH_OPTS[@]}" "$HOST" "cd /opt/confidant && sudo docker compose $COMPOSE_FILES up -d --build"

echo
echo "Deployed. App URL: https://$FQDN"
echo "Model pull runs in background on first boot: sudo docker logs -f confidant-ollama-init-1"
