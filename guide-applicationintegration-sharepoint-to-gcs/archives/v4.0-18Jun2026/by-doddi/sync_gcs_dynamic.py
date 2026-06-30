#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import sys

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

    payload_cf = {
        "site_name": site_name,
        "library_name": params.get("CONFIG_Sharepoint_Library", "Documents"),
        "check_gcs_config": True
    }
    
    req_cf = urllib.request.Request(cf_endpoint, data=json.dumps(payload_cf).encode("utf-8"), headers=headers_cf, method="POST")
    
    try:
        print("🔒 Step 1: Invoking Cloud Function instructing dynamic read of gs://.../config/target_urls.txt ...")
        with urllib.request.urlopen(req_cf, timeout=3600) as resp:
            cf_resp = json.loads(resp.read().decode("utf-8"))
            if log_helper:
                log_helper.log_cloud("=== Dynamic GCS Cloud Function Response ===")
                log_helper.log_cloud(json.dumps(cf_resp, indent=2))
            sync_list = cf_resp.get("items", [])
            print(f"🟢 Resolved {len(sync_list)} item(s) from dynamic GCS configuration for synchronization.")
    except urllib.error.HTTPError as e:
        print(f"❌ Cloud Function invocation failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception during Cloud Function invocation: {e}")
        sys.exit(1)
        
    if not sync_list:
        print("ℹ️ No items resolved to synchronize from GCS config. Exiting cleanly.")
        return
        
    access_token = get_auth_token()
    integration_url = f"https://{LOCATION}-integrations.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/integrations/{PARENT_INTEGRATION_NAME}:schedule"
    
    headers_int = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    batch_size = params.get("CONFIG_Batch_Size", 100)
    total_batches = (len(sync_list) + batch_size - 1) // batch_size
    print(f"\n🚀 Step 2: Triggering Application Integration ({PARENT_INTEGRATION_NAME}) across {total_batches} batch(es)...")

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
                    log_helper.log_cloud(f"=== Dynamic GCS Batch {batch_num} Response ===")
                    log_helper.log_cloud(json.dumps(resp_data, indent=2))
                execution_id = resp_data.get("executionId") or resp_data.get("scheduleId") or (resp_data.get("executionIds", ["Check Console"])[0])
                execution_ids.append(execution_id)
                print(f" 🟢 Batch {batch_num}/{total_batches} ({len(batch)} items) triggered -> Execution ID: {execution_id}")
        except urllib.error.HTTPError as e:
            print(f"❌ Integration batch {batch_num} trigger failed (Code {e.code}): {e.reason}")
            print(e.read().decode("utf-8"))
            sys.exit(1)
        except Exception as e:
            print(f"❌ Exception triggering batch {batch_num}: {e}")
            sys.exit(1)

    print("================================================================")
    print("🎉 ALL DYNAMIC GCS SYNC BATCHES SCHEDULED SUCCESSFULLY!")
    print("================================================================")
    for eid in execution_ids:
        print(f" - {eid}")
        print(f"   https://console.cloud.google.com/integrations/logs;integration_name={PARENT_INTEGRATION_NAME};execution_id={eid};region={LOCATION}?project={PROJECT_ID}")
    print("================================================================")

if __name__ == "__main__":
    run_dynamic_gcs_sync()
