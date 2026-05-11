#!/usr/bin/env python3
"""
bootstrap_databricks.py
========================
Run this on your Mac after generating a Databricks PAT.

Usage:
    python3 infra/bootstrap_databricks.py
"""

import os, sys, json, subprocess, time
import urllib.request, urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WORKSPACE_URL    = "https://adb-7405615013053011.11.azuredatabricks.net"
ACCOUNT_ID       = "76c6c924-41d2-4d21-82c7-ea1f94c95604"
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
STORAGE_ACCOUNT  = "stretaillhdev"
CATALOG          = "retail_prod"
SCHEMAS          = ["bronze", "silver", "gold", "ml"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}
ACCOUNT_BASE = f"https://accounts.azuredatabricks.net/api/2.0/accounts/{ACCOUNT_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(method: str, path: str, body: dict = None, ok_on_409: bool = True):
    """Workspace-level API call."""
    url  = f"{WORKSPACE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 409 and ok_on_409:
            return {"_conflict": True}
        msg = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {msg}") from e


def account_api(method: str, path: str, body: dict = None, ok_on_409: bool = True):
    """Account-level API call (accounts.azuredatabricks.net)."""
    url  = f"{ACCOUNT_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 409 and ok_on_409:
            return {"_conflict": True}
        msg = e.read().decode()
        raise RuntimeError(f"Account API HTTP {e.code} {method} {path}: {msg}") from e


