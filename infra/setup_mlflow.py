import os
#!/usr/bin/env python3
"""
setup_mlflow.py
===============
Creates the /Shared/retail-lakehouse workspace folder so MLflow experiments
can be created under it by the ML notebooks.

Run once before the first ml_retrain_job execution:
    python3 infra/setup_mlflow.py
"""
import json, urllib.request

WORKSPACE_URL = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
HEADERS       = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api(method, path, body=None):
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}

# Create the workspace folder
print("Creating /Shared/retail-lakehouse workspace folder...")
api("POST", "/api/2.0/workspace/mkdirs", {"path": "/Shared/retail-lakehouse"})
print("  Done.")

# Verify it exists
status = api("GET", "/api/2.0/workspace/get-status?path=/Shared/retail-lakehouse")
print(f"  Verified: path={status.get('path')}  type={status.get('object_type')}")
print("\nReady — run the ML job now.")
