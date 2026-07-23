#!/usr/bin/env python3
"""
⚡ HIGH-SPEED PRE-SYNC DRY-RUN AUDIT FOR SHAREPOINT DOCUMENT FILES (BEFORE SYNC)
Target: SharePoint Document Library Files (.pdf, .docx, .pptx, .xlsx, images, etc.)
Hierarchy: Detailed Subsite Breakdown (Discovered Files, Filtered Files, Valid Files Expected to Sync)
Engine: Multi-Threaded Graph API Traversal with Automatic 404 Fallback & Active Filter Evaluator
Output: Terminal Display + Auto-Saves to check_files_before_sync.txt
Location: app/v12-category/app/check/check_files_before_sync.py
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import threading
import concurrent.futures
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
try:
    os.chdir(ROOT_DIR)
except Exception:
    pass

class TeeLogger:
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log_file = open(filepath, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()

def load_parameters():
    possible_paths = [
        os.path.join(os.getcwd(), "parameters.json"),
        os.path.join(os.path.dirname(__file__), "parameters.json"),
        os.path.join(os.path.dirname(__file__), "..", "parameters.json"),
        os.path.join(os.path.dirname(__file__), "hideme", "parameters.json"),
        os.path.join(os.path.dirname(__file__), "..", "hideme", "maxis-parameters.json"),
        os.path.join(os.getcwd(), "hideme", "maxis-parameters.json"),
        os.path.join(os.path.dirname(__file__), "hideme", "maxis-parameters-old.json")
    ]
    for p in possible_paths:
        if os.path.exists(p):
            print(f"📖 Loaded parameter configuration from: {os.path.abspath(p)}")
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("Could not find 'parameters.json' in current directory or parent paths.")

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

    req = urllib.request.Request(token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("access_token")

def graph_get_paginated(url, headers, max_retries=3, timeout=20):
    results = []
    curr_url = url
    while curr_url:
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(curr_url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    val = data.get("value", [])
                    results.extend(val)
                    curr_url = data.get("@odata.nextLink")
                    break
            except Exception:
                if attempt == max_retries - 1:
                    curr_url = None
                else:
                    time.sleep(1)
    return results

def extract_subsite_path(sp_url, fallback_name="DEN-Portal"):
    if not sp_url:
        return fallback_name
    try:
        parsed = urllib.parse.urlparse(sp_url)
        path = parsed.path
        if "/sites/" in path:
            path = path.split("/sites/", 1)[1]
        path = path.replace("/Shared Documents", "").replace("/shared documents", "")
        parts = [p for p in path.split("/") if p and not "." in p.rsplit("/", 1)[-1]]
        if parts:
            return "/".join(parts)
    except Exception:
        pass
    return fallback_name

def evaluate_file_filters(file_name, file_url, ignore_keywords):
    name_lower = (file_name or "").lower()
    url_lower = (file_url or "").lower()

    # Filter A: Hidden office temp files starting with ~$
    if file_name and file_name.startswith("~$"):
        return True, "Filter A (Office Lock/Temp File)"

    # Filter B: Active Path & Filename Ignore Keywords
    for kw in ignore_keywords:
        kw_lower = kw.lower()
        if kw_lower in url_lower or kw_lower in name_lower:
            return True, f"Filter B (Keyword '{kw}')"

    return False, None

def main():
    report_dir = os.path.join(ROOT_DIR, "report")
    os.makedirs(report_dir, exist_ok=True)
    output_filename = os.path.join(report_dir, "check_files_before_sync.txt")
    tee = TeeLogger(output_filename)
    original_stdout = sys.stdout
    sys.stdout = tee

    try:
        print("=" * 95)
        print("⚡ SHAREPOINT DOCUMENT FILES PRE-SYNC DRY-RUN AUDIT & FILTER COMPLIANCE REPORT")
        print("=" * 95)

        params = load_parameters()
        tenant_id = params.get("CONFIG_M365_Tenant_Id")
        client_id = params.get("CONFIG_M365_Client_Id")
        secret_name = params.get("CONFIG_M365_Secret_Name")
        hostname = params.get("CONFIG_Sharepoint_Hostname") or params.get("CONFIG_SharePoint_Hostname", "maxis365.sharepoint.com")
        bucket_name = params.get("CONFIG_GCS_Bucket")
        ignore_keywords = params.get("CONFIG_Ignore_Path_Keywords", [])

        print(f"• Target Tenant Hostname       : {hostname}")
        print(f"• Target GCS Bucket           : gs://{bucket_name}")
        print(f"• Active Ignore Path Keywords : {ignore_keywords}")
        print("-" * 95)

        secret_val = get_secret_gcloud(secret_name) if secret_name and secret_name.startswith("projects/") else secret_name
        token = get_graph_token(tenant_id, client_id, secret_val)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Collect configured sites from parameters.json
        sites_to_sync = set()
        single_site = params.get("CONFIG_Sharepoint_Sites")
        if single_site:
            sites_to_sync.add(single_site)
        for cat in params.get("CONFIG_Categories", []):
            cat_site = cat.get("sharepoint_site")
            if isinstance(cat_site, str):
                sites_to_sync.add(cat_site)
            elif isinstance(cat_site, list):
                for s in cat_site:
                    sites_to_sync.add(s)

        if not sites_to_sync:
            sites_to_sync.add("sites/DEN")

        def get_all_subsites_recursive(s_id, current_prefix=""):
            subsites = []
            if not s_id:
                return subsites
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

        print("🌐 Resolving SharePoint Site IDs & Scoping Subsites (with 404 Automatic Fallback)...")
        target_sites = []
        seen_site_ids = set()

        for s_path in sorted(sites_to_sync):
            clean_path = s_path[len("sites/"):] if s_path.startswith("sites/") else s_path
            resolve_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{clean_path}"
            
            site_id = None
            try:
                req = urllib.request.Request(resolve_url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    site_data = json.loads(resp.read().decode("utf-8"))
                    site_id = site_data.get("id")
            except urllib.error.HTTPError as he:
                if he.code == 404:
                    # 404 Fallback logic to parent site collection
                    parent_site = clean_path.rsplit('/', 1)[0] if '/' in clean_path else ""
                    if parent_site:
                        parent_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{parent_site}"
                        try:
                            req_p = urllib.request.Request(parent_url, headers=headers)
                            with urllib.request.urlopen(req_p, timeout=15) as resp_p:
                                site_id = json.loads(resp_p.read().decode("utf-8")).get("id")
                        except Exception:
                            pass
                    if not site_id:
                        root_den = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/DEN"
                        try:
                            req_r = urllib.request.Request(root_den, headers=headers)
                            with urllib.request.urlopen(req_r, timeout=15) as resp_r:
                                site_id = json.loads(resp_r.read().decode("utf-8")).get("id")
                        except Exception:
                            pass
            except Exception:
                pass

            if site_id and site_id not in seen_site_ids:
                seen_site_ids.add(site_id)
                target_sites.append({"id": site_id, "name": clean_path, "prefix": ""})
                for sub in get_all_subsites_recursive(site_id, ""):
                    if sub["id"] not in seen_site_ids:
                        seen_site_ids.add(sub["id"])
                        target_sites.append(sub)

        print(f"✅ Resolved {len(target_sites)} enumerable site collections / subsites.")

        # Multi-threaded file discovery across drives & document libraries
        subsite_discovered = defaultdict(int)
        subsite_filtered = defaultdict(int)

        def scan_site_files(site_obj):
            s_id = site_obj["id"]
            s_name = site_obj["name"]
            discovered_items = []
            
            try:
                # Query default drives
                drives = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/drives", headers, max_retries=2, timeout=15)
                for d in drives:
                    d_id = d.get("id")
                    items = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/drives/{d_id}/root/children", headers, max_retries=2, timeout=15)
                    for it in items:
                        if "file" in it:
                            fname = it.get("name", "")
                            web_url = it.get("webUrl", "")
                            discovered_items.append((fname, web_url, s_name))
            except Exception:
                pass

            return discovered_items

        print("📡 Multi-threaded parallel file inventory scan across Document Libraries...")
        all_files = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(scan_site_files, s) for s in target_sites]
            for f in concurrent.futures.as_completed(futures):
                try:
                    all_files.extend(f.result())
                except Exception:
                    pass

        filter_breakdown = defaultdict(int)
        valid_files_count = 0

        for fname, web_url, s_name in all_files:
            path_key = extract_subsite_path(web_url, fallback_name=s_name)
            subsite_discovered[path_key] += 1

            is_filt, filt_reason = evaluate_file_filters(fname, web_url, ignore_keywords)
            if is_filt:
                subsite_filtered[path_key] += 1
                filter_breakdown[filt_reason] += 1
            else:
                valid_files_count += 1

        all_keys = sorted(set(list(subsite_discovered.keys())))

        print("\n" + "=" * 95)
        print("📊 PRE-SYNC DOCUMENT FILES DETAILED RECONCILIATION BY SUBSITE & SUB-CATEGORY")
        print("=" * 95)
        print(f"{'Subsite / Sub-Category Path':<40}{'Discovered Files':<18}{'Filtered Files':<18}{'Expected Valid Files':<20}")
        print("-" * 95)

        total_disc = sum(subsite_discovered.values())
        total_filt = sum(subsite_filtered.values())

        for key in all_keys:
            disc = subsite_discovered[key]
            filt = subsite_filtered[key]
            valid = disc - filt
            print(f"{key:<40}{disc:<18}{filt:<18}{valid:<20}")

        print("=" * 95)
        print(f"{'TOTAL DOCUMENT FILES ACROSS TENANT':<40}{total_disc:<18}{total_filt:<18}{total_disc - total_filt:<20}")
        print("=" * 95)

        print("\n" + "=" * 95)
        print("📊 PRE-SYNC DOCUMENT FILES AUDIT SUMMARY")
        print("=" * 95)
        print(f"• Total Discovered SharePoint Document Files : {total_disc} Files")
        print(f"• Filtered / Excluded Files (Skipped)        : {total_filt} Files")
        print(f"• Expected Valid Files to Sync to GCS        : {total_disc - total_filt} Files")
        if filter_breakdown:
            print("  └─ Active Filter Rule Triggers Breakdown:")
            for reason, count in filter_breakdown.items():
                print(f"     - {reason}: {count} files")
        print("=" * 95)
        print(f"\n💾 Report auto-saved to: {os.path.abspath(output_filename)}")

    finally:
        sys.stdout = original_stdout
        tee.close()

if __name__ == "__main__":
    main()