def banner(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print('='*60)


def step(n: int, total: int, text: str):
    print(f"\n[{n}/{total}] {text}")


# ---------------------------------------------------------------------------
# Step 1 — Verify token + get current user
# ---------------------------------------------------------------------------
def verify_token():
    banner("Retail Lakehouse — Databricks Bootstrap")
    step(1, 6, "Verifying token + current user...")
    me = api("GET", "/api/2.0/preview/scim/v2/Me")
    username = me.get("userName", "")
    display  = me.get("displayName", username)
    print(f"  Authenticated as: {display}  ({username})")
    print(f"  Workspace: {WORKSPACE_URL}")
    return username


# ---------------------------------------------------------------------------
# Step 2 — Grant metastore admin to current workspace user via Account API
# ---------------------------------------------------------------------------
def grant_metastore_admin(username: str):
    step(2, 6, "Granting metastore admin to workspace user...")

    # Step A: get metastore_id from workspace-level summary endpoint
    # Correct endpoint: /api/2.1/unity-catalog/metastore_summary (underscore, no trailing path)
    metastore_id = None
    try:
        summary = api("GET", "/api/2.1/unity-catalog/metastore_summary")
        metastore_id = summary.get("metastore_id", "")
        metastore_name = summary.get("name", "")
        print(f"  Metastore: {metastore_name}  (id={metastore_id})")
    except RuntimeError as e:
        print(f"  Could not get metastore summary: {e}")

    # Step B: if we couldn't get it from the workspace, list via Account API
    if not metastore_id:
        try:
            metastores = account_api("GET", "/metastores")
            for m in metastores.get("metastores", []):
                if "retaillh" in m.get("name", "").lower():
                    metastore_id = m["metastore_id"]
                    print(f"  Found via Account API: {m['name']} ({metastore_id})")
                    break
        except RuntimeError as e:
            print(f"  Account API list also failed: {e}")

    if not metastore_id:
        print("  WARNING: Could not determine metastore_id. Catalog creation may fail.")
        return

    # Step C: set metastore owner to current user via Account API
    try:
        result = account_api("PATCH", f"/metastores/{metastore_id}", {
            "owner": username
        })
        print(f"  Set metastore owner → {username}")
    except RuntimeError as e:
        print(f"  Account API PATCH owner failed: {e}")

    # Step D: also grant CREATE CATALOG explicitly via workspace permissions API
    try:
        api("PATCH", f"/api/2.1/unity-catalog/permissions/metastore/{metastore_id}", {
            "changes": [{
                "principal": username,
                "add": ["CREATE CATALOG"]
            }]
        }, ok_on_409=True)
        print(f"  Granted CREATE CATALOG on metastore to {username}")
    except RuntimeError as e:
        print(f"  Explicit grant skipped: {e}")

    print("  Permission setup complete.")


# ---------------------------------------------------------------------------
# Step 3 — Unity Catalog: retail_prod catalog + schemas
# ---------------------------------------------------------------------------
def setup_unity_catalog():
    step(3, 6, f"Creating Unity Catalog: {CATALOG}")

    result = api("POST", "/api/2.1/unity-catalog/catalogs", {
        "name": CATALOG,
        "comment": "Retail Customer 360 & Demand Forecasting Lakehouse"
    })
    if result.get("_conflict"):
        print(f"  Catalog '{CATALOG}' already exists.")
    else:
        print(f"  Created catalog: {CATALOG}")

    for schema in SCHEMAS:
        result = api("POST", "/api/2.1/unity-catalog/schemas", {
            "catalog_name": CATALOG,
            "name": schema,
            "comment": f"Retail lakehouse {schema} layer"
        })
        if result.get("_conflict"):
            print(f"  Schema '{schema}' already exists.")
        else:
            print(f"  Created schema: {CATALOG}.{schema}")

    print(f"\n  Unity Catalog ready: {CATALOG}.{{bronze,silver,gold,ml}}")


# ---------------------------------------------------------------------------
# Step 4 — Verify/install Databricks CLI
# ---------------------------------------------------------------------------
def ensure_databricks_cli():
    step(4, 6, "Checking Databricks CLI...")
    try:
        result = subprocess.run(
            ["databricks", "--version"], capture_output=True, text=True
        )
        print(f"  Databricks CLI: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        pass

    print("  Databricks CLI not found. Installing via Homebrew...")
    result = subprocess.run(
        ["brew", "install", "databricks"],
        capture_output=False, text=True
    )
    if result.returncode == 0:
        print("  Installed via Homebrew.")
        return True
    else:
        print("  Could not auto-install. Run: brew install databricks")
        return False


# ---------------------------------------------------------------------------
# Step 5 — Bundle deploy
# ---------------------------------------------------------------------------
def deploy_bundle(cli_available: bool):
    step(5, 6, "Deploying Databricks bundle (dev target)...")

    if not cli_available:
        print("  SKIPPED — Databricks CLI not available.")
        print("  Once installed, run:")
        print(f"    cd databricks")
        print(f"    export DATABRICKS_HOST={WORKSPACE_URL}")
        print(f"    export DATABRICKS_TOKEN={TOKEN}")
        print(f"    databricks bundle deploy --target dev \\")
        print(f"      --var storage_account={STORAGE_ACCOUNT} \\")
        print(f"      --var databricks_host={WORKSPACE_URL}")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    bundle_dir = os.path.join(script_dir, "..", "databricks")

    env = os.environ.copy()
    env["DATABRICKS_HOST"]  = WORKSPACE_URL
    env["DATABRICKS_TOKEN"] = TOKEN

    result = subprocess.run(
        [
            "databricks", "bundle", "deploy",
            "--target", "dev",
            f"--var=storage_account={STORAGE_ACCOUNT}",
            f"--var=databricks_host={WORKSPACE_URL}",
        ],
        cwd=bundle_dir,
        env=env,
        text=True,
    )

    if result.returncode != 0:
        print("  Bundle deploy failed — check output above.")
    else:
        print("  Bundle deployed to dev.")


# ---------------------------------------------------------------------------
# Step 6 — Start Lakeflow pipeline
# ---------------------------------------------------------------------------
def start_pipeline():
    step(6, 6, "Starting Lakeflow pipeline (smoke test)...")

    pipelines = api("GET", "/api/2.0/pipelines?max_results=50")
    pipeline_id = None
    for p in pipelines.get("statuses", []):
        if "retail-lakehouse-pipeline-dev" in p.get("name", ""):
            pipeline_id = p["pipeline_id"]
            break

    if not pipeline_id:
        print("  Pipeline not found yet — bundle may still be deploying.")
        print(f"  Start it manually: {WORKSPACE_URL}/#joblist/pipelines")
        return

    print(f"  Pipeline ID: {pipeline_id}")
    api("POST", f"/api/2.0/pipelines/{pipeline_id}/updates", {"full_refresh": False})
    print(f"  Pipeline started!")
    print(f"  Monitor: {WORKSPACE_URL}/#joblist/pipelines/{pipeline_id}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        username = verify_token()
        grant_metastore_admin(username)
        setup_unity_catalog()
        cli_ok = ensure_databricks_cli()
        deploy_bundle(cli_ok)
        start_pipeline()
    except RuntimeError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    banner("Bootstrap Complete!")
    print(f"""
  Workspace:    {WORKSPACE_URL}
  Catalog:      {CATALOG}
  Schemas:      bronze | silver | gold | ml

  Next steps:
    1. Watch pipeline:  {WORKSPACE_URL}/#joblist/pipelines
    2. Once gold tables are populated, run the ML job:
         databricks jobs run-now --job-name retail-ml-retrain-dev
    3. Connect Power BI:
         Server: {WORKSPACE_URL}
         Catalog: {CATALOG}  Schema: gold
""")


if __name__ == "__main__":
    main()
