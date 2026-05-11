import os
#!/usr/bin/env python3
"""
get_pipeline_error.py  — paginate all pipeline events and print errors/warnings
"""

import json, urllib.request, urllib.error, urllib.parse

WORKSPACE_URL = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
PIPELINE_ID   = "b4fe7fb9-0d40-49e6-8d70-f249f6032b08"

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
        print(f"HTTP {e.code} {method} {path}: {msg[:500]}")
        return None

# ── Paginate ALL events, collect everything ───────────────────────────────────
all_events = []
params = urllib.parse.urlencode({"max_results": 100, "order_by": "timestamp desc"})
page   = api("GET", f"/api/2.0/pipelines/{PIPELINE_ID}/events?{params}")
all_events.extend((page or {}).get("events", []))

# Follow next_page_token if present
while True:
    token = (page or {}).get("next_page_token")
    if not token:
        break
    p2 = urllib.parse.urlencode({"max_results": 100, "order_by": "timestamp desc",
                                  "page_token": token})
    page = api("GET", f"/api/2.0/pipelines/{PIPELINE_ID}/events?{p2}")
    batch = (page or {}).get("events", [])
    if not batch:
        break
    all_events.extend(batch)

print(f"Total events fetched: {len(all_events)}\n")

# ── Print ALL ERROR events with full details ──────────────────────────────────
print("=" * 70)
print("ERROR EVENTS")
print("=" * 70)
for ev in all_events:
    if ev.get("level") != "ERROR":
        continue
    ts      = ev.get("timestamp", "")[:19]
    etype   = ev.get("event_type", "")
    msg     = ev.get("message", "")
    details = ev.get("details", {})
    origin  = ev.get("origin", {})

    print(f"\n[{ts}] {etype}")
    print(f"  flow: {origin.get('flow_name', 'N/A')}  batch: {origin.get('batch_id', '')}")
    print(f"  msg:  {msg}")
    if details:
        print(f"  details:\n{json.dumps(details, indent=4)}")

# ── Also print the raw cluster log link ──────────────────────────────────────
print("\n" + "=" * 70)
print("CLUSTER / DRIVER LOG")
print("=" * 70)
# Get last update to find cluster_id
upd_list = api("GET", f"/api/2.0/pipelines/{PIPELINE_ID}/updates?max_results=1")
for upd in (upd_list or {}).get("updates", []):
    cid = upd.get("cluster_id", "")
    uid = upd.get("update_id", "")
    print(f"  update_id:  {uid}")
    print(f"  cluster_id: {cid}")
    print(f"  Driver logs: {WORKSPACE_URL}/#setting/clusters/{cid}/driverLogs")

# ── Check if bronze paths have any files ─────────────────────────────────────
print("\n" + "=" * 70)
print("EXTERNAL LOCATION VALIDATION (via Unity Catalog LIST)")
print("=" * 70)
for path in ["bronze@stretaillhdev.dfs.core.windows.net/transactions",
             "bronze@stretaillhdev.dfs.core.windows.net/customers",
             "bronze@stretaillhdev.dfs.core.windows.net/products"]:
    result = api("GET", f"/api/2.1/unity-catalog/external-locations/bronze_retaillh/validate"
                        f"?url=abfss://{path}/")
    print(f"  abfss://{path}/ → {json.dumps(result)}")
