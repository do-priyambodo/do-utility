#!/usr/bin/env python3
import json
import re
import os
import subprocess
import sys
import urllib.request
import urllib.error

# Add parent path to sys.path so we can import log_helper
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import log_helper
except ImportError:
    log_helper = None

# Define ANSI colors for premium styling
COLOR_HEADER = "\033[95m"
COLOR_INFO = "\033[94m"
COLOR_SUCCESS = "\033[92m"
COLOR_WARN = "\033[93m"
COLOR_FAIL = "\033[91m"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"

def print_header(title):
    print(f"\n{COLOR_BOLD}{COLOR_HEADER}=== {title} ==={COLOR_RESET}")

def print_result(status, name, message=None):
    if status == "PASSED":
        print(f"  {COLOR_SUCCESS}✅ [PASSED]{COLOR_RESET} {name}" + (f": {message}" if message else ""))
    elif status == "FAILED":
        print(f"  {COLOR_FAIL}❌ [FAILED]{COLOR_RESET} {name}" + (f": {COLOR_WARN}{message}{COLOR_RESET}" if message else ""))
    elif status == "WARN":
        print(f"  {COLOR_WARN}⚠️ [WARNING]{COLOR_RESET} {name}" + (f": {COLOR_INFO}{message}{COLOR_RESET}" if message else ""))

def get_auth_token():
    try:
        return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
    except Exception as e:
        print_result("FAILED", "GCP Access Token", f"Could not retrieve auth token: {e}")
        return None

def check_gcp_project(project_id):
    try:
        cmd = ["gcloud", "projects", "describe", project_id, "--format", "json"]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8").strip()

def check_service_account(sa_email, project_id):
    try:
        cmd = ["gcloud", "iam", "service-accounts", "describe", sa_email, "--project", project_id, "--format", "json"]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8").strip()

def check_gcs_bucket(bucket_name, project_id):
    try:
        # Check if bucket exists
        cmd = ["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}", "--project", project_id, "--format", "json"]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8").strip()

def check_secret_manager(secret_path, project_id):
    try:
        # Secret path format: projects/<project>/secrets/<name>/versions/<version>
        # or just projects/<project>/secrets/<name>
        match = re.match(r"^projects/([0-9a-zA-Z_-]+)/secrets/([a-zA-Z0-9_-]+)(/versions/([a-zA-Z0-9_]+))?$", secret_path)
        if not match:
            return False, "Invalid secret path format"
        
        proj = match.group(1)
        name = match.group(2)
        version = match.group(4)
        
        if version:
            cmd = ["gcloud", "secrets", "versions", "describe", version, f"--secret={name}", f"--project={proj}", "--format", "json"]
        else:
            cmd = ["gcloud", "secrets", "describe", name, f"--project={proj}", "--format", "json"]
            
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8").strip()

def check_connector_connection(connection_path, token):
    try:
        # Connection path format: projects/<project_id>/locations/<location>/connections/<connection_name>
        url = f"https://connectors.googleapis.com/v1/{connection_path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            state = data.get("status", {}).get("state", "UNKNOWN")
            if state != "ACTIVE":
                return False, f"Connection is in state: {state}"
            return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP Error (Code {e.code}): {e.reason}"
    except Exception as e:
        return False, str(e)

