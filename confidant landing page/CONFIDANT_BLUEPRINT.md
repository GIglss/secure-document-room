# Confidant Landing-Page Orchestrator — Corrected Blueprint

**Decisions baked in**
- **Email path:** Azure Communication Services (ACS) Email. The Function sends mail directly. **No Logic App, no Office 365 connector, no interactive OAuth consent.** Uses an Azure-managed (pre-verified) sender domain so provisioning is fully non-interactive.
- **Structure:** ONE Static Web App bound to one domain (`goneset.com`), each landing page is a folder (`/confidant`, `/otherpage`, …). Adding a page = add a folder + commit. No new Azure resources per page.
- **Runtime:** Node 18 (SWA managed functions). Not switching to Python/C# — no benefit here.

**Corrected flow**
```
[ Visitor Browser ]
     │  (1) GA4 pageview / click events
     ▼
[ HTML form submit ] --POST /api/DemoRequest--> [ Azure Static Web App (Free) ]
                                                       │  managed Node function
                                                       ▼
                                        [ @azure/communication-email ]
                                                       │  ACS Email (pre-verified domain)
                                                       ▼
                                                 [ Your Inbox ]
```

---

## Module / skill decomposition (for the orchestrator)

| Module | Responsibility | Idempotent? |
|---|---|---|
| `scaffold-page` | Generate/refresh a page folder + form + GA tag from template | yes |
| `git-sync` | init / commit / create GitHub repo / push | yes (create is create-or-skip) |
| `provision-core` | RG + ACS Email + managed domain + Communication Service | yes (`az group create` etc. are upsert) |
| `provision-swa` | Create SWA, link GitHub, inject app settings | yes |
| `bind-domain` | Custom domain + DNS (one-time, has a manual DNS step) | partial |
| `verify-smoke` | Hit the deployed page, submit a test lead, assert 200 + inbox | n/a |

The **one-time manual steps** (cannot be fully automated) are listed at the very bottom — surface these to the user before running.

---

## Phase 1 — Source files

Target layout (folders-per-page; the `api/` folder is shared by ALL pages):

```
.
├── confidant/
│   └── index.html
├── staticwebapp.config.json
├── 404.html
└── api/
    ├── host.json
    ├── package.json
    └── DemoRequest/
        ├── function.json
        └── index.js
```

### `confidant/index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Confidant — Request a Demo</title>
  <!-- Google Analytics 4 (replace G-XXXXXXXXXX with your Measurement ID) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-XXXXXXXXXX');
  </script>
</head>
<body>
  <h1>Request a Demo</h1>
  <form id="demoForm">
    <label for="email">Business Email</label>
    <input type="email" id="email" name="email" required placeholder="name@company.com" />
    <button type="submit" id="submitBtn">Submit Request</button>
    <p id="statusMsg" role="status" aria-live="polite"></p>
  </form>
  <script>
    const form = document.getElementById('demoForm');
    const statusMsg = document.getElementById('statusMsg');

    document.getElementById('submitBtn').addEventListener('click', () => {
      gtag('event', 'demo_click', { event_category: 'Engagement', event_label: 'confidant' });
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      statusMsg.textContent = 'Sending…';
      const email = document.getElementById('email').value;
      try {
        const res = await fetch('/api/DemoRequest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // `page` lets the shared function label which landing page the lead came from
          body: JSON.stringify({ email, page: 'confidant' })
        });
        if (res.ok) {
          gtag('event', 'generate_lead', { event_category: 'Engagement', event_label: 'confidant' });
          statusMsg.textContent = 'Thanks — your request has been sent.';
          form.reset();
        } else {
          statusMsg.textContent = 'Something went wrong. Please try again.';
        }
      } catch (err) {
        statusMsg.textContent = 'Network error. Please try again.';
      }
    });
  </script>
