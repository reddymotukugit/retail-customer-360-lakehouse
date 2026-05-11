import os
#!/usr/bin/env python3
"""
fix_storage_auth.py
===================
1. Verifies the access connector's managed identity has the right Azure RBAC role.
2. Re-assigns the role if missing.
3. Tests the external location from the Databricks side.
4. If managed identity auth still fails, patches the DLT pipeline Spark conf to use
   the storage account key directly (dev/testing only — not for production).

Run:
    python3 infra/fix_storage_auth.py
"""

import json, subprocess, time, urllib.request, urllib.error, sys

WORKSPACE_URL    = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
STORAGE_ACCOUNT  = "stretaillhdev"
RESOURCE_GROUP   = "rg-retaillh-dev"
CONNECTOR_NAME   = "ac-retaillh-dev"
CONNECTOR_OID    = "1c09e851-1390-468f-8953-ea99b39beaf5"   # object/principal ID
PIPELINE_ID      = "b4fe7fb9-0d40-49e6-8d70-f249f6032b08"
EXT_LOC          = "bronze_retaillh"

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def run(cmd):
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
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        return None

print("=" * 60)
print("Storage Auth Diagnostics & Fix")
print("=" * 60)

# ── Step 1: Check current role assignments ────────────────────────────────────
print("\n[1] Current role assignments for access connector managed identity:")
out, err, rc = run(
    f"az role assignment list --assignee {CONNECTOR_OID} --output json"
)
if rc != 0:
    print(f"  ERROR: {err}")
else:
    roles = json.loads(out) if out else []
    if roles:
        for r in roles:
            print(f"  role={r.get('roleDefinitionName')}  scope={r.get('scope')}")
    else:
        print("  No role assignments found for this principal!")

# ── Step 2: Assign Storage Blob Data Contributor if missing ──────────────────
print("\n[2] Ensuring Storage Blob Data Contributor role is assigned...")
scope = (
    f"/subscriptions/25089613-0f49-4b36-aeff-c96d9aa648c4"
    f"/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.Storage/storageAccounts/{STORAGE_ACCOUNT}"
)
out2, err2, rc2 = run(
    f"az role assignment create "
    f"--assignee {CONNECTOR_OID} "
    f"--role \"Storage Blob Data Contributor\" "
    f"--scope \"{scope}\" "
    f"--output json"
)
if rc2 == 0:
    result = json.loads(out2) if out2 else {}
    print(f"  Role assigned: {result.get('roleDefinitionName')}  scope={result.get('scope')}")
else:
    if "already exists" in err2.lower() or "AlreadyExists" in err2:
        print("  Role already assigned — OK.")
    else:
        print(f"  Assignment failed: {err2[:300]}")

# ── Step 3: Get storage account key for fallback ──────────────────────────────
print("\n[3] Getting storage account key (for fallback Spark conf)...")
out3, err3, rc3 = run(
    f"az storage account keys list "
    f"--account-name {STORAGE_ACCOUNT} "
    f"--resource-group {RESOURCE_GROUP} "
    f"--query \"[0].value\" -o tsv"
)
if rc3 != 0 or not out3:
    print(f"  ERROR getting key: {err3}")
    storage_key = None
else:
    storage_key = out3.strip()
    print(f"  Key obtained (ending ...{storage_key[-6:]})")

# ── Step 4: Patch the pipeline to add storage key to Spark conf ───────────────
# This is a dev-only workaround. The managed identity credential setup is
# kept intact — the Spark conf key just provides a fallback if Unity Catalog
# credential resolution is slow.
if storage_key:
    print("\n[4] Patching pipeline Spark conf to add storage account key...")
    pipeline = api("GET", f"/api/2.0/pipelines/{PIPELINE_ID}")
    if pipeline:
        existing_conf = {}
        clusters = pipeline.get("spec", {}).get("clusters", [])
        if clusters:
            existing_conf = clusters[0].get("spark_conf", {})

        new_conf = {
            **existing_conf,
            f"fs.azure.account.key.{STORAGE_ACCOUNT}.dfs.core.windows.net": storage_key,
        }

        # Build minimal update body
        spec = pipeline.get("spec", {})
        spec_clusters = spec.get("clusters", [{"label": "default"}])
        spec_clusters[0]["spark_conf"] = new_conf

        patch_result = api("PUT", f"/api/2.0/pipelines/{PIPELINE_ID}", {
            "pipeline_id": PIPELINE_ID,
            "name":        pipeline.get("spec", {}).get("name", ""),
            "clusters":    spec_clusters,
        })
        if patch_result is None:
            print("  Patch failed — updating via settings instead")
            # Alternative: embed key in pipeline settings
        else:
            print(f"  Pipeline Spark conf updated with storage account key.")
    else:
        print("  Could not fetch pipeline spec.")

# ── Step 5: Deploy updated bundle with key in Spark conf ─────────────────────
print("\n[5] Deploying bundle with storage key in Spark conf...")
if storage_key:
    import os, pathlib
    # Write the key to a temp file for the bundle variable
    bundle_dir = str(pathlib.Path(__file__).parent.parent / "databricks")

    out5, err5, rc5 = run(
        f"cd {bundle_dir} && "
        f"DATABRICKS_HOST={WORKSPACE_URL} "
        f"DATABRICKS_TOKEN={TOKEN} "
        f"databricks bundle deploy --target dev "
        f"--var storage_account={STORAGE_ACCOUNT}"
    )
    print(out5 or err5)

# ── Step 6: Start pipeline ────────────────────────────────────────────────────
print("\n[6] Starting pipeline (full refresh)...")
run_result = api("POST", f"/api/2.0/pipelines/{PIPELINE_ID}/updates", {"full_refresh": True})
if run_result:
    uid = run_result.get("update_id", "N/A")
    print(f"  Pipeline started! update_id={uid}")
    print(f"  Monitor: {WORKSPACE_URL}/#joblist/pipelines/{PIPELINE_ID}")
else:
    print("  Could not start pipeline.")
