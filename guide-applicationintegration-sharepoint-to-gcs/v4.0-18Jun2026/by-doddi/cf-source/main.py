import os
import json
import requests
import urllib.parse
import datetime
import functions_framework
from msal import ConfidentialClientApplication
from google.cloud import secretmanager
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Global resilient HTTP session with automatic retry backoff for M365 throttling (429) & Gateway timeouts (504)
def get_resilient_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

http = get_resilient_session()

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

# Helper to handle OData paginated Microsoft Graph API requests
def graph_get_paginated(url, headers):
    results = []
    while url:
        response = http.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            raise Exception(f"Graph API returned status {response.status_code} for url {url}: {response.text}")
        data = response.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return results

# Helper to recursively enumerate all child subsites (e.g., DEN/Consumer, DEN/Business)
def get_all_subsites_recursive(root_site_id, headers, current_prefix=""):
    subsites = []
    url = f"https://graph.microsoft.com/v1.0/sites/{root_site_id}/sites"
    try:
        children = graph_get_paginated(url, headers)
        for child in children:
            child_id = child.get("id")
            raw_name = child.get("name", "")
            sub_prefix = f"{current_prefix}{raw_name}/" if raw_name else f"{current_prefix}subsite/"
            subsites.append({"id": child_id, "name": raw_name, "prefix": sub_prefix})
            subsites.extend(get_all_subsites_recursive(child_id, headers, sub_prefix))
    except Exception as e:
        print(f"Warning: Failed to list subsites under {root_site_id}: {e}")
    return subsites

