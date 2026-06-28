import urllib.request
import urllib.error
import json
import subprocess
import sys
import os

try:
    import log_helper
except ImportError:
    log_helper = None

def get_auth_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
    except Exception as e:
        print(f"❌ Failed to get access token: {e}")
        sys.exit(1)

def check_status(project_id, location, integration_name, execution_id):
    if log_helper:
        log_helper.init_logging("setup")
        
    token = get_auth_token()
    url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}/executions/{execution_id}"
    
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    
    try:
        print(f"🔍 Fetching execution status for ID {execution_id} from Google Cloud...")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if log_helper:
                log_helper.log_cloud(f"=== Execution Detail Status check for ID: {execution_id} ===")
                log_helper.log_cloud(json.dumps(data, indent=2))
            
            # Print state to console/setup.log
            state = data.get("eventExecutionDetails", {}).get("eventExecutionState", "UNKNOWN")
            print(f"================================================================")
            print(f"ℹ️ Execution ID: {execution_id}")
            print(f"ℹ️ State: {state}")
            print(f"================================================================")
            # Print full json to stdout (so pipeline wrappers can parse it if needed)
            print(json.dumps(data, indent=2))
            
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error querying status (Code {e.code}): {e.reason}")
        print(e.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python3 check_execution.py <project_id> <location> <integration_name> <execution_id>")
        sys.exit(1)
    check_status(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
