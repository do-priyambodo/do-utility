#!/usr/bin/env python3
import json
import subprocess
import os
import sys
import urllib.parse

def check_dynamic_sync():
    print("================================================================================")
    print("🔍 DIAGNOSTIC CHECK: DYNAMIC SHAREPOINT-TO-GCS SYNC PIPELINE (V5.0)")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in current directory.")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    bucket_name = params.get("CONFIG_GCS_Bucket")
    batch_size = params.get("CONFIG_Batch_Size", 10)
    max_workers = params.get("CONFIG_Max_Parallel_Workers", 10)
    integration_name = params.get("CONFIG_Parent_Integration_Name", "yourorg-sharepoint-gcs-parent")
    project_id = params.get("CONFIG_ProjectId", "your-project")

    if not bucket_name:
        print("❌ Error: CONFIG_GCS_Bucket not defined in parameters.json.")
        sys.exit(1)

    print(f"📂 Step 1: Fetching dynamic configuration from gs://{bucket_name}/config/target_urls.txt...")
    target_urls = []
    try:
        raw_cfg = subprocess.check_output(["gcloud", "storage", "cat", f"gs://{bucket_name}/config/target_urls.txt"]).decode("utf-8")
        target_urls = [l.strip() for l in raw_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
        print(f"✅ Successfully read {len(target_urls)} active target URL(s) from GCS.\n")
    except Exception as e:
        print(f"❌ Failed to read target_urls.txt from GCS: {e}")
        print("ℹ️ Ensure the file exists in your GCS bucket. You can run './upload_gcs_targets.sh' to create/upload it.")
        sys.exit(1)

    if not target_urls:
        print("ℹ️ No target URLs found in configuration. Nothing to sync.")
        return

    pages_count = 0
    files_count = 0
    page_urls = []
    file_urls = []

    for u in target_urls:
        clean_url = u.split("?")[0].strip()
        parsed = urllib.parse.urlparse(clean_url)
        filename = os.path.basename(urllib.parse.unquote(parsed.path))
        if filename.lower().endswith(".aspx"):
            pages_count += 1
            page_urls.append((filename, u))
        else:
            files_count += 1
            file_urls.append((filename, u))

    total_batches = (len(target_urls) + batch_size - 1) // batch_size

    print("================================================================================")
    print("📊 TARGET INVENTORY BREAKDOWN")
    print("================================================================================")
    print(f" • Total Targeted Items   : {len(target_urls)}")
    print(f" • Modern Site Pages (.aspx): {pages_count} (Will convert to executive .pdf reports)")
    print(f" • Document Files         : {files_count} (Will stream raw binary to GCS)")
    print("--------------------------------------------------------------------------------")
    print(f" • Micro-Batch Configuration: Sliced into {total_batches} batch(es) of max {batch_size} items")
    print(f" • Concurrency Execution    : Up to {max_workers} batches executing concurrently in parallel")
    print("================================================================================\n")

    print(f"📂 Step 2: Inspecting existing GCS bucket inventory (gs://{bucket_name}/)...")
    existing_count = 0
    total_size_bytes = 0
    try:
        ls_out = subprocess.check_output(["gcloud", "storage", "ls", "--long", f"gs://{bucket_name}/**"], stderr=subprocess.DEVNULL).decode("utf-8")
        for line in ls_out.splitlines():
            if "/pages/" in line or "/files/" in line:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[0].isdigit():
                    size_b = int(parts[0])
                    total_size_bytes += size_b
                    existing_count += 1
        size_mb = total_size_bytes / (1024 * 1024)
        print(f"✅ Found {existing_count} existing cached file(s) in GCS totaling {size_mb:.2f} MB.\n")
    except Exception:
        print("ℹ️ Could not fetch detailed sizes from GCS or bucket folders are currently empty.\n")

    print("================================================================================")
    print("📈 EXPECTED PERFORMANCE & TIME ESTIMATION")
    print("================================================================================")
    est_seconds_serial = len(target_urls) * 2.0
    est_seconds_parallel = max(15.0, est_seconds_serial / min(max_workers, total_batches))
    print(f" • Serial Execution Estimate  : ~{est_seconds_serial/60:.1f} minutes ({len(target_urls)} items one-by-one)")
    print(f" • Parallel Execution Estimate: ~{est_seconds_parallel:.0f} seconds (~{est_seconds_parallel/60:.1f} min) with {max_workers} workers")
    print("   *(Note: Subsequent daily runs with Delta Cache hits will complete in <30 seconds!)*")
    print("================================================================================\n")

    print("================================================================================")
    print("🖥️ HOW TO MONITOR PROGRESS & EXPECTED RESULTS")
    print("================================================================================")
    print("1. Real-Time Console Stream:")
    print("   Run 'python3 sync_gcs_dynamic.py' and watch unbroken batch summaries appear as workers finish:")
    print("   -----------------------------------------------------------------------------")
    print("   ⚡ Processing Micro-Batch 1/1 (10 URLs)...")
    print("   ✅ Cloud Function resolved Batch 1 successfully!")
    print("      • Items needing upload: 8 | Skipped (Delta hit): 2")
    print("   🟢 Integration triggered successfully -> Execution ID: 9f8a7b6c-...")
    print("   🎉 Micro-Batch 1/1 COMPLETED SUCCESSFULLY!")
    print("   -----------------------------------------------------------------------------\n")
    print("2. Google Cloud Console Dashboards:")
    print(f"   • Application Integration: Go to Executions for '{integration_name}' in project '{project_id}'")
    print("   • Logs Explorer          : Filter by resource.type=\"cloud_function\" AND resource.labels.function_name=\"doddi-sharepoint-list-files\"\n")
    print("3. Permanent GCS Completion Manifests:")
    print(f"   Check completion records saved after every batch: gs://{bucket_name}/config/status/")
    print("================================================================================\n")

if __name__ == "__main__":
    check_dynamic_sync()
