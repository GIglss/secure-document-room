# Confidant v2 — serverless control plane

Azure Functions app **func-confidant-kcrrr5q7** (Linux Consumption, Python 3.12,
`confidant-core-rg`). Python v2 programming model: everything lives in
`function_app.py`.

| Function          | Trigger                    | Purpose                                        |
|-------------------|----------------------------|------------------------------------------------|
| `sandbox_cleanup` | Timer, every 1 minute      | Hard-deletes closed / inactive sandbox VMs     |
| `dashboard_data`  | `GET /api/dashboard-data`  | JSON aggregates from the `insights`/`sessions` tables |
| `dashboard`       | `GET /api/dashboard`       | Self-contained HTML provider dashboard         |

All table access uses the app's system-assigned managed identity via
`DefaultAzureCredential` (the core storage account has
`allowSharedKeyAccess=false`, so account keys can never be used).

## Getting the dashboard URL + key

Both HTTP routes use `authLevel=function`. Use a **host** function key (works
for every function in the app) — a per-function key would let the page load but
break its internal `dashboard-data` fetch:

```bash
KEY=$(az functionapp keys list \
  -n func-confidant-kcrrr5q7 -g confidant-core-rg \
  --query functionKeys.default -o tsv)

echo "https://func-confidant-kcrrr5q7.azurewebsites.net/api/dashboard?code=$KEY"
```

Open that URL in a browser. The page propagates the same `?code=` value to its
`dashboard-data` fetch. For raw JSON:

```bash
curl "https://func-confidant-kcrrr5q7.azurewebsites.net/api/dashboard-data?code=$KEY"
```

## INACTIVITY_MINUTES

App setting on the Function app; how long a sandbox with `status=active` may
sit without activity (`now - last_activity`) before the cleanup timer deletes
its VM. Only sessions that have actually logged in (`logged_in_at` set) are
subject to the inactivity rule. Current value: **15**.

Change it (takes effect on the next timer run — no redeploy needed):

```bash
az functionapp config appsettings set \
  -n func-confidant-kcrrr5q7 -g confidant-core-rg \
  --settings INACTIVITY_MINUTES=30
```

Rows with `status=closed` are deleted immediately regardless of this setting.

## Deletion flow

```
every 1 min: sandbox_cleanup timer
  |
  read all rows from `sessions` table (core storage, Entra RBAC)
  |
  for each row:                                (per-row try/except — one bad
  |                                             row never blocks the others)
  +-- status == "closed"  ----------------------------------+
  |                                                         |
  +-- status == "active" AND logged_in_at set               |
  |     AND now - last_activity > INACTIVITY_MINUTES -------+
  |                                                         |
  +-- anything else -> skip                                 v
                                        DELETE SANDBOX (RG confidant-sandboxes-rg)
                                          1. VM   vm-confidant-<sandbox_id>
                                             (waits; OS disk + NIC have
                                              deleteOption=Delete and cascade)
                                          2. NIC  nic-vm-confidant-<id>   } explicit
                                          3. PIP  pip-vm-confidant-<id>   } sweeps —
                                          4. any disk named vm-confidant-<id>*
                                             (PIP never cascades; NIC/disk
                                              sweeps cover stragglers)
                                          all steps tolerate 404 -> idempotent
                                                          |
                                          on success: row.status = "deleted",
                                                      row.deleted_at = now
                                          on failure: row untouched -> retried
                                                      on the next minute tick
```

## Deploying changes

Consumption Linux needs a remote (Oryx) build for Python deps:

```bash
cd infra/v2/functions
zip -r /tmp/confidant-func.zip . -x '*.pyc' -x '__pycache__/*'
az functionapp deployment source config-zip \
  -n func-confidant-kcrrr5q7 -g confidant-core-rg \
  --src /tmp/confidant-func.zip --build-remote true
```

(The app has `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and `ENABLE_ORYX_BUILD=true`
set; `--build-remote true` keeps it explicit.)

## App settings used

| Setting                 | Meaning                                              |
|-------------------------|------------------------------------------------------|
| `TABLES_ENDPOINT`       | Core storage table endpoint (Entra data-plane RBAC)  |
| `SANDBOX_RG`            | Resource group holding sandbox VMs                   |
| `INACTIVITY_MINUTES`    | Inactivity window before hard delete                 |
| `AZURE_SUBSCRIPTION_ID` | Subscription for the compute/network mgmt SDK calls  |
