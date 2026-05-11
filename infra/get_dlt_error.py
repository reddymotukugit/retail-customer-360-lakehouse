import os
#!/usr/bin/env python3
"""get_dlt_error.py v3 — introspect event_log schema then fetch exceptions"""
import json, time, urllib.request, urllib.error, sys

WORKSPACE_URL = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
PIPELINE_ID   = "b4fe7fb9-0d40-49e6-8d70-f249f6032b08"
WH_ID         = "48a9de72ac127b76"

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api(method, path, body=None):
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        return None

def run_sql(sql):
    stmt = api("POST", "/api/2.0/sql/statements", {
        "warehouse_id": WH_ID,
        "statement":    sql,
        "wait_timeout": "45s",
        "on_wait_timeout": "CONTINUE",
    })
    if not stmt:
        return None, None
    stmt_id = stmt.get("statement_id")
    state   = stmt.get("status", {}).get("state", "PENDING")
    for _ in range(30):
        if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
            break
        time.sleep(2)
        r     = api("GET", f"/api/2.0/sql/statements/{stmt_id}")
        state = (r or {}).get("status", {}).get("state", state)
        stmt  = r or stmt
    if state != "SUCCEEDED":
        err = (stmt or {}).get("status", {}).get("error", {})
        print(f"  SQL FAILED ({state}): {err.get('message','')[:300]}")
        return None, None
    cols = [c["name"] for c in stmt.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = stmt.get("result", {}).get("data_array", [])
    return cols, rows

# Start warehouse
api("POST", f"/api/2.0/sql/warehouses/{WH_ID}/start")
time.sleep(6)

# ── Step 1: describe event_log schema ────────────────────────────────────────
print("=== event_log schema ===")
cols, rows = run_sql(f"DESCRIBE event_log('{PIPELINE_ID}')")
if cols and rows:
    for r in rows:
        print(f"  {r}")

# ── Step 2: grab one raw ERROR row to see all fields ─────────────────────────
print("\n=== One raw ERROR row (last 2 hours) ===")
cols2, rows2 = run_sql(f"""
SELECT *
FROM event_log('{PIPELINE_ID}')
WHERE level = 'ERROR'
  AND timestamp >= current_timestamp() - INTERVAL 2 HOURS
ORDER BY timestamp DESC
LIMIT 1
""")
if cols2 and rows2:
    print(f"  Columns: {cols2}")
    for r in rows2:
        for c, v in zip(cols2, r):
            print(f"  {c}: {v}")

# ── Step 3: fetch error + details with correct column names ──────────────────
print("\n=== ERROR events with details (last 2 hours) ===")
# Use SELECT * and just print everything — we'll know the right column names from step 2
cols3, rows3 = run_sql(f"""
SELECT *
FROM event_log('{PIPELINE_ID}')
WHERE level = 'ERROR'
  AND timestamp >= current_timestamp() - INTERVAL 2 HOURS
ORDER BY timestamp DESC
LIMIT 10
""")
if cols3 and rows3:
    for row in rows3:
        print("\n  ---")
        for c, v in zip(cols3, row):
            if v is not None and str(v).strip() not in ('', 'null', '{}'):
                print(f"  {c}: {str(v)[:500]}")
