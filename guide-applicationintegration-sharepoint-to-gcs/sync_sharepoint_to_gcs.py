import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import sys

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

def run_sync():
    # 1. Load configurations from parameters.json
    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)
        
    with open("parameters.json", "r") as f:
        params = json.load(f)
        
    PROJECT_ID = params.get("CONFIG_ProjectId")
    LOCATION = params.get("CONFIG_Location")
    PARENT_INTEGRATION_NAME = params.get("CONFIG_Parent_Integration_Name")
    
    # Cloud Function regional endpoints
    cf_endpoint = "https://your-sharepoint-list-files-xxxxxx-as.a.run.app"
    
    print("================================================================")
    print("🚀 STARTING E2E SHAREPOINT TO GCS SYNC PIPELINE (V4-HYBRID)")
    print("================================================================")
    
    # Step 1: Retrieve OIDC identity token and call Cloud Function to traverse SharePoint
    identity_token = get_identity_token()
    headers_cf = {
        "Authorization": f"Bearer {identity_token}",
        "Content-Type": "application/json"
    }
    payload_cf = {
        "site_name": "your-sharepoint-subsite-name",
        "library_name": params.get("CONFIG_Library", "Shared Documents")
    }
    
    cf_request_bytes = json.dumps(payload_cf).encode("utf-8")
    req_cf = urllib.request.Request(cf_endpoint, data=cf_request_bytes, headers=headers_cf, method="POST")
    
    try:
        print("🔒 Step 1: Invoking SharePoint traversal Cloud Function (Option B pages resolved)...")
        with urllib.request.urlopen(req_cf) as resp:
            sync_list = json.loads(resp.read().decode("utf-8"))
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
        
    # Step 2: Call Application Integration passing the sync list payload
    access_token = get_auth_token()
    integration_url = f"https://{LOCATION}-integrations.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/integrations/{PARENT_INTEGRATION_NAME}:execute"
    
    headers_int = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Format payload for Parent integration parameter input
    payload_int = {
        "triggerId": "api_trigger/v4-your-cloudfunction-sharepoint-gcs-v4-parent-trigger",
        "inputParameters": {
            "`Parent_Files_List`": {
                "jsonValue": json.dumps(sync_list)
            }
        }
    }
    
    int_request_bytes = json.dumps(payload_int).encode("utf-8")
    req_int = urllib.request.Request(integration_url, data=int_request_bytes, headers=headers_int, method="POST")
    
    try:
        print(f"\n🚀 Step 2: Triggering Application Integration: {PARENT_INTEGRATION_NAME}...")
        with urllib.request.urlopen(req_int) as resp_int:
            resp_data = json.loads(resp_int.read().decode("utf-8"))
            execution_id = resp_data.get("executionId")
            print("================================================================")
            print("🎉 SYNC JOB SUBMITTED SUCCESSFULLY TO APPLICATION INTEGRATION!")
            print("================================================================")
            print(f"👉 Execution ID: {execution_id}")
            print(f"📝 View execution logs in GCP Console here:")
            print(f"   https://console.cloud.google.com/integrations/logs;integration_name={PARENT_INTEGRATION_NAME};execution_id={execution_id};region={LOCATION}?project={PROJECT_ID}")
            print("================================================================")
    except urllib.error.HTTPError as e:
        print(f"❌ Application Integration execution failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception during Integration trigger: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_sync()
