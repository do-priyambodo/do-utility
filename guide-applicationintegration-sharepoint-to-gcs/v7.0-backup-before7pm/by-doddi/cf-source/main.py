import os
import json
import urllib.parse
import datetime
import re
import functions_framework
from google.cloud import storage

from graph_client import get_secret, get_graph_token, graph_get_paginated, http
from pdf_renderer import render_html_to_pdf_base64
from sharepoint_traversal import get_all_subsites_recursive, list_drive_items_recursive, render_page_to_html

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
    conv_engine = req_data.get("pdf_conversion_engine") or params.get("CONFIG_PDF_Conversion_Engine", "playwright")
    
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
                    trigger_integ = req_data.get("trigger_integration", True)
                    if page_id and trigger_integ:
                        try:
                            d_url = f"https://graph.microsoft.com/v1.0/sites/{root_site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                            d_resp = http.get(d_url, headers=headers, timeout=60)
                            if d_resp.status_code == 200:
                                html_rendered = render_page_to_html(d_resp.json(), raw_url, headers)
                        except Exception as ex:
                            print(f"Warning: Failed to render {aspx_name}: {ex}")

                    if trigger_integ:
                        if not html_rendered:
                            html_rendered = f"<!DOCTYPE html><html><head><title>{filename}</title></head><body><h1>{filename}</h1><p>Source URL: <a href='{raw_url}'>{raw_url}</a></p></body></html>"
                        item_obj["VirtualContent"] = render_html_to_pdf_base64(html_rendered, fallback_title=filename, engine=conv_engine)

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
                        
                        trigger_integ = req_data.get("trigger_integration", True)
                        if trigger_integ:
                            detail_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                            detail_resp = http.get(detail_url, headers=headers, timeout=60)
                            if detail_resp.status_code == 200:
                                page_detail = detail_resp.json()
                                html_content = render_page_to_html(page_detail, p.get("webUrl", ""), headers)
                                page_obj["VirtualContent"] = render_html_to_pdf_base64(html_content, fallback_title=pdf_name, engine=conv_engine)
                            if not page_obj.get("VirtualContent"):
                                page_obj["VirtualContent"] = render_html_to_pdf_base64(f"<!DOCTYPE html><html><head><title>{pdf_name}</title></head><body><h1>{pdf_name}</h1></body></html>", fallback_title=pdf_name, engine=conv_engine)

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

        # Phase 4a.1: Generate config/metadata.jsonl Manifest for Vertex AI Discovery Engine / CCAI GKA
        if bucket_obj and len(all_list) > 0:
            try:
                print("🧠 Generating config/metadata.jsonl manifest for Vertex AI Datastore indexing...")
                jsonl_lines = []
                for item in all_list:
                    raw_name = item.get("Name", "doc")
                    rel_path = item.get("RelativePath", "")
                    # Sanitize doc_id strictly to [a-zA-Z0-9_-]
                    base_name = raw_name.rsplit('.', 1)[0]
                    doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
                    gcs_uri = f"gs://{bucket_name}/{rel_path}"
                    meta_record = {
                        "_id": doc_id,
                        "id": doc_id,
                        "structData": {
                            "sharepoint_url": item.get("Url", ""),
                            "title": raw_name,
                            "relative_path": rel_path
                        },
                        "content": {
                            "mimeType": "application/pdf",
                            "uri": gcs_uri
                        }
                    }
                    jsonl_lines.append(json.dumps(meta_record))
                jsonl_content = "\n".join(jsonl_lines)
                meta_blob = bucket_obj.blob("config/metadata.jsonl")
                meta_blob.upload_from_string(jsonl_content, content_type="application/x-ndjson")
                print(f"✅ Successfully uploaded {len(jsonl_lines)} records to gs://{bucket_name}/config/metadata.jsonl")
            except Exception as ex_meta:
                print(f"Warning: Failed to generate or upload config/metadata.jsonl: {ex_meta}")

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
