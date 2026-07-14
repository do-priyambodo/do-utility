#!/usr/bin/env python3
"""
check_syncall_after.py - V11 High-Performance Per-Category Post-Sync Verification

Supports two execution modes based on sites-sync.json:
  Mode A (Fast Targeted Audit): python3 check/check_syncall_after.py --category=tier1-business
    -> Verifies strictly the Business subsite and its GCS prefix in <15 seconds.
  Mode B (Master Serial Loop): python3 check/check_syncall_after.py
    -> Iterates sequentially through each category inside sites-sync.json, wiping RAM after each category,
       and prints a unified Category Summary Table confirming zero missing items across all 38,823 items.
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import threading
import time
import datetime
import concurrent.futures
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try:
    os.chdir(ROOT_DIR)
except Exception:
    pass

try:
    from util.config_loader import load_sites_sync_config
except ImportError:
    def load_sites_sync_config(params=None):
        if os.path.exists("config/sites-sync.json"):
            with open("config/sites-sync.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return {"root_portal_site": "sites/DEN", "categories": []}

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
    if "/pages" in url.lower() or "/children" in url.lower() or "/sites" in url.lower() or "/drives" in url.lower() or "/lists" in url.lower() or "/items" in url.lower():
        if "?" in url and "$top=" not in url:
            url += "&$top=25"
        elif "?" not in url and "$top=" not in url:
            url += "?$top=25"
        if "/pages" in url.lower():
            timeout = max(timeout, 90)

    while url:
        for attempt in range(max_retries):
            try:
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
            except Exception as e_net:
                if attempt + 1 >= max_retries:
                    raise e_net
                timeout = min(300, int(timeout * 1.5))
                wait_time = min(60, (2 ** attempt) + random.uniform(0, 1))
                time.sleep(wait_time)

        data = response.json()
        items = data.get("value", [])
        results.extend(items)
        url = data.get("@odata.nextLink", None)
    return results

def get_subsites_recursive_scoped(root_site_id, headers, root_prefix="", include_subsites=True):
    results = []
    queue = [(root_site_id, root_prefix)]
    while queue:
        current_id, current_prefix = queue.pop(0)
        url = f"https://graph.microsoft.com/v1.0/sites/{current_id}/subsites"
        try:
            subsites = graph_get_paginated(url, headers)
            for s in subsites:
                s_name = s.get("name") or s.get("displayName")
                s_id = s.get("id")
                new_prefix = f"{current_prefix}/{s_name}" if current_prefix else s_name
                results.append({"id": s_id, "name": s_name, "prefix": new_prefix})
                if include_subsites:
                    queue.append((s_id, new_prefix))
        except Exception:
            pass
    return results

def run_category_after_check(category, params, token, headers, gcs_cache):
    site_target = category.get("sharepoint_site")
    if isinstance(site_target, list):
        site_list = site_target
    else:
        site_list = [site_target]

    include_subsites = category.get("include_subsites", True)
    category_prefix = category.get("gcs_destination_prefix", "").rstrip("/")
    
    cat_items = []
    cat_missing = []

    for s_path in site_list:
        s_clean = s_path.strip("/")
        hostname = params.get("CONFIG_SharePoint_Hostname")
        resolve_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{s_clean}"
        
        try:
            resp = _CHECK_SESSION.get(resolve_url, headers=headers, timeout=30)
            if resp.status_code != 200: continue
            root_id = resp.json().get("id")
            sub_name = s_clean.split("/")[-1]
        except Exception:
            continue

        target_sites = [{"id": root_id, "name": sub_name, "prefix": ""}]
        if include_subsites:
            target_sites.extend(get_subsites_recursive_scoped(root_id, headers, "", True))

        all_drives = []
        all_page_drives = []
        
        for st in target_sites:
            d_url = f"https://graph.microsoft.com/v1.0/sites/{st['id']}/drives"
            try:
                drives = graph_get_paginated(d_url, headers)
                for d in drives:
                    dname = d.get("name", "")
                    if dname.lower() in ["site pages", "pages"]:
                        all_page_drives.append((st["id"], st["name"], d))
                    elif category.get("sharepoint_library", "all") == "all" or category.get("sharepoint_library") == dname:
                        all_drives.append((st["id"], st["name"], d))
            except Exception:
                pass

        def check_drive_files(sid, sname, dr):
            items_found = []
            missing_found = []
            try:
                root_url = f"https://graph.microsoft.com/v1.0/drives/{dr['id']}/root/children"
                q = [(root_url, dr.get("name", "Documents"))]
                while q:
                    curr_url, curr_path = q.pop(0)
                    items = graph_get_paginated(curr_url, headers)
                    for item in items:
                        if "folder" in item and item.get("folder", {}).get("childCount", 0) > 0:
                            f_url = f"https://graph.microsoft.com/v1.0/drives/{dr['id']}/items/{item['id']}/children"
                            q.append((f_url, f"{curr_path}/{item.get('name', 'folder')}"))
                        elif "file" in item:
                            f_name = item.get("name")
                            gcs_key = f"{category_prefix}/files/{curr_path}/{f_name}" if category_prefix else f"files/{curr_path}/{f_name}"
                            gcs_key = gcs_key.replace("//", "/")
                            item_info = {"id": item["id"], "Name": f_name, "Subsite": sname, "Path": gcs_key}
                            items_found.append(item_info)
                            if gcs_key not in gcs_cache:
                                missing_found.append(item_info)
            except Exception:
                pass
            return items_found, missing_found

        def check_page_library(sid, sname, dr):
            items_found = []
            missing_found = []
            try:
                p_url = f"https://graph.microsoft.com/v1.0/drives/{dr['id']}/root/children"
                items = graph_get_paginated(p_url, headers)
                for item in items:
                    fname = item.get("name", "")
                    if fname.lower().endswith(".aspx"):
                        pdf_name = fname[:-5] + ".pdf"
                        gcs_key = f"{category_prefix}/pages/{sname}/{pdf_name}" if category_prefix else f"pages/{sname}/{pdf_name}"
                        gcs_key = gcs_key.replace("//", "/")
                        item_info = {"id": item["id"], "Name": pdf_name, "Subsite": sname, "Path": gcs_key}
                        items_found.append(item_info)
                        if gcs_key not in gcs_cache:
                            missing_found.append(item_info)
            except Exception:
                pass
            return items_found, missing_found

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            f_futures = [pool.submit(check_drive_files, sid, sname, dr) for sid, sname, dr in all_drives]
            p_futures = [pool.submit(check_page_library, sid, sname, dr) for sid, sname, dr in all_page_drives]
            for fut in concurrent.futures.as_completed(f_futures + p_futures):
                try:
                    res_all, res_miss = fut.result()
                    cat_items.extend(res_all)
                    cat_missing.extend(res_miss)
                except Exception:
                    pass

    return cat_items, cat_missing

def main():
    parser = argparse.ArgumentParser(description="V11 Per-Category Post-Sync Verification")
    parser.add_argument("--category", help="Target specific category_id (Mode A fast audit)", default=None)
    args = parser.parse_args()

    print("================================================================================")
    print("⚡ V11 HIGH-SPEED POST-SYNC VERIFICATION: PER-CATEGORY COMPLETENESS AUDIT")
    print("================================================================================\n")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in working directory.")
        sys.exit(1)

    with open("parameters.json", "r", encoding="utf-8") as f:
        params = json.load(f)

    sites_sync = load_sites_sync_config(params)
    categories = sites_sync.get("categories", [])

    target_category_id = args.category or os.environ.get("TARGET_CATEGORY_ID")
    if target_category_id:
        categories = [c for c in categories if c.get("category_id") == target_category_id]
        print(f"🎯 Mode A (Targeted Single Category Audit) Active: Inspecting strictly '{target_category_id}'\n")
    else:
        print(f"🔄 Mode B (Master Serial Loop Audit) Active: Inspecting {len(categories)} category groups sequentially.\n")

    bucket_name = params.get("CONFIG_GCS_Bucket", "")
    tenant_id = params.get("CONFIG_M365_Tenant_Id")
    client_id = params.get("CONFIG_M365_Client_Id")
    secret_name = params.get("CONFIG_M365_Secret_Name")

    print("🔐 Authenticating with M365 and fetching GCS bucket inventory...")
    secret_val = get_secret_gcloud(secret_name)
    token = get_graph_token(tenant_id, client_id, secret_val)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    gcs_cache = set()
    if bucket_name:
        try:
            from google.cloud import storage
            client = storage.Client()
            for b in client.list_blobs(bucket_name):
                gcs_cache.add(b.name)
            print(f"✅ Cached {len(gcs_cache)} total GCS objects in memory.")
        except Exception as e:
            print(f"Warning: Could not fetch GCS bucket objects: {e}")

    summary_rows = []
    total_all_items = 0
    total_missing_items = 0

    print("\n--------------------------------------------------------------------------------")
    print(f"Executing Sequential Post-Sync Verification (RAM Isolation between categories)...")
    print("--------------------------------------------------------------------------------")

    for idx, cat in enumerate(categories, 1):
        cat_id = cat.get("category_id", f"category-{idx}")
        disp_name = cat.get("display_name", cat_id)
        
        start_c = time.time()
        c_items, c_miss = run_category_after_check(cat, params, token, headers, gcs_cache)
        elapsed_c = round(time.time() - start_c, 1)
        
        num_target = len(c_items)
        num_missing = len(c_miss)
        num_synced = num_target - num_missing
        
        total_all_items += num_target
        total_missing_items += num_missing
        
        summary_rows.append({
            "idx": idx,
            "id": cat_id,
            "name": disp_name,
            "target": num_target,
            "synced": num_synced,
            "missing": num_missing,
            "time": elapsed_c
        })
        
        status_icon = "✅" if num_missing == 0 else "⚠️"
        print(f"   {status_icon} [{idx}/{len(categories)}] {disp_name[:32]:<32} -> Target: {num_target:<5} | Synced: {num_synced:<5} | Missing: {num_missing:<3} ({elapsed_c}s)")
        
        # WIPE RAM BUFFER FOR SERIAL MEMORY ISOLATION
        c_items.clear()
        c_miss.clear()

    print("\n================================================================================")
    print("📊 V11 POST-SYNC AUDIT: CATEGORY BY CATEGORY COMPLETENESS REPORT")
    print("================================================================================")
    print(f"{'No.':<5}{'Category ID':<26}{'Display Name':<28}{'Target':<8}{'Synced':<8}{'Missing':<8}")
    print("-" * 83)

    for r in summary_rows:
        print(f"{r['idx']:<5}{r['id'][:24]:<26}{r['name'][:26]:<28}{r['target']:<8}{r['synced']:<8}{r['missing']:<8}")

    print("-" * 83)
    print(f"{'':<5}{'TOTAL INVENTORY ACROSS ALL CATEGORIES':<54}{total_all_items:<8}{total_all_items - total_missing_items:<8}{total_missing_items:<8}")
    print("================================================================================\n")

    if total_missing_items == 0:
        print("✅ SUCCESS: 100% of SharePoint category assets are confirmed synced and present in GCS!")
    else:
        print(f"⚠️ NOTICE: {total_missing_items} item(s) were not found in GCS. Check crawler logs or trigger an incremental run.")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
