import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import sys
import datetime
import concurrent.futures
import threading
import re

try:
    import log_helper
except ImportError:
    log_helper = None

def get_auth_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
    except Exception as e:
        print(f"❌ Failed to get gcloud access token: {e}")
        sys.exit(1)

def get_identity_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-identity-token"]).decode("utf-8").strip()
    except Exception as e:
        print(f"❌ Failed to get gcloud identity token: {e}")
        sys.exit(1)

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
    except Exception as e:
        print(f"❌ Failed to retrieve Cloud Function URI: {e}")
        return None

def run_dynamic_gcs_sync():
    if log_helper:
        log_helper.init_logging("setup")
        
    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)
        
    with open("parameters.json", "r") as f:
        params = json.load(f)

    PROJECT_ID = params.get("CONFIG_ProjectId")
    LOCATION = params.get("CONFIG_Location")
    PARENT_INTEGRATION_NAME = params.get("CONFIG_Parent_Integration_Name")
    FUNCTION_NAME = params.get("CONFIG_CloudFunction_Name")
    
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")
    if not cf_endpoint and FUNCTION_NAME:
        print("🔍 Resolving Cloud Function URI dynamically...")
        cf_endpoint = get_cf_url(FUNCTION_NAME, LOCATION, PROJECT_ID)
        
    if not cf_endpoint:
        print("❌ Could not resolve Cloud Function URI.")
        sys.exit(1)
    else:
        print(f"✅ Resolved Cloud Function URI: {cf_endpoint}")

    print("================================================================")
    print("🚀 STARTING DYNAMIC GCS CONFIG ON-DEMAND SYNC PIPELINE")
    print("================================================================")
    
    identity_token = get_identity_token()
    headers_cf = {
        "Authorization": f"Bearer {identity_token}",
        "Content-Type": "application/json"
    }

    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    site_name = site_path[len("sites/"):] if site_path.startswith("sites/") else site_path
    bucket_name = params.get("CONFIG_GCS_Bucket")
    batch_size = params.get("CONFIG_Batch_Size", 10)

    print(f"📂 Step 1: Reading target URLs directly from gs://{bucket_name}/config/target_urls.txt for upstream slicing...")
    target_urls = []
    try:
        raw_cfg = subprocess.check_output(["gcloud", "storage", "cat", f"gs://{bucket_name}/config/target_urls.txt"]).decode("utf-8")
        target_urls = [l.strip() for l in raw_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
        print(f"🟢 Resolved {len(target_urls)} total URL(s) from GCS configuration.")
    except Exception as e:
        print(f"❌ Failed to read target_urls.txt from GCS: {e}")
        sys.exit(1)

    if not target_urls:
        print("ℹ️ No target URLs found to synchronize. Exiting cleanly.")
        return

    max_workers = params.get("CONFIG_Max_Parallel_Workers", 10)
    total_batches = (len(target_urls) + batch_size - 1) // batch_size
    print(f"\n🚀 Step 2: Slicing into {total_batches} micro-batch(es) (max {batch_size} items/batch, running up to {max_workers} batches in parallel)...")

    access_token = get_auth_token()
    integration_url = f"https://{LOCATION}-integrations.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/integrations/{PARENT_INTEGRATION_NAME}:schedule"
    headers_int = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    print_lock = threading.Lock()
    manifest_lock = threading.Lock()
    unified_manifest_records = []
    execution_ids = []

    def process_batch(batch_num, batch_urls):
        log_buf = []
        log_buf.append(f"\n================================================================================")
        log_buf.append(f"⚡ Processing Micro-Batch {batch_num}/{total_batches} ({len(batch_urls)} URLs)...")
        log_buf.append(f"================================================================================")
        for idx, u in enumerate(batch_urls, 1):
            log_buf.append(f"   🔹 [{idx}/{len(batch_urls)}] Target: {u}")
        log_buf.append(f"   ⏳ Invoking Cloud Function ({cf_endpoint}) to render/resolve batch...")

        force_sync = "--force" in sys.argv or "--force-full-sync" in sys.argv
        payload_cf = {
            "site_name": site_name,
            "library_name": params.get("CONFIG_Sharepoint_Library", "Documents"),
            "target_urls": batch_urls,
            "sync_files": params.get("CONFIG_Sync_SharePoint_Files", True),
            "sync_pages": params.get("CONFIG_Sync_SharePoint_Pages", True),
            "pdf_conversion_engine": params.get("CONFIG_PDF_Conversion_Engine", "playwright"),
            "force_full_sync": force_sync
        }
        req_cf = urllib.request.Request(cf_endpoint, data=json.dumps(payload_cf).encode("utf-8"), headers=headers_cf, method="POST")
        
        try:
            with urllib.request.urlopen(req_cf, timeout=3600) as resp:
                cf_resp = json.loads(resp.read().decode("utf-8"))
                sync_list = cf_resp.get("items", [])
                all_count = cf_resp.get("all_resources_count", len(batch_urls))
                skipped_count = all_count - len(sync_list)
                log_buf.append(f"   ✅ Cloud Function resolved Batch {batch_num} successfully!")
                log_buf.append(f"      • Total items scanned in batch: {all_count}")
                log_buf.append(f"      • Items needing upload (Delta hit/rendered): {len(sync_list)}")
                if skipped_count > 0:
                    log_buf.append(f"      • Skipped (Unchanged in GCS / Delta cache hit): {skipped_count}")
                for item in sync_list:
                    log_buf.append(f"      📄 Prepared item: {item.get('Name')} -> gs://{bucket_name}/{item.get('RelativePath')}")
                    raw_name = item.get("Name", "doc")
                    rel_path = item.get("RelativePath", "")
                    base_name = raw_name.rsplit('.', 1)[0]
                    doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
                    record = {
                        "_id": doc_id,
                        "id": doc_id,
                        "structData": {
                            "sharepoint_url": item.get("Url", ""),
                            "title": raw_name,
                            "relative_path": rel_path
                        },
                        "content": {
                            "mimeType": "application/pdf",
                            "uri": f"gs://{bucket_name}/{rel_path}"
                        }
                    }
                    with manifest_lock:
                        unified_manifest_records.append(record)
        except Exception as e:
            with print_lock:
                print("\n".join(log_buf))
                print(f"   ❌ Cloud Function invocation failed for batch {batch_num}: {e}")
            return None

        log_buf.append(f"   ⏳ Submitting Batch {batch_num} to Application Integration...")
        payload_int = {
            "triggerId": f"api_trigger/{PARENT_INTEGRATION_NAME}-trigger",
            "inputParameters": {
                "`Parent_Files_List`": {
                    "jsonValue": json.dumps(sync_list)
                }
            }
        }
        req_int = urllib.request.Request(integration_url, data=json.dumps(payload_int).encode("utf-8"), headers=headers_int, method="POST")
        
        execution_id = None
        try:
            with urllib.request.urlopen(req_int) as resp_int:
                resp_data = json.loads(resp_int.read().decode("utf-8"))
                execution_id = resp_data.get("executionId") or resp_data.get("scheduleId") or (resp_data.get("executionIds", ["Check Console"])[0])
                log_buf.append(f"   🟢 Integration triggered successfully -> Execution ID: {execution_id}")
        except Exception as e:
            with print_lock:
                print("\n".join(log_buf))
                print(f"   ❌ Integration trigger failed for batch {batch_num}: {e}")
            return None

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        status_data = {
            "batch_number": batch_num,
            "total_batches": total_batches,
            "timestamp_utc": now_utc.isoformat(),
            "status": "SUCCESS",
            "item_count": len(batch_urls),
            "execution_id": execution_id,
            "processed_urls": batch_urls
        }
        status_filename = f"batch_completion_{now_utc.strftime('%Y%m%d_%H%M%SZ')}_batch_{batch_num}_of_{total_batches}.json"
        tmp_path = f"/tmp/{status_filename}"
        status_gcs_uri = f"gs://{bucket_name}/config/status/{status_filename}"
        try:
            with open(tmp_path, "w") as sf:
                json.dump(status_data, sf, indent=2)
            subprocess.run(["gcloud", "storage", "cp", tmp_path, status_gcs_uri], check=True)
            log_buf.append(f"   📄 Logged completion audit status to {status_gcs_uri}")
            log_buf.append(f"   🎉 Micro-Batch {batch_num}/{total_batches} COMPLETED SUCCESSFULLY!\n")
        except Exception as e:
            log_buf.append(f"   ⚠️ Warning: Could not write completion status to GCS: {e}\n")

        with print_lock:
            print("\n".join(log_buf))
        return execution_id

    batches = []
    for i in range(0, len(target_urls), batch_size):
        batch_urls = target_urls[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        batches.append((batch_num, batch_urls))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_batch, b_num, b_urls): b_num for b_num, b_urls in batches}
        for future in concurrent.futures.as_completed(futures):
            eid = future.result()
            if eid:
                execution_ids.append(eid)

    if unified_manifest_records:
        print(f"\n🧠 Uploading consolidated config/metadata.jsonl ({len(unified_manifest_records)} records) to GCS...")
        try:
            jsonl_str = "\n".join(json.dumps(r) for r in unified_manifest_records)
            upload_cmd = ["gcloud", "storage", "cp", "-", f"gs://{bucket_name}/config/metadata.jsonl"]
            proc = subprocess.run(upload_cmd, input=jsonl_str.encode("utf-8"), check=True, capture_output=True)
            print(f"✅ Successfully written consolidated metadata manifest to gs://{bucket_name}/config/metadata.jsonl")
        except Exception as e_manifest:
            print(f"❌ Failed to write consolidated metadata manifest: {e_manifest}")

    print("\n================================================================")
    print("🎉 ALL DYNAMIC GCS SYNC BATCHES SCHEDULED SUCCESSFULLY!")
    print("================================================================")
    for eid in execution_ids:
        print(f" - {eid}")
        print(f"   https://console.cloud.google.com/integrations/logs;integration_name={PARENT_INTEGRATION_NAME};execution_id={eid};region={LOCATION}?project={PROJECT_ID}")
    print("================================================================")

if __name__ == "__main__":
    run_dynamic_gcs_sync()