def validate():
    if log_helper:
        log_helper.init_logging("setup")

    print_header("Step 1: Checking parameter presence & formats in parameters.json")
    
    params_file = "parameters.json"
    if not os.path.exists(params_file) and os.path.exists("../parameters.json"):
        params_file = "../parameters.json"
        
    if not os.path.exists(params_file):
        print_result("FAILED", "parameters.json", "File not found!")
        sys.exit(1)
        
    with open(params_file, "r") as f:
        try:
            params = json.load(f)
        except Exception as e:
            print_result("FAILED", "parameters.json", f"Failed to parse JSON: {e}")
            sys.exit(1)

    # Define parameters configuration & regex rules
    uuid_pattern = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    rules = {
        "CONFIG_ProjectId": {
            "pattern": r"^[a-z0-9-]{6,30}$",
            "error": "Must be 6-30 chars, lowercase, numbers, and dashes"
        },
        "CONFIG_Location": {
            "pattern": r"^[a-z]{2,15}-[a-z]{2,15}[0-9]$",
            "error": "Must be valid GCP region format (e.g. asia-southeast1)"
        },
        "CONFIG_Service_Account": {
            "pattern": r"^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.gserviceaccount\.com$",
            "error": "Must be a valid service account email address"
        },
        "CONFIG_Child_Integration_Name": {
            "pattern": r"^[a-zA-Z0-9_-]{1,64}$",
            "error": "Must be a valid integration name"
        },
        "CONFIG_Parent_Integration_Name": {
            "pattern": r"^[a-zA-Z0-9_-]{1,64}$",
            "error": "Must be a valid integration name"
        },
        "CONFIG_SharePoint_Connection": {
            "pattern": r"^projects/[a-zA-Z0-9_-]+/locations/[a-zA-Z0-9_-]+/connections/[a-zA-Z0-9_-]+$",
            "error": "Must follow path: projects/<id>/locations/<loc>/connections/<name>"
        },
        "CONFIG_GCS_Connection": {
            "pattern": r"^projects/[a-zA-Z0-9_-]+/locations/[a-zA-Z0-9_-]+/connections/[a-zA-Z0-9_-]+$",
            "error": "Must follow path: projects/<id>/locations/<loc>/connections/<name>"
        },
        "CONFIG_Sharepoint_Sites": {
            "pattern": r"^sites/[a-zA-Z0-9_\-\.%/]+$",
            "error": "Must start with sites/ followed by site path"
        },
        "CONFIG_Sharepoint_Library": {
            "pattern": r"^[a-zA-Z0-9_\-\. %]+$",
            "error": "Must be a valid document library name"
        },
        "CONFIG_GCS_Bucket": {
            "pattern": r"^[a-z0-9][a-z0-9-._]{1,61}[a-z0-9]$",
            "error": "Must be a valid GCS bucket name (3-63 characters, lowercase, numbers, dashes, dots)"
        },
        "CONFIG_CloudFunction_Name": {
            "pattern": r"^[a-z0-9-]{1,63}$",
            "error": "Must be a valid Cloud Function name"
        },
        "CONFIG_M365_Tenant_Id": {
            "pattern": uuid_pattern,
            "error": "Must be a valid tenant UUID"
        },
        "CONFIG_M365_Client_Id": {
            "pattern": uuid_pattern,
            "error": "Must be a valid client ID UUID"
        },
        "CONFIG_M365_Secret_Name": {
            "pattern": r"^projects/[0-9]+/secrets/[a-zA-Z0-9_-]+(/versions/[a-zA-Z0-9_]+)?$",
            "error": "Must follow Secret Manager path format"
        },
        "CONFIG_SharePoint_Hostname": {
            "pattern": r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
            "error": "Must be a valid domain/hostname format"
        },
        "CONFIG_Developer_Group_Or_User": {
            "pattern": r"^(user:|group:|ggrp)[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+$",
            "error": "Must be prefixed with user: or group: followed by email address"
        },
        "CONFIG_PDF_Conversion_Engine": {
            "pattern": r"^(weasyprint|playwright)$",
            "error": "Must be either 'weasyprint' or 'playwright'"
        }
    }

    all_passed = True
    resolved_params = {}
    
    # Pre-processing resolve logic for connection strings
    project_id = params.get("CONFIG_ProjectId", "")
    location = params.get("CONFIG_Location", "")
    
    for key, value in params.items():
        if isinstance(value, str):
            value_resolved = value.replace("$CONFIG_ProjectId", project_id).replace("$CONFIG_Location", location)
            resolved_params[key] = value_resolved
        else:
            resolved_params[key] = value

    # Check formatting rules
    for key, rule in rules.items():
        if key not in params:
            print_result("FAILED", key, "Missing parameter")
            all_passed = False
            continue
            
        value = params[key]
        if not value or str(value).startswith("your-") or str(value).startswith("yourorg"):
            print_result("FAILED", key, f"Placeholder detected: '{value}'")
            all_passed = False
            continue
            
        pattern = rule["pattern"]
        error_msg = rule["error"]
        
        # Test format against raw value or resolved value
        test_val = resolved_params[key]
        if not re.match(pattern, test_val):
            print_result("FAILED", key, f"Value '{test_val}' is invalid. {error_msg}")
            all_passed = False
        else:
            print_result("PASSED", f"Format: {key}")

    if not all_passed:
        print(f"\n{COLOR_FAIL}❌ Format validation failed. Please fix formats in parameters.json before proceeding.{COLOR_RESET}")
        sys.exit(1)
        
    print_header("Step 2: Checking GCP Resource Existence (Live Checks)")
    token = get_auth_token()
    if not token:
        print(f"{COLOR_WARN}⚠️ Skipping live checks due to missing GCP auth token.{COLOR_RESET}")
        sys.exit(0)
        
    live_passed = True
    
    # Project Check
    ok, err = check_gcp_project(project_id)
    if not ok:
        print_result("FAILED", f"GCP Project: '{project_id}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"GCP Project: '{project_id}'")
        
    # Service Account Check
    sa_email = resolved_params.get("CONFIG_Service_Account", "")
    ok, err = check_service_account(sa_email, project_id)
    if not ok:
        print_result("FAILED", f"Service Account: '{sa_email}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"Service Account: '{sa_email}'")
        
    # GCS Bucket Check
    bucket_name = resolved_params.get("CONFIG_GCS_Bucket", "")
    ok, err = check_gcs_bucket(bucket_name, project_id)
    if not ok:
        print_result("FAILED", f"GCS Bucket: '{bucket_name}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"GCS Bucket: '{bucket_name}'")
        
    # Secret Manager Secret Check
    secret_path = resolved_params.get("CONFIG_M365_Secret_Name", "")
    ok, err = check_secret_manager(secret_path, project_id)
    if not ok:
        print_result("FAILED", f"Secret Path: '{secret_path}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"Secret Path: '{secret_path}'")
        
    # SharePoint Connection Check
    sp_conn = resolved_params.get("CONFIG_SharePoint_Connection", "")
    ok, err = check_connector_connection(sp_conn, token)
    if not ok:
        print_result("FAILED", f"SharePoint Connector Connection: '{sp_conn}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"SharePoint Connector Connection: '{sp_conn}'")
        
    # GCS Connection Check
    gcs_conn = resolved_params.get("CONFIG_GCS_Connection", "")
    ok, err = check_connector_connection(gcs_conn, token)
    if not ok:
        print_result("FAILED", f"GCS Connector Connection: '{gcs_conn}'", err)
        live_passed = False
    else:
        print_result("PASSED", f"GCS Connector Connection: '{gcs_conn}'")

    if live_passed:
        print(f"\n{COLOR_SUCCESS}🎉 ALL PARAMETERS AND GCP RESOURCES COMPLETED VALIDATION SUCCESSFULLY!{COLOR_RESET}")
    else:
        print(f"\n{COLOR_FAIL}❌ Resource existence checks failed. Please verify configurations/permissions in Google Cloud.{COLOR_RESET}")
        sys.exit(1)

if __name__ == "__main__":
    validate()
