"""Confidant v2 control plane — Azure Functions (Python v2 model).

Functions:
  - sandbox_cleanup   timer, every 1 minute: deletes closed / inactive sandbox VMs.
  - dashboard_data    GET /api/dashboard-data (function key): insights aggregates JSON.
  - dashboard         GET /api/dashboard (function key): self-contained HTML dashboard.

All storage data-plane access uses Entra RBAC (DefaultAzureCredential) — the core
storage account has allowSharedKeyAccess=false, so account keys never work here.
"""

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

import azure.functions as func
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

app = func.FunctionApp()

TABLES_ENDPOINT = os.environ.get("TABLES_ENDPOINT", "")
SANDBOX_RG = os.environ.get("SANDBOX_RG", "confidant-sandboxes-rg")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

# Lazily-created singletons (one credential / client set per worker).
_credential = None
_table_service = None
_compute_client = None
_network_client = None


def _cred():
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _tables():
    global _table_service
    if _table_service is None:
        _table_service = TableServiceClient(endpoint=TABLES_ENDPOINT, credential=_cred())
    return _table_service


def _compute():
    global _compute_client
    if _compute_client is None:
        _compute_client = ComputeManagementClient(_cred(), SUBSCRIPTION_ID)
    return _compute_client


def _network():
    global _network_client
    if _network_client is None:
        _network_client = NetworkManagementClient(_cred(), SUBSCRIPTION_ID)
    return _network_client