# Recursively list files in a SharePoint folder (drive item)
def list_drive_items_recursive(token, drive_id, item_id="root", parent_path="", all_results=None, sync_results=None, base_file_url="", bucket_obj=None, gcs_cache=None, max_items=None):
    if all_results is None:
        all_results = []
    if sync_results is None:
        sync_results = []
    if max_items is not None and len(all_results) >= max_items:
        return all_results, sync_results
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children"
    if item_id == "root":
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        
    items = graph_get_paginated(url, headers)
    
    for item in items:
        if max_items is not None and len(all_results) >= max_items:
            break
        item_name = item.get("name")
        item_id = item.get("id")
        
        # SharePoint connector download needs the actual relative URL or absolute web URL.
        # Let's provide Name, Url, and RelativePath
        if "folder" in item:
            # It is a folder, recurse into it
            new_parent_path = f"{parent_path}{item_name}/"
            list_drive_items_recursive(token, drive_id, item_id, new_parent_path, all_results, sync_results, base_file_url, bucket_obj, gcs_cache, max_items)
        else:
            # It is a file
            # Skip non-downloadable system error pages or aspx forms in document libraries
            if item_name.lower().endswith(".aspx"):
                continue
            relative_path = f"{parent_path}{item_name}"
            
            # Construct direct SharePoint URL to avoid preview page URL mismatch issues in SharePoint connector
            relative_path_encoded = "/".join([urllib.parse.quote(part) for part in relative_path.split("/")]) if "/" in relative_path else urllib.parse.quote(relative_path)
            direct_url = f"{base_file_url}{relative_path_encoded}"
            
            file_item = {
                "Name": item_name,
                "Url": direct_url,
                "RelativePath": relative_path,
                "IsPage": False
            }
            all_results.append(file_item)
            
            needs_sync = True
            # Option 1: Incremental sync change check against GCS blob updated time
            gcs_check_path = f"files/{relative_path}"
            if gcs_cache is not None and gcs_check_path in gcs_cache:
                sp_mod = item.get("lastModifiedDateTime")
                if sp_mod:
                    try:
                        sp_dt = datetime.datetime.fromisoformat(sp_mod.replace("Z", "+00:00"))
                        if gcs_cache[gcs_check_path] >= sp_dt:
                            needs_sync = False
                    except Exception:
                        pass
            elif bucket_obj and gcs_cache is None:
                try:
                    blob = bucket_obj.get_blob(gcs_check_path)
                    sp_mod = item.get("lastModifiedDateTime")
                    if blob and blob.updated and sp_mod:
                        sp_dt = datetime.datetime.fromisoformat(sp_mod.replace("Z", "+00:00"))
                        if blob.updated >= sp_dt:
                            needs_sync = False
                except Exception:
                    pass

            if needs_sync:
                sync_results.append(file_item)
            
    return all_results, sync_results

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
    
    # Load parameters.json if it exists in local context
    params = {}
    if os.path.exists("parameters.json"):
        try:
            with open("parameters.json", "r") as f:
                params = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load parameters.json: {e}")

    # Default configuration fallback
    site_name = req_data.get("site_name") or params.get("CONFIG_Sharepoint_Sites", "").replace("sites/", "")
    library_name = req_data.get("library_name") or params.get("CONFIG_Sharepoint_Library", "Documents")
    
    # Optional integration automatic trigger parameters
    trigger_integration = req_data.get("trigger_integration", False)
    integration_name = req_data.get("integration_name") or params.get("CONFIG_Parent_Integration_Name")
    location = req_data.get("location") or params.get("CONFIG_Location")
    project_id_override = req_data.get("project_id") or params.get("CONFIG_ProjectId")

    # Option 1: Incremental sync bucket client init
    bucket_name = req_data.get("bucket_name") or params.get("CONFIG_GCS_Bucket")
    force_full_sync = req_data.get("force_full_sync", False) or params.get("CONFIG_Force_Full_Sync", False)
    
    bucket_obj = None
    gcs_cache = {}
    if bucket_name and not force_full_sync:
        try:
            storage_client = storage.Client()
            bucket_obj = storage_client.bucket(bucket_name)
            print("🔍 Pre-fetching GCS blobs metadata for O(1) incremental comparison...")
            for b in storage_client.list_blobs(bucket_name, prefix="files/"):
                if b.updated:
                    gcs_cache[b.name] = b.updated
            for b in storage_client.list_blobs(bucket_name, prefix="pages/"):
                if b.updated:
                    gcs_cache[b.name] = b.updated
            print(f"✅ Cached {len(gcs_cache)} GCS blob timestamps in memory.")
        except Exception as e:
            print(f"Warning: Could not init GCS bucket client or pre-fetch cache: {e}")

    # M365 Tenant Details
    tenant_id = req_data.get("tenant_id") or params.get("CONFIG_M365_Tenant_Id")
    client_id = req_data.get("client_id") or params.get("CONFIG_M365_Client_Id")
    secret_name = req_data.get("secret_name") or params.get("CONFIG_M365_Secret_Name")
    site_hostname = req_data.get("site_hostname") or params.get("CONFIG_SharePoint_Hostname")

    if not all([tenant_id, client_id, secret_name, site_hostname]):
        raise ValueError("Missing required M365 configuration parameters in parameters.json or request payload.")

    
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
        
        site_resp = http.get(resolve_site_url, headers=headers, timeout=60)
        if site_resp.status_code != 200:
            return (f"Failed to resolve SharePoint Site: {site_resp.text}", 500)
            
        root_site_id = site_resp.json().get("id")
        
        target_sites = [{"id": root_site_id, "name": site_name, "prefix": ""}]
        print("🔍 Scoping child subsites across SharePoint site collection...")
        target_sites.extend(get_all_subsites_recursive(root_site_id, headers, ""))
        print(f"✅ Enumerable sites resolved (Total: {len(target_sites)} site collections/subsites).")

        all_list = []
        sync_list = []
        
        for site_info in target_sites:
            curr_site_id = site_info["id"]
            site_prefix = site_info["prefix"] # e.g. "Consumer/" or "Business/"
            
            # 5. Traverse Document Libraries (Drives) in the site
            drives_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/drives"
            try:
                drives = graph_get_paginated(drives_url, headers)
            except Exception as e:
                print(f"Warning: Failed to list drives for site {curr_site_id}: {e}")
                continue
                
            target_drive_id = None
            target_drive_url = None
            for d in drives:
                d_name = d.get("name", "")
                if d_name == library_name or (library_name in ["Shared Documents", "Documents"] and d_name in ["Shared Documents", "Documents"]):
                    target_drive_id = d.get("id")
                    target_drive_url = d.get("webUrl")
                    break
                    
            if not target_drive_id and drives:
                for d in drives:
                    if d.get("driveType") == "documentLibrary" and d.get("name") not in ["Site Pages", "Style Library", "Form Templates", "Site Assets"]:
                        target_drive_id = d.get("id")
                        target_drive_url = d.get("webUrl")
                        break
                if not target_drive_id:
                    target_drive_id = drives[0].get("id")
                    target_drive_url = drives[0].get("webUrl")
                
            # 6. Recursively list all files inside the target Document Library
            max_items = req_data.get("max_items")
            if target_drive_id:
                if target_drive_url:
                    base_file_url = f"{target_drive_url.rstrip('/')}/"
                else:
                    library_encoded = urllib.parse.quote(library_name)
                    sub_path = f"{site_url_path}/{site_prefix}" if site_prefix else site_url_path
                    base_file_url = f"https://{site_hostname}/{sub_path.rstrip('/')}/{library_encoded}/"
                list_drive_items_recursive(token, target_drive_id, "root", site_prefix, all_list, sync_list, base_file_url, bucket_obj, gcs_cache, max_items)
                
            # 7. Query modern site pages under Option B
            if max_items is None or len(all_list) < max_items:
                pages_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages"
                try:
                    pages = graph_get_paginated(pages_url, headers)
                    for p in pages:
                        if max_items is not None and len(all_list) >= max_items:
                            break
                        page_id = p.get("id")
                        page_name = p.get("name", "Page.aspx")
                        html_name = page_name.replace(".aspx", ".html")
                        rel_page_path = f"pages/{site_prefix}{html_name}"
                        
                        page_obj = {
                            "Name": html_name,
                            "RelativePath": rel_page_path,
                            "IsPage": True
                        }
                        
                        detail_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                        detail_resp = http.get(detail_url, headers=headers, timeout=60)
                        if detail_resp.status_code == 200:
                            page_detail = detail_resp.json()
                            html_content = render_page_to_html(page_detail)
                            page_obj["VirtualContent"] = html_content
                        
                        all_list.append(page_obj)
                        
                        needs_sync = True
                        if gcs_cache is not None and rel_page_path in gcs_cache:
                            p_mod = p.get("lastModifiedDateTime")
                            if p_mod:
                                try:
                                    sp_dt_p = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                    if gcs_cache[rel_page_path] >= sp_dt_p:
                                        needs_sync = False
                                except Exception:
                                    pass
                        elif bucket_obj and not gcs_cache:
                            try:
                                blob_p = bucket_obj.get_blob(rel_page_path)
                                p_mod = p.get("lastModifiedDateTime")
                                if blob_p and blob_p.updated and p_mod:
                                    sp_dt_p = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                    if blob_p.updated >= sp_dt_p:
                                        needs_sync = False
                            except Exception:
                                pass
                        
                        if needs_sync:
                            sync_list.append(page_obj)
                except Exception as e:
                    print(f"Warning: Could not fetch pages for site {curr_site_id}: {e}")
                
        # 8. Optionally trigger Application Integration directly (Serverless Orchestration)
        integration_triggered = False
        execution_ids = []
        if trigger_integration and len(sync_list) > 0:
            import google.auth
            from google.auth.transport.requests import Request
            
            print(f"🤖 Auto-triggering Application Integration asynchronously: {integration_name} in {location}...")
            credentials, credentials_project_id = google.auth.default()
            project_id = project_id_override or credentials_project_id or params.get("CONFIG_ProjectId")
            if not project_id:
                raise ValueError("Project ID not specified in parameters.json or GCP credentials.")
            
            credentials.refresh(Request())
            access_token = credentials.token
            
            integration_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}:schedule"
            
            headers_int = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            batch_size = params.get("CONFIG_Batch_Size", 100)
            for i in range(0, len(sync_list), batch_size):
                batch = sync_list[i:i + batch_size]
                payload_int = {
                    "triggerId": f"api_trigger/{integration_name}-trigger",
                    "inputParameters": {
                        "`Parent_Files_List`": {
                            "jsonValue": json.dumps(batch)
                        }
                    }
                }
                
                int_resp = http.post(integration_url, json=payload_int, headers=headers_int, timeout=60)
                if int_resp.status_code == 200:
                    exec_data = int_resp.json()
                    eid = exec_data.get("executionId")
                    if eid:
                        execution_ids.append(eid)
                    integration_triggered = True
                    print(f"🟢 Batch ({len(batch)} items) scheduled -> Execution ID: {eid}")
                else:
                    print(f"❌ Integration trigger failed (Code {int_resp.status_code}): {int_resp.text}")
                    raise Exception(f"Failed to trigger Application Integration batch: {int_resp.text}")
                
        # Return sync list and execution status cleanly as JSON
        response_payload = {
            "all_resources_count": len(all_list),
            "sync_resources_count": len(sync_list),
            "item_count": len(sync_list),
            "integration_triggered": integration_triggered,
            "execution_id": execution_ids[0] if execution_ids else None,
            "execution_ids": execution_ids,
            "all_resources": all_list,
            "sync_resources": sync_list,
            "items": sync_list
        }
        return (json.dumps(response_payload, indent=2), 200, {"Content-Type": "application/json"})
        
    except Exception as e:
        import traceback
        err_msg = f"Error executing SharePoint traversal Cloud Function: {e}\n{traceback.format_exc()}"
        print(err_msg)
        return (err_msg, 500)
