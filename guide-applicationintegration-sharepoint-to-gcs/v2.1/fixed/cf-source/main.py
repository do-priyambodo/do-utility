import os
import json
import requests
import urllib.parse
import functions_framework
from msal import ConfidentialClientApplication
from google.cloud import secretmanager

# Helper to retrieve secret from Secret Manager
def get_secret(secret_name):
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("utf-8").strip()

# Get OAuth token for Graph API
def get_graph_token(tenant_id, client_id, client_secret):
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = ConfidentialClientApplication(
        client_id,
        client_credential=client_secret,
        authority=authority
    )
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" in result:
        return result["access_token"]
    else:
        error_desc = result.get("error_description", "Unknown error")
        raise Exception(f"Failed to get access token: {error_desc}")

# Recursively list files in a SharePoint folder (drive item)
def list_drive_items_recursive(token, drive_id, item_id="root", parent_path="", results=None, base_file_url=""):
    if results is None:
        results = []
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children"
    if item_id == "root":
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Graph API returned status {response.status_code} for url {url}: {response.text}")
        
    items_data = response.json()
    items = items_data.get("value", [])
    
    for item in items:
        item_name = item.get("name")
        item_id = item.get("id")
        
        # SharePoint connector download needs the actual relative URL or absolute web URL.
        # Let's provide Name, Url, and RelativePath
        if "folder" in item:
            # It is a folder, recurse into it
            new_parent_path = f"{parent_path}{item_name}/"
            list_drive_items_recursive(token, drive_id, item_id, new_parent_path, results, base_file_url)
        else:
            # It is a file
            # Skip non-downloadable system error pages or aspx forms in document libraries
            if item_name.lower().endswith(".aspx"):
                continue
            relative_path = f"{parent_path}{item_name}"
            # Construct direct SharePoint URL to avoid preview page URL mismatch issues in SharePoint connector
            relative_path_encoded = "/".join([urllib.parse.quote(part) for part in relative_path.split("/")]) if "/" in relative_path else urllib.parse.quote(relative_path)
            direct_url = f"{base_file_url}{relative_path_encoded}"
            
            results.append({
                "Name": item_name,
                "Url": direct_url,
                "RelativePath": relative_path,
                "IsPage": False
            })
            
    return results

