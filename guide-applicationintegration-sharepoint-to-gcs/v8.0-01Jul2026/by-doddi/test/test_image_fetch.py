import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
"""
Diagnostic script to test SharePoint page image fetching and Base64 embedding in PDF HTML rendering.
"""
import json
import os
import sys
import urllib.parse

# Add cf-sharepoint to path so we can import modules directly
sys.path.insert(0, os.path.join(ROOT_DIR, "cf-sharepoint"))

from graph_client import get_secret, get_graph_token, http
from sharepoint_traversal import render_page_to_html, fetch_image_as_data_uri

def test_image_fetching():
    print("================================================================================")
    print("🧪 DIAGNOSTIC TEST: SHAREPOINT IMAGE RESOLUTION & BASE64 EMBEDDING")
    print("================================================================================")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    tenant_id = params.get("CONFIG_M365_Tenant_Id")
    client_id = params.get("CONFIG_M365_Client_Id")
    secret_name = params.get("CONFIG_M365_Secret_Name")
    site_hostname = params.get("CONFIG_SharePoint_Hostname")
    site_name = params.get("CONFIG_Sharepoint_Sites", "").replace("sites/", "")

    if not all([tenant_id, client_id, secret_name, site_hostname]):
        print("❌ Error: Missing M365 parameters in parameters.json")
        sys.exit(1)

    print("🔐 Step 1: Authenticating with Microsoft Entra ID...")
    try:
        secret = get_secret(secret_name)
        token = get_graph_token(tenant_id, client_id, secret)
        print("✅ Graph API token acquired successfully!")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"🌐 Step 2: Resolving SharePoint Site ID for 'sites/{site_name}' on '{site_hostname}'...")
    resolve_url = f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:/sites/{site_name}"
    resp = http.get(resolve_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"❌ Failed to resolve SharePoint site: {resp.text}")
        sys.exit(1)

    site_id = resp.json().get("id")
    print(f"✅ Site ID resolved: {site_id}")

    print("📄 Step 3: Fetching Modern Site Pages from SharePoint...")
    pages_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages"
    p_resp = http.get(pages_url, headers=headers, timeout=30)
    if p_resp.status_code != 200:
        print(f"❌ Failed to list site pages: {p_resp.text}")
        sys.exit(1)

    pages = p_resp.json().get("value", [])
    print(f"✅ Found {len(pages)} modern site page(s).")

    if not pages:
        print("ℹ️ No site pages found to test image embedding.")
        return

    for idx, page_meta in enumerate(pages[:3]):
        page_id = page_meta.get("id")
        page_title = page_meta.get("name", f"Page-{idx}")
        web_url = page_meta.get("webUrl", "")
        print("--------------------------------------------------------------------------------")
        print(f"🔍 Testing Page {idx+1}: {page_title} ({web_url})")

        detail_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
        d_resp = http.get(detail_url, headers=headers, timeout=30)
        if d_resp.status_code != 200:
            print(f"⚠️ Could not expand page layout for {page_title}: {d_resp.text}")
            continue

        page_detail = d_resp.json()
        
        # Test rendering to HTML which invokes resolve_and_embed_images_in_html and fetch_image_as_data_uri
        print("   ⏳ Rendering HTML and resolving inline/card images...")
        html_output = render_page_to_html(page_detail, web_url, headers)

        data_uri_count = html_output.count("data:image/")
        print(f"   ✅ Rendered HTML length: {len(html_output)} chars")
        print(f"   🖼️ Base64 Embedded Images found in HTML: {data_uri_count}")
        
        if data_uri_count > 0:
            print("   🎉 SUCCESS! Images were downloaded and converted to Base64 inline data URIs!")
        else:
            print("   ℹ️ No images were found or embedded in this specific page layout.")

    print("================================================================================")
    print("✅ IMAGE FETCHING DIAGNOSTIC TEST COMPLETE!")
    print("================================================================================")

if __name__ == "__main__":
    test_image_fetching()
