# [REVISION CHECK]: V11 3-Tier Sharded Category Synchronization Pipeline & Master Loop Active
import os
import sys
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

# Add parent/util to sys.path for config_loader
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "util"))

try:
    from util.config_loader import load_sites_sync_config
except ImportError:
    try:
        from config_loader import load_sites_sync_config
    except ImportError:
        def load_sites_sync_config(params=None):
            for p in ["config/sites-sync.json", "sites-sync.json", "../config/sites-sync.json"]:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
            return {"root_portal_site": "sites/DEN", "categories": []}

def combine_metadata_shards(bucket_obj, bucket_name: str):
    """
    Atomically combines all per-category metadata_part.jsonl shards into a single master
    gs://<bucket>/config/metadata.jsonl manifest required by Vertex AI Search (AgentAssist).
    Deduplicates across categories using unique document ID / source_url.
    """
    print(f"🧩 [Aggregator] Aggregating all category metadata shards across gs://{bucket_name}/...")
    try:
        combined_records = {}
        shard_count = 0
        for blob in bucket_obj.list_blobs():
            if blob.name.endswith("metadata_part.jsonl"):
                shard_count += 1
                try:
                    content = blob.download_as_text()
                    for line in content.splitlines():
                        if line.strip():
                            record = json.loads(line.strip())
                            doc_id = record.get("id")
                            if doc_id:
                                combined_records[doc_id] = record
                except Exception as ex_shard:
                    print(f"Warning: Could not parse shard blob {blob.name}: {ex_shard}")

        if combined_records:
            master_lines = [json.dumps(rec) for rec in combined_records.values()]
            master_content = "\n".join(master_lines)
            master_blob = bucket_obj.blob("config/metadata.jsonl")
            master_blob.upload_from_string(master_content, content_type="application/x-ndjson")
            print(f"✅ [Aggregator Success] Combined {shard_count} category shard(s) into {len(combined_records)} unique master records at gs://{bucket_name}/config/metadata.jsonl")
        else:
            print("ℹ️ [Aggregator Notice] No metadata_part.jsonl shards found to aggregate.")
    except Exception as ex_agg:
        print(f"Warning: Failed to aggregate metadata shards: {ex_agg}")

