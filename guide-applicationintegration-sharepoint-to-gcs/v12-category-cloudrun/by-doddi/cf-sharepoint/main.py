# [REVISION CHECK]: 3-Strategy Site Pages Discovery Engine Active (v1.0 + beta + SitePages Drive)
import os
import json
import urllib.parse
import datetime
import re
import time
import gc
import concurrent.futures
import functions_framework
from google.cloud import storage

from graph_client import get_secret, get_graph_token, graph_get_paginated, http
from pdf_renderer import render_html_to_pdf_base64
from sharepoint_traversal import get_all_subsites_recursive, list_drive_items_recursive, render_page_to_html
from config_schema import validate_parameters
from util.config_loader import load_sites_sync_config, is_category_active

def combine_metadata_shards(bucket_name):
    print(f"⚡ Master Metadata Aggregator: Combining all category shards into root config/metadata.jsonl...")
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix="categories/"))
    
    master_catalog = {}
    for blob in blobs:
        if blob.name.endswith("metadata_part.jsonl"):
            try:
                content = blob.download_as_text()
                for line in content.strip().splitlines():
                    if not line.strip(): continue
                    try:
                        entry = json.loads(line)
                        entry_id = entry.get("id") or entry.get("structData", {}).get("source_url")
                        if entry_id:
                            master_catalog[entry_id] = line
                    except Exception:
                        pass
            except Exception as ex_shard:
                print(f"Warning: Failed to read shard {blob.name}: {ex_shard}")
                    
    master_blob = bucket.blob("config/metadata.jsonl")
    master_blob.upload_from_string("\n".join(master_catalog.values()) + "\n", content_type="application/jsonl")
    print(f"✅ Master Catalog Updated! Total unified records for Vertex AI Search: {len(master_catalog)}")

