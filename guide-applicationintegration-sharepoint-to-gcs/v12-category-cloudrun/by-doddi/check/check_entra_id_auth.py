import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
"""
Pre-Flight Diagnostic: Verify Azure AD / Entra ID Authentication & Microsoft Graph API Token Generation.
Reads parameters dynamically from config-parameters.json and retrieves secret via gcloud CLI.
Zero pip dependencies required.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
import subprocess

def main():
    print("================================================================================")
    print("🔐 PRE-FLIGHT DIAGNOSTIC: AZURE AD / ENTRA ID AUTHENTICATION CHECK")
    print("================================================================================")

    config_path = "config-parameters.json"
    if not os.path.exists(config_path):
        print(f"❌ Error: {config_path} not found!")
        sys.exit(1)

    with open(config_path, "r") as f:
        params = json.load(f)

    tenant_id = params.get("CONFIG_M365_Tenant_Id", "")
    client_id = params.get("CONFIG_M365_Client_Id", "")
    secret_path = params.get("CONFIG_M365_Secret_Name", "")

    if not tenant_id or not client_id or not secret_path:
        print("❌ Error: Missing M365 parameters (Tenant ID, Client ID, or Secret Name) in config-parameters.json!")
        sys.exit(1)

    print(f"🏢 M365 Tenant ID : {tenant_id}")
    print(f"🆔 M365 Client ID : {client_id}")
    print(f"�� Secret Path    : {secret_path}")
    print("--------------------------------------------------------------------------------")

    print("🔍 Step 1: Retrieving Azure AD Client Secret from GCP Secret Manager...")
    try:
        # Extract secret name or version path
        client_secret = subprocess.check_output(
            ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_path.split('/')[-3]}" if "secrets/" in secret_path else f"--secret={secret_path}"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        print("✅ Secret retrieved successfully from GCP Secret Manager!")
    except Exception as ex:
        # Try direct version access if formatted as full path
        try:
            client_secret = subprocess.check_output(
                ["gcloud", "secrets", "versions", "access", secret_path.split("/")[-1], f"--secret={secret_path.split('/')[-3]}"],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            print("✅ Secret retrieved successfully from GCP Secret Manager (by version path)!")
        except Exception as ex2:
            print(f"❌ Failed to retrieve secret via gcloud CLI. Please check Secret Manager permissions.\nError: {ex2}")
            sys.exit(1)

    print("🌐 Step 2: Requesting OAuth 2.0 Access Token from Microsoft Entra ID...")
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(token_url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            access_token = resp_data.get("access_token")
            expires_in = resp_data.get("expires_in", "Unknown")
            if access_token:
                preview = access_token[:15] + "..." + access_token[-10:]
                print("================================================================================")
                print("🎉 AZURE AD AUTHENTICATION PASSED SUCCESSFULLY!")
                print("================================================================================")
                print(f"👉 Token Preview  : {preview}")
                print(f"👉 Token Lifespan : {expires_in} seconds")
                print("👉 Microsoft Graph API credentials are valid and ready for SharePoint traversal!")
                print("================================================================================")
            else:
                print("❌ Token request succeeded but no access_token found in response:")
                print(resp_data)
                sys.exit(1)
    except urllib.error.HTTPError as he:
        print(f"❌ Entra ID Authentication Failed (HTTP {he.code}):")
        err_body = he.read().decode("utf-8", errors="ignore")
        print(err_body)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error communicating with Entra ID: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
