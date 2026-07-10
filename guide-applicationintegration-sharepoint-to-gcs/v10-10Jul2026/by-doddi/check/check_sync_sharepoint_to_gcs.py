import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
import json
import subprocess
import os
import sys
import urllib.request
import urllib.error
import threading
import time

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
        return subprocess.check_output(["gcloud", "auth", "print-identity-token"]).decode("utf-8").strip()
    except Exception as e:
        return None

def get_cf_url(function_name, location, project_id):
    # First inspect as a custom container Cloud Run service
    try:
        cmd_run = [
            "gcloud", "run", "services", "describe", function_name,
            "--region", location,
            "--project", project_id,
            "--format", "value(status.url)"
        ]
        url = subprocess.check_output(cmd_run, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        if url and url.startswith("https://"):
            return url
    except Exception:
        pass
    # Fallback to standard Cloud Functions Gen2 describe
    try:
        cmd_cf = [
            "gcloud", "functions", "describe", function_name,
            "--gen2",
            "--region", location,
            "--project", project_id,
            "--format", "value(serviceConfig.uri)"
        ]
        return subprocess.check_output(cmd_cf, stderr=subprocess.DEVNULL).decode("utf-8").strip()
    except Exception:
        return None

def check_full_sync():
    print("================================================================================")
    print("🔍 DIAGNOSTIC CHECK: FULL SHAREPOINT-TO-GCS TRAVERSAL SYNC (V6.0)")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in current directory.")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    bucket_name = params.get("CONFIG_GCS_Bucket")
    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    library_name = params.get("CONFIG_Sharepoint_Library", "Documents")
    batch_size = params.get("CONFIG_Batch_Size", 10)
    integration_name = params.get("CONFIG_Parent_Integration_Name", "yourorg-sharepoint-gcs-parent")
    project_id = params.get("CONFIG_ProjectId", "your-project")

    if not bucket_name:
        print("❌ Error: CONFIG_GCS_Bucket not defined in parameters.json.")
        sys.exit(1)

    print(f"📂 Step 1: Inspecting Target SharePoint Configuration...")
    sync_files = params.get("CONFIG_Sync_SharePoint_Files", True)
    sync_pages = params.get("CONFIG_Sync_SharePoint_Pages", True)
    print(f" • Target Subsite Path    : {site_path}")
    print(f" • Target Document Library: {library_name}")
    print(f" • Sync Scope Toggles     : Files={sync_files} | Pages={sync_pages}")
    print(f" • Orchestration Batch Size: Sliced into chunks of {batch_size} items per trigger\n")

    print(f"📂 Step 2: Inspecting existing GCS bucket inventory (gs://{bucket_name}/)...")
    existing_pages = 0
    existing_files = 0
    total_size_bytes = 0
    try:
        ls_out = subprocess.check_output(["gcloud", "storage", "ls", "--long", f"gs://{bucket_name}/**"], stderr=subprocess.DEVNULL).decode("utf-8")
        for line in ls_out.splitlines():
            if "/pages/" in line or "/files/" in line:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[0].isdigit():
                    size_b = int(parts[0])
                    total_size_bytes += size_b
                    if "/pages/" in line:
                        existing_pages += 1
                    else:
                        existing_files += 1
        size_mb = total_size_bytes / (1024 * 1024)
        print(f"✅ Found {existing_pages + existing_files} existing cached file(s) in GCS totaling {size_mb:.2f} MB.")
        print(f"   • Cached Modern Site Pages (.pdf): {existing_pages}")
        print(f"   • Cached Document Files          : {existing_files}\n")
    except Exception:
        print("ℹ️ Could not fetch detailed sizes from GCS or bucket folders are currently empty.\n")

    print(f"📂 Step 3: Analyzing Live SharePoint Inventory vs Delta Cache...")
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")
    function_name = params.get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files")
    location = params.get("CONFIG_Location", "asia-southeast1")
    if not cf_endpoint and function_name:
        cf_endpoint = get_cf_url(function_name, location, project_id)
        
    token = get_identity_token()
    if cf_endpoint and token:
        try:
            site_name_clean = site_path[len("sites/"):] if site_path.startswith("sites/") else site_path
            payload = {
                "site_name": site_name_clean,
                "library_name": library_name,
                "trigger_integration": False,
                "sync_files": sync_files,
                "sync_pages": sync_pages
            }
            req = urllib.request.Request(cf_endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
            print("   ⏳ Connecting to Cloud Function to analyze Microsoft Graph API inventory...")
            with run_with_heartbeat("Crawling SharePoint inventory & checking Delta Cache", urllib.request.urlopen, req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                all_items = data.get("all_resources", data.get("items", []))
                sync_items = data.get("sync_resources", data.get("items", []))
                skipped_count = len(all_items) - len(sync_items)
                print(f"✅ Live Analysis Complete!")
                print(f"   • Total Items Scanned in SharePoint: {len(all_items)}")
                print(f"   • Skipped (Delta Hit / Already in GCS): {skipped_count}")
                print(f"   • Items Needing Sync to GCS        : {len(sync_items)}\n")
        except Exception as e:
            print(f"ℹ️ Could not complete live dry-run against Cloud Function: {e}\n")
    else:
        print("ℹ️ Skipping live dry-run (Cloud Function URL or auth token unavailable).\n")

    print("================================================================================")
    print("⚡ HOW TO TRIGGER & MONITOR PROGRESS (RECOMMENDED PRODUCTION WORKFLOW)")
    print("================================================================================")
    print("1. Cloud Scheduler (Recommended Unattended Production Execution):")
    print(f"   Trigger your automated scheduler job:")
    print(f"   gcloud scheduler jobs run {params.get('CONFIG_Scheduler_Job_Name', 'doddi-sharepoint-sync-hourly')} --location={location} --project={project_id}\n")
    print("2. Google Cloud Console Dashboards:")
    print(f"   • Application Integration: Go to Executions for '{integration_name}' in project '{project_id}'")
    print(f"   • Logs Explorer          : Filter by resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"{function_name}\"")
    print("   • Cloud Scheduler        : View Cron job execution status ('Success'/'Failed') and click 'View Logs'\n")
    print("3. Post-Sync Inventory Verification:")
    print("   Run 'python3 check/check_syncall_after.py' to compare live SharePoint vs GCS counts.")
    print("================================================================================\n")

if __name__ == "__main__":
    check_full_sync()
