import urllib.parse
import datetime
import base64
import html
from graph_client import graph_get_paginated, http

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

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

from collections import deque
from functools import lru_cache

import threading
import concurrent.futures

# Iterative multi-threaded BFS file enumeration in a SharePoint folder (guarantees high-speed OData discovery and 0% stack overflow on >15,000 items)
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
    
    queue = deque([(item_id, parent_path)])
    lock = threading.Lock()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        while queue:
            if max_items is not None and len(all_results) >= max_items:
                break
            
            batch = []
            while queue and len(batch) < 10:
                batch.append(queue.popleft())
                
            def fetch_folder(folder_tuple):
                f_id, f_path = folder_tuple
                url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{f_id}/children"
                if f_id == "root":
                    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                try:
                    return f_path, graph_get_paginated(url, headers)
                except Exception:
                    return f_path, []

            futures = [executor.submit(fetch_folder, item) for item in batch]
            for future in concurrent.futures.as_completed(futures):
                if max_items is not None and len(all_results) >= max_items:
                    break
                p_path, items = future.result()
                
                for item in items:
                    if max_items is not None and len(all_results) >= max_items:
                        break
                    item_name = item.get("name", "")
                    child_id = item.get("id")
                    
                    if "folder" in item:
                        queue.append((child_id, f"{p_path}{item_name}/"))
                    else:
                        if item_name.lower().endswith(".aspx"):
                            continue
                        relative_path = f"{p_path}{item_name}"
                        relative_path_encoded = "/".join([urllib.parse.quote(part) for part in relative_path.split("/")]) if "/" in relative_path else urllib.parse.quote(relative_path)
                        direct_url = f"{base_file_url}{relative_path_encoded}"
                        
                        file_item = {
                            "Name": item_name,
                            "Url": direct_url,
                            "RelativePath": relative_path,
                            "IsPage": False
                        }
                        needs_sync = True
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

                        with lock:
                            all_results.append(file_item)
                            if needs_sync:
                                sync_results.append(file_item)
                
    return all_results, sync_results

@lru_cache(maxsize=512)
def _cached_fetch_image_by_url(raw_src, source_url, auth_token):
    headers = {"Authorization": auth_token} if auth_token else {}
    try:
        parsed_src = urllib.parse.urlparse(source_url) if source_url else None
        host_name = parsed_src.netloc if (parsed_src and parsed_src.netloc) else "priyambodo.sharepoint.com"
        host_scheme = f"{parsed_src.scheme}://{host_name}" if (parsed_src and parsed_src.scheme) else f"https://{host_name}"
        
        full_img_url = raw_src if (raw_src.startswith("http://") or raw_src.startswith("https://")) else (f"{host_scheme}{raw_src}" if raw_src.startswith("/") else f"{host_scheme}/{raw_src}")
        
        # Strategy 1: Translate SharePoint OData/OneDrive APIs (_api/v2.x/drives/...) directly to Microsoft Graph
        if "/_api/v2.0/drives/" in full_img_url or "/_api/v2.1/drives/" in full_img_url:
            try:
                graph_odata_url = full_img_url.replace(f"https://{host_name}/_api/v2.0/drives/", "https://graph.microsoft.com/v1.0/drives/") \
                                              .replace(f"https://{host_name}/_api/v2.1/drives/", "https://graph.microsoft.com/v1.0/drives/") \
                                              .replace("/_api/v2.0/drives/", "https://graph.microsoft.com/v1.0/drives/") \
                                              .replace("/_api/v2.1/drives/", "https://graph.microsoft.com/v1.0/drives/")
                odata_resp = http.get(graph_odata_url, headers=headers, timeout=5)
                if odata_resp.status_code == 200 and odata_resp.content:
                    ct = odata_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                    b64_str = base64.b64encode(odata_resp.content).decode("utf-8")
                    return f"data:{ct};base64,{b64_str}"
            except Exception:
                pass

        # Parse canonical clean URL and inspect query parameters for dynamic handlers
        parsed_full = urllib.parse.urlparse(full_img_url)
        clean_img_url = full_img_url.split("?")[0].strip()
        parsed_img = urllib.parse.urlparse(clean_img_url)
        img_host = parsed_img.netloc or host_name
        img_path = parsed_img.path
        
        # Strategy 2: Extract real file path from dynamic handlers
        extracted_path = None
        if parsed_full.query:
            qs_params = urllib.parse.parse_qs(parsed_full.query)
            for param_key in ["path", "SourceUrl", "file", "url", "serverRelativeUrl", "fileAbsoluteUrl"]:
                if param_key in qs_params and qs_params[param_key]:
                    val = qs_params[param_key][0].strip()
                    if val and (val.startswith("/") or val.startswith("http")):
                        val_parsed = urllib.parse.urlparse(val)
                        extracted_path = val_parsed.path
                        img_host = val_parsed.netloc or img_host
                        break
        
        target_paths = [extracted_path] if extracted_path else []
        if img_path and img_path not in target_paths and not img_path.lower().endswith(".ashx") and not img_path.lower().endswith(".aspx"):
            target_paths.append(img_path)

        # Strategy 3: Native Graph API Site-Path Content Endpoint
        for t_path in target_paths:
            if t_path and t_path.startswith("/"):
                try:
                    graph_site_path_url = f"https://graph.microsoft.com/v1.0/sites/{img_host}:{t_path}:/content"
                    g_resp = http.get(graph_site_path_url, headers=headers, timeout=5)
                    if g_resp.status_code == 200 and g_resp.content:
                        ct = g_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                        b64_str = base64.b64encode(g_resp.content).decode("utf-8")
                        return f"data:{ct};base64,{b64_str}"
                except Exception:
                    pass
                
        # Strategy 4: Graph Shares Endpoint
        if clean_img_url and not clean_img_url.lower().endswith(".ashx") and not clean_img_url.lower().endswith(".aspx"):
            try:
                encoded_share = "u!" + base64.urlsafe_b64encode(clean_img_url.encode("utf-8")).decode("utf-8").rstrip("=")
                share_api_url = f"https://graph.microsoft.com/v1.0/shares/{encoded_share}/driveItem/content"
                share_resp = http.get(share_api_url, headers=headers, timeout=5)
                if share_resp.status_code == 200 and share_resp.content:
                    ct = share_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                    b64_str = base64.b64encode(share_resp.content).decode("utf-8")
                    return f"data:{ct};base64,{b64_str}"
            except Exception:
                pass
                
        # Strategy 5: Direct HTTP fallback download (5s timeout)
        try:
            direct_resp = http.get(full_img_url, headers=headers, timeout=5)
            if direct_resp.status_code == 200 and direct_resp.content:
                ct = direct_resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                b64_str = base64.b64encode(direct_resp.content).decode("utf-8")
                return f"data:{ct};base64,{b64_str}"
        except Exception:
            pass
    except Exception as e:
        print(f"Warning: _cached_fetch_image_by_url failed for {raw_src}: {e}")
    return ""

