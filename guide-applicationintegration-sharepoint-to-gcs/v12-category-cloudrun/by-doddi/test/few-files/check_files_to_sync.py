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

def main():
    print("================================================================")
    print("🔍 CHECKING FILES TO SYNC VIA SHAREPOINT TRAVERSAL CLOUD FUNCTION")
    print("================================================================")

    param_path = "config-parameters.json"
    if not os.path.exists(param_path):
        param_path = os.path.join(parent_dir, "config-parameters.json")
        
    if not os.path.exists(param_path):
        print(f"❌ Error: config-parameters.json not found in current directory or {parent_dir}!")
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

    all_resources = cf_resp.get("all_resources", [])
    all_resources = [item for item in all_resources if not (not item.get("IsPage") and item.get("Name", "").lower().endswith(".aspx"))]
    all_count = len(all_resources)

    sync_list = cf_resp.get("items", [])
    sync_list = [item for item in sync_list if not (not item.get("IsPage") and item.get("Name", "").lower().endswith(".aspx"))]

    all_docs = [x for x in all_resources if not x.get("IsPage")]
    all_pages = [x for x in all_resources if x.get("IsPage")]
    sync_docs = [x for x in sync_list if not x.get("IsPage")]
    sync_pages = [x for x in sync_list if x.get("IsPage")]

    output_file = "files-to-sync-result.txt"
    output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), output_file)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("================================================================\n")
        out.write("SHAREPOINT TO GCS - SYNCHRONIZATION INSPECTION REPORT\n")
        out.write("================================================================\n")
        out.write("📊 SUMMARY OF SHAREPOINT RESOURCES & SYNC STATUS:\n")
        out.write("----------------------------------------------------------------\n")
        out.write(f"Total Available Resources in SharePoint : {all_count}\n")
        out.write(f"  - Total Documents (Files)             : {len(all_docs)}\n")
        out.write(f"  - Total Site Pages                    : {len(all_pages)}\n\n")
        out.write(f"Total Items Requiring Synchronization   : {len(sync_list)}\n")
        out.write(f"  - Documents to Sync                   : {len(sync_docs)}\n")
        out.write(f"  - Site Pages to Sync                  : {len(sync_pages)}\n")
        out.write("================================================================\n\n")
        
        out.write(f"--- PART 1: ALL AVAILABLE RESOURCES IN SHAREPOINT ({all_count}) ---\n")
        if not all_resources:
            out.write("No resources found in SharePoint library.\n\n")
        else:
            for idx, item in enumerate(all_resources, 1):
                res_type = "Page" if item.get("IsPage") else "Document"
                name = item.get("Name", "")
                rel_path = item.get("RelativePath", "")
                url = item.get("Url", "")
                out.write(f"{idx}. [{res_type}] {name}\n")
                out.write(f"   Relative Path : {rel_path}\n")
                if url:
                    out.write(f"   Source URL    : {url}\n")
                out.write("\n")

        out.write("================================================================\n")
        out.write(f"--- PART 2: FILES THAT WILL BE SYNCHRONIZED ({len(sync_list)}) ---\n")
        if not sync_list:
            out.write("No files or pages require synchronization at this time.\n")
        else:
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

    print("\n================================================================")
    print("📊 SUMMARY OF SHAREPOINT RESOURCES & SYNC STATUS:")
    print("================================================================")
    print(f" 📂 Total Available Resources : {all_count}")
    print(f"    - Documents (Files)       : {len(all_docs)}")
    print(f"    - Site Pages              : {len(all_pages)}")
    print(f" 🔄 Total Items to Sync       : {len(sync_list)}")
    print(f"    - Documents to Sync       : {len(sync_docs)}")
    print(f"    - Site Pages to Sync      : {len(sync_pages)}")
    print("================================================================")
    print(f"💾 Detailed report written to: {output_path}")

if __name__ == "__main__":
    main()
