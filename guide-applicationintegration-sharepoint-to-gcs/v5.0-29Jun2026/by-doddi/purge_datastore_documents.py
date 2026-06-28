#!/usr/bin/env python3
"""
Manually purge all indexed documents from Vertex AI Search Datastore.
Reads parameters dynamically from parameters.json.
Uses standard Python library (zero pip dependency).
"""
import json
import os
import sys
import urllib.request
import urllib.error
import subprocess

def main():
    print("================================================================================")
    print("🗑️ VERTEX AI SEARCH / DATASTORE MANUAL PURGE TOOL")
    print("================================================================================")

    config_path = "parameters.json"
    if not os.path.exists(config_path):
        print(f"❌ Error: {config_path} not found!")
        sys.exit(1)

    with open(config_path, "r") as f:
        params = json.load(f)

    project_id = params.get("CONFIG_ProjectId", "")
    location = params.get("CONFIG_Datastore_Location", "global")
    datastore_id = params.get("CONFIG_Datastore_Id", "")

    if not project_id or not datastore_id:
        print("❌ Error: Missing required Datastore parameters in parameters.json!")
        sys.exit(1)

    print(f"🎯 Target Datastore ID : {datastore_id} ({location})")
    print(f"🏢 GCP Project ID      : {project_id}")
    print("--------------------------------------------------------------------------------")
    print("⚠️ WARNING: This will purge ALL indexed documents from this Datastore!")
    
    # Check if --force flag is passed or prompt
    if "--force" not in sys.argv:
        confirm = input("Are you sure you want to wipe the Datastore index? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Aborted purge operation.")
            sys.exit(0)

    print("🔐 Acquiring IAM access token via gcloud...")
    try:
        access_token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    except Exception as ex:
        print(f"❌ Error acquiring access token: {ex}")
        sys.exit(1)

    endpoint = (
        f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/"
        f"locations/{location}/collections/default_collection/dataStores/"
        f"{datastore_id}/branches/0/documents:purge"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_id
    }

    payload = {
        "filter": "*"
    }

    print("🚀 Submitting purge request to Discovery Engine API...")
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            operation_name = data.get("name", "Unknown")
            print("\n�� DATASTORE PURGE JOB SUBMITTED SUCCESSFULLY!")
            print("================================================================================")
            print(f"👉 Operation ID: {operation_name}")
            print("👉 Vertex AI Search is now actively wiping all records in the background.")
            print("================================================================================\n")
    except urllib.error.HTTPError as he:
        print(f"\n❌ Error submitting purge job (HTTP {he.code}):")
        print(he.read().decode("utf-8", errors="ignore"))
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
