#!/usr/bin/env python3
import json
import subprocess
import os
import sys

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
    print(f" • Target Subsite Path    : {site_path}")
    print(f" • Target Document Library: {library_name}")
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