# Cloud Function entrypoint
@functions_framework.http
def main(request):
    start_time = time.time()
    max_execution_seconds = 86000  # Cloud Run Job has 24h budget; limit loop iteration safety
    
    # 1. Parse JSON payload or query parameters
    req_data = request.get_json(silent=True) or {}
    
    # Load config-parameters.json if it exists in local context
    params = {}
    if os.path.exists("config-parameters.json"):
        try:
            with open("config-parameters.json", "r") as f:
                params = json.load(f)
            params = validate_parameters(params)
        except Exception as e:
            print(f"Warning: Failed to load or validate config-parameters.json: {e}")

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
    
    storage_client = None
    bucket_obj = None
    if bucket_name:
        try:
            storage_client = storage.Client()
            bucket_obj = storage_client.bucket(bucket_name)
        except Exception as e:
            print(f"Warning: Could not init GCS bucket client: {e}")

    # M365 Tenant Details
    tenant_id = req_data.get("tenant_id") or params.get("CONFIG_M365_Tenant_Id")
    client_id = req_data.get("client_id") or params.get("CONFIG_M365_Client_Id")
    secret_name = req_data.get("secret_name") or params.get("CONFIG_M365_Secret_Name")
    site_hostname = req_data.get("site_hostname") or params.get("CONFIG_SharePoint_Hostname")

    if not all([tenant_id, client_id, secret_name, site_hostname]):
        raise ValueError("Missing required M365 configuration parameters in config-parameters.json or request payload.")

    try:
        # 2. Fetch Azure AD Client Secret dynamically via GCP Secret Manager
        client_secret = get_secret(secret_name)
        
        # 3. Authenticate with Microsoft Entra ID
        token = get_graph_token(tenant_id, client_id, client_secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 4. Determine which categories to sync
        target_override = os.environ.get("TARGET_CATEGORY_ID") or req_data.get("category_id")
        
        # If user explicitly requests a backward-compatible single site sync via request site_name parameter
        if req_data.get("site_name"):
            print(f"🎯 Backward compatibility override: Syncing single site '{site_name}'")
            categories_to_sync = [{
                "category_id": "on-demand-site",
                "display_name": f"On-Demand Sync for {site_name}",
                "sharepoint_site": f"sites/{site_name}",
                "include_subsites": True,
                "sharepoint_library": library_name,
                "gcs_destination_prefix": "" # Syncs directly to files/ and pages/
            }]
            is_master_loop = False
        else:
            sites_sync_config = load_sites_sync_config(params)
            all_categories = sites_sync_config.get("categories", [])
            if target_override:
                categories_to_sync = [c for c in all_categories if c.get("category_id") == target_override]
                print(f"🎯 On-Demand Single Category Override Active: Running ONLY '{target_override}'")
                is_master_loop = False
            else:
                # Filter active categories only for the master loop
                categories_to_sync = [c for c in all_categories if is_category_active(c)]
                print(f"🔄 Option 1 Master Loop Active: Iterating through {len(categories_to_sync)} active category groups sequentially.")
                is_master_loop = True

        all_execution_ids = []
        total_sync_resources = 0
        total_all_resources = 0

        # Loop through categories
        for cat_idx, category in enumerate(categories_to_sync, 1):
            category_id = category.get("category_id", f"category-{cat_idx}")
            category_name = category.get("display_name", f"Category {cat_idx}")
            category_prefix = category.get("gcs_destination_prefix", "").strip()
            
            print(f"\n================================================================================")
            print(f"⚡ [{cat_idx}/{len(categories_to_sync)}] Starting sync for category '{category_id}' ({category_name})")
            print(f"📂 Destination Prefix: {category_prefix or '(Root)'}")
            print(f"================================================================================")

            # Pre-fetch GCS cache scoped to this category
            gcs_cache = {}
            if bucket_obj and not force_full_sync:
                try:
                    print(f"🔍 Pre-fetching GCS blobs metadata under prefix '{category_prefix}' for O(1) incremental comparison...")
                    files_prefix = f"{category_prefix}files/" if category_prefix else "files/"
                    for b in storage_client.list_blobs(bucket_name, prefix=files_prefix):
                        if b.updated:
                            gcs_cache[b.name] = b.updated
                    pages_prefix = f"{category_prefix}pages/" if category_prefix else "pages/"
                    for b in storage_client.list_blobs(bucket_name, prefix=pages_prefix):
                        if b.updated:
                            gcs_cache[b.name] = b.updated
                    print(f"✅ Cached {len(gcs_cache)} GCS blob timestamps in memory.")
                except Exception as e:
                    print(f"Warning: Could not pre-fetch cache: {e}")

            # Resolve site list for category
            site_target = category.get("sharepoint_site")
            if isinstance(site_target, list):
                site_list = site_target
            else:
                site_list = [site_target] if site_target else []

            include_subsites = category.get("include_subsites", True)
            target_sites = []
            
            for s_path in site_list:
                s_clean = s_path.strip("/")
                if s_clean.startswith("sites/"):
                    cat_site_name = s_clean[len("sites/"):]
                else:
                    cat_site_name = s_clean
                
                resolve_site_url = f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:/sites/{cat_site_name}"
                site_resp = http.get(resolve_site_url, headers=headers, timeout=60)
                if site_resp.status_code != 200:
                    print(f"Warning: Failed to resolve SharePoint Site '{s_path}': {site_resp.text}")
                    continue
                
                cat_site_id = site_resp.json().get("id")
                target_sites.append({"id": cat_site_id, "name": cat_site_name, "prefix": ""})
                
                if include_subsites:
                    print(f"🔍 Scoping child subsites recursively under '{s_path}'...")
                    target_sites.extend(get_all_subsites_recursive(cat_site_id, headers, ""))
            
            print(f"✅ Enumerable sites resolved for category (Total: {len(target_sites)}).")

            all_list = []
            sync_list = []
            
            def parse_bool_flag(val, default=True):
                if val is None: return default
                if isinstance(val, bool): return val
                return str(val).strip().lower() in ["true", "yes", "1", "y"]

            sync_files_flag = parse_bool_flag(req_data.get("sync_files", params.get("CONFIG_Sync_SharePoint_Files", True)))
            sync_pages_flag = parse_bool_flag(req_data.get("sync_pages", params.get("CONFIG_Sync_SharePoint_Pages", True)))
            orphan_cleanup_flag = parse_bool_flag(req_data.get("orphan_cleanup", params.get("CONFIG_Enable_Orphan_Cleanup", False)), default=False)
            print(f"⚙️ Sync Scope Settings -> Files: {sync_files_flag} | Pages: {sync_pages_flag} | Orphan Cleanup: {orphan_cleanup_flag}")

            target_urls = req_data.get("target_urls", [])
            
            # Dynamic GCS Config Read (if target_urls are omitted)
            check_gcs_config = req_data.get("check_gcs_config", False) or req_data.get("use_gcs_config", False)
            if not target_urls and bucket_obj and check_gcs_config:
                try:
                    cfg_blob = bucket_obj.get_blob("config/target_urls.txt")
                    if cfg_blob:
                        raw_cfg = cfg_blob.download_as_text()
                        target_urls = [l.strip() for l in raw_cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
                        print(f"📂 Loaded {len(target_urls)} dynamic target URL(s) live from GCS gs://{bucket_name}/config/target_urls.txt")
                except Exception as e:
                    print(f"Warning: Could not read dynamic GCS config: {e}")

            if target_urls:
                print(f"🎯 Bypassing Graph folder traversal: Scoping directly to {len(target_urls)} targeted URL(s)...")
                # Targeted URL Sync logic with category prefix
                pages_dict = {}
                for ts in target_sites:
                    try:
                        p_url = f"https://graph.microsoft.com/v1.0/sites/{ts['id']}/pages"
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
                    
                    rel_path = f"{category_prefix}pages/{filename}" if is_page else f"{category_prefix}files/{filename}"
                    if "/sites/" in url_path:
                        parts = [p for p in url_path.split("/") if p and p.lower() not in ["sites", "sitepages", "shared documents", "documents"]]
                        if len(parts) > 1:
                            sub_folder = "/".join(parts[1:-1])
                            if sub_folder:
                                rel_path = f"{category_prefix}pages/{sub_folder}/{filename}" if is_page else f"{category_prefix}files/{sub_folder}/{filename}"

                    item_obj = {
                        "Name": filename,
                        "Url": raw_url,
                        "RelativePath": rel_path,
                        "IsPage": is_page
                    }
                    
                    if is_page and not sync_pages_flag:
                        continue
                    if not is_page and not sync_files_flag:
                        continue

                    if is_page:
                        aspx_name = os.path.basename(url_path).lower()
                        page_info = pages_dict.get(aspx_name)
                        
                        if not page_info and pages_dict:
                            print(f"🗑️ Status Log: Inactive target page detected ({aspx_name}). Checking GCS bucket for deletion...")
                            if bucket_obj:
                                try:
                                    stale_blob = bucket_obj.get_blob(rel_path)
                                    if stale_blob:
                                        stale_blob.delete()
                                        print(f"✅ Successfully deleted inactive file from GCS: gs://{bucket_name}/{rel_path}")
                                except Exception as ex_del:
                                    print(f"Warning: Failed to delete inactive GCS file {rel_path}: {ex_del}")
                            continue
                        
                        needs_sync = True
                        if gcs_cache and rel_path in gcs_cache:
                            p_mod = page_info.get("lastModifiedDateTime")
                            if p_mod:
                                try:
                                    sp_dt = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                    if gcs_cache[rel_path] >= sp_dt:
                                        needs_sync = False
                                except Exception:
                                    pass
                        if not needs_sync:
                            all_list.append(item_obj)
                            continue
                        item_obj["_page_id"] = page_info.get("id")
                        for ts in target_sites:
                            item_obj["_site_id"] = ts["id"]
                            break
                        item_obj["_raw_url"] = raw_url
                        item_obj["_filename"] = filename
                        all_list.append(item_obj)
                        sync_list.append(item_obj)
                    else:
                        needs_sync = True
                        if gcs_cache and rel_path in gcs_cache:
                            needs_sync = False
                        if needs_sync:
                            sync_list.append(item_obj)
                        all_list.append(item_obj)

            else:
                # Full category traversal
                seen_page_urls = set()
                max_items = params.get("CONFIG_Max_Items")
                
                for site_idx, site in enumerate(target_sites, 1):
                    curr_site_id = site["id"]
                    curr_site_name = site["name"]
                    site_prefix = site["prefix"]
                    
                    print(f"⚙️ [{site_idx}/{len(target_sites)}] Crawling subsite: '{curr_site_name}'...")
                    
                    # Traversal Part A: Files Sync
                    if sync_files_flag:
                        try:
                            drives_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/drives"
                            drives = graph_get_paginated(drives_url, headers)
                            for d in drives:
                                d_name = d.get("name", "").lower()
                                d_type = d.get("driveType", "").lower()
                                if d_name in ["site assets", "style library", "teams wiki data"] or d_type == "personal":
                                    continue
                                print(f"   📂 Traversing library '{d.get('name')}'...")
                                base_file_url = f"https://graph.microsoft.com/v1.0/drives/{d['id']}/items"
                                list_drive_items_recursive(
                                    token=token,
                                    drive_id=d["id"],
                                    item_id="root",
                                    parent_path=site_prefix,
                                    all_results=all_list,
                                    sync_results=sync_list,
                                    base_file_url=base_file_url,
                                    bucket_obj=bucket_obj,
                                    gcs_cache=gcs_cache,
                                    max_items=max_items,
                                    gcs_prefix=category_prefix
                                )
                        except Exception as ex_files:
                            print(f"Warning: Files traversal failed for site {curr_site_name}: {ex_files}")
                    
                    # Traversal Part B: Pages Sync
                    if sync_pages_flag:
                        try:
                            pages = []
                            lists_url = f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists"
                            lists = graph_get_paginated(lists_url, headers)
                            for lst in lists:
                                l_name = lst.get("name", "").lower()
                                l_display = lst.get("displayName", "").lower()
                                l_tmpl = lst.get("list", {}).get("template", "").lower()
                                if any(k in l_name or k in l_display for k in ["page", "sitepages", "faq", "article", "kb", "wiki"]) or l_tmpl in ["sitepages", "sitepage", "wikipage"]:
                                    items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{curr_site_id}/lists/{lst['id']}/items?expand=fields", headers, max_retries=3, timeout=20)
                                    for itm in items:
                                        fields = itm.get("fields", {})
                                        iname = fields.get("FileLeafRef") or fields.get("LinkFilename") or ""
                                        if iname.lower().endswith(".aspx"):
                                            u = itm.get("webUrl", "")
                                            if u and u not in seen_page_urls:
                                                seen_page_urls.add(u)
                                                pages.append(itm)
                            
                            for p in pages:
                                if max_items is not None and len(all_list) >= max_items:
                                    break
                                page_id = p.get("id")
                                page_name = p.get("name") or p.get("fields", {}).get("FileLeafRef") or "Page.aspx"
                                pdf_name = page_name.replace(".aspx", ".pdf")
                                rel_page_path = f"{category_prefix}pages/{site_prefix}{pdf_name}" if category_prefix else f"pages/{site_prefix}{pdf_name}"
                                
                                page_obj = {
                                    "Name": pdf_name,
                                    "Url": p.get("webUrl", ""),
                                    "RelativePath": rel_page_path,
                                    "IsPage": True
                                }
                                needs_sync = True
                                if gcs_cache and rel_page_path in gcs_cache:
                                    p_mod = p.get("lastModifiedDateTime")
                                    if p_mod:
                                        try:
                                            sp_dt_p = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                            if gcs_cache[rel_page_path] >= sp_dt_p:
                                                needs_sync = False
                                        except Exception:
                                            pass
                                if not needs_sync:
                                    all_list.append(page_obj)
                                    continue
                                page_obj["_page_id"] = page_id
                                page_obj["_site_id"] = curr_site_id
                                page_obj["_raw_url"] = p.get("webUrl", "")
                                page_obj["_filename"] = pdf_name
                                all_list.append(page_obj)
                                sync_list.append(page_obj)
                        except Exception as ex_pages:
                            print(f"Warning: Pages traversal failed for site {curr_site_name}: {ex_pages}")

            structured_metric = {
                "severity": "INFO",
                "component": "sharepoint-discovery",
                "event": "DISCOVERY_COMPLETE",
                "category_id": category_id,
                "total_discovered": len(all_list),
                "delta_to_sync": len(sync_list),
                "delta_skipped": len(all_list) - len(sync_list),
            }
            print(json.dumps(structured_metric))

            # 7b. Scoped Orphan Cleanup for Category
            if trigger_integration and bucket_obj and gcs_cache and not target_urls and sync_files_flag and sync_pages_flag and max_items is None and orphan_cleanup_flag:
                if len(gcs_cache) > 0 and len(all_list) < (len(gcs_cache) * 0.8):
                    print(f"🛡️ SAFETY CIRCUIT BREAKER TRIPPED: Discovered items ({len(all_list)}) dropped below 80% of existing GCS cache ({len(gcs_cache)}). Aborting scoped deletions to prevent data wipe!")
                else:
                    print("🔍 Status Log: Scoped Orphan Cleanup active. Checking category GCS inventory for deleted/inactive SharePoint files...")
                    active_gcs_paths = set(item.get("RelativePath") for item in all_list if item.get("RelativePath"))
                    deleted_count = 0
                    for cached_path in list(gcs_cache.keys()):
                        if cached_path not in active_gcs_paths:
                            try:
                                stale_blob = bucket_obj.get_blob(cached_path)
                                if stale_blob:
                                    stale_blob.delete()
                                    deleted_count += 1
                                    print(f"🗑️ Status Log: Deleted inactive file from GCS: gs://{bucket_name}/{cached_path}")
                            except Exception as ex_del:
                                print(f"Warning: Could not delete orphaned GCS file {cached_path}: {ex_del}")
                    if deleted_count > 0:
                        print(f"✅ Status Log: Cleaned up {deleted_count} inactive/deleted file(s) from category folder in GCS.")
                    else:
                        print("✅ Status Log: No inactive/deleted files found in category folder in GCS.")

            # Phase 4a.1: Generate local metadata_part.jsonl shard
            if trigger_integration and bucket_obj and len(all_list) > 0:
                try:
                    shard_name = f"{category_prefix}config/metadata_part.jsonl" if category_prefix else "config/metadata_part.jsonl"
                    print(f"🧠 Generating local metadata shard: gs://{bucket_name}/{shard_name}...")
                    jsonl_lines = []
                    for item in all_list:
                        raw_name = item.get("Name", "doc")
                        rel_path = item.get("RelativePath", "")
                        base_name = raw_name.rsplit('.', 1)[0]
                        doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
                        ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else ''
                        if item.get("IsPage") or rel_path.startswith("pages/") or "/pages/" in rel_path or ext == 'pdf':
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
                        
                        gcs_uri = f"gs://{bucket_name}/{rel_path}"
                        meta_record = {
                            "id": doc_id,
                            "structData": {
                                "sharepoint_url": item.get("Url", ""),
                                "title": raw_name,
                                "relative_path": rel_path,
                                "category_id": category_id,
                                "category_name": category_name
                            },
                            "content": {
                                "mimeType": mime_val,
                                "uri": gcs_uri
                            }
                        }
                        jsonl_lines.append(json.dumps(meta_record))
                    
                    jsonl_content = "\n".join(jsonl_lines)
                    meta_blob = bucket_obj.blob(shard_name)
                    meta_blob.upload_from_string(jsonl_content, content_type="application/x-ndjson")
                    print(f"✅ Successfully uploaded {len(jsonl_lines)} records to gs://{bucket_name}/{shard_name}")
                except Exception as ex_meta:
                    print(f"Warning: Failed to generate metadata shard: {ex_meta}")

            # 8. Parallel Pipelined Chunk Rendering & Micro-Batch Orchestration
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            integration_triggered = False
            execution_ids = []
            raw_batch_size = params.get("CONFIG_Batch_Size", 5)
            raw_workers = params.get("CONFIG_Max_Parallel_Workers", 5)

            file_batch_size = params.get("CONFIG_File_Batch_Size", 20 * raw_batch_size if raw_batch_size <= 10 else raw_batch_size)
            page_batch_size = params.get("CONFIG_Page_Batch_Size", raw_batch_size)
            max_workers = min(3, max(1, raw_workers))
            chunk_size = min(30, max(20, file_batch_size * max_workers))

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
                import google.auth
                from google.auth.transport.requests import Request
                print(f"⚡ Pipelined Execution: Processing {len(sync_list)} items (File Batch: {file_batch_size}, Page Batch: {page_batch_size}, Workers: {max_workers})...")
                credentials, credentials_project_id = google.auth.default()
                project_id = project_id_override or credentials_project_id or params.get("CONFIG_ProjectId")
                if not project_id:
                    raise ValueError("Project ID not specified in config-parameters.json or GCP credentials.")
                credentials.refresh(Request())
                access_token = credentials.token
                integration_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_name}:schedule"
                
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
                            return resp.json().get("executionId")
                        elif resp.status_code in [429, 500, 502, 503, 504]:
                            time.sleep(2 ** attempt)
                    raise Exception(f"Failed to schedule batch after retries: {resp.text}")

                for c_start in range(0, len(sync_list), chunk_size):
                    # Wall-Clock Circuit Breaker Guard
                    if time.time() - start_time > max_execution_seconds:
                        print(f"⏱️ Wall-Clock Time Guard triggered after {time.time() - start_time:.1f}s. Completing category sync gracefully.")
                        break

                    chunk = sync_list[c_start : c_start + chunk_size]
                    print(f"   🚀 Processing Pipelined Chunk {c_start + 1} to {min(c_start + chunk_size, len(sync_list))}...")
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
                                    execution_ids.append(eid)
                                    integration_triggered = True
                            except Exception as ex_sched:
                                print(f"❌ Batch scheduling error: {ex_sched}")

                    for item in chunk:
                        item.pop("VirtualContent", None)
                    gc.collect()
                    time.sleep(0.3)
            elif len(sync_list) > 0:
                print(f"⚡ Rendering pages in parallel without Integration trigger ({len(sync_list)} items)...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    list(executor.map(_render_lazy_page, sync_list))
                for item in sync_list: item.pop("VirtualContent", None)
                gc.collect()

            # Record category outcomes
            total_sync_resources += len(sync_list)
            total_all_resources += len(all_list)
            all_execution_ids.extend(execution_ids)

            # RAM cleanup after category sync
            del all_list
            del sync_list
            del gcs_cache
            gc.collect()
            print(f"✅ Finished sync for category '{category_id}'!")

        # 5. Master Metadata Consolidation
        if is_master_loop and bucket_name:
            combine_metadata_shards(bucket_name)

        response_payload = {
            "all_resources_count": total_all_resources,
            "sync_resources_count": total_sync_resources,
            "item_count": total_sync_resources,
            "integration_triggered": len(all_execution_ids) > 0,
            "execution_id": all_execution_ids[0] if all_execution_ids else None,
            "execution_ids": all_execution_ids
        }
        return (json.dumps(response_payload, indent=2), 200, {"Content-Type": "application/json"})
        
    except Exception as e:
        import traceback
        err_msg = f"Error executing SharePoint traversal Cloud Function: {e}\n{traceback.format_exc()}"
        print(err_msg)
        return (err_msg, 500)

if __name__ == "__main__":
    # Mock environment execution for Cloud Run Job
    class MockRequest:
        def __init__(self, data):
            self.data = data
        def get_json(self, silent=True):
            return self.data
            
    print("🚀 Standalone container CLI entrypoint active (Cloud Run Job)...")
    mock_payload = {
        "trigger_integration": True
    }
    target_cat = os.environ.get("TARGET_CATEGORY_ID")
    if target_cat:
        mock_payload["category_id"] = target_cat
        
    mock_req = MockRequest(mock_payload)
    main(mock_req)
