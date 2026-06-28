#!/usr/bin/env python3
"""
Trigger Vertex AI Search (Discovery Engine) Datastore ingestion from Google Cloud Storage.
Reads parameters dynamically from parameters.json and imports config/metadata.jsonl.
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
    print("🧠 VERTEX AI SEARCH / DATASTORE GCS INGESTION TRIGGER")
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
    gcs_bucket = params.get("CONFIG_GCS_Bucket", "")

    if not project_id or not datastore_id or not gcs_bucket:
        print("❌ Error: Missing required Datastore parameters in parameters.json!")
        print(f"   • CONFIG_ProjectId       : {project_id}")
        print(f"   • CONFIG_Datastore_Id    : {datastore_id}")
        print(f"   • CONFIG_GCS_Bucket      : {gcs_bucket}")
        sys.exit(1)

    manifest_uri = f"gs://{gcs_bucket}/config/metadata.jsonl"
    print(f"📂 Target GCS Manifest    : {manifest_uri}")
    print(f"🎯 Target Datastore ID    : {datastore_id} ({location})")
    print(f"🏢 GCP Project ID         : {project_id}")
    print("--------------------------------------------------------------------------------")

    print("🔐 Acquiring Google Cloud IAM access token via gcloud...")
    try:
        access_token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        if not access_token:
            raise ValueError("Empty access token returned by gcloud.")
    except Exception as ex:
        print(f"❌ Error acquiring access token: {ex}")
        sys.exit(1)

    endpoint = (
        f"https://discoveryengine.googleapis.com/v1/projects/{project_id}/"
        f"locations/{location}/collections/default_collection/dataStores/"
        f"{datastore_id}/branches/0/documents:import"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_id
    }

    payload = {
        "gcsSource": {
            "inputUris": [manifest_uri],
            "dataSchema": "custom"
        },
        "reconciliationMode": "FULL"
    }

    print("🚀 Submitting import job to Google Cloud Discovery Engine API...")
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            operation_name = data.get("name", "Unknown")
            print("\n🎉 DATASTORE INGESTION JOB SUBMITTED SUCCESSFULLY!")
            print("================================================================================")
            print(f"👉 Operation ID: {operation_name}")
            print("👉 Vertex AI Search is now actively indexing your metadata.jsonl in the background.")
            print("👉 You can view progress under 'Activity' or 'Documents' in the Google Cloud Console.")
            print("================================================================================\n")
    except urllib.error.HTTPError as he:
        print(f"\n❌ Error submitting import job (HTTP {he.code}):")
        print(he.read().decode("utf-8", errors="ignore"))
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
