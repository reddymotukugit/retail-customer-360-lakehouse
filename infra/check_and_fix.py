import os
#!/usr/bin/env python3
"""
check_and_fix.py
================
1. Shows the pipeline's current cluster Spark conf (to verify the storage key landed).
2. Queries the event log for the actual exception from the latest failed run.
3. If the key is missing from the Spark conf, patches it directly via the API.
"""
import json, subprocess, time, urllib.request, urllib.error, sys

WORKSPACE_URL   = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
PIPELINE_ID     = "b4fe7fb9-0d40-49e6-8d70-f249f6032b08"
STORAGE_ACCOUNT = "stretaillhdev"
RESOURCE_GROUP  = "rg-retaillh-dev"
WH_ID           = "48a9de72ac127b76"

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def run_cli(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

def api(method, path, body=None):
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:400]}")
        return None

def run_sql(sql):
    stmt = api("POST", "/api/2.0/sql/statements", {
        "warehouse_id": WH_ID, "statement": sql,
        "wait_timeout": "45s", "on_wait_timeout": "CONTINUE",
    })
    if not stmt:
        return None, None
    stmt_id = stmt.get("statement_id")
    state   = stmt.get("status", {}).get("state", "PENDING")
    for _ in range(30):
        if state in ("SUCCEEDED", "FAILED", "CANCELED"):
            break
        time.sleep(2)
        r = api("GET", f"/api/2.0/sql/statements/{stmt_id}")
        state = (r or {}).get("status", {}).get("state", state)
        stmt  = r or stmt
    if state != "SUCCEEDED":
        print(f"  SQL {state}: {(stmt or {}).get('status',{}).get('error',{}).get('message','')[:200]}")
        return None, None
    cols = [c["name"] for c in stmt.get("manifest",{}).get("schema",{}).get("columns",[])]
    rows = stmt.get("result",{}).get("data_array",[])
    return cols, rows

# ── Step 1: Check pipeline Spark conf ─────────────────────────────────────────
print("=== Step 1: Pipeline cluster Spark conf ===")
pipeline = api("GET", f"/api/2.0/pipelines/{PIPELINE_ID}")
clusters = (pipeline or {}).get("spec", {}).get("clusters", [])
key_found = False
for cl in clusters:
    sc = cl.get("spark_conf", {})
    print(f"  label={cl.get('label')}")
    for k, v in sc.items():
        display_v = v[:20] + "..." if len(str(v)) > 20 else v
        print(f"    {k} = {display_v}")
        if "account.key" in k:
            key_found = True

if key_found:
    print("\n  ✓ Storage account key IS in the pipeline Spark conf.")
else:
    print("\n  ✗ Storage account key is MISSING from pipeline Spark conf.")
    print("    Will patch it directly via API...")

# ── Step 2: Get latest error from event log ────────────────────────────────────
print("\n=== Step 2: Latest exception from event log ===")
api("POST", f"/api/2.0/sql/warehouses/{WH_ID}/start")
time.sleep(6)

cols, rows = run_sql(f"""
SELECT
  timestamp,
  origin.flow_name,
  level,
  message,
  error
FROM event_log('{PIPELINE_ID}')
WHERE level = 'ERROR'
  AND timestamp >= current_timestamp() - INTERVAL 30 MINUTES
ORDER BY timestamp DESC
LIMIT 5
""")
if cols and rows:
    for row in rows:
        d = dict(zip(cols, row))
        print(f"\n  [{d.get('timestamp','')[:19]}]  flow={d.get('flow_name')}")
        print(f"  msg: {d.get('message')}")
        err = d.get("error", "")
        if err:
            try:
                e = json.loads(err)
                for ex in e.get("exceptions", []):
                    print(f"  exception: {ex.get('class_name')}")
                    print(f"  {ex.get('message','')[:600]}")
            except Exception:
                print(f"  error: {str(err)[:400]}")

# ── Step 3: If key missing, get key and patch pipeline directly ────────────────
if not key_found:
    print("\n=== Step 3: Getting storage key and patching pipeline ===")
    key_out, key_err, key_rc = run_cli(
        f"az storage account keys list --account-name {STORAGE_ACCOUNT} "
        f"--resource-group {RESOURCE_GROUP} --query \"[0].value\" -o tsv"
    )
    if key_rc != 0 or not key_out:
        print(f"  Could not get key: {key_err}")
        sys.exit(1)
    storage_key = key_out.strip()
    print(f"  Key obtained (...{storage_key[-6:]})")

    # Build the updated pipeline spec with the key injected
    spec = (pipeline or {}).get("spec", {})
    updated_clusters = []
    for cl in spec.get("clusters", []):
        sc = dict(cl.get("spark_conf", {}))
        sc[f"fs.azure.account.key.{STORAGE_ACCOUNT}.dfs.core.windows.net"] = storage_key
        updated_clusters.append({**cl, "spark_conf": sc})

    patch_body = {
        "pipeline_id":  PIPELINE_ID,
        "name":         spec.get("name", ""),
        "catalog":      spec.get("catalog", "retail_prod"),
        "schema":       spec.get("schema", "bronze"),
        "clusters":     updated_clusters,
        "libraries":    spec.get("libraries", []),
        "configuration": spec.get("configuration", {}),
        "continuous":   spec.get("continuous", False),
        "development":  spec.get("development", True),
        "channel":      spec.get("channel", "CURRENT"),
        "edition":      spec.get("edition", "ADVANCED"),
        "photon":       spec.get("photon", False),
    }
    result = api("PUT", f"/api/2.0/pipelines/{PIPELINE_ID}", patch_body)
    if result is None:
        print("  Patch via PUT failed. Trying minimal update...")
        # Minimal update — only clusters
        result2 = api("PATCH", f"/api/2.0/pipelines/{PIPELINE_ID}", {
            "clusters": updated_clusters
        })
        print(f"  PATCH result: {result2}")
    else:
        print("  Pipeline Spark conf patched successfully.")
else:
    storage_key = None

# ── Step 4: Start pipeline ─────────────────────────────────────────────────────
print("\n=== Step 4: Starting pipeline (full refresh) ===")
run_result = api("POST", f"/api/2.0/pipelines/{PIPELINE_ID}/updates", {"full_refresh": True})
if run_result:
    uid = run_result.get("update_id")
    print(f"  Started! update_id={uid}")
    print(f"  Monitor: {WORKSPACE_URL}/#joblist/pipelines/{PIPELINE_ID}")
else:
    print("  Could not start pipeline.")
