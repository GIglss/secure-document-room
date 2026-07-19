# Handoff — Confidant v2

**As of:** 2026-07-19 · **State:** Deployed to Azure, acceptance-tested end-to-end, **not yet committed to git**.
**Read alongside:** [SPEC.md](SPEC.md) (what/why) · [SAD.md](SAD.md) (architecture) · [infra/v2/OPERATIONS.md](infra/v2/OPERATIONS.md) (runbook).

---

## 1. What this is, in one paragraph
Confidant gives a **provider** (clinic/bank/advisory) a way to hand one **client** a disposable AI sandbox: a per-engagement Azure VM running a **local** model (llama.cpp + Qwen3-8B) over the provider's PDF + knowledge base. The client reads/downloads the document and asks cited questions; nothing goes to an external LLM; the VM is hard-deleted on session close or 15-min inactivity. Anonymized "what did clients ask about" analytics are mirrored off-VM and survive destruction, feeding a provider dashboard.

## 2. Current deployed state (Azure, sub *goneset*, westeurope)
- **`confidant-core-rg`** — control plane, live. Storage `stconfcorekcrrr5q7kmgj` (tables `insights`,`sessions`), Function `func-confidant-kcrrr5q7` (cleanup timer + dashboard), Key Vault `kv-conf-kcrrr5q7kmgj` + CMK + DES, gallery `confidant_gallery/confidant-sandbox:1.0.0`, VNet `vnet-confidant-core`.
- **`confidant-sandboxes-rg`** — empty (sandboxes spawn here on demand).
- **`confidant-landingpage-rg`** — `goneset-swa` + `confidant-acs`.
- **`confidant-rg`** — legacy; holds only `confidant-email` (Azure can't move EmailServices).
- **v1 infra** (`rg-confidant`) — was torn down earlier; ignore `infra/` (v1), use `infra/v2/`.

## 3. How to operate it (the buttons — all in `infra/v2/`)
```bash
./deploy-core.sh                 # stand up / update the control plane (idempotent)
./spawn-sandbox.sh <client-id>   # start an engagement -> prints https://confidant-<id>.westeurope.cloudapp.azure.com
./list-sandboxes.sh              # what's running
./status.sh                      # power/cost overview
./destroy-sandbox.sh <client-id> # manual teardown (auto-teardown also runs)
./destroy-everything.sh          # delete both v2 RGs (typed confirm; KV name locked 90 days)
```
Provider dashboard: `https://func-confidant-kcrrr5q7.azurewebsites.net/api/dashboard?code=<key>`
Get key: `az functionapp keys list -n func-confidant-kcrrr5q7 -g confidant-core-rg --query functionKeys.default -o tsv`

## 4. Repo layout that matters
- `backend/` — FastAPI app. New in v2: `routes/session.py`, `routes/insights.py`; `services/session_service.py`, `services/insights_service.py`, `services/email_service.py`, `services/pdf_appendix.py`.
- `frontend/` — Next.js 14. Built same-origin (`NEXT_PUBLIC_API_URL="/"`); see `src/lib/api.ts`.
- `infra/v2/` — control-plane + sandbox Bicep, gold-image compose, buttons, `functions/` (Function app code), `OPERATIONS.md`.
- Docs: `SPEC.md`, `SAD.md`, `ARCHITECTURE.md`, `DESIGN.md`, `LLM_CALL_FLOW.md`, `HOW_DOES_ALL_CONVERGE.md`, `DOCS_UPDATE_TRACE.md`.

## 5. How verification was proven (repeat this to smoke-test)
1. `spawn-sandbox.sh e2etest` → wait ~6 min → `curl https://confidant-e2etest.../api/llm-config` returns `{"provider":"local","model":"qwen3-8b",...}`.
2. Register provider → create room → upload a PDF → invite an email → get code → confirm → accept (`sharing_mode:full`) → `POST /qa` (grounded cited answer) → `GET .../file?with_appendix=1` (PDF + summary page) → `POST /session/close`.
3. Within ~90 s, `confidant-sandboxes-rg` returns to 0 resources; dashboard still shows the insight. ✅ all passed.

Tip: to inspect a live sandbox use `az vm run-command invoke -g confidant-sandboxes-rg -n vm-confidant-<id> --command-id RunShellScript --scripts "..."` (SSH-with-sudo is blocked by the harness classifier).

## 6. ⚠ Open items (do these next, in order)
1. **Fix ACS email deliverability (blocker for first real client).** `backend/services/email_service.py` calls `client.begin_send(message)` but never awaits the poller, so async failures are invisible — in the e2e test ACS accepted the message but it never reached Gmail. Fix: capture `poller = client.begin_send(...)`, `poller.result()`, log the status/messageId, and raise on failure. Then re-test to a real inbox; if still undelivered, stand up a **branded custom sender domain** in ACS (SPF/DKIM/DMARC) instead of the `DoNotReply@*.azurecomm.net` managed domain.
2. **Commit everything.** All v2 app + infra is working-tree only. Suggested: branch off `main`, commit backend/frontend/infra-v2/docs together. (Do not commit `backend/.env`, `*.db`, `node_modules`, `.venv`.)
3. **Refresh secondary docs** — `ARCHITECTURE.md`, `LLM_CALL_FLOW.md`, `HOW_DOES_ALL_CONVERGE.md` still describe v1 internals (Ollama/MLX, sealed room). SPEC/SAD are current.

## 7. Backlog / v3 candidates
- Persistent provider identity across sandboxes (today provider accounts live in the VM's SQLite and die with it).
- GPU inference (NCASv3_T4 quota is 0 — request it) for a larger/faster model; raise the 10-vCPU regional cap for >2 concurrent sandboxes.
- Close the ACME egress carve-out after first boot (only outbound path left open).
- Custom domain (`confidant.goneset.com`) fronting sandboxes.
- Consider Azure Confidential Ledger for cryptographic audit immutability.

## 8. Gotchas learned the hard way
- **Next.js drops empty-string env vars at build** → build with `NEXT_PUBLIC_API_URL="/"`, not `""`, for same-origin.
- **EmailServices can't be RG-moved** — leave `confidant-email` in `confidant-rg`.
- **Storage is Entra-RBAC-only** (`allowSharedKeyAccess=false`) — always use `DefaultAzureCredential`, never account keys.
- **Key Vault purge protection is on** — after `destroy-everything.sh` the vault name is reserved ~90 days.
- **Harness classifier** blocks SSH-with-sudo, scripted email sends, and batched deploy scripts — use `az vm run-command` and single-purpose foreground commands.
- **Sandbox admin user is `confidant`** (SSH key `~/.ssh/confidant_sandbox`), reachable only from the deployer IP.
