#!/usr/bin/env python3
"""
discover_categories.py - V11 Fast SharePoint Subsite Discovery Utility
Discovers all child subsite categories under the root portal site in <3 seconds without crawling libraries or counting items.
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, Any, List

# Ensure project root is in python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "util"))

try:
    from util.config_loader import load_sites_sync_config
except ImportError:
    def load_sites_sync_config(params=None):
        if os.path.exists("config/sites-sync.json"):
            with open("config/sites-sync.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return {"root_portal_site": "sites/DEN", "categories": []}

def get_secret_gcloud(secret_name: str) -> str:
    try:
        secret_part = secret_name.split("/")[-1]
        secret_id = secret_name.split("/")[-3] if "secrets/" in secret_name else secret_name
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", secret_part, f"--secret={secret_id}"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"], text=True, stderr=subprocess.DEVNULL).strip()

def get_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }).encode("utf-8")
    req = urllib.request.Request(token_url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("access_token")

def main():
    parser = argparse.ArgumentParser(description="V11 Fast SharePoint Subsite Category Discovery")
    parser.add_argument("--root", help="Override root portal site path (e.g. 'sites/DEN')", default=None)
    args = parser.parse_args()

    start_t = time.time()
    print("================================================================================")
    print("🚀 V11 SHAREPOINT FAST CATEGORY DISCOVERY (ROOT ONLY — NO ITEM COUNTING)")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in current directory.")
        sys.exit(1)

    with open("parameters.json", "r", encoding="utf-8") as f:
        params = json.load(f)

    sites_sync = load_sites_sync_config(params)
    root_site_path = args.root or sites_sync.get("root_portal_site") or "sites/DEN"
    root_site_path_clean = root_site_path[len("sites/"):] if root_site_path.startswith("sites/") else root_site_path

    tenant_id = params.get("CONFIG_M365_Tenant_Id")
    client_id = params.get("CONFIG_M365_Client_Id")
    secret_name = params.get("CONFIG_M365_Secret_Name")
    hostname = params.get("CONFIG_SharePoint_Hostname")

    if not all([tenant_id, client_id, secret_name, hostname]):
        print("❌ Error: Missing M365 authentication credentials inside parameters.json.")
        sys.exit(1)

    print(f" • Hostname        : {hostname}")
    print(f" • Root Site Scope : sites/{root_site_path_clean}")
    print("🔐 Authenticating with Microsoft Entra ID...")
    
    secret_val = get_secret_gcloud(secret_name)
    token = get_graph_token(tenant_id, client_id, secret_val)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resolve_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{root_site_path_clean}"
    print(f"🌐 Resolving Root Site ID via Microsoft Graph API...")
    
    req = urllib.request.Request(resolve_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            root_info = json.loads(resp.read().decode("utf-8"))
            root_id = root_info.get("id")
            root_web_url = root_info.get("webUrl", f"https://{hostname}/sites/{root_site_path_clean}")
    except Exception as e:
        print(f"❌ Failed to resolve root site 'sites/{root_site_path_clean}': {e}")
        sys.exit(1)

    print(f"✅ Root Site Resolved! ID: {root_id.split(',')[1] if ',' in root_id else root_id}")
    print("⚡ Discovering direct child subsites (categories)...")

    subsites_url = f"https://graph.microsoft.com/v1.0/sites/{root_id}/subsites?$top=100"
    categories_found = []
    
    while subsites_url:
        sub_req = urllib.request.Request(subsites_url, headers=headers)
        with urllib.request.urlopen(sub_req, timeout=20) as resp:
            sub_data = json.loads(resp.read().decode("utf-8"))
            for site in sub_data.get("value", []):
                name = site.get("name") or site.get("displayName")
                web_url = site.get("webUrl")
                if name and web_url:
                    categories_found.append({"name": name, "web_url": web_url, "id": site.get("id")})
            subsites_url = sub_data.get("@odata.nextLink")

    elapsed = round(time.time() - start_t, 2)
    print("\n--------------------------------------------------------------------------------")
    print(f"Found {len(categories_found)} Subsite Categories under 'sites/{root_site_path_clean}' (Execution Time: {elapsed}s):")
    print("--------------------------------------------------------------------------------")
    print(f"{'No.':<5}{'Category / Subsite Name':<35}{'Web URL':<40}")
    print("-" * 80)

    for idx, c in enumerate(sorted(categories_found, key=lambda x: x["name"]), 1):
        print(f"{idx:<5}{c['name'][:33]:<35}{c['web_url']:<40}")

    print("================================================================================")
    print("💡 TIP: Copy any Category Name above directly into your 'sites-sync.json' to onboard it!")
    print("================================================================================")

if __name__ == "__main__":
    main()
