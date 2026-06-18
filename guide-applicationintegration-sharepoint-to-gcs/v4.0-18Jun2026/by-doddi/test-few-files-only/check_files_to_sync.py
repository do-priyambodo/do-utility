#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import sys

# Locate parent directory for config reference
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

def main():
    print("================================================================")
    print("🔍 CHECKING FILES TO SYNC VIA SHAREPOINT TRAVERSAL CLOUD FUNCTION")
    print("================================================================")

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
    FUNCTION_NAME = params.get("CONFIG_CloudFunction_Name")
    
    cf_endpoint = params.get("CONFIG_CloudFunction_URL")
    if not cf_endpoint and FUNCTION_NAME:
        print("🔍 Resolving Cloud Function URI dynamically...")
        cf_endpoint = get_cf_url(FUNCTION_NAME, LOCATION, PROJECT_ID)
        
    if not cf_endpoint:
        print("❌ Could not resolve Cloud Function URI. Please ensure Cloud Function is deployed.")
        sys.exit(1)
    else:
        print(f"✅ Resolved Cloud Function URI: {cf_endpoint}")

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
        "force_full_sync": False
    }

    req_cf = urllib.request.Request(cf_endpoint, data=json.dumps(payload_cf).encode("utf-8"), headers=headers_cf, method="POST")

    print("🔒 Invoking Cloud Function to inspect SharePoint and GCS incremental sync state...")
    try:
        with urllib.request.urlopen(req_cf, timeout=3600) as resp:
            cf_resp = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ Cloud Function invocation failed (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to invoke Cloud Function: {e}")
        sys.exit(1)

    all_count = cf_resp.get("all_resources_count", len(cf_resp.get("all_resources", [])))
    sync_list = cf_resp.get("items", [])
    sync_list = [item for item in sync_list if not (not item.get("IsPage") and item.get("Name", "").lower().endswith(".aspx"))]

    output_file = "files-to-sync-result.txt"
    output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), output_file)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("================================================================\n")
        out.write("SHAREPOINT TO GCS - FILES TO SYNCHRONIZE REPORT\n")
        out.write("================================================================\n")
        out.write(f"Total Resources Found in SharePoint : {all_count}\n")
        out.write(f"Total Items Requiring Sync          : {len(sync_list)}\n")
        out.write("================================================================\n\n")
        
        if not sync_list:
            out.write("No files or pages require synchronization at this time.\n")
        else:
            out.write("--- Detailed List of Files to Sync ---\n")
            for idx, item in enumerate(sync_list, 1):
                res_type = "Page" if item.get("IsPage") else "Document"
                name = item.get("Name", "")
                rel_path = item.get("RelativePath", "")
                url = item.get("Url", "")
                out.write(f"{idx}. [{res_type}] {name}\n")
                out.write(f"   Relative Path : {rel_path}\n")
                if url:
                    out.write(f"   Source URL    : {url}\n")
                out.write("\n")

    print(f"\n🟢 Traversal & Incremental Comparison Complete!")
    print(f" 📊 Total Resources in SharePoint : {all_count}")
    print(f" 📦 Total Items Requiring Sync   : {len(sync_list)}")
    print(f"💾 Result successfully written to: {output_path}")

if __name__ == "__main__":
    main()
