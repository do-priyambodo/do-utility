import os
import json
import urllib.request
import urllib.error
import functions_framework
import google.auth
import google.auth.transport.requests

@functions_framework.http
def main(request):
    """
    HTTP Cloud Function entrypoint to trigger Vertex AI Datastore document indexing.
    Designed to be invoked by Cloud Scheduler with OIDC authentication (roles/run.invoker).
    """
    req_data = request.get_json(silent=True) or {}
    
    # Load default configuration from config-parameters.json if available
    params = {}
    if os.path.exists("config-parameters.json"):
        try:
            with open("config-parameters.json", "r") as f:
                params = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config-parameters.json: {e}")
            
    project_id = req_data.get("project_id") or params.get("CONFIG_ProjectId")
    datastore_id = req_data.get("datastore_id") or params.get("CONFIG_Datastore_Id")
    location = req_data.get("location") or params.get("CONFIG_Datastore_Location", "global")
    bucket_name = req_data.get("bucket_name") or params.get("CONFIG_GCS_Bucket")
    reconciliation_mode = req_data.get("reconciliation_mode", "INCREMENTAL")
    
    if not project_id or not datastore_id or not bucket_name:
        error_msg = "❌ Missing required configuration: project_id, datastore_id, or bucket_name."
        print(error_msg)
        return (json.dumps({"status": "ERROR", "message": error_msg}), 400, {"Content-Type": "application/json"})
        
    manifest_uri = f"gs://{bucket_name}/config/metadata.jsonl"
    import_url = f"https://discoveryengine.googleapis.com/v1beta/projects/{project_id}/locations/{location}/collections/default_collection/dataStores/{datastore_id}/branches/0/documents:import"
    
    print("================================================================")
    print("🚀 STARTING VERTEX AI DATASTORE DOCUMENT IMPORT (CF-DATASTORE)")
    print("================================================================")
    print(f"📌 Project ID:         {project_id}")
    print(f"📌 Datastore ID:       {datastore_id} ({location})")
    print(f"📌 Manifest Path:      {manifest_uri}")
    print(f"📌 ReconciliationMode: {reconciliation_mode}")
    print("----------------------------------------------------------------")
    
    try:
        # Obtain Google Cloud OAuth 2.0 access token
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token
        
        payload = {
            "gcsSource": {
                "inputUris": [manifest_uri],
                "dataSchema": "document"
            },
            "reconciliationMode": reconciliation_mode
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        print(f"📤 Sending import request to Vertex AI Discovery Engine API...")
        api_req = urllib.request.Request(import_url, data=payload_bytes, headers=headers, method="POST")
        
        with urllib.request.urlopen(api_req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            
        print("✅ Vertex AI Datastore import operation initiated successfully!")
        print(f"👉 Operation Name: {resp_data.get('name', 'N/A')}")
        print("================================================================")
        
        return (json.dumps({
            "status": "SUCCESS",
            "message": "Vertex AI Datastore import initiated successfully.",
            "operation": resp_data.get("name"),
            "manifest_uri": manifest_uri
        }), 200, {"Content-Type": "application/json"})
        
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Discovery Engine API HTTP Error {e.code}: {error_body}")
        return (json.dumps({
            "status": "ERROR",
            "code": e.code,
            "error": error_body
        }), e.code, {"Content-Type": "application/json"})
    except Exception as e:
        print(f"❌ Unexpected error during datastore import: {e}")
        return (json.dumps({
            "status": "ERROR",
            "message": str(e)
        }), 500, {"Content-Type": "application/json"})
