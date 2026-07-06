import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
"""
Standalone helper script to manually test Vertex AI Search / Discovery Engine
Datastore incremental indexing from synced GCS metadata manifest (config/metadata.jsonl).
"""
import json
import urllib.request
import urllib.error
import subprocess
import sys
import os
import time

def get_access_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
    except Exception as e:
        print(f"❌ Failed to get gcloud access token: {e}")
        sys.exit(1)

def run_datastore_sync():
    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    project_id = params.get("CONFIG_ProjectId")
    location = params.get("CONFIG_Datastore_Location", "global")
    datastore_id = params.get("CONFIG_Datastore_Id")
    bucket_name = params.get("CONFIG_GCS_Bucket")

    if not all([project_id, datastore_id, bucket_name]):
        print("❌ Error: CONFIG_ProjectId, CONFIG_Datastore_Id, and CONFIG_GCS_Bucket must be configured in parameters.json!")
        sys.exit(1)

    print("================================================================")
    print("🚀 STARTING MANUAL VERTEX AI DATASTORE INCREMENTAL IMPORT")
    print("================================================================")
    print(f"📌 Project ID:        {project_id}")
    print(f"📌 Datastore ID:      {datastore_id}")
    print(f"📌 Datastore Region:  {location}")
    print(f"📂 Source Manifest:   gs://{bucket_name}/config/metadata.jsonl")
    print("================================================================")

    url = f"https://discoveryengine.googleapis.com/v1beta/projects/{project_id}/locations/{location}/collections/default_collection/dataStores/{datastore_id}/branches/0/documents:import"

    payload = {
        "gcsSource": {
            "inputUris": [
                f"gs://{bucket_name}/config/metadata.jsonl"
            ]
        },
        "reconciliationMode": "INCREMENTAL"
    }

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_id
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    print("\n⏳ Submitting importDocuments request to Vertex AI Discovery Engine...")
    start_time = time.time()
    try:
        with urllib.request.urlopen(req) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            elapsed = int(time.time() - start_time)
            print(f"✅ Import operation submitted successfully in {elapsed}s!")
            print("----------------------------------------------------------------")
            print("Operation Details:")
            print(json.dumps(res_json, indent=2))
            print("----------------------------------------------------------------")
            op_name = res_json.get("name")
            if op_name:
                print(f"🌐 You can monitor this operation in Google Cloud Console under Vertex AI Search > {datastore_id} > Activity.")
            print("🎉 MANUAL DATASTORE INDEXING TEST PASSED!")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        print("Error Details:")
        try:
            print(json.dumps(json.loads(err_body), indent=2))
        except Exception:
            print(err_body)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during Datastore import: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_datastore_sync()
