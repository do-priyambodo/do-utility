#!/usr/bin/env python3
"""
check_syncall_before.py - V9.0 High-Performance Pre-Sync Verification

Calculates:
  1. Total modern site pages and document files in the target SharePoint site/library.
  2. How many files and pages will be synchronized (Delta estimation).
  3. How many files and pages are already up-to-date in GCS and will be skipped.

Features:
  - Multi-Threaded Direct Client-Side Discovery (ThreadPoolExecutor with 10 concurrent workers)
    to inspect 9,000+ SharePoint assets in seconds without touching backend Cloud Functions.
  - Automatic O(1) GCS Delta Cache memory comparison.
  - Seamless fallback to Traversal Cloud Function invocation if direct access is restricted.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import threading
import time
import datetime
import concurrent.futures

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try:
    os.chdir(ROOT_DIR)
except Exception:
    pass

def run_with_heartbeat(msg, func, *args, **kwargs):
    stop_event = threading.Event()
    start_time = time.time()
    def heartbeat():
        while not stop_event.is_set():
            elapsed = int(time.time() - start_time)
            if elapsed > 0:
                sys.stdout.write(f"\r   ⏳ {msg} (Elapsed time: {elapsed}s)... ")
                sys.stdout.flush()
            time.sleep(1)
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    try:
        res = func(*args, **kwargs)
        stop_event.set()
        t.join(timeout=1)
        elapsed = int(time.time() - start_time)
        sys.stdout.write(f"\r   ✅ Completed in {elapsed}s!                                    \n")
        sys.stdout.flush()
        return res
    except Exception as e:
        stop_event.set()
        t.join(timeout=1)
        print()
        raise e

def get_secret_gcloud(secret_name):
    try:
        secret_part = secret_name.split("/")[-1]
        secret_id = secret_name.split("/")[-3] if "secrets/" in secret_name else secret_name
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", secret_part, f"--secret={secret_id}"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"], text=True, stderr=subprocess.DEVNULL).strip()

def get_graph_token(tenant_id, client_id, client_secret):
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

import requests
import random

_CHECK_SESSION = requests.Session()

def graph_get_paginated(url, headers, max_retries=10, timeout=30):
    results = []
    if "/children" in url or "/sites" in url or "/drives" in url:
        if "?" in url and "$top=" not in url:
            url += "&$top=999"
        elif "?" not in url:
            url += "?$top=999"

    while url:
        for attempt in range(max_retries):
            response = _CHECK_SESSION.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                break
            elif response.status_code in [429, 502, 503, 504]:
                retry_after = response.headers.get("Retry-After")
                wait_time = int(retry_after) if (retry_after and retry_after.isdigit()) else min(60, (2 ** attempt) + random.uniform(0, 1))
                time.sleep(wait_time)
                continue
            else:
                raise Exception(f"Graph API returned fatal status {response.status_code}: {response.text}")
        else:
            raise Exception(f"Graph API request failed after {max_retries} attempts: {url}")

        data = response.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return results

from collections import deque

def crawl_files_bfs(token, drive_id, all_files, sync_files, gcs_cache, lock, subsite_name="Home"):
    queue = deque([("root", "")])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        while queue:
            batch = []
            while queue and len(batch) < 10:
                batch.append(queue.popleft())

            def fetch_folder(folder_item):
                f_id, f_path = folder_item
                url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{f_id}/children"
                if f_id == "root":
                    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                try:
                    return f_path, graph_get_paginated(url, headers)
                except Exception as e:
                    return f_path, []

            futures = [executor.submit(fetch_folder, item) for item in batch]
            for future in concurrent.futures.as_completed(futures):
                parent_path, items = future.result()
                for item in items:
                    item_name = item.get("name", "")
                    curr_id = item.get("id")
                    if "folder" in item:
                        queue.append((curr_id, f"{parent_path}{item_name}/"))
                    else:
                        if item_name.lower().endswith(".aspx"):
                            pdf_name = item_name.replace(".aspx", ".pdf")
                            rel_page_path = f"pages/{parent_path}{pdf_name}"
                            page_obj = {"Name": pdf_name, "RelativePath": rel_page_path, "IsPage": True, "Subsite": subsite_name}
                            needs_sync = True
                            if gcs_cache and rel_page_path in gcs_cache:
                                sp_mod = item.get("lastModifiedDateTime")
                                if sp_mod:
                                    try:
                                        sp_dt = datetime.datetime.fromisoformat(sp_mod.replace("Z", "+00:00"))
                                        if gcs_cache[rel_page_path] >= sp_dt:
                                            needs_sync = False
                                    except Exception:
                                        pass
                            with lock:
                                if not any(x["RelativePath"] == rel_page_path for x in all_files):
                                    all_files.append(page_obj)
                                    if needs_sync:
                                        sync_files.append(page_obj)
                        else:
                            rel_path = f"{parent_path}{item_name}"
                            file_obj = {"Name": item_name, "RelativePath": rel_path, "IsPage": False, "Subsite": subsite_name}
                            needs_sync = True
                            gcs_path = f"files/{rel_path}"
                            if gcs_cache and gcs_path in gcs_cache:
                                sp_mod = item.get("lastModifiedDateTime")
                                if sp_mod:
                                    try:
                                        sp_dt = datetime.datetime.fromisoformat(sp_mod.replace("Z", "+00:00"))
                                        if gcs_cache[gcs_path] >= sp_dt:
                                            needs_sync = False
                                    except Exception:
                                        pass
                            with lock:
                                all_files.append(file_obj)
                                if needs_sync:
                                    sync_files.append(file_obj)

def crawl_pages_bfs(token, drive_id, all_items, sync_items, gcs_cache, lock, subsite_name="Home"):
    queue = deque([("root", "")])
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    seen_paths = set()

    while queue:
        curr_id, parent_path = queue.popleft()
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{curr_id}/children"
        if curr_id == "root":
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"

        try:
            items = graph_get_paginated(url, headers, max_retries=3, timeout=20)
            for item in items:
                item_name = item.get("name")
                if not item_name:
                    continue
                if "folder" in item:
                    queue.append((item.get("id"), f"{parent_path}{item_name}/"))
                elif item_name.lower().endswith(".aspx"):
                    pdf_name = item_name.replace(".aspx", ".pdf")
                    rel_page_path = f"pages/{parent_path}{pdf_name}"
                    if rel_page_path in seen_paths:
                        continue
                    seen_paths.add(rel_page_path)

                    page_obj = {"Name": pdf_name, "RelativePath": rel_page_path, "IsPage": True, "Subsite": subsite_name}
                    needs_sync = True
                    if gcs_cache and rel_page_path in gcs_cache:
                        p_mod = item.get("lastModifiedDateTime")
                        if p_mod:
                            try:
                                sp_dt = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                                if gcs_cache[rel_page_path] >= sp_dt:
                                    needs_sync = False
                            except Exception:
                                pass
                    with lock:
                        all_items.append(page_obj)
                        if needs_sync:
                            sync_items.append(page_obj)
        except Exception:
            pass

def run_fast_direct_check(params):
    tenant_id = params.get("CONFIG_M365_Tenant_Id")
    client_id = params.get("CONFIG_M365_Client_Id")
    secret_name = params.get("CONFIG_M365_Secret_Name")
    hostname = params.get("CONFIG_SharePoint_Hostname", "priyambodo.sharepoint.com")
    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/doddi-sharepoint-to-gcs")
    library_name = params.get("CONFIG_Sharepoint_Library", "Documents")
    bucket_name = params.get("CONFIG_GCS_Bucket")

    if not (tenant_id and client_id and secret_name and bucket_name):
        raise Exception("Missing required configuration for direct client-side check.")

    gcs_cache = {}
    graph_token = [None]
    err_holder = []

    def load_graph_token():
        try:
            secret_val = get_secret_gcloud(secret_name)
            graph_token[0] = get_graph_token(tenant_id, client_id, secret_val)
        except Exception as e:
            err_holder.append(e)

    def load_gcs_cache():
        try:
            from google.cloud import storage
            client = storage.Client()
            for b in client.list_blobs(bucket_name):
                if b.updated:
                    gcs_cache[b.name] = b.updated
        except Exception:
            try:
                ls_out = subprocess.check_output(
                    ["gcloud", "storage", "ls", "--long", "--recursive", f"gs://{bucket_name}/**"],
                    stderr=subprocess.DEVNULL
                ).decode("utf-8")
                for line in ls_out.splitlines():
                    parts = line.strip().split(maxsplit=2)
                    if len(parts) >= 3 and parts[0].isdigit():
                        ts_str = parts[1]
                        uri = parts[2]
                        prefix = f"gs://{bucket_name}/"
                        if uri.startswith(prefix):
                            rel_name = uri[len(prefix):]
                            try:
                                dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                gcs_cache[rel_name] = dt
                            except Exception:
                                pass
            except Exception:
                pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as init_pool:
        f1 = init_pool.submit(load_graph_token)
        f2 = init_pool.submit(load_gcs_cache)
        concurrent.futures.wait([f1, f2])

    if err_holder or not graph_token[0]:
        raise Exception(f"Could not initialize direct Graph API session: {err_holder[0] if err_holder else 'Auth failed'}")

    token = graph_token[0]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Resolve subsite and drive
    site_name_clean = site_path[len("sites/"):] if site_path.startswith("sites/") else site_path
    site_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{site_name_clean}"
    req = urllib.request.Request(site_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        site_data = json.loads(resp.read().decode("utf-8"))
        site_id = site_data.get("id")

    def get_all_subsites_recursive(s_id, current_prefix=""):
        subsites = []
        url = f"https://graph.microsoft.com/v1.0/sites/{s_id}/sites"
        try:
            children = graph_get_paginated(url, headers)
            for child in children:
                child_id = child.get("id")
                raw_name = child.get("name", "")
                sub_prefix = f"{current_prefix}{raw_name}/" if raw_name else f"{current_prefix}subsite/"
                subsites.append({"id": child_id, "name": raw_name, "prefix": sub_prefix})
                subsites.extend(get_all_subsites_recursive(child_id, sub_prefix))
        except Exception:
            pass
        return subsites

    target_sites = [{"id": site_id, "name": site_name_clean, "prefix": ""}]
    target_sites.extend(get_all_subsites_recursive(site_id, ""))

    all_target_drives = []
    all_page_drives = []
    system_libraries = {"style library", "form templates", "site assets"}
    for s in target_sites:
        s_id = s["id"]
        s_name = s["name"] or "Home"
        drives_url = f"https://graph.microsoft.com/v1.0/sites/{s_id}/drives"
        try:
            s_drives = graph_get_paginated(drives_url, headers)
            for d in s_drives:
                d_name = d.get("name", "")
                d_lower = d_name.lower()
                d_clean = d_lower.replace(" ", "")
                if d_clean in ["sitepages", "pages"] or d_lower == "site pages":
                    all_page_drives.append((s_id, s_name, d))
                elif d.get("driveType") == "documentLibrary" and d_lower not in system_libraries:
                    if not library_name or library_name.lower() in ["all", "*"] or d_lower == library_name.lower() or (library_name in ["Shared Documents", "Documents"] and d_name in ["Shared Documents", "Documents"]):
                        all_target_drives.append((s_id, s_name, d))
            if not any(sid == s_id for sid, _, _ in all_target_drives) and s_drives:
                for d in s_drives:
                    if d.get("name", "").lower() not in system_libraries and d.get("name", "").lower().replace(" ", "") not in ["sitepages", "pages"]:
                        all_target_drives.append((s_id, s_name, d))
                        break
        except Exception:
            pass

    print("--------------------------------------------------------------------------------")
    print(f"🏢 SHAREPOINT SITE & SUBSITE COLLECTION DISCOVERY (Root: '{site_name_clean}')")
    print(f"   • Total Site Collections / Subsites Scanned: {len(target_sites)}")
    print(f"   • Total Document Libraries / Drives Found  : {len(all_target_drives)}")
    print(f"   • Total Site Pages Libraries / Drives Found: {len(all_page_drives)}")
    for idx, (sid, sname, d) in enumerate(all_target_drives, 1):
        print(f"     {idx}. [{sname[:20]}] Library '{d.get('name')}' (Drive ID: {d.get('id', '')[:15]}...)")
    print(f"   • Active Configured Target ('CONFIG_Sharepoint_Library'): '{library_name}'")
    print("--------------------------------------------------------------------------------\n")

    all_items = []
    sync_items = []
    lock = threading.Lock()

    def scan_drive_files(sid, sname, d):
        crawl_files_bfs(token, d.get("id"), all_items, sync_items, gcs_cache, lock, subsite_name=sname)

    def scan_page_library(sid, sname, d):
        crawl_pages_bfs(token, d.get("id"), all_items, sync_items, gcs_cache, lock, subsite_name=sname)

    def scan_subsite_pages_unthrottled(s):
        s_name = s["name"] or "Home"
        s_id = s["id"]
        discovered_pages = []
        seen_names = set()

        # Strategy 1: Modern Site Pages API v1.0
        try:
            pages = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/pages", headers, max_retries=3, timeout=20)
            for p in pages:
                pname = p.get("name", "Page.aspx")
                if pname and pname not in seen_names:
                    seen_names.add(pname)
                    discovered_pages.append((pname, p.get("lastModifiedDateTime")))
        except Exception:
            pass

        # Strategy 1.5: Modern Site Pages API via /sitePages/pages endpoint (for departmental sub-hubs)
        try:
            pages_sp = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/sitePages/pages", headers, max_retries=3, timeout=20)
            for p in pages_sp:
                pname = p.get("name", "Page.aspx")
                if pname and pname not in seen_names:
                    seen_names.add(pname)
                    discovered_pages.append((pname, p.get("lastModifiedDateTime")))
        except Exception:
            pass

        # Strategy 2: Modern Site Pages API beta
        try:
            pages_beta = graph_get_paginated(f"https://graph.microsoft.com/beta/sites/{s_id}/pages", headers, max_retries=3, timeout=20)
            for p in pages_beta:
                pname = p.get("name", "Page.aspx")
                if pname and pname not in seen_names:
                    seen_names.add(pname)
                    discovered_pages.append((pname, p.get("lastModifiedDateTime")))
        except Exception:
            pass

        # Strategy 3: Query SharePoint List Items directly across all lists (/sites/{id}/lists/{list_id}/items)
        try:
            lists = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/lists", headers, max_retries=3, timeout=20)
            for lst in lists:
                try:
                    items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/lists/{lst['id']}/items?expand=fields", headers, max_retries=3, timeout=20)
                    for itm in items:
                        fields = itm.get("fields", {})
                        iname = fields.get("FileLeafRef") or fields.get("LinkFilename") or ""
                        if iname.lower().endswith(".aspx") and iname not in seen_names:
                            seen_names.add(iname)
                            discovered_pages.append((iname, fields.get("Modified", itm.get("lastModifiedDateTime"))))
                except Exception:
                    # Fallback when expand=fields fails (common for SitePages canvas layout items)
                    try:
                        raw_items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/lists/{lst['id']}/items", headers, max_retries=3, timeout=20)
                        for itm in raw_items:
                            web_url = itm.get("webUrl", "")
                            if web_url.lower().endswith(".aspx"):
                                iname = os.path.basename(urllib.parse.urlsplit(web_url).path)
                                if iname and iname not in seen_names:
                                    seen_names.add(iname)
                                    discovered_pages.append((iname, itm.get("lastModifiedDateTime")))
                    except Exception:
                        pass

                # Strategy 4.5: Direct Drive query for lists named SitePages / Site Pages / Pages
                if any(k in lst.get("name", "").lower() for k in ["sitepages", "site pages", "pages"]):
                    try:
                        drive_items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/lists/{lst['id']}/drive/root/children", headers, max_retries=3, timeout=20)
                        for di in drive_items:
                            iname = di.get("name", "")
                            if iname.lower().endswith(".aspx") and iname not in seen_names:
                                seen_names.add(iname)
                                discovered_pages.append((iname, di.get("lastModifiedDateTime")))
                    except Exception:
                        pass
        except Exception:
            pass

        # Strategy 4: Direct BFS crawl across all Drives on the subsite (.aspx files)
        try:
            drives_list = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/drives", headers, max_retries=3, timeout=20)
            for sp_drive in drives_list:
                try:
                    queue = deque([("root", "")])
                    while queue:
                        curr_id, parent_path = queue.popleft()
                        url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/items/{curr_id}/children"
                        if curr_id == "root":
                            url = f"https://graph.microsoft.com/v1.0/drives/{sp_drive['id']}/root/children"
                        items = graph_get_paginated(url, headers, max_retries=3, timeout=20)
                        for item in items:
                            iname = item.get("name", "")
                            if "folder" in item:
                                queue.append((item.get("id"), f"{parent_path}{iname}/"))
                            elif iname.lower().endswith(".aspx") and iname not in seen_names:
                                seen_names.add(iname)
                                discovered_pages.append((iname, item.get("lastModifiedDateTime")))
                except Exception:
                    pass
        except Exception:
            pass

        for page_name, p_mod in discovered_pages:
            pdf_name = page_name.replace(".aspx", ".pdf")
            rel_page_path = f"pages/{pdf_name}"
            page_obj = {"Name": pdf_name, "RelativePath": rel_page_path, "IsPage": True, "Subsite": s_name}
            needs_sync = True
            if gcs_cache and rel_page_path in gcs_cache:
                if p_mod:
                    try:
                        sp_dt = datetime.datetime.fromisoformat(p_mod.replace("Z", "+00:00"))
                        if gcs_cache[rel_page_path] >= sp_dt:
                            needs_sync = False
                    except Exception:
                        pass
            with lock:
                if not any(x["RelativePath"] == rel_page_path for x in all_items):
                    all_items.append(page_obj)
                    if needs_sync:
                        sync_items.append(page_obj)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        f_list = [pool.submit(scan_drive_files, sid, sname, d) for sid, sname, d in all_target_drives]
        p_list = [pool.submit(scan_page_library, sid, sname, d) for sid, sname, d in all_page_drives]
        concurrent.futures.wait(f_list + p_list)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as page_pool:
        api_list = [page_pool.submit(scan_subsite_pages_unthrottled, s) for s in target_sites]
        concurrent.futures.wait(api_list)

    return all_items, sync_items

def main():
    print("================================================================================")
    print("⚡ HIGH-SPEED PRE-SYNC CHECK: SHAREPOINT INVENTORY & DELTA (BEFORE SYNC)")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in working directory.")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    project_id = params.get("CONFIG_ProjectId", "")
    bucket_name = params.get("CONFIG_GCS_Bucket", "")
    site_path = params.get("CONFIG_Sharepoint_Sites", "sites/yourorg-sharepoint-to-gcs")
    library_name = params.get("CONFIG_Sharepoint_Library", "Documents")

    print("📂 Step 1: Loading Pipeline Parameters...")
    print(f" • Project ID            : {project_id}")
    print(f" • Target GCS Bucket     : gs://{bucket_name}")
    print(f" • Target SharePoint Site: {site_path}")
    print(f" • Document Library      : {library_name}\n")

    all_items = None
    sync_items = None

    print("⚡ Step 2: Executing Multi-Threaded Direct Discovery (10 concurrent workers)...")
    try:
        start_t = time.time()
        all_items, sync_items = run_with_heartbeat("Crawling SharePoint assets & evaluating O(1) GCS Delta Cache concurrently", run_fast_direct_check, params)
    except Exception as e:
        print(f"ℹ️ Direct client-side check notice ({e}). Falling back to Traversal Cloud Function...")
        # Fall back to Traversal Cloud Function call
        cf_endpoint = params.get("CONFIG_CloudFunction_URL")
        function_name = params.get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files")
        location = params.get("CONFIG_Location", "asia-southeast1")
        try:
            if not cf_endpoint and function_name:
                cmd = ["gcloud", "functions", "describe", function_name, "--gen2", "--region", location, "--project", project_id, "--format", "value(serviceConfig.uri)"]
                cf_endpoint = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
            token = subprocess.check_output(["gcloud", "auth", "print-identity-token"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
            site_name_clean = site_path[len("sites/"):] if site_path.startswith("sites/") else site_path
            payload = {"site_name": site_name_clean, "library_name": library_name, "trigger_integration": False, "sync_files": True, "sync_pages": True}
            req = urllib.request.Request(cf_endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
            resp = run_with_heartbeat("Querying Traversal Cloud Function for live inventory", urllib.request.urlopen, req, timeout=600)
            data = json.loads(resp.read().decode("utf-8"))
            all_items = data.get("all_resources", data.get("items", []))
            sync_items = data.get("sync_resources", data.get("items", []))
        except Exception as ex2:
            print(f"❌ Failed to inspect inventory: {ex2}")
            sys.exit(1)

    # Calculate SharePoint target totals
    total_sp_pages = sum(1 for x in all_items if x.get("IsPage"))
    total_sp_files = sum(1 for x in all_items if not x.get("IsPage"))
    total_sp_items = len(all_items)

    # Calculate items that WILL be synced (Delta)
    delta_pages = sum(1 for x in sync_items if x.get("IsPage"))
    delta_files = sum(1 for x in sync_items if not x.get("IsPage"))
    delta_total = len(sync_items)

    # Calculate items already up to date (Skipped by cache)
    skipped_pages = total_sp_pages - delta_pages
    skipped_files = total_sp_files - delta_files
    skipped_total = total_sp_items - delta_total

    print("\n================================================================================")
    print("📊 SHAREPOINT SITE COLLECTION DEPARTMENT BREAKDOWN (ASSETS BY SUBSITE)")
    print("================================================================================")
    print(f"{'No.':<5}{'Subsite / Department Name':<40}{'Files':<12}{'Pages':<12}{'Total':<10}")
    print("-" * 80)
    
    from collections import defaultdict
    sub_f = defaultdict(int)
    sub_p = defaultdict(int)
    for x in all_items:
        sname = x.get("Subsite", "Home") or "Home"
        if x.get("IsPage"):
            sub_p[sname] += 1
        else:
            sub_f[sname] += 1
            
    all_subs = sorted(list(set(list(sub_f.keys()) + list(sub_p.keys()))))
    for idx, sname in enumerate(all_subs, 1):
        fc = sub_f[sname]
        pc = sub_p[sname]
        print(f"{idx:<5}{sname[:38]:<40}{fc:<12}{pc:<12}{fc + pc:<10}")
        
    print("-" * 80)
    print(f"{'':<5}{'TOTAL INVENTORY ACROSS SITE':<40}{total_sp_files:<12}{total_sp_pages:<12}{total_sp_items:<10}")
    print("================================================================================\n")
    print("================================================================================")
    print("📊 PRE-SYNC VERIFICATION REPORT (BEFORE SYNC)")
    print("================================================================================")
    print(f"1️⃣  TOTAL SHAREPOINT TARGET INVENTORY:")
    print(f"    • Total Modern Site Pages (.aspx -> .pdf): {total_sp_pages:>6}")
    print(f"    • Total Document Files                   : {total_sp_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL INVENTORY ITEMS                  : {total_sp_items:>6}")
    print("--------------------------------------------------------------------------------")
    print(f"2️⃣  ITEMS TO BE SYNCED (DELTA NEEDING UPLOAD/RENDER):")
    print(f"    • Pages Needing Sync                     : {delta_pages:>6}")
    print(f"    • Files Needing Sync                     : {delta_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL DELTA TO SYNC                    : {delta_total:>6}")
    print("--------------------------------------------------------------------------------")
    print(f"3️⃣  ITEMS ALREADY UP-TO-DATE IN GCS (WILL BE SKIPPED):")
    print(f"    • Pages Skipped (Unchanged in GCS)       : {skipped_pages:>6}")
    print(f"    • Files Skipped (Unchanged in GCS)       : {skipped_files:>6}")
    print(f"    ----------------------------------------------------------------------------")
    print(f"    • TOTAL SKIPPED                          : {skipped_total:>6}")
    print("================================================================================")

    if delta_total == 0:
        print("✅ RECOMMENDATION: All SharePoint items are already synced and up to date!")
    else:
        print(f"🚀 RECOMMENDATION: Proceed with synchronization. {delta_total} item(s) will be processed.")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
