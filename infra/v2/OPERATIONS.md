# Confidant v2 — Operations

Two-plane design in subscription `goneset` (`0f94670d-...5886`), region `westeurope`:

- **Control plane** (`confidant-core-rg`, persistent, cheap): VNet + NSG, analytics
  storage (tables `insights`/`sessions` + private endpoint), Key Vault + CMK + Disk
  Encryption Set, Compute Gallery, Function app shell (listener code deployed separately).
- **Sandboxes** (`confidant-sandboxes-rg`, ephemeral): one E-series VM per client from
  the gallery gold image, hard-deleted after inactivity.

Never touch `confidant-rg` or `confidant-landingpage-rg` from these scripts (v1 / landing page).

## Buttons

| Script | What it does |
|---|---|
| `./deploy-core.sh` | Idempotent: creates both RGs + deploys `main.bicep` (whole control plane). Re-run any time. |
| `./spawn-sandbox.sh <id>` | Deploys `sandbox.bicep` into the sandboxes RG, prints `https://confidant-<id>.westeurope.cloudapp.azure.com`. Needs ≥1 gallery image version. |
| `./destroy-sandbox.sh <id>` | Hard-deletes that sandbox's VM + NIC + public IP + OS disk. |
| `./list-sandboxes.sh` | Table of live sandboxes (state, host, IP). |
| `./status.sh` | Control-plane inventory, function state, image versions, sandboxes. |
| `./destroy-everything.sh` | Deletes BOTH v2 RGs after typed confirmation. **Key Vault purge protection means the vault name stays locked (soft-deleted, unpurgeable) for 90 days.** |

Env overrides: `VM_SIZE`, `OS_DISK_MODE` (`Persistent` \| `EphemeralNvme` \| `EphemeralCache`), `LOCATION`, `SSH_KEY_FILE`, `DEPLOYER_IP`.

## VM size + quota (checked 2026-07-18)

Regional cap: **10 vCPUs** in westeurope, 0 in use. Family findings:

| Size | Family quota | Ephemeral OS disk | Linux $/h (westeurope) |
|---|---|---|---|
| Standard_E4s_v5 (requested) | **0** — blocked | — | — |
| **Standard_E4s_v6 (chosen)** | 10 free | **No** (no temp disk, no cache disk on v6 s-sizes) | **$0.319 (~€0.29)** |
| Standard_E4as_v5 | 0 — blocked | — | — |
| Standard_E4ds_v6 (ephemeral option) | 10 free (Edsv6) | **Yes** — local NVMe (`NvmeDisk` placement) | $0.395 (~€0.36) |
| D8s_v6 / D4s_v6 | 10 free (Dsv6) | No | — |

Consequences:

- Default: `Standard_E4s_v6` + **Persistent** 64 GB Premium SSD OS disk with
  `deleteOption: Delete` (dies with the VM) and CMK encryption via the DES.
- Want a true ephemeral OS disk? `VM_SIZE=Standard_E4ds_v6 OS_DISK_MODE=EphemeralNvme ./spawn-sandbox.sh <id>`
  (same 4 vCPU / 32 GB; ephemeral disks can't use a DES — they inherit the
  CMK-encrypted gallery image encryption). `EphemeralCache` exists for Esv5-style
  sizes if quota is ever granted.
- One sandbox eats 4 of the 10 regional vCPUs → **max 2 concurrent sandboxes**
  until a quota increase.

## Storage networking decision

The core storage account keeps **public network access enabled with
`defaultAction: Allow`**, plus a **private endpoint** (table sub-resource) in
`snet-endpoints` with the `privatelink.table.core.windows.net` zone linked to the VNet. Why:

- The consumption Function app lives outside the VNet with no fixed egress, and is
  **not** covered by the "trusted Azure services" firewall bypass — a default-deny
  firewall would silently break its table access. VNet-integrating the function
  needs a premium/flex plan (cost).