# Cloud Function / Cloud Run Job entrypoint
@functions_framework.http
def main(request):
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

    # Load dynamic category config
    sites_sync = load_sites_sync_config(params)
    categories = sites_sync.get("categories", [])

    # Support optional single-category on-demand overrides via --update-env-vars="TARGET_CATEGORY_ID=..." or payload
    target_category_id = req_data.get("category_id") or req_data.get("target_category_id") or os.environ.get("TARGET_CATEGORY_ID")
    if target_category_id:
        categories_to_sync = [c for c in categories if c.get("category_id") == target_category_id]
        print(f"🎯 Single-Category Override Active: Running strictly for category '{target_category_id}' ({len(categories_to_sync)} matched)", flush=True)
    elif len(categories) > 0:
        categories_to_sync = categories
        print(f"🔄 Option 1 Master Loop Active: Sequentially running {len(categories_to_sync)} categories from sites-sync.json", flush=True)
    else:
        # Legacy fallback if sites-sync.json is empty
        legacy_site = req_data.get("site_name") or params.get("CONFIG_Sharepoint_Sites", "sites/DEN")
        legacy_lib = req_data.get("library_name") or params.get("CONFIG_Sharepoint_Library", "all")
        categories_to_sync = [{
            "category_id": "default-legacy",
            "display_name": f"Legacy Sync ({legacy_site})",
            "sharepoint_site": legacy_site,
            "include_subsites": True,
            "sharepoint_library": legacy_lib,
            "gcs_destination_prefix": ""
        }]
        print(f"⚠️ No categories found in sites-sync.json. Using legacy fallback: {legacy_site}", flush=True)

    # Optional integration automatic trigger parameters
    integration_name = req_data.get("integration_name") or params.get("CONFIG_Parent_Integration_Name")
    raw_trigger = req_data.get("trigger_integration")
    if raw_trigger is not None:
        trigger_integration = str(raw_trigger).lower() == "true"
    else:
        trigger_integration = bool(integration_name)
    location = req_data.get("location") or params.get("CONFIG_Location", "asia-southeast1")
    project_id_override = req_data.get("project_id") or params.get("CONFIG_ProjectId")

    # Incremental sync bucket client init
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
            for b in storage_client.list_blobs(bucket_name):
                if b.updated and not b.name.startswith("config/") and not b.name.startswith("status/"):
                    gcs_cache[b.name] = b.updated
            print(f"✅ Cached {len(gcs_cache)} GCS blob timestamps across all prefixes in memory.")
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
        print("="*70, flush=True)
        print("🚀 [Step 1/7] Initializing M365 Authentication & Pipeline Discovery...", flush=True)
        print("="*70, flush=True)

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

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        total_global_all = 0
        total_global_sync = 0
        all_execution_ids = []
        global_integration_triggered = False

        # ==============================================================================
        # OPTION 1 MASTER SERIAL CATEGORY LOOP
        # ==============================================================================
        for cat_idx, category in enumerate(categories_to_sync, 1):
            cat_id = category.get("category_id", f"category-{cat_idx}")
            disp_name = category.get("display_name", cat_id)
            sharepoint_site_input = category.get("sharepoint_site", "sites/DEN")
            include_subsites = category.get("include_subsites", True)
            library_name = category.get("sharepoint_library", "all")
            gcs_prefix = category.get("gcs_destination_prefix", "").rstrip("/")
            if gcs_prefix and not gcs_prefix.endswith("/"):
                gcs_prefix += "/"

            site_list = sharepoint_site_input if isinstance(sharepoint_site_input, list) else [sharepoint_site_input]
            print("\n" + "="*75, flush=True)
            print(f"📂 [Category {cat_idx}/{len(categories_to_sync)}] {disp_name} (ID: {cat_id})", flush=True)
            print(f"   • Target Sites     : {site_list}")
            print(f"   • Include Subsites : {include_subsites}")
            print(f"   • Target Library   : {library_name}")
            print(f"   • GCS Prefix Shard : {gcs_prefix or '(root)'}")
            print("="*75, flush=True)

            target_sites = []
            for s_path in site_list:
                site_name_clean = s_path[len("sites/"):] if s_path.startswith("sites/") else s_path
                resolve_site_url = f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:/sites/{site_name_clean}"
                try:
                    site_resp = http.get(resolve_site_url, headers=headers, timeout=30)
                    if site_resp.status_code == 200:
                        r_id = site_resp.json().get("id")
                        target_sites.append({"id": r_id, "name": site_name_clean, "prefix": ""})
                        if include_subsites:
                            print(f"   🔎 Scoping child subsites under '{site_name_clean}'...", flush=True)
                            target_sites.extend(get_all_subsites_recursive(r_id, headers, ""))
                        else:
                            print(f"   🛡️ Duplicate Crawl Prevention Active: Subsite recursion disabled for '{site_name_clean}'.", flush=True)
                except Exception as ex_resolve:
                    print(f"Warning: Could not resolve site '{s_path}': {ex_resolve}", flush=True)

            all_list = []
            sync_list = []

            def parse_bool_flag(val, default=True):
                if val is None: return default
                if isinstance(val, bool): return val
                return str(val).strip().lower() in ["true", "yes", "1", "y"]

            sync_files_flag = parse_bool_flag(req_data.get("sync_files", params.get("CONFIG_Sync_SharePoint_Files", True)))
            sync_pages_flag = parse_bool_flag(req_data.get("sync_pages", params.get("CONFIG_Sync_SharePoint_Pages", True)))

            target_urls = req_data.get("target_urls", [])
            check_gcs_config = req_data.get("check_gcs_config", False) or req_data.get("use_gcs_config", False)
            if not target_urls and bucket_obj and check_gcs_config:
                try:
                    cfg_blob = bucket_obj.get_blob("config/target_urls.txt")
                    if cfg_blob:
                        raw_cfg = cfg_blob.download_as_text()
                        target_urls = [l.strip() for l in raw_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
                except Exception:
                    pass

            discovery_start_time = time.time()
            for site_info in target_sites:
                if time.time() - discovery_start_time > 2100 or time.time() - start_time > max_execution_seconds:
                    print(f"⏱️ Wall-Clock Time Guard reached. Finalizing discovered category inventory ({len(sync_list)} delta items)...", flush=True)
                    break

                curr_site_id = site_info["id"]
                site_prefix = site_info["prefix"] # e.g. "Consumer/" or "Business/"
                site_label = site_info.get("name") or curr_site_id
                print(f"   📡 Scanning site/subsite '{site_label}' (Subsite Prefix: '{site_prefix}')...", flush=True)
                
                # Traverse Document Libraries (Drives) in the site
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

                max_items = req_data.get("max_items")
                if drives_to_scan and sync_files_flag:
                    for target_drive in drives_to_scan:
                        if max_items is not None and len(all_list) >= max_items: break
                        if time.time() - discovery_start_time > 2100: break
                        td_id = target_drive.get("id")
                        td_url = target_drive.get("webUrl")
                        base_file_url = f"{td_url.rstrip('/')}/" if td_url else f"https://{site_hostname}/sites/{site_info['name']}/{target_drive.get('name', 'Documents')}/"
                        # Pass combined prefix (gcs_prefix + site_prefix) to list_drive_items_recursive
                        combined_prefix = f"{gcs_prefix}{site_prefix}" if gcs_prefix else site_prefix
                        list_drive_items_recursive(token, td_id, "root", combined_prefix, all_list, sync_list, base_file_url, bucket_obj, gcs_cache, max_items)

                if time.time() - discovery_start_time > 2100: break

                # Query modern site pages (4-Strategy Robust Discovery)
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
                        except Exception: pass

                    def _strat1_5_pages():
                        try:
                            p_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/sitePages/pages", headers, max_retries=2, timeout=15)
                            with page_lock:
                                for p in p_list:
                                    u = p.get("webUrl", "")
                                    if u and u not in seen_page_urls:
                                        seen_page_urls.add(u)
                                        pages.append(p)
                        except Exception: pass

                    def _strat2_pages():
                        try:
                            p_list = graph_get_paginated(f"https://graph.microsoft.com/beta/sites/{curr_site_id}/pages", headers, max_retries=2, timeout=15)
                            with page_lock:
                                for p in p_list:
                                    u = p.get("webUrl", "")
                                    if u and u not in seen_page_urls:
                                        seen_page_urls.add(u)
                                        pages.append(p)
                        except Exception: pass

                    def _strat3_pages():
                        try:
                            drives_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/drives", headers, max_retries=2, timeout=15)
                            for sp_drive in drives_list:
                                if time.time() - discovery_start_time > 2100: break
                                try:
                                    queue = deque([("root", "")])
                                    while queue:
                                        if time.time() - discovery_start_time > 2100: break
                                        c_id, p_path = queue.popleft()
                                        url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/items/{c_id}/children"
                                        if c_id == "root": url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/root/children"
                                        items = graph_get_paginated(url, headers, max_retries=2, timeout=15)
                                        for item in items:
                                            iname = item.get("name", "")
                                            if "folder" in item:
                                                queue.append((item.get("id"), f"{p_path}{iname}/"))
                                            elif iname.lower().endswith(".aspx"):
                                                u = item.get("webUrl", "")
                                                with page_lock:
                                                    if u and u not in seen_page_urls:
                                                        seen_page_urls.add(u)
                                                        pages.append(item)
                                except Exception: pass
                        except Exception: pass

                    def _strat4_pages():
                        try:
                            lists = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists", headers, max_retries=2, timeout=15)
                            for lst in lists:
                                if time.time() - discovery_start_time > 2100: break
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
                                    try:
                                        raw_items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/items", headers, max_retries=2, timeout=15)
                                        for itm in raw_items:
                                            web_url = itm.get("webUrl", "")
                                            if web_url.lower().endswith(".aspx"):
                                                with page_lock:
                                                    if web_url and web_url not in seen_page_urls:
                                                        seen_page_urls.add(web_url)
                                                        pages.append(itm)
                                    except Exception: pass

                                if any(k in lst.get("name", "").lower() for k in ["sitepages", "site pages", "pages"]):
                                    try:
                                        di_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/drive/root/children", headers, max_retries=2, timeout=15)
                                        for di in di_list:
                                            iname = di.get("name", "")
                                            if iname.lower().endswith(".aspx"):
                                                u = di.get("webUrl", "")
                                                with page_lock:
                                                    if u and u not in seen_page_urls:
                                                        seen_page_urls.add(u)
                                                        pages.append(di)
                                    except Exception: pass
                        except Exception: pass

                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [executor.submit(_strat1_pages), executor.submit(_strat1_5_pages), executor.submit(_strat2_pages), executor.submit(_strat3_pages), executor.submit(_strat4_pages)]
                        concurrent.futures.wait(futures, timeout=120)

                    for p in pages:
                        if max_items is not None and len(all_list) >= max_items: break
                        page_id = p.get("id")
                        page_name = p.get("name") or p.get("fields", {}).get("FileLeafRef") or "Page.aspx"
                        pdf_name = page_name.replace(".aspx", ".pdf")
                        rel_page_path = f"{gcs_prefix}pages/{site_prefix}{pdf_name}" if gcs_prefix else f"pages/{site_prefix}{pdf_name}"
                        rel_page_path = rel_page_path.replace("//", "/")
                        
                        page_obj = {
                            "Name": pdf_name,
                            "Url": p.get("webUrl", ""),
                            "RelativePath": rel_page_path,
                            "IsPage": True
                        }
                        needs_sync = True
                        if rel_page_path in gcs_cache:
                            p_mod = p.get("lastModifiedDateTime")
                            if p_mod:
                                try:
                                    sp_dt_p = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                    if gcs_cache[rel_page_path] >= sp_dt_p:
                                        needs_sync = False
                                except Exception: pass
                        elif bucket_obj and not gcs_cache:
                            try:
                                blob_p = bucket_obj.get_blob(rel_page_path)
                                p_mod = p.get("lastModifiedDateTime")
                                if blob_p and blob_p.updated and p_mod:
                                    sp_dt_p = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                    if blob_p.updated >= sp_dt_p:
                                        needs_sync = False
                            except Exception: pass

                        if not needs_sync:
                            all_list.append(page_obj)
                            continue

                        page_obj["_page_id"] = page_id
                        page_obj["_site_id"] = curr_site_id
                        page_obj["_raw_url"] = p.get("webUrl", "")
                        page_obj["_filename"] = pdf_name
                        all_list.append(page_obj)
                        sync_list.append(page_obj)

                print(f"   ✅ Discovered '{site_label}' -> Category Subtotal: {len(all_list)} items ({len(sync_list)} pending delta sync)", flush=True)

            structured_metric = {
                "severity": "INFO",
                "component": "sharepoint-category-discovery",
                "category_id": cat_id,
                "event": "CATEGORY_DISCOVERY_COMPLETE",
                "total_discovered": len(all_list),
                "delta_to_sync": len(sync_list),
                "delta_skipped": len(all_list) - len(sync_list),
            }
            print(json.dumps(structured_metric), flush=True)

            # Sharded Metadata Output for Vertex AI / CCAI indexing
            if bucket_obj and len(all_list) > 0:
                try:
                    jsonl_lines = []
                    for item in all_list:
                        raw_name = item.get("Name", "doc")
                        rel_path = item.get("RelativePath", "")
                        base_name = raw_name.rsplit('.', 1)[0]
                        doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
                        ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else ''
                        mime_val = "application/pdf" if (item.get("IsPage") or rel_path.startswith("pages/") or ext == 'pdf') else "application/octet-stream"
                        full_gcs_path = rel_path if (item.get("IsPage") or "pages/" in rel_path or "files/" in rel_path) else f"files/{rel_path}"
                        full_gcs_path = full_gcs_path.replace("//", "/")
                        gcs_uri = f"gs://{bucket_name}/{full_gcs_path}"
                        meta_record = {
                            "id": doc_id,
                            "structData": {
                                "sharepoint_url": item.get("Url", ""),
                                "title": raw_name,
                                "category_id": cat_id,
                                "category_name": disp_name,
                                "relative_path": full_gcs_path
                            },
                            "content": {
                                "mimeType": mime_val,
                                "uri": gcs_uri
                            }
                        }
                        jsonl_lines.append(json.dumps(meta_record))
                    
                    shard_content = "\n".join(jsonl_lines)
                    shard_path = f"{gcs_prefix}config/metadata_part.jsonl" if gcs_prefix else "config/metadata_part.jsonl"
                    shard_blob = bucket_obj.blob(shard_path)
                    shard_blob.upload_from_string(shard_content, content_type="application/x-ndjson")
                    print(f"   📄 Sharded metadata manifest uploaded: gs://{bucket_name}/{shard_path} ({len(jsonl_lines)} records)", flush=True)
                except Exception as ex_meta:
                    print(f"Warning: Failed to generate/upload sharded metadata for {cat_id}: {ex_meta}", flush=True)

            # Processing & Pipelined Execution for Category
            raw_batch_size = params.get("CONFIG_Batch_Size", 5)
            raw_workers = params.get("CONFIG_Max_Parallel_Workers", 5)
            file_batch_size = params.get("CONFIG_File_Batch_Size", 20 * raw_batch_size if raw_batch_size <= 10 else raw_batch_size)
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
                print(f"   ⚡ Pipelined Execution: Processing {len(sync_list)} items for {cat_id}...", flush=True)
                credentials, credentials_project_id = google.auth.default()
                project_id = project_id_override or credentials_project_id or params.get("CONFIG_ProjectId")
                if not project_id:
                    raise ValueError("Project ID not specified in parameters.json or GCP credentials.")
                credentials.refresh(Request())
                access_token = credentials.token
                integration_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}:schedule"
                
                scheduler_session = requests.Session()
                sched_retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
                scheduler_session.mount("https://", HTTPAdapter(max_retries=sched_retries, pool_connections=max_workers, pool_maxsize=max_workers * 2))
                scheduler_session.headers.update({"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})

                def _schedule_single_batch(batch_items):
                    nonlocal access_token
                    clean_batch = [{k: v for k, v in item.items() if not k.startswith("_")} for item in batch_items]
                    payload_int = {
                        "triggerId": f"api_trigger/{integration_name}-trigger",
                        "inputParameters": {
                            "`Parent_Files_List`": {"jsonValue": json.dumps(clean_batch)}
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
                    if time.time() - start_time > max_execution_seconds: break
                    chunk = sync_list[c_start : c_start + chunk_size]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        list(executor.map(_render_lazy_page, chunk))

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
                                    all_execution_ids.append(eid)
                                    global_integration_triggered = True
                            except Exception as ex_sched:
                                print(f"❌ Batch scheduling error: {ex_sched}", flush=True)

                    for item in chunk: item.pop("VirtualContent", None)
            elif len(sync_list) > 0:
                print(f"   ⚙️ Rendering pages in parallel without parent trigger ({len(sync_list)} items)...", flush=True)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    list(executor.map(_render_lazy_page, sync_list))

            total_global_all += len(all_list)
            total_global_sync += len(sync_list)
            print(f"   🏁 Category '{disp_name}' completed. Wiping RAM buffer...", flush=True)
            all_list.clear()
            sync_list.clear()
            target_sites.clear()

        # ==============================================================================
        # MASTER AGGREGATOR AT JOB COMPLETION
        # ==============================================================================
        if bucket_obj and len(categories_to_sync) > 0:
            combine_metadata_shards(bucket_obj, bucket_name)

        print(f"\n🧹 [Step 7/7] Finalizing V11 pipeline execution (Total All: {total_global_all}, Total Synced: {total_global_sync})...", flush=True)
        response_payload = {
            "all_resources_count": total_global_all,
            "sync_resources_count": total_global_sync,
            "item_count": total_global_sync,
            "integration_triggered": global_integration_triggered,
            "execution_id": all_execution_ids[0] if all_execution_ids else None,
            "execution_ids": all_execution_ids,
            "categories_processed": len(categories_to_sync)
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