# Helper to download SharePoint image and return as Base64 data URI
def fetch_image_as_data_uri(raw_src, source_url="", headers=None):
    if not raw_src or not headers or raw_src.startswith("data:") or raw_src.startswith("blob:"):
        return ""
    auth_token = headers.get("Authorization", "") if headers else ""
    return _cached_fetch_image_by_url(raw_src, source_url, auth_token)

# Helper to resolve and embed inline images inside Rich Text HTML payloads
def resolve_and_embed_images_in_html(html_snippet, source_url="", headers=None):
    if not html_snippet or not headers or not BeautifulSoup:
        return html_snippet
    try:
        soup = BeautifulSoup(html_snippet, "html.parser")
        imgs = soup.find_all("img")
        if not imgs:
            return html_snippet
            
        for img in imgs:
            raw_src = img.get("src", "").strip()
            # If src is blob: or empty, inspect data-sp-original-src, data-src, or originalsource!
            if not raw_src or raw_src.startswith("blob:"):
                for attr_key in ["data-sp-original-src", "data-src", "originalsource", "original-src", "data-original-src"]:
                    val = img.get(attr_key, "").strip()
                    if val and not val.startswith("blob:"):
                        raw_src = val
                        break
                        
            if not raw_src or raw_src.startswith("data:") or raw_src.startswith("blob:"):
                continue
                
            img_data_uri = fetch_image_as_data_uri(raw_src, source_url, headers)
            if img_data_uri:
                img["src"] = img_data_uri
                img["style"] = "max-width:100%; height:auto;"
                
        return str(soup)
    except Exception as e:
        print(f"Warning: resolve_and_embed_images_in_html failed ({e})")
        return html_snippet

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
    html_parts.append("        @page { size: A4 portrait; margin: 0.8cm; @frame footer { -pdf-frame-content: footerContent; bottom: 0.5cm; margin-left: 0.8cm; margin-right: 0.8cm; height: 1cm; } }")
    html_parts.append("        body { font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #323130; background-color: #ffffff; margin: 0; padding: 0; }")
    html_parts.append("        .header-banner { background-color: #f3f2f1; border-left: 6px solid #0078d4; padding: 20px; margin-bottom: 25px; border-radius: 4px; }")
    html_parts.append("        h1 { color: #0078d4; font-size: 24pt; font-weight: 600; margin: 0 0 12px 0; }")
    html_parts.append("        .meta-text { font-size: 9.5pt; color: #605e5c; margin: 3px 0; }")
    html_parts.append("        .section { margin-bottom: 25px; clear: both; }")
    html_parts.append("        .sidebar-section { background-color: #faf9f8; border: 1px solid #edebe9; border-radius: 4px; padding: 18px; margin-top: 20px; }")
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
    html_parts.append("        img { max-width: 100%; height: auto; }")
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
    
    canvas = page.get("canvasLayout", {})
    horizontal_sections = canvas.get("horizontalSections", [])
    vertical_section = canvas.get("verticalSection", {})
    
    all_sections = []
    for sec in horizontal_sections:
        all_sections.append(("main", sec.get("columns", [])))
    if vertical_section and vertical_section.get("webparts"):
        all_sections.append(("sidebar", [{"webparts": vertical_section.get("webparts", [])}]))
    
    if all_sections:
        for sec_idx, (sec_type, columns) in enumerate(all_sections):
            sec_class = "sidebar-section" if sec_type == "sidebar" else "section"
            html_parts.append(f"    <div class='{sec_class}' id='section-{sec_idx}'>")
            if sec_type == "sidebar":
                html_parts.append("        <h2 style='color:#605e5c; font-size:14pt; border-bottom:2px solid #605e5c; padding-bottom:4px;'>📌 Sidebar Information</h2>")
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
                    
                    inner_html = wp.get("innerHtml") or props.get("text", "") or props.get("html", "")
                    if inner_html and inner_html.strip():
                        embedded_html = resolve_and_embed_images_in_html(inner_html, source_url, headers)
                        html_parts.append(f"            <div class='webpart-card text-content'>{embedded_html}</div>")
                        continue
                        
                    raw_title = wp_data.get("title", wp.get("webPartType", "")).strip()
                    if raw_title.lower() in ["spacer", "divider"] or wp.get("webPartType", "").lower() in ["spacer", "divider"]:
                        if raw_title.lower() == "divider" or wp.get("webPartType", "").lower() == "divider":
                            html_parts.append("            <hr class='divider-hr'>")
                        continue

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
                    raw_img = ""
                    if image_sources:
                        raw_img = image_sources[0].get("value", "").strip()
                    elif props.get("fileAbsoluteUrl"):
                        raw_img = props.get("fileAbsoluteUrl").strip()
                    elif props.get("serverRelativeUrl"):
                        raw_img = props.get("serverRelativeUrl").strip()

                    if raw_img and headers:
                        try:
                            img_data_uri = fetch_image_as_data_uri(raw_img, source_url, headers)
                        except Exception as e:
                            print(f"Warning: Failed to fetch card image {raw_img}: {e}")

                    if overlay_text or alt_text or caption_text or img_data_uri:
                        html_parts.append("            <div class='webpart-card people-grid'>")
                        if img_data_uri:
                            html_parts.append("                <table border='0' cellpadding='0' cellspacing='0' width='100%'><tr>")
                            html_parts.append(f"                <td width='150' valign='top'><img src='{img_data_uri}' style='max-width:140px; height:auto;' /></td>")
                            html_parts.append("                <td valign='top'>")
                        if overlay_text:
                            html_parts.append(f"                <div class='person-name'>📌 {html.escape(overlay_text)}</div>")
                        if caption_text:
                            html_parts.append(f"                <div class='person-detail'><b>Title/Caption:</b> {html.escape(caption_text)}</div>")
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
                    
                    has_content = False
                    if html_strings:
                        for hs in html_strings:
                            val = hs.get("value", "")
                            if val and val.strip():
                                embedded_hs = resolve_and_embed_images_in_html(val, source_url, headers)
                                html_parts.append(f"                <div class='text-content'>{embedded_hs}</div>")
                                has_content = True
                                
                    if plain_texts:
                        items_dict = {}
                        general_texts = []
                        for pt in plain_texts:
                            key = pt.get("key", "")
                            value = pt.get("value", "")
                            if not value or not str(value).strip():
                                continue
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
                                it_title = html.escape(item.get("title", item.get("description", "Link Item")))
                                it_url = "#"
                                for l in links:
                                    l_key = l.get("key", "")
                                    l_val = l.get("value", "")
                                    if f"items[{idx}]." in l_key or f"[{idx}]" in l_key:
                                        it_url = html.escape(l_val)
                                        break
                                if it_url != "#":
                                    html_parts.append(f"                    <li><a href='{it_url}' target='_blank'>🔗 {it_title}</a></li>")
                                else:
                                    html_parts.append(f"                    <li>▪️ {it_title}</li>")
                            html_parts.append("                </ul>")
                            has_content = True
                        
                        if general_texts:
                            for gt in general_texts:
                                clean_gt = html.escape(str(gt))
                                html_parts.append(f"                <p class='text-content'>{clean_gt}</p>")
                                has_content = True
                                
                    if not has_content:
                        desc = wp_data.get("description", "") or props.get("description", "") or props.get("summary", "") or props.get("title", "")
                        if desc and str(desc).strip():
                            html_parts.append(f"                <p class='text-content'>{html.escape(str(desc))}</p>")
                        elif props:
                            prop_texts = []
                            for k, v in props.items():
                                if isinstance(v, str) and len(v.strip()) > 2 and not v.startswith("http") and k not in ["id", "version", "layoutId"]:
                                    prop_texts.append(f"<b>{html.escape(k)}:</b> {html.escape(v)}")
                            if prop_texts:
                                html_parts.append(f"                <div class='text-content'><p>{'<br>'.join(prop_texts)}</p></div>")
                            
                    html_parts.append("            </div>")
                html_parts.append("        </div>")
            html_parts.append("    </div>")
    else:
        html_parts.append("    <p class='text-content'>No section canvas layout content found on this page.</p>")
        
    html_parts.append("</body>")
    html_parts.append("</html>")
    return "\n".join(html_parts)