# Parse canvas layout and render a premium modern site page as HTML
def render_page_to_html(page):
    title = page.get("title", "Untitled Page")
    creator = page.get("createdBy", {}).get("user", {}).get("displayName", "Unknown")
    creator_email = page.get("createdBy", {}).get("user", {}).get("email", "N/A")
    modified_time = page.get("lastModifiedDateTime", "N/A")
    
    html_parts = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append("<html>")
    html_parts.append("<head>")
    html_parts.append("    <meta charset='utf-8'>")
    html_parts.append(f"    <title>{title}</title>")
    html_parts.append("    <style>")
    html_parts.append("        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 850px; margin: 40px auto; padding: 0 20px; color: #242424; background-color: #fafafa; }")
    html_parts.append("        .container { background: #ffffff; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e1e1e1; }")
    html_parts.append("        h1 { border-bottom: 2px solid #0078d4; padding-bottom: 12px; color: #0078d4; font-size: 2.2rem; margin-top: 0; }")
    html_parts.append("        .metadata { font-size: 0.9rem; color: #666; margin-bottom: 30px; padding: 12px 16px; background: #f3f2f1; border-radius: 4px; border-left: 4px solid #0078d4; }")
    html_parts.append("        .section { margin-bottom: 35px; padding-bottom: 20px; border-bottom: 1px solid #eee; }")
    html_parts.append("        .column { margin-bottom: 20px; }")
    html_parts.append("        .webpart { margin-bottom: 25px; padding: 20px; background: #ffffff; border: 1px solid #edebe9; border-radius: 4px; transition: box-shadow 0.2s ease; }")
    html_parts.append("        .webpart:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.05); }")
    html_parts.append("        .webpart-title { font-weight: bold; color: #0078d4; font-size: 1.1rem; margin-bottom: 12px; border-bottom: 1px solid #f3f2f1; padding-bottom: 6px; }")
    html_parts.append("        .text-content { font-size: 1.05rem; color: #323130; }")
    html_parts.append("        ul { padding-left: 24px; }")
    html_parts.append("        li { margin-bottom: 8px; }")
    html_parts.append("        a { color: #0078d4; text-decoration: none; font-weight: 500; }")
    html_parts.append("        a:hover { text-decoration: underline; }")
    html_parts.append("    </style>")
    html_parts.append("</head>")
    html_parts.append("<body>")
    html_parts.append("    <div class='container'>")
    html_parts.append(f"        <h1>{title}</h1>")
    html_parts.append("        <div class='metadata'>")
    html_parts.append(f"            <strong>Created By:</strong> {creator} ({creator_email})<br>")
    html_parts.append(f"            <strong>Last Modified:</strong> {modified_time}")
    html_parts.append("        </div>")
    
    # Render Canvas Content
    canvas = page.get("canvasLayout", {})
    sections = canvas.get("horizontalSections", [])
    
    if sections:
        for sec_idx, sec in enumerate(sections):
            html_parts.append(f"        <div class='section' id='section-{sec_idx}'>")
            columns = sec.get("columns", [])
            for col_idx, col in enumerate(columns):
                html_parts.append(f"            <div class='column' id='section-{sec_idx}-col-{col_idx}'>")
                webparts = col.get("webparts", [])
                for wp in webparts:
                    wp_data = wp.get("data", {})
                    wp_title = wp_data.get("title", wp.get("webPartType", "Web Part"))
                    
                    html_parts.append("                <div class='webpart'>")
                    if wp_title:
                        html_parts.append(f"                    <div class='webpart-title'>{wp_title}</div>")
                    
                    # Collect texts and items inside webpart processed content
                    processed = wp_data.get("serverProcessedContent", {})
                    plain_texts = processed.get("searchablePlainTexts", [])
                    html_strings = processed.get("htmlStrings", [])
                    links = processed.get("links", [])
                    
                    # Render htmlStrings if any (typically Text webparts store HTML here)
                    if html_strings:
                        for hs in html_strings:
                            html_parts.append(f"                    <div class='text-content'>{hs.get('value', '')}</div>")
                    
                    # Render plain texts and items
                    elif plain_texts:
                        # Let's try to find lists or key/value properties
                        items_dict = {}
                        general_texts = []
                        for pt in plain_texts:
                            key = pt.get("key", "")
                            value = pt.get("value", "")
                            if "items[" in key:
                                # Parse nested item properties like items[0].title
                                parts = key.split(".")
                                item_idx_str = parts[0].replace("items[", "").replace("]", "")
                                try:
                                    item_idx = int(item_idx_str)
                                    prop_name = parts[1] if len(parts) > 1 else "title"
                                    if item_idx not in items_dict:
                                        items_dict[item_idx] = {}
                                    items_dict[item_idx][prop_name] = value
                                except ValueError:
                                    general_texts.append(value)
                            elif key != "title":
                                general_texts.append(value)
                        
                        # Render structured items (e.g., Quick Links)
                        if items_dict:
                            # Sort by item index
                            sorted_indices = sorted(items_dict.keys())
                            html_parts.append("                    <ul>")
                            for idx in sorted_indices:
                                item = items_dict[idx]
                                it_title = item.get("title", "Link Item")
                                # Look for matching link URL in links
                                it_url = "#"
                                for l in links:
                                    l_key = l.get("key", "")
                                    l_val = l.get("value", "")
                                    if f"items[{idx}]." in l_key:
                                        it_url = l_val
                                        break
                                html_parts.append(f"                        <li><a href='{it_url}' target='_blank'>{it_title}</a></li>")
                            html_parts.append("                    </ul>")
                        
                        # Render general plain texts
                        if general_texts:
                            for gt in general_texts:
                                html_parts.append(f"                    <p class='text-content'>{gt}</p>")
                    
                    # Fallback webpart properties preview
                    else:
                        desc = wp_data.get("description", "")
                        if desc:
                            html_parts.append(f"                    <p class='text-content'>{desc}</p>")
                            
                    html_parts.append("                </div>")
                html_parts.append("            </div>")
            html_parts.append("        </div>")
    else:
        html_parts.append("        <p>No section canvas layout content found on this page.</p>")
        
    html_parts.append("    </div>")
    html_parts.append("</body>")
    html_parts.append("</html>")
    
    return "\n".join(html_parts)

