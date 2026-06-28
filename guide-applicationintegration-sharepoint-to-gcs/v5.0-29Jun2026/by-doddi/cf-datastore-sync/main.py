import json
import os
import requests
import google.auth
from google.auth.transport.requests import Request
import functions_framework

@functions_framework.http
def main(request):
    print("================================================================================")
    print("🧠 [CLOUD FUNCTION LOG] Waking up Vertex AI Search Datastore Ingestion Engine...")
    print("================================================================================")

    config_path = "parameters.json"
    if not os.path.exists(config_path):
        print(f"❌ Error: {config_path} not found inside Cloud Function container.")
        return ("Configuration parameters.json not found", 500)

    with open(config_path, "r") as f:
        params = json.load(f)

    project_id = params.get("CONFIG_ProjectId", "")
    location = params.get("CONFIG_Datastore_Location", "global")
    datastore_id = params.get("CONFIG_Datastore_Id", "")
    gcs_bucket = params.get("CONFIG_GCS_Bucket", "")

    if not project_id or not datastore_id or not gcs_bucket:
        print("❌ Error: Missing required Datastore parameters in parameters.json!")
        return ("Missing configuration parameters", 400)

    manifest_uri = f"gs://{gcs_bucket}/config/metadata.jsonl"
    print(f"📂 [LOG] Target Manifest : {manifest_uri}")
    print(f"🎯 [LOG] Datastore ID    : {datastore_id} ({location})")
    print(f"🏢 [LOG] Project ID      : {project_id}")

    try:
        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        access_token = credentials.token
    except Exception as ex:
        print(f"❌ [LOG] Error authenticating IAM token: {ex}")
        return (f"Auth error: {ex}", 500)

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
        "reconciliationMode": "INCREMENTAL"
    }

    print("🚀 [LOG] Submitting POST request to Discovery Engine import API...")
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)

    if resp.status_code == 200:
        data = resp.json()
        operation_name = data.get("name", "Unknown")
        print(f"🎉 [LOG SUCCESS] Ingestion triggered successfully! Operation: {operation_name}")
        return ({
            "status": "SUCCESS",
            "operation_id": operation_name,
            "manifest_uri": manifest_uri,
            "datastore_id": datastore_id
        }, 200, {"Content-Type": "application/json"})
    else:
        print(f"❌ [LOG ERROR] Discovery Engine API failed (HTTP {resp.status_code}): {resp.text}")
        return ({
            "status": "ERROR",
            "error_code": resp.status_code,
            "message": resp.text
        }, resp.status_code, {"Content-Type": "application/json"})
