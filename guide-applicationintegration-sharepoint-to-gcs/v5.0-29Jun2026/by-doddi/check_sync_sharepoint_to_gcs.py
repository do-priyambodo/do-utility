#!/usr/bin/env python3
import json
import subprocess
import os
import sys
import urllib.request
import urllib.error

def get_identity_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-identity-token"]).decode("utf-8").strip()
    except Exception as e:
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
        return subprocess.check_output(cmd).decode("utf-8").strip()
    except Exception:
        return None

def check_full_sync():
    print("================================================================================")
    print("🔍 DIAGNOSTIC CHECK: FULL SHAREPOINT-TO-GCS TRAVERSAL SYNC (V5.0)")
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
            with urllib.request.urlopen(req, timeout=60) as resp:
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
    print("⚡ HOW V5.0 FULL TRAVERSAL SYNC WORKS AT RUNTIME")
    print("================================================================================")
    print("1. O(1) Memory Cache : The Cloud Function pre-fetches all existing GCS timestamps.")
    print("2. Graph API Crawl   : Recursively crawls SharePoint folders & modern site pages.")
    print("3. Delta Comparison  : Skips downloading unchanged items (reducing 17 GB+ daily transfer down to MBs).")
    print("4. Automated Deletion: Purges orphaned GCS files deleted from SharePoint.")
    print("================================================================================\n")

    print("================================================================================")
    print("🖥️ HOW TO MONITOR PROGRESS & EXPECTED RESULTS")
    print("================================================================================")
    print("1. Terminal Console Stream (Manual Execution):")
    print("   Run 'python3 sync_sharepoint_to_gcs.py' to watch batch scheduling outputs:")
    print("   -----------------------------------------------------------------------------")
    print("   🔒 Step 1: Invoking SharePoint traversal Cloud Function...")
    print("   🟢 Found 1,743 total items (documents & pre-rendered pages) to synchronize.")
    print("   🚀 Step 2: Submitting batches to Application Integration...")
    print("   🟢 Batch 1 scheduled -> Execution ID: 39017360-...")
    print("   🎉 ALL SYNC BATCHES SCHEDULED SUCCESSFULLY!")
    print("   -----------------------------------------------------------------------------\n")
    print("2. Google Cloud Console Dashboards:")
    print(f"   • Application Integration: Go to Executions for '{integration_name}' in project '{project_id}'")
    print("   • Logs Explorer          : Filter by resource.type=\"cloud_function\" AND resource.labels.function_name=\"doddi-sharepoint-list-files\"")
    print("   • Cloud Scheduler        : View Cron job execution status ('Success'/'Failed') and click 'View Logs'\n")
    print("3. Verification CLI Helper:")
    print(f"   Run check_execution.py with an Execution ID to inspect workflow step details.")
    print("================================================================================\n")

if __name__ == "__main__":
    check_full_sync()