- Compensating controls: `allowSharedKeyAccess: false` (no account keys, no SAS —
  data plane is **Entra RBAC only**), TLS 1.2 minimum, HTTPS only.
- In-VNet sandbox VMs resolve the account to the private endpoint, so their table
  traffic never leaves the VNet regardless.

If the function later moves to a VNet-integrated plan, flip `defaultAction` to
`Deny` in `core.bicep` and re-run `./deploy-core.sh`.

## NSG / egress: the ACME carve-out

`nsg-sandbox` (on `snet-sandbox`):

- **Inbound**: 443/TCP from Internet; SSH only from the deployer IP
  (`AllowSshFromDeployerDebugOnly` — debug-only, delete once stable:
  `az network nsg rule delete -g confidant-core-rg --nsg-name nsg-sandbox -n AllowSshFromDeployerDebugOnly`);
  everything else denied (including VM↔VM).
- **Outbound**: VNet (private endpoint), DNS to Azure resolver `168.63.129.16` only,
  and **TCP 80+443 to Internet — this is the single egress carve-out**, needed for
  ACME/Let's Encrypt issuance at first boot (directory + HTTP-01). Everything else denied.

To close the carve-out after a sandbox has its cert (breaks renewals — sandboxes
live <hours, so usually irrelevant):

```bash
az network nsg rule update -g confidant-core-rg --nsg-name nsg-sandbox \
  -n AllowHttpHttpsOutAcmeCarveout --access Deny
```

(Subnet-wide — flip back to `Allow` before spawning a sandbox that needs a fresh cert.)

## 15-minute auto-delete

The Function app (`func-confidant-*`) is a **shell**: settings
`INACTIVITY_MINUTES=15`, `SANDBOX_RG=confidant-sandboxes-rg`, `TABLES_ENDPOINT=<core
table endpoint>` are wired; the listener code is deployed by another agent. Intended
flow: sandboxes heartbeat into the `sessions` table via their system MI (Storage Table
Data Contributor); a timer function reads `sessions`, and any sandbox idle ≥15 min is
hard-deleted (VM, NIC, PIP) using the function MI's Virtual Machine Contributor +
Network Contributor on the sandboxes RG. Reader on the core RG lets it resolve
gallery/subnet ids.

## CMK / gallery

- Key Vault `kv-conf-<suffix>` (RBAC mode, purge protection ON) holds RSA-3072 key
  `cmk-gallery`; DES `des-confidant-gallery` wraps it (its MI has Key Vault Crypto
  Service Encryption User).
- Gallery `confidant_gallery`, image definition `confidant-sandbox` (Linux Gen2,
  publisher `confidant` / offer `sandbox` / sku `e4s-cpu`, NVMe-capable — required
  by v6 sizes). When the image build phase publishes versions, encrypt them with the
  DES id from `./deploy-core.sh` outputs (`diskEncryptionSetId`).

## Cost

| Item | Idle monthly (approx) |
|---|---|
| VNet, NSG, gallery + image definition, DES, RGs | €0 |
| Storage (LRS tables, tiny) + function storage | ~€0.10 |
| Key Vault (per-operation billing, idle) | ~€0.05 |
| Private DNS zone | ~€0.45 |
| Function app (consumption, idle/low volume) | ~€0 |
| **Private endpoint** | **~€6.80 (€0.0095/h)** |
| **Control plane idle total** | **~€7.5/mo** (~€0.7/mo if you drop the private endpoint) |

The private endpoint is the entire idle cost. If €1–3/mo matters more than keeping
sandbox→table traffic private, delete `pe-*-table` + the DNS zone (data plane is
still Entra-RBAC-only over TLS).

Per sandbox-hour: **Standard_E4s_v6 ≈ $0.32/h (~€0.29)** + 64 GB Premium SSD OS disk
(~€0.013/h) + public IP (~€0.004/h) ≈ **~€0.31/h**, only while it exists — the
15-min reaper keeps the meter honest. `E4ds_v6` ephemeral variant: $0.395/h, no disk cost.
