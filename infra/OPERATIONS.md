# Confidant — Operations Guide

One "sandbox VM" per client engagement runs the whole app (frontend, backend,
local LLM via Ollama, Caddy HTTPS) in Docker Compose. Client data lives only on
the VM. Anonymized conversation insights are written to an Azure Table Storage
table (`insights`) **outside** the VM, so they survive when the room is destroyed.

Everything lives in the resource group **`rg-confidant`** (subscription
*goneset*), so the whole solution can be slept or deleted without touching
other workloads.

## Chosen infrastructure (and why)

| Item | Value | Rationale |
|---|---|---|
| Region | `westeurope` | Preferred region; quota checked here + spaincentral + francecentral |
| VM size | `Standard_D8s_v6` (8 vCPU, 32 GB) | **No GPU quota anywhere**: NCASv3_T4 family = 0 vCPUs in all three regions, and Dsv5/Dasv5 families are also 0. D8s_v6 is unrestricted with family quota 10 and is the newest/cheapest 8-core option. NVMe-only SKU (bicep sets `diskControllerType=NVMe`). |
| LLM model | `qwen3:4b` (Ollama, CPU) | 4B model is the practical ceiling for CPU inference on 8 cores. If GPU quota is ever granted, re-provision with `GPU=true VM_SIZE=Standard_NC8as_T4_v3` and set `LOCAL_LLM_MODEL=qwen3:8b` in the VM's `.env`. |
| OS disk | 128 GB StandardSSD_LRS | Docs + Chroma + Ollama models |
| Auto-shutdown | daily 20:00 UTC | Cost safety net (DevTestLab schedule). NOTE: this *stops* the VM; it is deallocated so compute billing ends, but run `./up.sh` next morning. |

## Scripts

All scripts live in `infra/`, are idempotent where possible, and read
overrides from the environment (`RG`, `LOCATION`, `VM_SIZE`, `GPU`, ...).

| Script | What it does |
|---|---|
| `provision.sh` | Creates `rg-confidant` + deploys `main.bicep` (storage + insights table, ACS email with Azure-managed domain, VM with managed identity, NSG allowing 80/443 from anywhere and SSH only from your current public IP, role assignment, auto-shutdown). Generates `~/.ssh/confidant_vm` if missing. Prints outputs (FQDN, sender address, ...). Re-run any time. |
| `deploy-app.sh` | Tars the repo (no .git/node_modules/venv/data), scp to the VM, extracts to `/opt/confidant`, generates `.env` on first deploy (random `SECRET_KEY`, FQDN, Azure Tables endpoint, ACS connection string + sender — preserved on later deploys), then `docker compose -f docker-compose.prod.yml up -d --build`. Auto-adds the GPU compose override if `nvidia-smi` exists on the VM. |
| `up.sh` | `az vm start` — wake the engagement. Containers auto-restart. |
| `down.sh` | `az vm deallocate` — standby at ~zero compute cost. Data preserved. |
| `status.sh` | Power state, URL, current cost mode. |
| `destroy-room.sh` | End of engagement: deletes VM + OS disk + NIC + public IP (client data destroyed). **Keeps** storage (insights) and ACS email. Asks for confirmation. |
| `destroy-all.sh` | Deletes the entire resource group after confirmation. |

Typical lifecycle:

```
./provision.sh      # once per engagement
./deploy-app.sh     # after provisioning, and after each code change
./down.sh           # evenings / idle periods
./up.sh             # resume
./destroy-room.sh   # engagement over -> client data destroyed
./provision.sh      # next engagement gets a fresh room (new FQDN)
```

Note: SSH is allowed only from the public IP you had when running
`provision.sh`. If your IP changes, just re-run `provision.sh` — it updates
the NSG rule in place.

## What costs what (approximate, EUR, westeurope, July 2026 list prices)

| State | Compute | Disk (128 GB StandardSSD) | Public IP | Storage acct + ACS | Total |
|---|---|---|---|---|---|
| **Running** | ~0.40–0.45/h (~300/mo if 24×7) | ~9/mo | ~3.6/mo | < 1/mo | **~0.42/h + ~13/mo fixed** |
| **Deallocated** (`down.sh`) | 0 | ~9/mo | ~3.6/mo | < 1/mo | **~13/mo** |
| **Room destroyed** (`destroy-room.sh`) | 0 | 0 | 0 | < 1/mo | **< 1/mo** |
| **Everything destroyed** | 0 | 0 | 0 | 0 | **0** |

- ACS email: ~0.0009 EUR per email — negligible at verification-code volume.
- Table storage: cents per month at insights volume.
- A working day (8 h) of running costs roughly **3.5 EUR**.
- The 20:00 UTC auto-shutdown caps a forgotten VM at ~1 extra evening-day of cost.

## Insights durability model

- Backend writes anonymized Q&A insights to table `insights` in the storage
  account via `AZURE_TABLES_ENDPOINT` + the VM's **system-assigned managed
  identity** (role: *Storage Table Data Contributor*, assigned in bicep).
- Works from inside containers (IMDS at 169.254.169.254 is reachable).
- Key-based fallback: put `AZURE_TABLES_CONNECTION_STRING` in
  `/opt/confidant/.env` (get it with
  `az storage account show-connection-string -g rg-confidant -n <account>`).

## Email sender

ACS Email with an **Azure-managed domain**: sender is
`DoNotReply@<guid>.azurecomm.net` (exact value in provision outputs and in the
VM's `.env` as `ACS_SENDER_ADDRESS`). Azure-managed domains are limited
(~100 emails/hour) — fine for verification codes. For higher volume or a
branded sender, add a custom domain to the Email Communication Service later.

## Moving to a dedicated subscription later

The user-level goal was isolation; a resource group delivers that for cost
tracking and lifecycle. To go further:

1. Create a new subscription under the same billing account (needs billing
   admin rights on the account — portal: Subscriptions → Add).
2. Move the RG: `az resource move` / portal "Move to another subscription".
   Storage accounts and VMs move fine; **Communication Services resources also
   support subscription move**, but the VM must be deallocated during the move
   and role assignments do NOT move — re-run `provision.sh` afterwards to
   restore the managed-identity role assignment.
3. Simpler alternative: `destroy-all.sh` here, switch `az account set -s <new>`,
   re-run `provision.sh` (loses accumulated insights unless you copy the table
   first with `az storage entity` / AzCopy).
