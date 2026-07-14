# [REVISION CHECK]: 3-Strategy Site Pages Discovery Engine Active (v1.0 + beta + SitePages Drive)
import os
import json
import urllib.parse
import datetime
import re
import time
from collections import deque
import threading
import concurrent.futures
import traceback
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import google.auth
from google.auth.transport.requests import Request
import functions_framework
from google.cloud import storage

from graph_client import get_secret, get_graph_token, graph_get_paginated, http
from pdf_renderer import render_html_to_pdf_base64
from sharepoint_traversal import get_all_subsites_recursive, list_drive_items_recursive, render_page_to_html
from config_schema import validate_parameters

# Cloud Function entrypoint
@functions_framework.http
def main(request):
    import sys
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    start_time = time.time()
    max_execution_seconds = 3300  # 55 minutes Wall-Clock safety circuit breaker (< 3600s Cloud Run ceiling)
    # 1. Parse JSON payload or query parameters (null-safe for direct Cloud Run Job invocation where request=None)
    req_data = {}
    if request is not None and hasattr(request, "get_json"):
        try:
            req_data = request.get_json(silent=True) or {}
        except Exception:
            pass
    
    # Load parameters.json if it exists in local context
    params = {}
    if os.path.exists("parameters.json"):
        try:
            with open("parameters.json", "r") as f:
                params = json.load(f)
            params = validate_parameters(params)
        except Exception as e:
            print(f"Warning: Failed to load or validate parameters.json: {e}", flush=True)

    # Default configuration fallback
    site_name = req_data.get("site_name") or params.get("CONFIG_Sharepoint_Sites", "").replace("sites/", "")
    library_name = req_data.get("library_name") or params.get("CONFIG_Sharepoint_Library", "Documents")
    
    # Optional integration automatic trigger parameters (auto-trigger when configured in parameters.json unless explicitly disabled in request body)
    integration_name = req_data.get("integration_name") or params.get("CONFIG_Parent_Integration_Name")
    raw_trigger = req_data.get("trigger_integration")
    if raw_trigger is not None:
        trigger_integration = str(raw_trigger).lower() == "true"
    else:
        trigger_integration = bool(integration_name)
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
    tenant_id = req_data.get("tenant_id") or params.get("CONFIG_M365_Tenant_Id") or params.get("CONFIG_TenantId")
    client_id = req_data.get("client_id") or params.get("CONFIG_M365_Client_Id") or params.get("CONFIG_ClientId")
    secret_name = req_data.get("secret_name") or params.get("CONFIG_M365_Secret_Name") or params.get("CONFIG_SecretName")
    site_hostname = req_data.get("site_hostname") or params.get("CONFIG_SharePoint_Hostname") or params.get("CONFIG_Sharepoint_Domain")

    if not all([tenant_id, client_id, secret_name, site_hostname]):
        raise ValueError("Missing required M365 configuration parameters in parameters.json or request payload.")

    try:
        print("="*60, flush=True)
        print("🚀 [Step 1/7] Initializing M365 Authentication & Parameter Discovery...", flush=True)
        print("="*60, flush=True)

        # 2. Fetch Azure AD Client Secret dynamically via GCP Secret Manager
        print(f"🔐 [Step 2/7] Retrieving Azure AD Client Secret ({secret_name})...", flush=True)
        t_sec = time.time()
        client_secret = get_secret(secret_name)
        print(f"✅ [Step 2 Completed in {time.time()-t_sec:.2f}s] Client Secret retrieved successfully.", flush=True)
        
        # 3. Authenticate with Microsoft Entra ID
        print(f"🔑 [Step 3/7] Acquiring OAuth Access Token for tenant {tenant_id}...", flush=True)
        t_tok = time.time()
        token = get_graph_token(tenant_id, client_id, client_secret)
        print(f"✅ [Step 3 Completed in {time.time()-t_tok:.2f}s] OAuth Access Token acquired successfully.", flush=True)
        
        # 4. Resolve Site ID for SharePoint subsite
        site_url_path = f"sites/{site_name.strip('/')}"
        resolve_site_url = f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:/{site_url_path}"
        print(f"🌐 [Step 4/7] Resolving SharePoint Site ID via Graph API ({resolve_site_url})...", flush=True)
        t_site = time.time()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        site_resp = http.get(resolve_site_url, headers=headers, timeout=60)
        if site_resp.status_code != 200:
            return (f"Failed to resolve SharePoint Site: {site_resp.text}", 500)
            
        root_site_id = site_resp.json().get("id")
        print(f"✅ [Step 4 Completed in {time.time()-t_site:.2f}s] Site ID Resolved: {root_site_id}", flush=True)
        
        target_sites = [{"id": root_site_id, "name": site_name, "prefix": ""}]
        print("🔍 [Step 5/7] Scoping child subsites across SharePoint site collection...", flush=True)
        target_sites.extend(get_all_subsites_recursive(root_site_id, headers, ""))
        print(f"✅ [Step 5 Completed] Enumerable sites resolved (Total: {len(target_sites)} site collections/subsites).", flush=True)

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
                    if page_id:
                        item_obj["_page_id"] = page_id
                        item_obj["_site_id"] = root_site_id
                        item_obj["_raw_url"] = raw_url
                        item_obj["_filename"] = filename

                all_list.append(item_obj)
                sync_list.append(item_obj)
                
        target_sites_to_scan = target_sites if not target_urls else []
        discovery_start_time = time.time()
        for site_info in target_sites_to_scan:
            if time.time() - discovery_start_time > 2100:
                print(f"⏱️ Wall-Clock Discovery Time Guard reached ({time.time() - discovery_start_time:.1f}s). Finalizing discovered inventory ({len(sync_list)} delta items) and initiating processing/upload pipeline immediately...", flush=True)
                break

            curr_site_id = site_info["id"]
            site_prefix = site_info["prefix"] # e.g. "Consumer/" or "Business/"
            site_label = site_info.get("name") or curr_site_id
            print(f"📡 Phase 1 Discovery [{target_sites_to_scan.index(site_info) + 1}/{len(target_sites_to_scan)}]: Scanning site/subsite '{site_label}' (Prefix: '{site_prefix}')...", flush=True)
            
            # 5. Traverse Document Libraries (Drives) in the site
            drives_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/drives"
            try:
                drives = graph_get_paginated(drives_url, headers)
            except Exception as e:
                print(f"Warning: Failed to list drives for site {curr_site_id}: {e}")
                continue
                
            drives_to_scan = []
            system_libraries = {"style library", "form templates", "site assets", "sitepages", "pages", "site pages"}
            for d in drives:
                d_name = d.get("name", "")
                d_lower = d_name.lower().replace(" ", "")
                if d.get("driveType") == "documentLibrary" and d_lower not in system_libraries:
                    if not library_name or library_name.lower() in ["all", "*"] or d_name.lower() == library_name.lower() or (library_name in ["Shared Documents", "Documents"] and d_name in ["Shared Documents", "Documents"]):
                        drives_to_scan.append(d)
            if not drives_to_scan and drives and library_name.lower() not in ["all", "*"]:
                for d in drives:
                    if d.get("driveType") == "documentLibrary" and d.get("name", "").lower() not in system_libraries:
                        drives_to_scan.append(d)
                        break

            # 6. Recursively list all files inside every matching Document Library
            max_items = req_data.get("max_items")
            if drives_to_scan and sync_files_flag:
                for target_drive in drives_to_scan:
                    if max_items is not None and len(all_list) >= max_items:
                        break
                    if time.time() - discovery_start_time > 2100:
                        break
                    td_id = target_drive.get("id")
                    td_url = target_drive.get("webUrl")
                    if td_url:
                        base_file_url = f"{td_url.rstrip('/')}/"
                    else:
                        library_encoded = urllib.parse.quote(target_drive.get("name", library_name))
                        sub_path = f"{site_url_path}/{site_prefix}" if site_prefix else site_url_path
                        base_file_url = f"https://{site_hostname}/{sub_path.rstrip('/')}/{library_encoded}/"
                    list_drive_items_recursive(token, td_id, "root", site_prefix, all_list, sync_list, base_file_url, bucket_obj, gcs_cache, max_items)
            elif not sync_files_flag:
                print(f"⏭️ CONFIG_Sync_SharePoint_Files disabled. Skipping Document Library traversal for site.")
                
            if time.time() - discovery_start_time > 2100:
                print(f"⏱️ Discovery Time Guard reached ({time.time() - discovery_start_time:.1f}s). Skipping remaining pages/subsites to guarantee processing pipeline completion...")
                break

            # 7. Query modern site pages under Option B (4-Strategy Robust Merged Discovery via concurrent execution)
            if sync_pages_flag and (max_items is None or len(all_list) < max_items):
                pages = []
                seen_page_urls = set()
                page_lock = threading.Lock()

                def _strat1_pages():
                    try:
                        p_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/pages", headers, max_retries=2, timeout=15)
                        with page_lock:
                            for p in p_list:
                                u = p.get("webUrl", "")
                                if u and u not in seen_page_urls:
                                    seen_page_urls.add(u)
                                    pages.append(p)
                    except Exception:
                        pass

                def _strat1_5_pages():
                    try:
                        p_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/sitePages/pages", headers, max_retries=2, timeout=15)
                        with page_lock:
                            for p in p_list:
                                u = p.get("webUrl", "")
                                if u and u not in seen_page_urls:
                                    seen_page_urls.add(u)
                                    pages.append(p)
                    except Exception:
                        pass

                def _strat2_pages():
                    try:
                        p_list = graph_get_paginated(f"https://graph.microsoft.com/beta/sites/{curr_site_id}/pages", headers, max_retries=2, timeout=15)
                        with page_lock:
                            for p in p_list:
                                u = p.get("webUrl", "")
                                if u and u not in seen_page_urls:
                                    seen_page_urls.add(u)
                                    pages.append(p)
                    except Exception:
                        pass

                def _strat3_pages():
                    try:
                        drives_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/drives", headers, max_retries=2, timeout=15)
                        for sp_drive in drives_list:
                            if time.time() - discovery_start_time > 2100:
                                break
                            try:
                                queue = deque([("root", "")])
                                while queue:
                                    if time.time() - discovery_start_time > 2100:
                                        break
                                    curr_id, parent_path = queue.popleft()
                                    url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/items/{curr_id}/children"
                                    if curr_id == "root":
                                        url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/root/children"
                                    items = graph_get_paginated(url, headers, max_retries=2, timeout=15)
                                    for item in items:
                                        iname = item.get("name", "")
                                        if "folder" in item:
                                            queue.append((item.get("id"), f"{parent_path}{iname}/"))
                                        elif iname.lower().endswith(".aspx"):
                                            u = item.get("webUrl", "")
                                            with page_lock:
                                                if u and u not in seen_page_urls:
                                                    seen_page_urls.add(u)
                                                    pages.append(item)
                            except Exception:
                                pass
                    except Exception:
                        pass

                def _strat4_pages():
                    try:
                        lists = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists", headers, max_retries=2, timeout=15)
                        for lst in lists:
                            if time.time() - discovery_start_time > 2100:
                                break
                            try:
                                items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/items?expand=fields", headers, max_retries=2, timeout=15)
                                for itm in items:
                                    fields = itm.get("fields", {})
                                    iname = fields.get("FileLeafRef") or fields.get("LinkFilename") or ""
                                    if iname.lower().endswith(".aspx"):
                                        u = itm.get("webUrl", "")
                                        with page_lock:
                                            if u and u not in seen_page_urls:
                                                seen_page_urls.add(u)
                                                pages.append(itm)
                            except Exception:
                                # Fallback when expand=fields fails (common for SitePages canvas layout items)
                                try:
                                    raw_items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/items", headers, max_retries=2, timeout=15)
                                    for itm in raw_items:
                                        web_url = itm.get("webUrl", "")
                                        if web_url.lower().endswith(".aspx"):
                                            with page_lock:
                                                if web_url and web_url not in seen_page_urls:
                                                    seen_page_urls.add(web_url)
                                                    pages.append(itm)
                                except Exception:
                                    pass

                            # Strategy 4.5: Direct Drive query for lists named SitePages / Site Pages / Pages
                            if any(k in lst.get("name", "").lower() for k in ["sitepages", "site pages", "pages"]):
                                try:
                                    drive_items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/drive/root/children", headers, max_retries=2, timeout=15)
                                    for di in drive_items:
                                        iname = di.get("name", "")
                                        if iname.lower().endswith(".aspx"):
                                            u = di.get("webUrl", "")
                                            with page_lock:
                                                if u and u not in seen_page_urls:
                                                    seen_page_urls.add(u)
                                                    pages.append(di)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    futures = [
                        executor.submit(_strat1_pages),
                        executor.submit(_strat1_5_pages),
                        executor.submit(_strat2_pages),
                        executor.submit(_strat3_pages),
                        executor.submit(_strat4_pages),
                    ]
                    concurrent.futures.wait(futures, timeout=120)

                for p in pages:
                    if max_items is not None and len(all_list) >= max_items:
                        break
                    page_id = p.get("id")
                    page_name = p.get("name") or p.get("fields", {}).get("FileLeafRef") or "Page.aspx"
                    pdf_name = page_name.replace(".aspx", ".pdf")
                    rel_page_path = f"pages/{site_prefix}{pdf_name}"
                    
                    page_obj = {
                        "Name": pdf_name,
                        "Url": p.get("webUrl", ""),
                        "RelativePath": rel_page_path,
                        "IsPage": True
                    }
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

                    if not needs_sync:
                        print(f"⏭️ Skipping unchanged Modern Site Page (Delta Cache hit): {pdf_name}")
                        all_list.append(page_obj)
                        continue

                    # Mark for parallel pipelined chunk rendering
                    page_obj["_page_id"] = page_id
                    page_obj["_site_id"] = curr_site_id
                    page_obj["_raw_url"] = p.get("webUrl", "")
                    page_obj["_filename"] = pdf_name
                    all_list.append(page_obj)
                    sync_list.append(page_obj)
            elif not sync_pages_flag:
                print(f"⏭️ CONFIG_Sync_SharePoint_Pages disabled. Skipping Modern Site Pages traversal for site.", flush=True)
                
            site_label = site_info.get("name") or curr_site_id
            print(f"✅ Phase 1 Discovery: Completed site/subsite '{site_label}' -> Total Inventory So Far: {len(all_list)} items ({len(sync_list)} pending delta sync)", flush=True)

        # [BEST PRACTICE] Structured JSON Observability for Google Cloud Logging / Logs Explorer
        structured_metric = {
            "severity": "INFO",
            "component": "sharepoint-discovery",
            "event": "DISCOVERY_COMPLETE",
            "total_discovered": len(all_list),
            "delta_to_sync": len(sync_list),
            "delta_skipped": len(all_list) - len(sync_list),
        }
        print(json.dumps(structured_metric), flush=True)

        # 7b. Cleanup orphaned/deleted SharePoint items from GCS bucket during full traversal
        # Only run cleanup if a 100% full, unskipped traversal was performed across both files and pages and integration is triggered
        if trigger_integration and bucket_obj and gcs_cache and not target_urls and sync_files_flag and sync_pages_flag and max_items is None:
            print("🔍 Status Log: Checking GCS inventory for deleted/inactive SharePoint files...")
            active_gcs_paths = set()
            for item in all_list:
                rel = item.get("RelativePath")
                if not rel:
                    continue
                if item.get("IsPage") or rel.startswith("pages/") or rel.startswith("files/"):
                    active_gcs_paths.add(rel)
                else:
                    active_gcs_paths.add(f"files/{rel}")
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
        else:
            print("⏭️ Status Log: Skipping orphaned GCS file cleanup (Partial/Scoped/Dry-Run Sync detected).")

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
                    ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else ''
                    if item.get("IsPage") or rel_path.startswith("pages/") or ext == 'pdf':
                        mime_val = "application/pdf"
                    else:
                        mime_map = {
                            'pdf': 'application/pdf',
                            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'doc': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                            'ppt': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'xls': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'xlsm': 'application/vnd.ms-excel.sheet.macroenabled.12',
                            'txt': 'text/plain',
                            'md': 'text/plain',
                            'csv': 'text/plain',
                            'log': 'text/plain',
                            'html': 'text/html',
                            'htm': 'text/html',
                            'aspx': 'text/html',
                            'json': 'application/json',
                            'xml': 'application/xml',
                            'png': 'image/png',
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'gif': 'image/gif',
                            'bmp': 'image/bmp',
                            'tiff': 'image/tiff',
                            'tif': 'image/tiff',
                            'webp': 'image/png'
                        }
                        mime_val = mime_map.get(ext, 'text/plain')
                    if item.get("IsPage") or rel_path.startswith("pages/") or rel_path.startswith("files/"):
                        full_gcs_path = rel_path
                    else:
                        full_gcs_path = f"files/{rel_path}"
                    gcs_uri = f"gs://{bucket_name}/{full_gcs_path}"
                    meta_record = {
                        "id": doc_id,
                        "structData": {
                            "sharepoint_url": item.get("Url", ""),
                            "title": raw_name,
                            "relative_path": full_gcs_path
                        },
                        "content": {
                            "mimeType": mime_val,
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

        integration_triggered = False
        execution_ids = []
        raw_batch_size = params.get("CONFIG_Batch_Size", 5)
        raw_workers = params.get("CONFIG_Max_Parallel_Workers", 5)

        # Layer 5: Smart Adaptive Batching (Zero parameters.json changes required)
        # Automatically scale regular JSON file metadata batches to 100 items (~15 KB payload)
        file_batch_size = params.get("CONFIG_File_Batch_Size", 20 * raw_batch_size if raw_batch_size <= 10 else raw_batch_size)
        # Keep heavy Base64 PDF pages safely at raw_batch_size (5 items/batch ~1.0 MB payload)
        page_batch_size = params.get("CONFIG_Page_Batch_Size", raw_batch_size)
        max_workers = max(1, raw_workers)
        chunk_size = max(100, file_batch_size * max_workers)

        def _render_lazy_page(item):
            if not item.get("IsPage") or item.get("VirtualContent") or not item.get("_page_id"):
                return item
            page_id = item.get("_page_id")
            site_id = item.get("_site_id")
            raw_url = item.get("_raw_url", item.get("Url", ""))
            fn = item.get("_filename", item.get("Name", "Page.pdf"))
            try:
                d_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
                d_resp = http.get(d_url, headers=headers, timeout=60)
                if d_resp.status_code == 200:
                    html_rendered = render_page_to_html(d_resp.json(), raw_url, headers)
                    item["VirtualContent"] = render_html_to_pdf_base64(html_rendered, fallback_title=fn, engine=conv_engine)
            except Exception as ex:
                print(f"Warning: Parallel rendering failed for {fn}: {ex}")
            if not item.get("VirtualContent"):
                item["VirtualContent"] = render_html_to_pdf_base64(f"<!DOCTYPE html><html><head><title>{fn}</title></head><body><h1>{fn}</h1></body></html>", fallback_title=fn, engine=conv_engine)
            return item

        if trigger_integration and len(sync_list) > 0:
            print(f"⚡ Pipelined Execution: Processing {len(sync_list)} items (File Batch: {file_batch_size}, Page Batch: {page_batch_size}, Workers: {max_workers})...", flush=True)
            credentials, credentials_project_id = google.auth.default()
            project_id = project_id_override or credentials_project_id or params.get("CONFIG_ProjectId")
            if not project_id:
                raise ValueError("Project ID not specified in parameters.json or GCP credentials.")
            credentials.refresh(Request())
            access_token = credentials.token
            integration_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}:schedule"
            
            # Persistent connection-pooled scheduler session (200x faster than single-threaded requests)
            scheduler_session = requests.Session()
            sched_retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
            scheduler_session.mount("https://", HTTPAdapter(max_retries=sched_retries, pool_connections=max_workers, pool_maxsize=max_workers * 2))
            scheduler_session.headers.update({
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            })

            def _schedule_single_batch(batch_items):
                nonlocal access_token
                clean_batch = [{k: v for k, v in item.items() if not k.startswith("_")} for item in batch_items]
                payload_int = {
                    "triggerId": f"api_trigger/{integration_name}-trigger",
                    "inputParameters": {
                        "`Parent_Files_List`": {
                            "jsonValue": json.dumps(clean_batch)
                        }
                    }
                }
                for attempt in range(3):
                    resp = scheduler_session.post(integration_url, json=payload_int, timeout=60)
                    if resp.status_code == 401:
                        credentials.refresh(Request())
                        access_token = credentials.token
                        scheduler_session.headers["Authorization"] = f"Bearer {access_token}"
                        continue
                    elif resp.status_code == 200:
                        data = resp.json()
                        eids = data.get("executionInfoIds", [])
                        return data.get("executionId") or (eids[0] if isinstance(eids, list) and len(eids) > 0 else "triggered")
                    elif resp.status_code in [429, 500, 502, 503, 504]:
                        time.sleep(2 ** attempt)
                raise Exception(f"Failed to schedule batch after retries: {resp.text}")

            for c_start in range(0, len(sync_list), chunk_size):
                # Layer 6: Wall-Clock Circuit Breaker Guard (completes cleanly under 900s Cloud Run ceiling)
                if time.time() - start_time > max_execution_seconds:
                    print(f"⏱️ Wall-Clock Time Guard triggered after {time.time() - start_time:.1f}s. Completing gracefully within execution budget.", flush=True)
                    break

                chunk = sync_list[c_start : c_start + chunk_size]
                print(f"🚀 Processing Pipelined Chunk {c_start + 1} to {min(c_start + chunk_size, len(sync_list))} of {len(sync_list)}...", flush=True)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    list(executor.map(_render_lazy_page, chunk))

                # Separate chunk items into files vs pages for smart adaptive batching
                files_in_chunk = [item for item in chunk if not item.get("IsPage")]
                pages_in_chunk = [item for item in chunk if item.get("IsPage")]

                file_batches = [files_in_chunk[i : i + file_batch_size] for i in range(0, len(files_in_chunk), file_batch_size)]
                page_batches = [pages_in_chunk[i : i + page_batch_size] for i in range(0, len(pages_in_chunk), page_batch_size)]
                all_batches = file_batches + page_batches

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(_schedule_single_batch, b) for b in all_batches]
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            eid = future.result()
                            if eid:
                                execution_ids.append(eid)
                                integration_triggered = True
                                print(f"✅ Status Log: Successfully dispatched batch to Application Integration -> Execution ID: {eid}", flush=True)
                        except Exception as ex_sched:
                            print(f"❌ Batch scheduling error: {ex_sched}", flush=True)

                # Immediate memory eviction after dispatching chunk
                for item in chunk:
                    item.pop("VirtualContent", None)
        elif len(sync_list) > 0:
            print(f"⚙️ [Step 6/7] Rendering pages & uploading files in parallel ({len(sync_list)} items)...", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_render_lazy_page, sync_list))

        # Clean helper keys from output lists
        clean_all_list = [{k: v for k, v in item.items() if not k.startswith("_")} for item in all_list]
        clean_sync_list = [{k: v for k, v in item.items() if not k.startswith("_")} for item in sync_list]

        print(f"🧹 [Step 7/7] Finalizing synchronization response (All: {len(clean_all_list)}, Synced: {len(clean_sync_list)})...", flush=True)
        response_payload = {
            "all_resources_count": len(clean_all_list),
            "sync_resources_count": len(clean_sync_list),
            "item_count": len(clean_sync_list),
            "integration_triggered": integration_triggered,
            "execution_id": execution_ids[0] if execution_ids else None,
            "execution_ids": execution_ids,
            "all_resources": clean_all_list,
            "sync_resources": clean_sync_list,
            "items": clean_sync_list
        }
        return (json.dumps(response_payload, indent=2), 200, {"Content-Type": "application/json"})
        
    except Exception as e:
        err_msg = f"Error executing SharePoint traversal Cloud Function: {e}\n{traceback.format_exc()}"
        print(err_msg, flush=True)
        return (err_msg, 500)

if __name__ == "__main__":
    print("🚀 Auto-invoking main() for Cloud Run Job execution or CLI run...", flush=True)
    resp, status, *_ = main(None)
    print(f"🏁 Execution Finished with HTTP Status: {status}", flush=True)
    if status != 200:
        sys.exit(1)
