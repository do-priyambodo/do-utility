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

def test_cf():
    if log_helper:
        log_helper.init_logging("setup")
    # Load configuration
    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)
        
    with open("parameters.json", "r") as f:
        params = json.load(f)
        
    PROJECT_ID = params.get("CONFIG_ProjectId")
    LOCATION = params.get("CONFIG_Location")
    FUNCTION_NAME = params.get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files")
    
    # Resolve Cloud Function URL from config or dynamically
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")
    if not cf_endpoint:
        print("🔍 Fetching Cloud Function URI dynamically...")
        cf_endpoint = get_cf_url(FUNCTION_NAME, LOCATION, PROJECT_ID)
        
    if not cf_endpoint:
        cf_endpoint = "https://yourorg-sharepoint-list-files-rzmyhdhywa-as.a.run.app"
        print(f"⚠️ Using fallback Cloud Function URI: {cf_endpoint}")
    else:
        print(f"✅ Resolved Cloud Function URI: {cf_endpoint}")

    print("🔒 Retrieving Google OIDC Identity Token...")
    identity_token = get_identity_token()
    
    headers = {
        "Authorization": f"Bearer {identity_token}",
        "Content-Type": "application/json"
    }
    
    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    if site_path.startswith("sites/"):
        site_name = site_path[len("sites/"):]
    else:
        site_name = site_path

    payload = {
        "site_name": site_name,
        "library_name": params.get("CONFIG_Sharepoint_Library", "Shared Documents"),
        "trigger_integration": False
    }
    
    print(f"📤 Sending test payload to Cloud Function:\n{json.dumps(payload, indent=2)}")
    request_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(cf_endpoint, data=request_bytes, headers=headers, method="POST")
    
    try:
        print("⚡ Invoking Cloud Function (Traversal only)...")
        with urllib.request.urlopen(req) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
            if log_helper:
                log_helper.log_cloud(json.dumps(response_data, indent=2))
            item_count = response_data.get("item_count", 0)
            items = response_data.get("items", [])
            print("================================================================")
            print("🎉 CLOUD FUNCTION TEST SUCCESSFUL!")
            print("================================================================")
            print(f"👉 Total Items Found: {item_count}")
            if item_count > 0:
                print("\nTraversed items:")
                for item in items:
                    name = item.get("Name")
                    path = item.get("RelativePath")
                    is_page = item.get("IsPage", False)
                    type_str = "Page" if is_page else "Document"
                    print(f" - [{type_str}] {name} (Path: {path})")
            print("================================================================")
    except urllib.error.HTTPError as e:
        print(f"❌ Cloud Function invocation failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_cf()