# Cloud Function entrypoint
@functions_framework.http
def main(request):
    # 1. Parse JSON payload or query parameters
    req_data = request.get_json(silent=True) or {}
    
    # Default configuration fallback
    site_name = req_data.get("site_name", "yourorg-sharepoint-to-gcs")
    library_name = req_data.get("library_name", "Shared Documents")
    
    # Optional integration automatic trigger parameters
    trigger_integration = req_data.get("trigger_integration", False)
    integration_name = req_data.get("integration_name", "yourorg-sharepoint-gcs-parent")
    location = req_data.get("location", "asia-southeast1")
    project_id_override = req_data.get("project_id")
    
    # Load parameters.json if it exists in local context
    params = {}
    if os.path.exists("parameters.json"):
        try:
            with open("parameters.json", "r") as f:
                params = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load parameters.json: {e}")

    # M365 Tenant Details
    tenant_id = params.get("CONFIG_M365_Tenant_Id", "36764916-28f8-4114-9116-60602e790f00")
    client_id = params.get("CONFIG_M365_Client_Id", "ab6207c5-b4c7-44f5-bd39-3ece91b5e3d0")
    secret_name = params.get("CONFIG_M365_Secret_Name", "projects/388889235558/secrets/yourorg-secret-sharepoint-clientsecret/versions/1")
    site_hostname = params.get("CONFIG_SharePoint_Hostname", "priyambodo.sharepoint.com")

    
    try:
        # 2. Fetch Azure AD Client Secret dynamically via GCP Secret Manager
        client_secret = get_secret(secret_name)
        
        # 3. Authenticate with Microsoft Entra ID
        token = get_graph_token(tenant_id, client_id, client_secret)
        
        # 4. Resolve Site ID for SharePoint subsite
        site_url_path = f"sites/{site_name.strip('/')}"
        resolve_site_url = f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:/{site_url_path}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        site_resp = requests.get(resolve_site_url, headers=headers)
        if site_resp.status_code != 200:
            return (f"Failed to resolve SharePoint Site: {site_resp.text}", 500)
            
        site_id = site_resp.json().get("id")
        
        # 5. Traverse Document Libraries (Drives) in the site
        drives_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        drives_resp = requests.get(drives_url, headers=headers)
        if drives_resp.status_code != 200:
            return (f"Failed to list drives: {drives_resp.text}", 500)
            
        drives = drives_resp.json().get("value", [])
        target_drive_id = None
        for d in drives:
            if d.get("name") == library_name:
                target_drive_id = d.get("id")
                break
                
        # Fallback to first drive if requested library name not matched
        if not target_drive_id and drives:
            target_drive_id = drives[0].get("id")
            
        sync_list = []
        
        # 6. Recursively list all files inside the target Document Library
        if target_drive_id:
            library_encoded = library_name.replace(" ", "%20")
            base_file_url = f"https://{site_hostname}/{site_url_path}/{library_encoded}/"
            list_drive_items_recursive(token, target_drive_id, "root", "", sync_list, base_file_url)
            
        # 7. Query modern site pages under Option B
        pages_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages"
        pages_resp = requests.get(pages_url, headers=headers)
        if pages_resp.status_code == 200:
            pages = pages_resp.json().get("value", [])
            for p in pages:
                page_id = p.get("id")
                # Fetch detail individually expanding canvasLayout
                detail_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                detail_resp = requests.get(detail_url, headers=headers)
                if detail_resp.status_code == 200:
                    page_detail = detail_resp.json()
                    page_name = page_detail.get("name", "Page.aspx")
                    html_name = page_name.replace(".aspx", ".html")
                    
                    # Compile and pre-render site canvas page to premium HTML layout
                    html_content = render_page_to_html(page_detail)
                    
                    sync_list.append({
                        "Name": html_name,
                        "RelativePath": f"pages/{html_name}",
                        "IsPage": True,
                        "VirtualContent": html_content
                    })
                
        # 8. Optionally trigger Application Integration directly (Serverless Orchestration)
        integration_triggered = False
        execution_id = None
        if trigger_integration and len(sync_list) > 0:
            import google.auth
            from google.auth.transport.requests import Request
            
            print(f"🤖 Auto-triggering Application Integration: {integration_name} in {location}...")
            credentials, credentials_project_id = google.auth.default()
            project_id = project_id_override or credentials_project_id or "work-mylab-machinelearning"
            
            credentials.refresh(Request())
            access_token = credentials.token
            
            integration_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}:execute"
            
            headers_int = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            payload_int = {
                "triggerId": f"api_trigger/{integration_name}-trigger",
                "inputParameters": {
                    "Parent_Files_List": {
                        "jsonValue": json.dumps(sync_list)
                    }
                }
            }
            
            int_resp = requests.post(integration_url, json=payload_int, headers=headers_int)
            if int_resp.status_code == 200:
                exec_data = int_resp.json()
                execution_id = exec_data.get("executionId")
                integration_triggered = True
                print(f"🟢 Integration triggered successfully! Execution ID: {execution_id}")
            else:
                print(f"❌ Integration trigger failed (Code {int_resp.status_code}): {int_resp.text}")
                raise Exception(f"Failed to trigger Application Integration: {int_resp.text}")
                
        # Return sync list and execution status cleanly as JSON
        response_payload = {
            "item_count": len(sync_list),
            "integration_triggered": integration_triggered,
            "execution_id": execution_id,
            "items": sync_list
        }
        return (json.dumps(response_payload, indent=2), 200, {"Content-Type": "application/json"})
        
    except Exception as e:
        import traceback
        err_msg = f"Error executing SharePoint traversal Cloud Function: {e}\n{traceback.format_exc()}"
        print(err_msg)
        return (err_msg, 500)
