import os
#!/usr/bin/env python3
"""
run_pipeline.py
===============
Triggers the Lakeflow pipeline (full_refresh=True by default to clear stale
checkpoints) and polls until it completes or fails.

Usage:
    python3 infra/run_pipeline.py            # full refresh (default)
    python3 infra/run_pipeline.py incremental
"""

import json, sys, time, urllib.request, urllib.error

WORKSPACE_URL = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
PIPELINE_NAME = "retail-lakehouse-pipeline-dev"

FULL_REFRESH  = "--incremental" not in sys.argv and "incremental" not in sys.argv

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}

def api(method, path, body=None):
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        print(f"  HTTP {e.code} {method} {path}: {msg[:300]}")
        return None

# ── Find pipeline ─────────────────────────────────────────────────────────────
print("Looking for pipeline...")
pipelines = api("GET", "/api/2.0/pipelines?max_results=50")
pipeline_id = None
for p in (pipelines or {}).get("statuses", []):
    if PIPELINE_NAME in p.get("name", ""):
        pipeline_id = p["pipeline_id"]
        print(f"  Found: {p['name']}")
        print(f"  ID:    {pipeline_id}")
        break

if not pipeline_id:
    print(f"ERROR: Pipeline '{PIPELINE_NAME}' not found.")
    raise SystemExit(1)

# ── Stop any running update ────────────────────────────────────────────────────
detail = api("GET", f"/api/2.0/pipelines/{pipeline_id}")
state = (detail or {}).get("state", "")
print(f"  Current state: {state}")
if state in ("RUNNING", "INITIALIZING", "RESETTING", "SETTING_UP_TABLES"):
    print("  Stopping current run first...")
    api("POST", f"/api/2.0/pipelines/{pipeline_id}/stop")
    time.sleep(10)

# ── Trigger update ────────────────────────────────────────────────────────────
mode = "FULL REFRESH" if FULL_REFRESH else "incremental"
print(f"\nStarting pipeline update ({mode})...")
run = api("POST", f"/api/2.0/pipelines/{pipeline_id}/updates",
          {"full_refresh": FULL_REFRESH})
if not run:
    print("ERROR: Could not start pipeline.")
    raise SystemExit(1)

update_id = run.get("update_id")
print(f"  update_id: {update_id}")
print(f"  Monitor:   {WORKSPACE_URL}/#joblist/pipelines/{pipeline_id}")

# ── Poll ──────────────────────────────────────────────────────────────────────
print("\nPolling every 15 s (Ctrl-C to stop watching)...\n")
last_state = ""
try:
    while True:
        time.sleep(15)
        info  = api("GET", f"/api/2.0/pipelines/{pipeline_id}/updates/{update_id}")
        upd   = (info or {}).get("update", {})
        state = upd.get("state", "?")
        if state != last_state:
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}]  state={state}")
            last_state = state
        if state in ("COMPLETED", "FAILED", "CANCELED"):
            break
except KeyboardInterrupt:
    print("\nStopped watching — pipeline still running in Databricks.")
    raise SystemExit(0)

# ── Fetch most recent error events if failed ──────────────────────────────────
if state == "FAILED":
    print("\n✗ Pipeline FAILED. Fetching error events...\n")
    import urllib.parse
    params = urllib.parse.urlencode({"max_results": 20, "order_by": "timestamp desc"})
    events = api("GET", f"/api/2.0/pipelines/{pipeline_id}/events?{params}")
    for ev in (events or {}).get("events", []):
        if ev.get("level") not in ("ERROR", "WARN"):
            continue
        ts  = ev.get("timestamp", "")[:19]
        msg = ev.get("message", "")
        det = ev.get("details", {})
        print(f"  [{ts}] {ev.get('level')} — {msg}")
        if det:
            print(f"    {json.dumps(det)[:400]}")
    print(f"\n  Full DAG: {WORKSPACE_URL}/#joblist/pipelines/{pipeline_id}")

elif state == "COMPLETED":
    print("\n✓ Pipeline COMPLETED successfully!")
    print("  Gold tables retail_prod.gold.daily_kpis and customer_360 are ready.")
    print("\n  Next — run the ML job:")
    print("    databricks bundle run ml_retrain_job --target dev")