</body>
</html>
```

### `staticwebapp.config.json`
```json
{
  "platform": { "apiRuntime": "node:18" },
  "navigationFallback": {
    "rewrite": "/confidant/index.html",
    "exclude": ["/api/*", "/*.{css,js,png,jpg,jpeg,svg,ico,webp}"]
  },
  "globalHeaders": {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' https://www.googletagmanager.com 'unsafe-inline'; img-src 'self' https://www.google-analytics.com https://*.googletagmanager.com; connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com"
  },
  "responseOverrides": { "404": { "rewrite": "/404.html" } }
}
```
> Note: SWA serves `confidant/index.html` at `/confidant/`. When you add a real root page, point `navigationFallback.rewrite` at it (or add per-folder routes). The CSP above is what GA4 needs; tighten `'unsafe-inline'` later if you move GA to a nonce.

### `api/host.json`
```json
{ "version": "2.0" }
```

### `api/package.json`
```json
{
  "name": "confidant-api",
  "version": "1.0.0",
  "dependencies": {
    "@azure/communication-email": "^1.0.0"
  }
}
```

### `api/DemoRequest/function.json`
```json
{
  "bindings": [
    { "authLevel": "anonymous", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["post"] },
    { "type": "http", "direction": "out", "name": "res" }
  ]
}
```

### `api/DemoRequest/index.js`
```js
const { EmailClient } = require("@azure/communication-email");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

module.exports = async function (context, req) {
  const email = req.body && typeof req.body.email === "string" ? req.body.email.trim() : "";
  const page = (req.body && req.body.page) || "unknown";

  if (!EMAIL_RE.test(email) || email.length > 254) {
    context.res = { status: 400, body: "Valid email required." };
    return;
  }

  const conn = process.env.ACS_CONNECTION_STRING;
  const sender = process.env.SENDER_ADDRESS;
  const recipient = process.env.RECIPIENT_ADDRESS;
  if (!conn || !sender || !recipient) {
    context.log.error("Missing ACS config");
    context.res = { status: 500, body: "Email backend misconfigured." };
    return;
  }

  try {
    const client = new EmailClient(conn);
    const poller = await client.beginSend({
      senderAddress: sender,
      content: {
        subject: `[Lead] New ${page} demo request`,
        plainText: `New demo request\n\nPage: ${page}\nEmail: ${email}\nTime: ${new Date().toISOString()}`
      },
      recipients: { to: [{ address: recipient }] },
      replyTo: [{ address: email }]
    });
    await poller.pollUntilDone();
    context.res = { status: 200, body: "Dispatched." };
  } catch (err) {
    context.log.error("ACS send failed:", err && err.message);
    context.res = { status: 500, body: "Send failure." };
  }
};
```

---

## Phase 2 — Git + GitHub (non-interactive)

```bash
# Requires: gh CLI authenticated WITH `workflow` scope
#   gh auth login   (or)   gh auth refresh -h github.com -s workflow
GH_OWNER=$(gh api user --jq .login)
REPO_NAME="goneset-landing"

git init
git add .
git commit -m "feat: confidant landing page, GA4 tag, ACS email lead API"
git branch -M main

# create-or-skip: creates the remote repo AND pushes in one step
gh repo create "$REPO_NAME" --private --source=. --remote=origin --push
GH_REPO="https://github.com/$GH_OWNER/$REPO_NAME"
echo "Repo: $GH_REPO"
```

---

## Phase 3 — Azure provisioning (ACS Email + SWA)

> Run after `az login`. `az extension add --name communication` is auto-installed by the first `az communication` call, or add it explicitly.

```bash
# ---- variables ----
SUB_ID=$(az account show --query id -o tsv)
RG="confidant-rg"
RG_LOCATION="eastus"
SWA_LOCATION="eastus2"          # SWA is region-limited: westus2|centralus|eastus2|westeurope|eastasia
ACS_DATA_LOCATION="unitedstates"
EMAIL_SVC="confidant-email"
ACS_NAME="confidant-acs"
SWA_NAME="goneset-swa"
RECIPIENT="gon.iglesias.g@gmail.com"   # your inbox
# GH_REPO comes from Phase 2

az extension add --name communication --only-show-errors
az group create -n "$RG" -l "$RG_LOCATION"

# 1) Email Communication Service
az communication email create -n "$EMAIL_SVC" -g "$RG" -l global \
  --data-location "$ACS_DATA_LOCATION"

# 2) Azure-managed, PRE-VERIFIED sender domain (no DNS needed)
az communication email domain create -n AzureManagedDomain \
  --email-service-name "$EMAIL_SVC" -g "$RG" -l global \
  --domain-management AzureManaged

SENDER_DOMAIN=$(az communication email domain show -n AzureManagedDomain \
  --email-service-name "$EMAIL_SVC" -g "$RG" --query fromSenderDomain -o tsv)
