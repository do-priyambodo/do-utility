import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import sys
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

def run_sync():
    if log_helper:
        log_helper.init_logging("setup")
    # 1. Load configurations from parameters.json
    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)
        
    with open("parameters.json", "r") as f:
        params = json.load(f)
        
    PROJECT_ID = params.get("CONFIG_ProjectId")
    LOCATION = params.get("CONFIG_Location")
    SERVICE_ACCOUNT = params.get("CONFIG_Service_Account")
    PARENT_INTEGRATION_NAME = params.get("CONFIG_Parent_Integration_Name")
    FUNCTION_NAME = params.get("CONFIG_CloudFunction_Name")
    
    # Resolve Cloud Function URL from config or dynamically
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")
    if not cf_endpoint and FUNCTION_NAME:
        print("🔍 Resolving Cloud Function URI dynamically...")
        cf_endpoint = get_cf_url(FUNCTION_NAME, LOCATION, PROJECT_ID)
        
    if not cf_endpoint:
        print("❌ Could not resolve Cloud Function URI. Please specify CONFIG_CloudFunction_URL in parameters.json or deploy the Cloud Function.")
        sys.exit(1)
    else:
        print(f"✅ Resolved Cloud Function URI: {cf_endpoint}")
        
    print("================================================================")
    print("🚀 STARTING E2E SHAREPOINT TO GCS SYNC PIPELINE (V4-HYBRID)")
    print("================================================================")
    
    # Step 1: Retrieve OIDC identity token and call Cloud Function to traverse SharePoint
    identity_token = get_identity_token()
    headers_cf = {
        "Authorization": f"Bearer {identity_token}",
        "Content-Type": "application/json"
    }

    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    if site_path.startswith("sites/"):
        site_name = site_path[len("sites/"):]
    else:
        site_name = site_path

    force_sync = "--force" in sys.argv or "--force-full-sync" in sys.argv
    payload_cf = {
        "site_name": site_name,
        "library_name": params.get("CONFIG_Sharepoint_Library", "Documents"),
        "sync_files": params.get("CONFIG_Sync_SharePoint_Files", True),
        "sync_pages": params.get("CONFIG_Sync_SharePoint_Pages", True),
        "pdf_conversion_engine": params.get("CONFIG_PDF_Conversion_Engine", "weasyprint"),
        "force_full_sync": force_sync
    }
    
    cf_request_bytes = json.dumps(payload_cf).encode("utf-8")
    req_cf = urllib.request.Request(cf_endpoint, data=cf_request_bytes, headers=headers_cf, method="POST")
    
    try:
        print("🔒 Step 1: Invoking SharePoint traversal Cloud Function (Option B pages resolved)...")
        with run_with_heartbeat("Crawling SharePoint site & comparing Delta Cache", urllib.request.urlopen, req_cf, timeout=3600) as resp:
            cf_resp = json.loads(resp.read().decode("utf-8"))
            if log_helper:
                log_helper.log_cloud("=== Cloud Function SharePoint Traversal Response ===")
                log_helper.log_cloud(json.dumps(cf_resp, indent=2))
            sync_list = cf_resp.get("items", [])
            # Exclude non-downloadable ASPX system/form pages located in document libraries
            sync_list = [item for item in sync_list if not (not item.get("IsPage") and item.get("Name", "").lower().endswith(".aspx"))]
            print(f"🟢 Found {len(sync_list)} total items (documents & pre-rendered pages) to synchronize.")
    except urllib.error.HTTPError as e:
        print(f"❌ SharePoint traversal failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception during SharePoint traversal: {e}")
        sys.exit(1)
        
    if not sync_list:
        print("ℹ️ No files or pages found to synchronize. Pipeline exiting cleanly.")
        return
        
    # Step 2: Call Application Integration asynchronously passing batched sync list payloads
    access_token = get_auth_token()
    integration_url = f"https://{LOCATION}-integrations.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/integrations/{PARENT_INTEGRATION_NAME}:schedule"
    
    headers_int = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    batch_size = params.get("CONFIG_Batch_Size", 100)
    total_batches = (len(sync_list) + batch_size - 1) // batch_size
    print(f"\n🚀 Step 2: Triggering Application Integration ({PARENT_INTEGRATION_NAME}) asynchronously across {total_batches} batch(es) of max {batch_size} items...")

    execution_ids = []
    for i in range(0, len(sync_list), batch_size):
        batch = sync_list[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        payload_int = {
            "triggerId": f"api_trigger/{PARENT_INTEGRATION_NAME}-trigger",
            "inputParameters": {
                "`Parent_Files_List`": {
                    "jsonValue": json.dumps(batch)
                }
            }
        }
        
        int_request_bytes = json.dumps(payload_int).encode("utf-8")
        req_int = urllib.request.Request(integration_url, data=int_request_bytes, headers=headers_int, method="POST")
        
        try:
            with urllib.request.urlopen(req_int) as resp_int:
                resp_data = json.loads(resp_int.read().decode("utf-8"))
                if log_helper:
                    log_helper.log_cloud(f"=== Batch {batch_num}/{total_batches} Trigger Response ===")
                    log_helper.log_cloud(json.dumps(resp_data, indent=2))
                execution_id = resp_data.get("executionId")
                execution_ids.append(execution_id)
                print(f" 🟢 Batch {batch_num}/{total_batches} ({len(batch)} items) scheduled -> Execution ID: {execution_id}")
        except urllib.error.HTTPError as e:
            print(f"❌ Application Integration batch {batch_num} execution failed (Code {e.code}): {e.reason}")
            print(e.read().decode("utf-8"))
            sys.exit(1)
        except Exception as e:
            print(f"❌ Exception during Integration trigger on batch {batch_num}: {e}")
            sys.exit(1)

    print("================================================================")
    print(f"🎉 ALL {total_batches} SYNC BATCH(ES) SUBMITTED SUCCESSFULLY TO APPLICATION INTEGRATION!")
    print("================================================================")
    print("👉 Scheduled Execution IDs:")
    for eid in execution_ids:
        print(f" - {eid}")
        print(f"   https://console.cloud.google.com/integrations/logs;integration_name={PARENT_INTEGRATION_NAME};execution_id={eid};region={LOCATION}?project={PROJECT_ID}")
    print("================================================================")

if __name__ == "__main__":
    run_sync()
