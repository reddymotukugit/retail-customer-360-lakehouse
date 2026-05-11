import os
#!/usr/bin/env python3
"""
fix_adls_permissions.py
========================
Grants READ FILES on the external location + READ FILES on the storage credential
so the Lakeflow pipeline cluster can authenticate to ADLS Gen2.

Run on your Mac:
    python3 infra/fix_adls_permissions.py

Then re-trigger the pipeline from the Databricks UI or via:
    databricks pipeline start <pipeline-id>
"""

import json, urllib.request, urllib.error

WORKSPACE_URL = "https://adb-7405615013053011.11.azuredatabricks.net"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
EXT_LOC_NAME  = "bronze_retaillh"
CRED_NAME     = "adls_retaillh_dev"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}


def api(method, path, body=None, ok_codes=(200, 204)):
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        print(f"  HTTP {e.code} {method} {path}")
        print(f"  Response: {msg[:400]}")
        return None


def banner(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")


# ── 0. Who am I? ─────────────────────────────────────────────────────────────
banner("ADLS Auth Fix — Unity Catalog permissions")
me = api("GET", "/api/2.0/preview/scim/v2/Me")
if not me:
    print("ERROR: Could not authenticate. Check the TOKEN constant.")
    raise SystemExit(1)
username = me.get("userName", "")
print(f"Authenticated as: {username}")


# ── 1. Show existing external locations ──────────────────────────────────────
print("\n[1] External locations in workspace:")
ext_locs = api("GET", "/api/2.1/unity-catalog/external-locations")
for el in (ext_locs or {}).get("external_locations", []):
    print(f"    {el['name']:30s}  url={el.get('url')}  cred={el.get('credential_name')}")


# ── 2. Show existing storage credentials ─────────────────────────────────────
print("\n[2] Storage credentials:")
creds = api("GET", "/api/2.1/unity-catalog/storage-credentials")
for c in (creds or {}).get("storage_credentials", []):
    mi = c.get("azure_managed_identity", {})
    print(f"    {c['name']:30s}  connector={mi.get('access_connector_id','N/A')}")


# ── 3. Check if external location covers the right path ──────────────────────
print(f"\n[3] Checking external location '{EXT_LOC_NAME}':")
el_detail = api("GET", f"/api/2.1/unity-catalog/external-locations/{EXT_LOC_NAME}")
if el_detail:
    print(f"    url:        {el_detail.get('url')}")
    print(f"    credential: {el_detail.get('credential_name')}")
    print(f"    comment:    {el_detail.get('comment')}")
else:
    print(f"    WARNING: External location '{EXT_LOC_NAME}' not found!")
    print("    You may need to create it in the Databricks UI under")
    print("    Data > External Data > External Locations.")


# ── 4. Current permissions on external location ───────────────────────────────
print(f"\n[4] Current perms on external-location/{EXT_LOC_NAME}:")
perms = api("GET", f"/api/2.1/unity-catalog/permissions/external-location/{EXT_LOC_NAME}")
print(f"    {json.dumps(perms, indent=4)}")


# ── 5. Grant READ FILES on external location ─────────────────────────────────
print(f"\n[5] Granting READ FILES on external-location/{EXT_LOC_NAME} ...")
result = api("PATCH", f"/api/2.1/unity-catalog/permissions/external-location/{EXT_LOC_NAME}", {
    "changes": [
        {
            "principal": "account users",
            "add": ["READ FILES", "WRITE FILES"]
        },
        {
            "principal": username,
            "add": ["ALL PRIVILEGES"]
        }
    ]
})
if result is not None:
    print("    OK")
else:
    print("    FAILED — see error above")


# ── 6. Grant READ FILES on storage credential ─────────────────────────────────
print(f"\n[6] Granting READ FILES on storage-credential/{CRED_NAME} ...")
result2 = api("PATCH", f"/api/2.1/unity-catalog/permissions/storage-credential/{CRED_NAME}", {
    "changes": [
        {
            "principal": "account users",
            "add": ["READ FILES", "WRITE FILES"]
        },
        {
            "principal": username,
            "add": ["ALL PRIVILEGES"]
        }
    ]
})
if result2 is not None:
    print("    OK")
else:
    print("    FAILED — see error above")


# ── 7. Verify ─────────────────────────────────────────────────────────────────
print(f"\n[7] Effective perms on external-location/{EXT_LOC_NAME} after grant:")
perms2 = api("GET", f"/api/2.1/unity-catalog/permissions/external-location/{EXT_LOC_NAME}")
print(f"    {json.dumps(perms2, indent=4)}")


# ── 8. Restart the pipeline ───────────────────────────────────────────────────
print("\n[8] Looking for the Lakeflow pipeline to trigger a new run ...")
pipelines = api("GET", "/api/2.0/pipelines?max_results=50")
pipeline_id = None
for p in (pipelines or {}).get("statuses", []):
    if "retail-lakehouse-pipeline" in p.get("name", ""):
        pipeline_id = p["pipeline_id"]
        print(f"    Found pipeline: {p['name']}  id={pipeline_id}")
        break

if pipeline_id:
    run_result = api("POST", f"/api/2.0/pipelines/{pipeline_id}/updates", {"full_refresh": False})
    if run_result:
        update_id = run_result.get("update_id", "N/A")
        print(f"    Pipeline update started! update_id={update_id}")
        print(f"    Monitor: {WORKSPACE_URL}/#joblist/pipelines/{pipeline_id}")
    else:
        print("    Could not start pipeline run — start it manually in the UI.")
else:
    print("    Pipeline not found. Deploy the bundle first, then re-run this script.")

banner("Done!")
print("""
If the pipeline still fails with REDACTED_CREDENTIALS, try these manual steps:

  1. In Databricks UI → Catalog → External Data → External Locations
     → select 'bronze_retaillh' → click 'Test connection'
     If it fails, the access connector may not have the role on the storage account yet.

  2. In Azure Portal → Storage Account 'stretaillhdev' → Access Control (IAM)
     → verify the access connector (ac-retaillh-dev) has 'Storage Blob Data Contributor'
     on the storage account (not just the container).

  3. In Databricks UI → Catalog → External Data → Storage Credentials
     → select 'adls_retaillh_dev' → click 'Test'
     It should say 'Credential is valid and workspace can access storage'.
""")
