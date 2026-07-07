#!/usr/bin/env python3
"""
check_syncall_before.py - V9.0 Pre-Sync Verification

Calculates:
  1. Total modern site pages and document files in the target SharePoint site/library.
  2. How many files and pages will be synchronized (Delta estimation).
  3. How many files and pages are already up-to-date in GCS and will be skipped.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import threading
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try:
    os.chdir(ROOT_DIR)
except Exception:
    pass

def run_with_heartbeat(msg, func, *args, **kwargs):
    stop_event = threading.Event()
    start_time = time.time()
    def heartbeat():
        while not stop_event.is_set():
            elapsed = int(time.time() - start_time)
            if elapsed > 0:
                sys.stdout.write(f"\r   ⏳ {msg} (Elapsed time: {elapsed}s)... ")
                sys.stdout.flush()
            time.sleep(1)
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    try:
        res = func(*args, **kwargs)
        stop_event.set()
        t.join(timeout=1)
        elapsed = int(time.time() - start_time)
        sys.stdout.write(f"\r   ✅ Completed in {elapsed}s!                                    \n")
        sys.stdout.flush()
        return res
    except Exception as e:
        stop_event.set()
        t.join(timeout=1)
        print()
        raise e

def get_identity_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-identity-token"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
    except Exception:
        return None

def get_cf_url(function_name, location, project_id):
    try:
        cmd = [
            "gcloud", "functions", "describe", function_name,
            "--gen2",
            "--region", location,
            "--project", project_id,
            "--format", "value(serviceConfig.uri)"
        ]
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
    except Exception:
        return None

def main():
    print("================================================================================")
    print("🔍 PRE-SYNC CHECK: SHAREPOINT INVENTORY & DELTA CALCULATION (BEFORE SYNC)")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in working directory.")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    project_id = params.get("CONFIG_ProjectId", "")
    location = params.get("CONFIG_Location", "asia-southeast1")
    bucket_name = params.get("CONFIG_GCS_Bucket", "")
    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    library_name = params.get("CONFIG_Sharepoint_Library", "Documents")
    function_name = params.get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files")
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")

    print("📂 Step 1: Loading Pipeline Parameters...")
    print(f" • Project ID            : {project_id}")
    print(f" • Target GCS Bucket     : gs://{bucket_name}")
    print(f" • Target SharePoint Site: {site_path}")
    print(f" • Document Library      : {library_name}\n")

    if not cf_endpoint and function_name and project_id:
        print("🔍 Resolving Traversal Cloud Function URI...")
        cf_endpoint = get_cf_url(function_name, location, project_id)

    if not cf_endpoint:
        print("❌ Could not resolve Traversal Cloud Function URL. Ensure CONFIG_CloudFunction_URL is set or function is deployed.")
        sys.exit(1)

    token = get_identity_token()
    if not token:
        print("❌ Failed to obtain Google OIDC identity token. Please run 'gcloud auth login'.")
        sys.exit(1)

    site_name_clean = site_path[len("sites/"):] if site_path.startswith("sites/") else site_path

    payload = {
        "site_name": site_name_clean,
        "library_name": library_name,
        "trigger_integration": False,
        "sync_files": True,
        "sync_pages": True
    }

    print(f"📂 Step 2: Querying Traversal Cloud Function for Live SharePoint Inventory & Delta Check...")
    req = urllib.request.Request(
        cf_endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with run_with_heartbeat("Scanning SharePoint items and evaluating O(1) GCS Delta Cache", urllib.request.urlopen, req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        print(f"❌ Traversal Cloud Function invocation failed (HTTP {e.code}): {e.reason}")
        print(f"   Response details: {err_msg}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error invoking Traversal Cloud Function: {e}")
        sys.exit(1)

    all_items = data.get("all_resources", data.get("items", []))
    sync_items = data.get("sync_resources", data.get("items", []))

    # Calculate SharePoint target totals
    total_sp_pages = sum(1 for x in all_items if x.get("IsPage"))
    total_sp_files = sum(1 for x in all_items if not x.get("IsPage"))
    total_sp_items = len(all_items)

    # Calculate items that WILL be synced (Delta)
    delta_pages = sum(1 for x in sync_items if x.get("IsPage"))
    delta_files = sum(1 for x in sync_items if not x.get("IsPage"))
    delta_total = len(sync_items)

    # Calculate items already up to date (Skipped by cache)
    skipped_pages = total_sp_pages - delta_pages
    skipped_files = total_sp_files - delta_files
    skipped_total = total_sp_items - delta_total

    print("\n================================================================================")
    print("📊 PRE-SYNC VERIFICATION REPORT (BEFORE SYNC)")
    print("================================================================================")
    print(f"1️⃣  TOTAL SHAREPOINT TARGET INVENTORY:")
    print(f"    • Total Modern Site Pages (.aspx -> .pdf): {total_sp_pages:>6}")
    print(f"    • Total Document Files                   : {total_sp_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL INVENTORY ITEMS                  : {total_sp_items:>6}")
    print("--------------------------------------------------------------------------------")
    print(f"2️⃣  ITEMS TO BE SYNCED (DELTA NEEDING UPLOAD/RENDER):")
    print(f"    • Pages Needing Sync                     : {delta_pages:>6}")
    print(f"    • Files Needing Sync                     : {delta_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL DELTA TO SYNC                    : {delta_total:>6}")
    print("--------------------------------------------------------------------------------")
    print(f"3️⃣  ITEMS ALREADY UP-TO-DATE IN GCS (WILL BE SKIPPED):")
    print(f"    • Pages Skipped (Unchanged in GCS)       : {skipped_pages:>6}")
    print(f"    • Files Skipped (Unchanged in GCS)       : {skipped_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL SKIPPED                          : {skipped_total:>6}")
    print("================================================================================")

    if delta_total == 0:
        print("✅ RECOMMENDATION: All SharePoint items are already synced and up to date!")
    else:
        print(f"🚀 RECOMMENDATION: Proceed with synchronization. {delta_total} item(s) will be processed.")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