def _parse_iso(value):
    """Parse an ISO-8601 string to an aware UTC datetime. Returns None on failure."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Sandbox cleanup timer
# ---------------------------------------------------------------------------

def _delete_sandbox_resources(sandbox_id: str) -> None:
    """Delete the sandbox VM and every resource that does not cascade.

    Naming (see infra/v2/sandbox.bicep):
      VM   = vm-confidant-<sandbox_id>
      NIC  = nic-vm-confidant-<sandbox_id>   (deleteOption=Delete → cascades, but verify)
      PIP  = pip-vm-confidant-<sandbox_id>   (does NOT cascade)
      Disk = <vmName>_...                    (deleteOption=Delete → cascades, but verify)

    Idempotent: every step tolerates 'already gone'. Raises on a real failure so
    the caller leaves the row un-marked and the next timer run retries.
    """
    vm_name = f"vm-confidant-{sandbox_id}"
    nic_name = f"nic-{vm_name}"
    pip_name = f"pip-{vm_name}"
    compute = _compute()
    network = _network()

    # 1. VM (cascades NIC + OS disk via deleteOption=Delete, but we verify below).
    try:
        logging.info("cleanup[%s]: deleting VM %s", sandbox_id, vm_name)
        compute.virtual_machines.begin_delete(SANDBOX_RG, vm_name).result()
    except ResourceNotFoundError:
        logging.info("cleanup[%s]: VM %s already gone", sandbox_id, vm_name)
    except HttpResponseError as e:
        if e.status_code == 404:
            logging.info("cleanup[%s]: VM %s already gone", sandbox_id, vm_name)
        else:
            raise

    # 2. NIC — normally cascade-deleted with the VM; delete explicitly if it lingers.
    try:
        network.network_interfaces.begin_delete(SANDBOX_RG, nic_name).result()
        logging.info("cleanup[%s]: NIC %s deleted", sandbox_id, nic_name)
    except ResourceNotFoundError:
        pass
    except HttpResponseError as e:
        if e.status_code != 404:
            raise

    # 3. Public IP — never cascades; must be deleted after the NIC releases it.
    try:
        network.public_ip_addresses.begin_delete(SANDBOX_RG, pip_name).result()
        logging.info("cleanup[%s]: public IP %s deleted", sandbox_id, pip_name)
    except ResourceNotFoundError:
        pass
    except HttpResponseError as e:
        if e.status_code != 404:
            raise

    # 4. Disks — the OS disk cascades via deleteOption=Delete, but sweep for
    #    leftovers named after the VM (Azure names the OS disk '<vmName>_...').
    for disk in compute.disks.list_by_resource_group(SANDBOX_RG):
        if disk.name == vm_name or disk.name.startswith(f"{vm_name}_"):
            if disk.managed_by:
                logging.warning(
                    "cleanup[%s]: disk %s still attached to %s, skipping",
                    sandbox_id, disk.name, disk.managed_by,
                )
                continue
            logging.info("cleanup[%s]: deleting leftover disk %s", sandbox_id, disk.name)
            compute.disks.begin_delete(SANDBOX_RG, disk.name).result()


@app.timer_trigger(schedule="0 */1 * * * *", arg_name="timer", run_on_startup=False)
def sandbox_cleanup(timer: func.TimerRequest) -> None:
    """Every minute: delete sandboxes that are closed, or active-but-inactive
    for more than INACTIVITY_MINUTES. Never throws — per-row errors are logged
    and retried on the next run."""
    inactivity_minutes = float(os.environ.get("INACTIVITY_MINUTES", "15"))
    now = datetime.now(timezone.utc)

    try:
        sessions = _tables().get_table_client("sessions")
        rows = list(sessions.list_entities())
    except Exception:
        logging.exception("sandbox_cleanup: could not read sessions table")
        return

    for row in rows:
        try:
            status = str(row.get("status", "")).lower()
            sandbox_id = row.get("sandbox_id") or row.get("RowKey")

            should_delete = False
            reason = ""
            if status == "closed":
                should_delete = True
                reason = "closed"
            elif status == "active":
                if _parse_iso(row.get("logged_in_at")) is not None:
                    last = _parse_iso(row.get("last_activity"))
                    if last is not None and (now - last) > timedelta(minutes=inactivity_minutes):
                        should_delete = True
                        reason = f"inactive > {inactivity_minutes:g} min"

            if not should_delete:
                continue

            logging.info("sandbox_cleanup: deleting sandbox %s (%s)", sandbox_id, reason)
            _delete_sandbox_resources(str(sandbox_id))

            row["status"] = "deleted"
            row["deleted_at"] = datetime.now(timezone.utc).isoformat()
            sessions.update_entity(mode=UpdateMode.MERGE, entity=dict(row))
            logging.info("sandbox_cleanup: sandbox %s marked deleted", sandbox_id)
        except Exception:
            logging.exception(
                "sandbox_cleanup: error processing row %s/%s (will retry next run)",
                row.get("PartitionKey"), row.get("RowKey"),
            )


# ---------------------------------------------------------------------------
# 2. Insights aggregation API
# ---------------------------------------------------------------------------

def _build_dashboard_data() -> dict:
    insights_rows = list(_tables().get_table_client("insights").list_entities())

    total_questions = len(insights_rows)

    by_category = Counter(
        str(r.get("category") or "uncategorized") for r in insights_rows
    )

    today = datetime.now(timezone.utc).date()
    day_counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(13, -1, -1)}
    for r in insights_rows:
        dt = _parse_iso(r.get("created_at"))
        if dt is not None:
            key = dt.date().isoformat()
            if key in day_counts:
                day_counts[key] += 1

    topics = Counter(
        str(r.get("topic_label")).strip()
        for r in insights_rows
        if r.get("topic_label") and str(r.get("topic_label")).strip()
    )

    shared = [r for r in insights_rows if r.get("question_text")]
    shared.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    full_conversations = [
        {
            "room_id": r.get("PartitionKey"),
            "asked_at": r.get("created_at"),
            "question": r.get("question_text"),
            "answer": r.get("answer_text"),
        }
        for r in shared[:50]
    ]

    session_rows = list(_tables().get_table_client("sessions").list_entities())
    sandboxes = [
        {
            "sandbox_id": r.get("sandbox_id") or r.get("RowKey"),
            "status": r.get("status"),
            "last_activity": r.get("last_activity"),
        }
        for r in session_rows
    ]

    return {
        "total_questions": total_questions,
        "by_category": [
            {"category": c, "count": n} for c, n in by_category.most_common()
        ],
        "trend": [{"date": d, "count": n} for d, n in day_counts.items()],
        "top_topics": [
            {"label": t, "count": n} for t, n in topics.most_common(10)
        ],
        "full_conversations": full_conversations,
        "sandboxes": sandboxes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.route(route="dashboard-data", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def dashboard_data(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = _build_dashboard_data()
    except Exception:
        logging.exception("dashboard_data failed")
        return func.HttpResponse(
            json.dumps({"error": "failed to build dashboard data"}),
            status_code=500,
            mimetype="application/json",
        )
    return func.HttpResponse(
        json.dumps(payload, default=str),
        status_code=200,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# 3. Dashboard HTML page
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confidant — Provider Dashboard</title>
<style>
  :root {
    --bg: #f6f7f9; --card: #ffffff; --ink: #1a2233; --muted: #6b7486;
    --accent: #2f5fdd; --accent-soft: #e3eafc; --line: #e4e7ee;
    --ok: #1e9e6a; --warn: #c88a1a; --dead: #9aa1af;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--ink); padding: 28px 20px 60px; }
  .wrap { max-width: 1080px; margin: 0 auto; }
  header { display: flex; align-items: baseline; justify-content: space-between;
           flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }
  header h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.2px; }
  header .sub { color: var(--muted); font-size: 13px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 14px; margin-bottom: 22px; }
  .stat { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
          padding: 16px 18px; }
  .stat .num { font-size: 30px; font-weight: 700; line-height: 1.1; }
  .stat .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase;
               letter-spacing: 0.06em; margin-top: 4px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
  @media (max-width: 760px) { .grid2 { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
          padding: 18px; margin-bottom: 14px; }
  .card h2 { font-size: 14px; font-weight: 600; text-transform: uppercase;
             letter-spacing: 0.05em; color: var(--muted); margin-bottom: 14px; }
  .barrow { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; }
  .barrow .name { flex: 0 0 130px; font-size: 13px; overflow: hidden;
                  text-overflow: ellipsis; white-space: nowrap; }
  .barrow .track { flex: 1; background: var(--accent-soft); border-radius: 4px; height: 18px; }
  .barrow .fill { background: var(--accent); height: 100%; border-radius: 4px; min-width: 2px; }
  .barrow .val { flex: 0 0 34px; font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }
  .topics { display: flex; flex-wrap: wrap; gap: 8px; }
  .topic { background: var(--accent-soft); color: var(--accent); border-radius: 999px;
           padding: 5px 12px; font-size: 13px; font-weight: 500; }
  .topic small { color: var(--muted); font-weight: 400; margin-left: 5px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: 0.05em; padding: 6px 8px;
       border-bottom: 1px solid var(--line); }
  td { padding: 8px; border-bottom: 1px solid var(--line); }
  tr:last-child td { border-bottom: none; }
  .pill { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 12px;
          font-weight: 600; }
  .pill.active { background: #e2f6ec; color: var(--ok); }
  .pill.closed { background: #fbf1dd; color: var(--warn); }
  .pill.deleted { background: #eef0f3; color: var(--dead); }
  .conv { border-bottom: 1px solid var(--line); padding: 13px 2px; }
  .conv:last-child { border-bottom: none; }
  .conv .meta { color: var(--muted); font-size: 12px; margin-bottom: 5px; }
  .conv .q { font-weight: 600; font-size: 14px; margin-bottom: 5px; }
  .conv .a { font-size: 13.5px; color: #3a4356; line-height: 1.5; white-space: pre-wrap; }
  .empty { color: var(--muted); font-size: 13px; padding: 6px 0; }
  #err { display: none; background: #fdeaea; color: #a02b2b; border: 1px solid #f2c7c7;
         border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 14px; }
  svg text { font-family: inherit; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Confidant &mdash; Provider Dashboard</h1>
    <span class="sub" id="genat">loading&hellip;</span>
  </header>
  <div id="err"></div>
  <div class="stats" id="stats"></div>
  <div class="grid2">
    <div class="card"><h2>Questions by category</h2><div id="cats"></div></div>
    <div class="card"><h2>Questions &mdash; last 14 days</h2><div id="trend"></div></div>
  </div>
  <div class="card"><h2>Top topics</h2><div class="topics" id="topics"></div></div>
  <div class="card"><h2>Sandboxes</h2><div id="sandboxes"></div></div>
  <div class="card"><h2>Shared conversations</h2><div id="convs"></div></div>
</div>
<script>
(function () {
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var fmtDT = function (iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return isNaN(d) ? esc(iso) : d.toLocaleString(undefined,
      { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  var code = new URLSearchParams(window.location.search).get("code");
  var url = "dashboard-data" + (code ? "?code=" + encodeURIComponent(code) : "");

  fetch(url).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status + " from dashboard-data (is the key valid for both functions? use a host key)");
    return r.json();
  }).then(render).catch(function (e) {
    var el = document.getElementById("err");
    el.style.display = "block";
    el.textContent = "Could not load dashboard data: " + e.message;
    document.getElementById("genat").textContent = "";
  });

  function render(d) {
    document.getElementById("genat").textContent =
      "generated " + fmtDT(d.generated_at);

    var activeSandboxes = (d.sandboxes || []).filter(function (s) {
      return String(s.status).toLowerCase() === "active";
    }).length;
    var stats = [
      [d.total_questions, "Total questions"],
      [(d.by_category || []).length, "Categories"],
      [activeSandboxes, "Active sandboxes"],
      [(d.full_conversations || []).length, "Shared conversations"]
    ];
    document.getElementById("stats").innerHTML = stats.map(function (s) {
      return '<div class="stat"><div class="num">' + esc(s[0]) +
             '</div><div class="lbl">' + esc(s[1]) + "</div></div>";
    }).join("");

    // Category bars
    var cats = d.by_category || [];
    var maxC = Math.max.apply(null, [1].concat(cats.map(function (c) { return c.count; })));
    document.getElementById("cats").innerHTML = cats.length ? cats.map(function (c) {
      return '<div class="barrow"><div class="name" title="' + esc(c.category) + '">' +
        esc(c.category) + '</div><div class="track"><div class="fill" style="width:' +
        (100 * c.count / maxC).toFixed(1) + '%"></div></div><div class="val">' +
        esc(c.count) + "</div></div>";
    }).join("") : '<div class="empty">No questions yet.</div>';

    // Trend SVG
    var t = d.trend || [];
    var W = 480, H = 160, PL = 30, PB = 24, PT = 10, PR = 8;
    var maxT = Math.max.apply(null, [1].concat(t.map(function (p) { return p.count; })));
    var iw = W - PL - PR, ih = H - PT - PB;
    var pts = t.map(function (p, i) {
      var x = PL + (t.length > 1 ? i * iw / (t.length - 1) : iw / 2);
      var y = PT + ih - (p.count / maxT) * ih;
      return [x, y, p];
    });
    var line = pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;height:auto">' +
      '<line x1="' + PL + '" y1="' + (PT + ih) + '" x2="' + (W - PR) + '" y2="' + (PT + ih) +
      '" stroke="#e4e7ee"/>' +
      '<text x="' + (PL - 6) + '" y="' + (PT + 4) + '" font-size="10" fill="#6b7486" text-anchor="end">' + maxT + "</text>" +
      '<text x="' + (PL - 6) + '" y="' + (PT + ih + 4) + '" font-size="10" fill="#6b7486" text-anchor="end">0</text>';
    if (t.length) {
      svg += '<polyline points="' + line + '" fill="none" stroke="#2f5fdd" stroke-width="2"/>';
      pts.forEach(function (p, i) {
        svg += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) +
               '" r="2.6" fill="#2f5fdd"><title>' + esc(p[2].date) + ": " + p[2].count + "</title></circle>";
        if (i % 3 === 0 || i === t.length - 1) {
          svg += '<text x="' + p[0].toFixed(1) + '" y="' + (H - 6) +
                 '" font-size="9" fill="#6b7486" text-anchor="middle">' +
                 esc(String(p[2].date).slice(5)) + "</text>";
        }
      });
    }
    svg += "</svg>";
    document.getElementById("trend").innerHTML = svg;

    // Topics
    var topics = d.top_topics || [];
    document.getElementById("topics").innerHTML = topics.length ? topics.map(function (tp) {
      return '<span class="topic">' + esc(tp.label) + "<small>" + esc(tp.count) + "</small></span>";
    }).join("") : '<div class="empty">No topics yet.</div>';

    // Sandboxes table
    var sb = d.sandboxes || [];
    document.getElementById("sandboxes").innerHTML = sb.length ?
      "<table><thead><tr><th>Sandbox</th><th>Status</th><th>Last activity</th></tr></thead><tbody>" +
      sb.map(function (s) {
        var st = String(s.status || "unknown").toLowerCase();
        var cls = st === "active" ? "active" : (st === "closed" ? "closed" : "deleted");
        return "<tr><td>" + esc(s.sandbox_id) + '</td><td><span class="pill ' + cls + '">' +
               esc(st) + "</span></td><td>" + fmtDT(s.last_activity) + "</td></tr>";
      }).join("") + "</tbody></table>" :
      '<div class="empty">No sandbox sessions recorded.</div>';

    // Conversations
    var convs = d.full_conversations || [];
    document.getElementById("convs").innerHTML = convs.length ? convs.map(function (c) {
      return '<div class="conv"><div class="meta">Room ' + esc(c.room_id) + " &middot; " +
        fmtDT(c.asked_at) + '</div><div class="q">' + esc(c.question) +
        '</div><div class="a">' + esc(c.answer || "(no answer recorded)") + "</div></div>";
    }).join("") : '<div class="empty">No fully-shared conversations yet.</div>';
  }
})();
</script>
</body>
</html>
"""


@app.route(route="dashboard", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(_DASHBOARD_HTML, status_code=200, mimetype="text/html")