SENDER_ADDRESS="DoNotReply@$SENDER_DOMAIN"
DOMAIN_ID=$(az communication email domain show -n AzureManagedDomain \
  --email-service-name "$EMAIL_SVC" -g "$RG" --query id -o tsv)

# 3) Communication Services resource, linked to the domain
az communication create -n "$ACS_NAME" -g "$RG" -l global \
  --data-location "$ACS_DATA_LOCATION" --linked-domains "$DOMAIN_ID"

ACS_CONN=$(az communication list-key -n "$ACS_NAME" -g "$RG" \
  --query primaryConnectionString -o tsv)

# 4) Static Web App + GitHub Actions CI/CD (non-interactive via gh token)
az staticwebapp create -n "$SWA_NAME" -g "$RG" -l "$SWA_LOCATION" \
  --source "$GH_REPO" --branch main \
  --app-location "/" --api-location "api" --output-location "" \
  --token "$(gh auth token)"

# 5) Inject secrets/config into SWA (this is what makes the function work)
az staticwebapp appsettings set -n "$SWA_NAME" -g "$RG" --setting-names \
  ACS_CONNECTION_STRING="$ACS_CONN" \
  SENDER_ADDRESS="$SENDER_ADDRESS" \
  RECIPIENT_ADDRESS="$RECIPIENT"
```

---

## Phase 4 — Sync the generated CI workflow locally

Azure commits `.github/workflows/azure-static-web-apps-*.yml` to `main`.

```bash
git pull --rebase origin main
```

---

## Phase 5 — Custom domain + add-a-page flow

**Bind `goneset.com`** (one-time; has a manual DNS step at your registrar):
```bash
# Apex domain validation returns a TXT record you must add at your DNS host, then re-run to validate.
az staticwebapp hostname set -n "$SWA_NAME" -g "$RG" --hostname goneset.com
```

**Add another page later** (no Azure changes needed):
```bash
mkdir -p otherpage && cp confidant/index.html otherpage/index.html
# edit title / GA label / body:{page:'otherpage'}
git add otherpage && git commit -m "feat: add otherpage landing" && git push
# CI redeploys automatically -> goneset.com/otherpage
```

---

## Cost reality (honest)
- **SWA Free tier:** $0/month.
- **ACS Email:** no fixed fee, ~**$0.00025 per email** + tiny data charge. At smoke-test volume this is cents/month — effectively free but **not literally $0**.
- No Logic App = no per-action connector billing.

## Deliverability note
Mail sends from `…azurecomm.net`. It will reach your inbox fine; Gmail may show "via azurecomm.net". If you later want mail **from `@goneset.com`**, switch the domain to `--domain-management CustomerManaged` and add the SPF/DKIM DNS records ACS gives you (optional upgrade).

---

## One-time manual steps (cannot be fully automated — surface these first)
1. `az login` — you are currently **not** logged in.
2. `gh auth login` **with `workflow` scope** (needed so `az staticwebapp create --token` can write the Actions workflow).
3. **GA4 Measurement ID** — create a GA4 property in the Google Analytics console and replace `G-XXXXXXXXXX` in the HTML. (No CLI for this.)
4. **DNS for `goneset.com`** — add the TXT/ALIAS records SWA returns, at your domain registrar.
5. (Optional) Custom `@goneset.com` sender — requires CustomerManaged domain + DKIM/SPF DNS records.

## What changed vs. the original blueprint (why)
- Removed Logic App + Office 365 connector — its OAuth consent is an interactive browser step that **cannot** be automated; it was the #1 blocker.
- Replaced with ACS Email + Azure-managed pre-verified domain — fully CLI-provisionable.
- Fixed the GA `<script src>` (was a dead URL).
- Fixed the fake `git remote`/`--source https://github.com` placeholders → real repo via `gh repo create`.
- Non-interactive CI: `--token $(gh auth token)` instead of `--login-with-github` (device-code prompt).
- SWA region corrected to `eastus2` (SWA isn't offered in `eastus`).
- One SWA / folders-per-page instead of one-RG-per-run (matches the `goneset.com/<page>` goal).
- Added `staticwebapp.config.json` (routing, security headers, CSP for GA), `host.json`, `package.json`.
- Server-side email validation + reply-to on the lead email.
```
