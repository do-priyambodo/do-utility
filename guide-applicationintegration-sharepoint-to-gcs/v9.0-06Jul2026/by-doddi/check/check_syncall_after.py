#!/usr/bin/env python3
"""
check_syncall_after.py - V9.0 Post-Sync Verification

Calculates:
  1. Total modern site pages (.pdf) and document files in the Google Cloud Storage (GCS) bucket.
  2. How many files and pages are already synced and up-to-date (Delta cache verification).
  3. Confirms whether any remaining delta items still require synchronization.
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

def inspect_gcs_bucket(bucket_name):
    gcs_pages = 0
    gcs_files = 0
    gcs_total_bytes = 0

    # Try Google Cloud Storage Python SDK first
    try:
        from google.cloud import storage
        client = storage.Client()
        blobs = client.list_blobs(bucket_name)
        for b in blobs:
            if b.name.startswith("pages/"):
                gcs_pages += 1
                gcs_total_bytes += (b.size or 0)
            elif b.name.startswith("files/"):
                gcs_files += 1
                gcs_total_bytes += (b.size or 0)
        return gcs_pages, gcs_files, gcs_total_bytes
    except Exception:
        pass

    # Fall back to gcloud storage CLI
    try:
        ls_out = subprocess.check_output(
            ["gcloud", "storage", "ls", "--long", "--recursive", f"gs://{bucket_name}/**"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8")
        for line in ls_out.splitlines():
            line_str = line.strip()
            if "/pages/" in line_str or "/files/" in line_str:
                parts = line_str.split()
                if len(parts) >= 3 and parts[0].isdigit():
                    size_b = int(parts[0])
                    gcs_total_bytes += size_b
                    if "/pages/" in line_str:
                        gcs_pages += 1
                    elif "/files/" in line_str:
                        gcs_files += 1
    except Exception:
        pass

    return gcs_pages, gcs_files, gcs_total_bytes

def main():
    print("================================================================================")
    print("🔍 POST-SYNC CHECK: GCS BUCKET INVENTORY & DELTA VERIFICATION (AFTER SYNC)")
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

    print(f"📂 Step 2: Inspecting Google Cloud Storage Bucket Inventory (gs://{bucket_name}/)...")
    gcs_pages, gcs_files, gcs_total_bytes = inspect_gcs_bucket(bucket_name)
    gcs_size_mb = gcs_total_bytes / (1024 * 1024) if gcs_total_bytes > 0 else 0.0
    gcs_total_items = gcs_pages + gcs_files
    print(f"✅ GCS Bucket Inspection Complete.")
    print(f"   • Modern Site Pages (.pdf) in GCS ('pages/'): {gcs_pages}")
    print(f"   • Document Files in GCS ('files/')          : {gcs_files}")
    print(f"   • Total Items Stored in GCS                 : {gcs_total_items} ({gcs_size_mb:.2f} MB)\n")

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

    print(f"📂 Step 3: Verifying Sync Completion via Live Delta Comparison...")
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
        with run_with_heartbeat("Checking SharePoint inventory against GCS Delta Cache", urllib.request.urlopen, req, timeout=600) as resp:
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

    # Calculate remaining delta (items still needing sync)
    remaining_pages = sum(1 for x in sync_items if x.get("IsPage"))
    remaining_files = sum(1 for x in sync_items if not x.get("IsPage"))
    remaining_total = len(sync_items)

    # Calculate already synced & up to date (Delta Cache Hit)
    synced_pages = total_sp_pages - remaining_pages
    synced_files = total_sp_files - remaining_files
    synced_total = total_sp_items - remaining_total

    print("\n================================================================================")
    print("📊 POST-SYNC VERIFICATION REPORT (AFTER SYNC)")
    print("================================================================================")
    print(f"1️⃣  GOOGLE CLOUD STORAGE BUCKET INVENTORY (gs://{bucket_name}):")
    print(f"    • Total Modern Site Pages Stored ('pages/') : {gcs_pages:>6}")
    print(f"    • Total Document Files Stored ('files/')    : {gcs_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL GCS OBJECTS STORED                  : {gcs_total_items:>6} ({gcs_size_mb:.2f} MB)")
    print("--------------------------------------------------------------------------------")
    print(f"2️⃣  ALREADY SYNCED & UP-TO-DATE IN GCS (DELTA CACHE VERIFIED):")
    print(f"    • Pages Already Synced & Up-To-Date         : {synced_pages:>6} / {total_sp_pages}")
    print(f"    • Files Already Synced & Up-To-Date         : {synced_files:>6} / {total_sp_files}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL IN-SYNC ITEMS                       : {synced_total:>6} / {total_sp_items}")
    print("--------------------------------------------------------------------------------")
    print(f"3️⃣  REMAINING DELTA (UNSYNCED / IN-PROGRESS ITEMS):")
    print(f"    • Remaining Pages Needing Sync              : {remaining_pages:>6}")
    print(f"    • Remaining Files Needing Sync              : {remaining_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL REMAINING DELTA                     : {remaining_total:>6}")
    print("================================================================================")

    if remaining_total == 0:
        print("🎉 SUCCESS: 100% of SharePoint pages and files are fully synchronized in GCS!")
    else:
        print(f"⚠️ NOTICE: {remaining_total} item(s) remain unsynced or modified since last sync trigger.")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
