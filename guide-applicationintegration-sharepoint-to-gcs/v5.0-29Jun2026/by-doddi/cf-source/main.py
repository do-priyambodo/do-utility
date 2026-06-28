import os
import json
import requests
import urllib.parse
import datetime
import functions_framework
from msal import ConfidentialClientApplication
from google.cloud import secretmanager
from google.cloud import storage
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import html
import io

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

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

# Convert rendered HTML string to Base64-encoded PDF bytes using xhtml2pdf
def render_html_to_pdf_base64(html_string):
    if not pisa:
        print("Warning: xhtml2pdf not installed. Falling back to HTML payload.")
        return base64.b64encode(html_string.encode("utf-8")).decode("utf-8")
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_string), dest=pdf_buffer)
    if pisa_status.err:
        print(f"Warning: xhtml2pdf rendering error: {pisa_status.err}")
    pdf_bytes = pdf_buffer.getvalue()
    return base64.b64encode(pdf_bytes).decode("utf-8")

# Parse canvas layout and render a high-fidelity Fluent UI SharePoint site page
def render_page_to_html(page, source_url="", headers=None):
    title = html.escape(page.get("title", "Untitled Page"))
    creator = html.escape(page.get("createdBy", {}).get("user", {}).get("displayName", "Unknown"))
    creator_email = html.escape(page.get("createdBy", {}).get("user", {}).get("email", "N/A"))
    modified_time = html.escape(str(page.get("lastModifiedDateTime", "N/A")))
    page_url = source_url or page.get("webUrl", "")
    
    html_parts = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append("<html>")
    html_parts.append("<head>")
    html_parts.append("    <meta charset='utf-8'>")
    html_parts.append(f"    <title>{title}</title>")
    html_parts.append("    <style>")
    html_parts.append("        @page { size: A4 portrait; margin: 1.5cm; @frame footer { -pdf-frame-content: footerContent; bottom: 0.5cm; margin-left: 1.5cm; margin-right: 1.5cm; height: 1cm; } }")
    html_parts.append("        body { font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #323130; background-color: #ffffff; margin: 0; padding: 0; }")
    html_parts.append("        .header-banner { background-color: #f3f2f1; border-left: 6px solid #0078d4; padding: 20px; margin-bottom: 25px; border-radius: 4px; }")
    html_parts.append("        h1 { color: #0078d4; font-size: 24pt; font-weight: 600; margin: 0 0 12px 0; }")
    html_parts.append("        .meta-text { font-size: 9.5pt; color: #605e5c; margin: 3px 0; }")
    html_parts.append("        .section { margin-bottom: 25px; clear: both; }")
    html_parts.append("        .webpart-card { background: #ffffff; border: 1px solid #edebe9; border-radius: 4px; padding: 18px; margin-bottom: 18px; }")
    html_parts.append("        .webpart-hero { background-color: #f0f6ff; border-left: 4px solid #0078d4; padding: 20px; margin-bottom: 20px; border-radius: 4px; }")
    html_parts.append("        .webpart-title { font-weight: 600; color: #0078d4; font-size: 13pt; margin-bottom: 12px; border-bottom: 1px solid #edebe9; padding-bottom: 6px; }")
    html_parts.append("        .text-content { font-size: 11pt; color: #323130; margin-bottom: 10px; }")
    html_parts.append("        .divider-hr { border: 0; height: 1px; background: #c8c6c4; margin: 25px 0; }")
    html_parts.append("        .people-grid { margin-top: 10px; padding: 12px; background-color: #faf9f8; border-radius: 4px; border: 1px solid #edebe9; }")
    html_parts.append("        .person-name { font-weight: 600; color: #201f1e; font-size: 11pt; margin-top: 8px; }")
    html_parts.append("        .person-detail { font-size: 9.5pt; color: #605e5c; margin-bottom: 2px; }")
    html_parts.append("        ul { padding-left: 20px; margin: 8px 0; list-style-type: square; }")
    html_parts.append("        li { margin-bottom: 6px; }")
    html_parts.append("        a { color: #0078d4; text-decoration: none; font-weight: 500; }")
    html_parts.append("    </style>")
    html_parts.append("</head>")
    html_parts.append("<body>")
    html_parts.append("    <div class='header-banner'>")
    html_parts.append(f"        <h1>{title}</h1>")
    html_parts.append(f"        <div class='meta-text'><b>Created By:</b> {creator} &lt;{creator_email}&gt;</div>")
    html_parts.append(f"        <div class='meta-text'><b>Last Modified:</b> {modified_time}</div>")
    if page_url:
        clean_page_url = html.escape(page_url)
        html_parts.append(f"        <div class='meta-text'><b>SharePoint Source:</b> <a href='{clean_page_url}'>{clean_page_url}</a></div>")
    html_parts.append("    </div>")
    
    # Render Canvas Content
    canvas = page.get("canvasLayout", {})
    sections = canvas.get("horizontalSections", [])
    
    if sections:
        for sec_idx, sec in enumerate(sections):
            html_parts.append(f"    <div class='section' id='section-{sec_idx}'>")
            columns = sec.get("columns", [])
            for col_idx, col in enumerate(columns):
                html_parts.append(f"        <div class='column' id='section-{sec_idx}-col-{col_idx}'>")
                webparts = col.get("webparts", [])
                for wp in webparts:
                    wp_data = wp.get("data", {})
                    props = wp_data.get("properties", {})
                    processed = wp_data.get("serverProcessedContent", {})
                    plain_texts = processed.get("searchablePlainTexts", [])
                    html_strings = processed.get("htmlStrings", [])
                    links = processed.get("links", [])
                    
                    # 1. Handle Direct Rich Text / HTML payloads (e.g. paragraphs, quotes, welcome letters)
                    inner_html = wp.get("innerHtml") or props.get("text", "")
                    if inner_html and inner_html.strip():
                        html_parts.append(f"            <div class='webpart-card text-content'>{inner_html}</div>")
                        continue
                        
                    raw_title = wp_data.get("title", wp.get("webPartType", "")).strip()
                    
                    # Filter out editorial clutter: Spacer & Divider
                    if raw_title.lower() in ["spacer", "divider"] or wp.get("webPartType", "").lower() in ["spacer", "divider"]:
                        if raw_title.lower() == "divider" or wp.get("webPartType", "").lower() == "divider":
                            html_parts.append("            <hr class='divider-hr'>")
                        continue

                    # 2. Handle Image / Profile cards with overlayText or altText (e.g. Leadership profiles)
                    overlay_text = props.get("overlayText", "").strip()
                    alt_text = props.get("altText", "").strip()
                    caption_text = props.get("captionText", "").strip()
                    if not caption_text and plain_texts:
                        for pt in plain_texts:
                            if pt.get("key") == "captionText":
                                caption_text = pt.get("value", "").strip()
                                break
                                
                    image_sources = processed.get("imageSources", [])
                    img_data_uri = ""
                    if image_sources and headers:
                        raw_img = image_sources[0].get("value", "").strip()
                        if raw_img:
                            try:
                                if raw_img.startswith("http://") or raw_img.startswith("https://"):
                                    full_img_url = raw_img
                                else:
                                    parsed_src = urllib.parse.urlparse(source_url) if source_url else None
                                    host_scheme = f"{parsed_src.scheme}://{parsed_src.netloc}" if (parsed_src and parsed_src.netloc) else "https://priyambodo.sharepoint.com"
                                    full_img_url = f"{host_scheme}{raw_img}" if raw_img.startswith("/") else f"{host_scheme}/{raw_img}"
                                encoded_share = "u!" + base64.urlsafe_b64encode(full_img_url.encode("utf-8")).decode("utf-8").rstrip("=")
                                share_api_url = f"https://graph.microsoft.com/v1.0/shares/{encoded_share}/driveItem/content"
                                img_resp = http.get(share_api_url, headers=headers, timeout=30)
                                if img_resp.status_code == 200 and img_resp.content:
                                    ct = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                                    b64_str = base64.b64encode(img_resp.content).decode("utf-8")
                                    img_data_uri = f"data:{ct};base64,{b64_str}"
                            except Exception as e:
                                print(f"Warning: Failed to fetch inline image {raw_img}: {e}")

                    if overlay_text or alt_text or caption_text or img_data_uri:
                        html_parts.append("            <div class='webpart-card people-grid'>")
                        if img_data_uri:
                            html_parts.append("                <table border='0' cellpadding='0' cellspacing='0' width='100%'><tr>")
                            html_parts.append(f"                <td width='110' valign='top'><img src='{img_data_uri}' width='95' height='95' /></td>")
                            html_parts.append("                <td valign='top'>")
                        if overlay_text:
                            html_parts.append(f"                <div class='person-name'>👤 {html.escape(overlay_text)}</div>")
                        if caption_text:
                            html_parts.append(f"                <div class='person-detail'><b>Role/Title:</b> {html.escape(caption_text)}</div>")
                        if alt_text and alt_text != overlay_text:
                            html_parts.append(f"                <div class='person-detail'><i>Description:</i> {html.escape(alt_text)}</div>")
                        if img_data_uri:
                            html_parts.append("                </td></tr></table>")
                        html_parts.append("            </div>")
                        continue
                    
                    card_class = "webpart-card"
                    if raw_title.lower() in ["hero", "banner", "news", "hero web part"]:
                        card_class = "webpart-hero"
                    
                    html_parts.append(f"            <div class='{card_class}'>")
                    wp_title_clean = html.escape(raw_title)
                    if wp_title_clean and wp_title_clean.lower() not in ["web part", "text", "image", "show an image on your page"]:
                        html_parts.append(f"                <div class='webpart-title'>{wp_title_clean}</div>")
                    
                    if html_strings:
                        for hs in html_strings:
                            val = hs.get("value", "")
                            html_parts.append(f"                <div class='text-content'>{val}</div>")
                    elif plain_texts:
                        items_dict = {}
                        general_texts = []
                        for pt in plain_texts:
                            key = pt.get("key", "")
                            value = pt.get("value", "")
                            if "items[" in key:
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
                        
                        if items_dict:
                            sorted_indices = sorted(items_dict.keys())
                            html_parts.append("                <ul>")
                            for idx in sorted_indices:
                                item = items_dict[idx]
                                it_title = html.escape(item.get("title", "Link Item"))
                                it_url = "#"
                                for l in links:
                                    l_key = l.get("key", "")
                                    l_val = l.get("value", "")
                                    if f"items[{idx}]." in l_key:
                                        it_url = html.escape(l_val)
                                        break
                                html_parts.append(f"                    <li><a href='{it_url}' target='_blank'>{it_title}</a></li>")
                            html_parts.append("                </ul>")
                        
                        if general_texts:
                            if raw_title.lower() == "people":
                                html_parts.append("                <div class='people-grid'>")
                                i = 0
                                while i < len(general_texts):
                                    name = html.escape(general_texts[i])
                                    detail1 = html.escape(general_texts[i+1]) if i+1 < len(general_texts) else ""
                                    detail2 = html.escape(general_texts[i+2]) if i+2 < len(general_texts) else ""
                                    html_parts.append(f"                    <div class='person-name'>👤 {name}</div>")
                                    if detail1:
                                        html_parts.append(f"                    <div class='person-detail'>{detail1}</div>")
                                    if detail2:
                                        html_parts.append(f"                    <div class='person-detail'>{detail2}</div>")
                                    i += 3
                                html_parts.append("                </div>")
                            else:
                                for gt in general_texts:
                                    clean_gt = html.escape(gt)
                                    html_parts.append(f"                <p class='text-content'>{clean_gt}</p>")
                    else:
                        desc = wp_data.get("description", "")
                        if desc:
                            clean_desc = html.escape(desc)
                            html_parts.append(f"                <p class='text-content'>{clean_desc}</p>")
                            
                    html_parts.append("            </div>")
                html_parts.append("        </div>")
            html_parts.append("    </div>")
    else:
        html_parts.append("    <p class='text-content'>No section canvas layout content found on this page.</p>")
        
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
        
        def parse_bool_flag(val, default=True):
            if val is None: return default
            if isinstance(val, bool): return val
            return str(val).strip().lower() in ["true", "yes", "1", "y"]

        sync_files_flag = parse_bool_flag(req_data.get("sync_files", params.get("CONFIG_Sync_SharePoint_Files", True)))
        sync_pages_flag = parse_bool_flag(req_data.get("sync_pages", params.get("CONFIG_Sync_SharePoint_Pages", True)))
        print(f"⚙️ Sync Scope Settings -> Files: {sync_files_flag} | Pages: {sync_pages_flag}")

        target_urls = req_data.get("target_urls", [])
        
        # Option A: Dynamic GCS Config Read
        check_gcs_config = req_data.get("check_gcs_config", False) or req_data.get("use_gcs_config", False)
        if not target_urls and bucket_obj and check_gcs_config:
            try:
                cfg_blob = bucket_obj.get_blob("config/target_urls.txt")
                if cfg_blob:
                    raw_cfg = cfg_blob.download_as_text()
                    target_urls = [l.strip() for l in raw_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
                    if target_urls:
                        print(f"📂 Loaded {len(target_urls)} dynamic target URL(s) live from GCS gs://{bucket_name}/config/target_urls.txt")
            except Exception as e:
                print(f"Warning: Could not read dynamic GCS config gs://{bucket_name}/config/target_urls.txt: {e}")

        if target_urls:
            print(f"🎯 Bypassing Graph folder traversal: Scoping directly to {len(target_urls)} targeted URL(s)...")
            
            pages_dict = {}
            try:
                p_url = f"https://graph.microsoft.com/v1.0/sites/{root_site_id}/pages"
                for p_item in graph_get_paginated(p_url, headers):
                    p_name = p_item.get("name", "").lower()
                    if p_name:
                        pages_dict[p_name] = {
                            "id": p_item.get("id"),
                            "lastModifiedDateTime": p_item.get("lastModifiedDateTime")
                        }
            except Exception as e:
                print(f"Warning: Could not list site pages for targeted rendering: {e}")

            for raw_url in target_urls:
                clean_url = raw_url.split("?")[0].strip()
                parsed = urllib.parse.urlparse(clean_url)
                url_path = urllib.parse.unquote(parsed.path)
                filename = os.path.basename(url_path)
                is_page = False
                if filename.lower().endswith(".aspx"):
                    is_page = True
                    filename = filename[:-5] + ".pdf"
                
                rel_path = f"pages/{filename}" if is_page else f"files/{filename}"
                if "/sites/" in url_path:
                    parts = [p for p in url_path.split("/") if p and p.lower() not in ["sites", "sitepages", "shared documents", "documents"]]
                    if len(parts) > 1:
                        sub_folder = "/".join(parts[1:-1])
                        if sub_folder:
                            rel_path = f"pages/{sub_folder}/{filename}" if is_page else f"files/{sub_folder}/{filename}"

                item_obj = {
                    "Name": filename,
                    "Url": raw_url,
                    "RelativePath": rel_path,
                    "IsPage": is_page
                }
                
                if is_page and not sync_pages_flag:
                    print(f"⏭️ CONFIG_Sync_SharePoint_Pages disabled. Skipping targeted page: {raw_url}")
                    continue
                if not is_page and not sync_files_flag:
                    print(f"⏭️ CONFIG_Sync_SharePoint_Files disabled. Skipping targeted file: {raw_url}")
                    continue

                if is_page:
                    aspx_name = os.path.basename(url_path).lower()
                    page_info = pages_dict.get(aspx_name)
                    
                    # 1. Deletion check for inactive / deleted pages
                    if not page_info and pages_dict:
                        print(f"🗑️ Status Log: Inactive target page detected ({aspx_name}). Checking GCS bucket for deletion...")
                        if bucket_obj:
                            try:
                                stale_blob = bucket_obj.get_blob(rel_path)
                                if stale_blob:
                                    stale_blob.delete()
                                    print(f"✅ Successfully deleted inactive file from GCS: gs://{bucket_name}/{rel_path}")
                                else:
                                    print(f"ℹ️ File already absent in GCS: gs://{bucket_name}/{rel_path}")
                            except Exception as ex_del:
                                print(f"Warning: Failed to delete inactive GCS file {rel_path}: {ex_del}")
                        continue
                    
                    # 2. Delta cache filter check
                    needs_sync = True
                    if page_info and not force_full_sync:
                        sp_mod = page_info.get("lastModifiedDateTime")
                        if sp_mod:
                            try:
                                sp_dt = datetime.datetime.fromisoformat(sp_mod.replace("Z", "+00:00"))
                                gcs_mod = gcs_cache.get(rel_path)
                                if gcs_mod and gcs_mod >= sp_dt:
                                    needs_sync = False
                                elif bucket_obj and not gcs_mod:
                                    blob = bucket_obj.get_blob(rel_path)
                                    if blob and blob.updated and blob.updated >= sp_dt:
                                        needs_sync = False
                            except Exception:
                                pass
                    
                    if not needs_sync:
                        print(f"⏭️ Skipping unchanged target URL (Delta Cache hit): {raw_url}")
                        all_list.append(item_obj)
                        continue

                    page_id = page_info["id"] if page_info else None
                    html_rendered = ""
                    if page_id:
                        try:
                            d_url = f"https://graph.microsoft.com/v1.0/sites/{root_site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                            d_resp = http.get(d_url, headers=headers, timeout=60)
                            if d_resp.status_code == 200:
                                html_rendered = render_page_to_html(d_resp.json(), raw_url, headers)
                        except Exception as ex:
                            print(f"Warning: Failed to render {aspx_name}: {ex}")
                    if not html_rendered:
                        html_rendered = f"<!DOCTYPE html><html><head><title>{filename}</title></head><body><h1>{filename}</h1><p>Source URL: <a href='{raw_url}'>{raw_url}</a></p></body></html>"
                    item_obj["VirtualContent"] = render_html_to_pdf_base64(html_rendered)

                all_list.append(item_obj)
                sync_list.append(item_obj)
                
        target_sites_to_scan = target_sites if not target_urls else []
        for site_info in target_sites_to_scan:
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
            if target_drive_id and sync_files_flag:
                if target_drive_url:
                    base_file_url = f"{target_drive_url.rstrip('/')}/"
                else:
                    library_encoded = urllib.parse.quote(library_name)
                    sub_path = f"{site_url_path}/{site_prefix}" if site_prefix else site_url_path
                    base_file_url = f"https://{site_hostname}/{sub_path.rstrip('/')}/{library_encoded}/"
                list_drive_items_recursive(token, target_drive_id, "root", site_prefix, all_list, sync_list, base_file_url, bucket_obj, gcs_cache, max_items)
            elif not sync_files_flag:
                print(f"⏭️ CONFIG_Sync_SharePoint_Files disabled. Skipping Document Library traversal for site.")
                
            # 7. Query modern site pages under Option B
            if sync_pages_flag and (max_items is None or len(all_list) < max_items):
                pages_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages"
                try:
                    pages = graph_get_paginated(pages_url, headers)
                    for p in pages:
                        if max_items is not None and len(all_list) >= max_items:
                            break
                        page_id = p.get("id")
                        page_name = p.get("name", "Page.aspx")
                        pdf_name = page_name.replace(".aspx", ".pdf")
                        rel_page_path = f"pages/{site_prefix}{pdf_name}"
                        
                        page_obj = {
                            "Name": pdf_name,
                            "Url": p.get("webUrl", ""),
                            "RelativePath": rel_page_path,
                            "IsPage": True
                        }
                        
                        detail_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                        detail_resp = http.get(detail_url, headers=headers, timeout=60)
                        if detail_resp.status_code == 200:
                            page_detail = detail_resp.json()
                            html_content = render_page_to_html(page_detail, p.get("webUrl", ""), headers)
                            page_obj["VirtualContent"] = render_html_to_pdf_base64(html_content)
                        if not page_obj.get("VirtualContent"):
                            page_obj["VirtualContent"] = render_html_to_pdf_base64(f"<!DOCTYPE html><html><head><title>{pdf_name}</title></head><body><h1>{pdf_name}</h1></body></html>")
                        
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
            elif not sync_pages_flag:
                print(f"⏭️ CONFIG_Sync_SharePoint_Pages disabled. Skipping Modern Site Pages traversal for site.")
                
        # 7b. Cleanup orphaned/deleted SharePoint items from GCS bucket during full traversal
        if bucket_obj and gcs_cache and not target_urls:
            print("🔍 Status Log: Checking GCS inventory for deleted/inactive SharePoint files...")
            active_gcs_paths = set(item.get("RelativePath") for item in all_list if item.get("RelativePath"))
            deleted_count = 0
            for cached_path in list(gcs_cache.keys()):
                if cached_path not in active_gcs_paths and not cached_path.startswith("config/") and not cached_path.startswith("status/"):
                    try:
                        stale_blob = bucket_obj.get_blob(cached_path)
                        if stale_blob:
                            stale_blob.delete()
                            deleted_count += 1
                            print(f"🗑️ Status Log: Deleted inactive file from GCS: gs://{bucket_name}/{cached_path}")
                    except Exception as ex_del:
                        print(f"Warning: Could not delete orphaned GCS file {cached_path}: {ex_del}")
            if deleted_count > 0:
                print(f"✅ Status Log: Cleaned up {deleted_count} inactive/deleted file(s) from GCS bucket.")
            else:
                print("✅ Status Log: No inactive/deleted files found in GCS bucket.")

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
