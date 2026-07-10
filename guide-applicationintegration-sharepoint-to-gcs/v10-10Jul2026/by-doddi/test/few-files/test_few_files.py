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
import argparse
import random

# Add parent directory to path to import log_helper if needed
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

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

def run_limited_test():
    parser = argparse.ArgumentParser(description="Run randomized sample verification test for SharePoint-to-GCS pipeline.")
    parser.add_argument("--docs", type=int, default=2, help="Number of random documents to sample (default: 2)")
    parser.add_argument("--pages", type=int, default=2, help="Number of random pages to sample (default: 2)")
    parser.add_argument("--force-full-sync", action=argparse.BooleanOptionalAction, default=True, help="Force full sync bypassing GCS incremental check (default: True)")
    args = parser.parse_args()

    if log_helper:
        log_helper.init_logging("setup")

    # Locate parameters.json in local or parent directory
    param_path = "parameters.json"
    if not os.path.exists(param_path):
        param_path = os.path.join(parent_dir, "parameters.json")
        
    if not os.path.exists(param_path):
        print(f"❌ Error: parameters.json not found in current directory or {parent_dir}!")
        sys.exit(1)
        
    with open(param_path, "r") as f:
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
        print("❌ Could not resolve Cloud Function URI. Please specify CONFIG_CloudFunction_URL in parameters.json or deploy Cloud Function.")
        sys.exit(1)
    else:
        print(f"✅ Resolved Cloud Function URI: {cf_endpoint}")
        
    print("================================================================")
    print(f"🧪 STARTING RANDOMIZED SAMPLE SYNC TEST (DOCS: {args.docs}, PAGES: {args.pages})")
    print("================================================================")
    
    # Step 1: Traverse SharePoint via Cloud Function
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
        "force_full_sync": args.force_full_sync
    }
    
    req_cf = urllib.request.Request(cf_endpoint, data=json.dumps(payload_cf).encode("utf-8"), headers=headers_cf, method="POST")
    
    try:
        print("🔒 Step 1: Invoking SharePoint traversal Cloud Function...")
        with urllib.request.urlopen(req_cf) as resp:
            cf_resp = json.loads(resp.read().decode("utf-8"))
            sync_list = cf_resp.get("items", [])
            sync_list = [item for item in sync_list if not (not item.get("IsPage") and item.get("Name", "").lower().endswith(".aspx"))]
            print(f"🟢 Found {len(sync_list)} total items in SharePoint library.")
    except urllib.error.HTTPError as e:
        print(f"❌ SharePoint traversal failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception during SharePoint traversal: {e}")
        sys.exit(1)
        
    if not sync_list:
        print("ℹ️ No files or pages found to synchronize. Test exiting cleanly.")
        return

    # RANDOMIZE PAYLOAD SELECTION
    docs = [item for item in sync_list if not item.get("IsPage")]
    pages = [item for item in sync_list if item.get("IsPage")]
    
    selected_docs = random.sample(docs, min(args.docs, len(docs)))
    selected_pages = random.sample(pages, min(args.pages, len(pages)))
    
    sliced_list = selected_docs + selected_pages
    random.shuffle(sliced_list)
    
    print(f"🎲 Randomized selection: Sampled {len(selected_docs)} documents (out of {len(docs)}) and {len(selected_pages)} pages (out of {len(pages)}).")
    print("📦 Files selected for test synchronization:")
    for item in sliced_list:
        item_type = "Page" if item.get("IsPage") else "Document"
        print(f"   - [{item_type}] {item.get('Name')} (Path: {item.get('RelativePath')})")

    # Step 2: Call Application Integration
    access_token = get_auth_token()
    integration_url = f"https://{LOCATION}-integrations.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/integrations/{PARENT_INTEGRATION_NAME}:execute"
    
    headers_int = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload_int = {
        "triggerId": f"api_trigger/{PARENT_INTEGRATION_NAME}-trigger",
        "inputParameters": {
            "`Parent_Files_List`": {
                "jsonValue": json.dumps(sliced_list)
            }
        }
    }
    
    req_int = urllib.request.Request(integration_url, data=json.dumps(payload_int).encode("utf-8"), headers=headers_int, method="POST")
    
    try:
        print(f"\n🚀 Step 2: Triggering Application Integration ({PARENT_INTEGRATION_NAME}) with {len(sliced_list)} items...")
        with urllib.request.urlopen(req_int) as resp_int:
            resp_data = json.loads(resp_int.read().decode("utf-8"))
            execution_id = resp_data.get("executionId")
            print("================================================================")
            print("🎉 LIMITED SAMPLE SYNC TEST SUBMITTED SUCCESSFULLY!")
            print("================================================================")
            print(f"👉 Execution ID: {execution_id}")
            print(f"📝 Monitor execution progress with:")
            print(f"   python3 ../check_application_integration_execution.py \"{PROJECT_ID}\" \"{LOCATION}\" \"{PARENT_INTEGRATION_NAME}\" \"{execution_id}\"")
            print("================================================================")
    except urllib.error.HTTPError as e:
        print(f"❌ Application Integration execution failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception during Integration trigger: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_limited_test()
