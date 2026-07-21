#!/usr/bin/env python3
"""
⚡ HIGH-SPEED PRE-SYNC AUDIT FOR MODERN SITE PAGES (BEFORE SYNC)
Target: Modern SharePoint Site Pages (.aspx -> .pdf renders)
Hierarchy: Detailed Subsite Breakdown (Discovered Pages, Filtered Pages, Valid Pages Expected to Sync)
Source Engine: Proven check_syncall_before.py Engine
Output: Terminal Display + Auto-Saves to check_pages_before_sync.txt
Location: app/v12-category/app/check/check_pages_before_sync.py
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

def extract_subsite_path(sp_url):
    if not sp_url:
        return "Unknown"
    try:
        parsed = urllib.parse.urlparse(sp_url)
        path = parsed.path
        if "/sites/" in path:
            path = path.split("/sites/", 1)[1]
        path = path.replace("/SitePages", "").replace("/sitepages", "")
        parts = [p for p in path.split("/") if p and not p.lower().endswith(".aspx")]
        if parts:
            return "/".join(parts)
    except Exception:
        pass
    return "DEN-Portal"

def evaluate_page_filters(page_name, page_url, ignore_keywords, filter_published, item_obj=None):
    web_url = (page_url or "").lower()
    if "/sitepages/templates/" in web_url:
        return True, "Filter A (Template Placeholder)"
    for kw in ignore_keywords:
        if kw.lower() in web_url or kw.lower() in (page_name or "").lower():
            return True, f"Filter B (Keyword '{kw}')"
    if filter_published and item_obj:
        promoted_state = item_obj.get("promotedState") or item_obj.get("publishingState", {}).get("level")
        version_str = item_obj.get("_UIVersionString") or item_obj.get("version", {}).get("label")
        if promoted_state == 1:
            return True, "Filter C (Draft News Post)"
        if version_str and not version_str.endswith(".0"):
            return True, f"Filter C (Draft Version {version_str})"
    return False, None

def main():
    report_dir = os.path.join(ROOT_DIR, "report")
    os.makedirs(report_dir, exist_ok=True)
    output_filename = os.path.join(report_dir, "check_pages_before_sync.txt")
    tee = TeeLogger(output_filename)
    original_stdout = sys.stdout
    sys.stdout = tee

    try:
        print("=" * 95)
        print("⚡ MODERN SITE PAGES PRE-SYNC DRY-RUN AUDIT & FILTER COMPLIANCE REPORT")
        print("=" * 95)

        params = load_parameters()
        tenant_id = params.get("CONFIG_M365_Tenant_Id")
        client_id = params.get("CONFIG_M365_Client_Id")
        secret_name = params.get("CONFIG_M365_Secret_Name")
        hostname = params.get("CONFIG_Sharepoint_Hostname") or params.get("CONFIG_SharePoint_Hostname", "maxis365.sharepoint.com")
        bucket_name = params.get("CONFIG_GCS_Bucket")
        ignore_keywords = params.get("CONFIG_Ignore_Path_Keywords", [])
        filter_published = params.get("CONFIG_Filter_Published_Pages_Only", True)

        print(f"• Target Tenant Hostname       : {hostname}")
        print(f"• Target GCS Bucket           : gs://{bucket_name}")
        print(f"• Active Ignore Path Keywords : {ignore_keywords}")
        print(f"• Filter Published Pages Only : {filter_published}")
        print("-" * 95)

        secret_val = get_secret_gcloud(secret_name) if secret_name and secret_name.startswith("projects/") else secret_name
        token = get_graph_token(tenant_id, client_id, secret_val)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        root_paths = set()
        single_site = params.get("CONFIG_Sharepoint_Sites")
        if single_site:
            root_paths.add(single_site)
        for cat in params.get("CONFIG_Categories", []):
            cat_site = cat.get("sharepoint_site")
            if isinstance(cat_site, str):
                root_paths.add(cat_site)
            elif isinstance(cat_site, list):
                for s in cat_site:
                    root_paths.add(s)

        if not root_paths:
            root_paths.add("sites/DEN")

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

        target_sites = []
        seen_site_ids = set()
        for r_path in root_paths:
            site_name_clean = r_path[len("sites/"):] if r_path.startswith("sites/") else r_path
            site_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{site_name_clean}"
            try:
                req = urllib.request.Request(site_url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    site_data = json.loads(resp.read().decode("utf-8"))
                    site_id = site_data.get("id")
                    if site_id and site_id not in seen_site_ids:
                        seen_site_ids.add(site_id)
                        target_sites.append({"id": site_id, "name": site_name_clean, "prefix": ""})
                        sub_list = get_all_subsites_recursive(site_id, "")
                        for sub in sub_list:
                            if sub["id"] not in seen_site_ids:
                                seen_site_ids.add(sub["id"])
                                target_sites.append(sub)
            except Exception:
                pass

        def scan_sp_pages(s):
            s_id = s["id"]
            discovered_pages = []
            seen_names = set()
            try:
                pages = graph_get_paginated(f"https://graph.microsoft.com/v1.0/sites/{s_id}/pages", headers, max_retries=2, timeout=15)
                for p in pages:
                    pname = p.get("name", "Page.aspx")
                    if pname and pname not in seen_names:
                        seen_names.add(pname)
                        discovered_pages.append((pname, p.get("webUrl", ""), p))
            except Exception:
                pass
            return discovered_pages

        all_sp_tuples = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(scan_sp_pages, s) for s in target_sites]
            for f in concurrent.futures.as_completed(futures):
                try:
                    all_sp_tuples.extend(f.result())
                except Exception:
                    pass

        subsite_discovered = defaultdict(int)
        subsite_filtered = defaultdict(int)
        filter_breakdown = defaultdict(int)

        for pname, web_url, item_obj in all_sp_tuples:
            sub_p = extract_subsite_path(web_url)
            subsite_discovered[sub_p] += 1
            is_filt, filt_reason = evaluate_page_filters(pname, web_url, ignore_keywords, filter_published, item_obj)
            if is_filt:
                subsite_filtered[sub_p] += 1
                filter_breakdown[filt_reason] += 1

        all_keys = sorted(set(list(subsite_discovered.keys())))

        print("\n" + "=" * 95)
        print("📊 PRE-SYNC PAGES DETAILED RECONCILIATION BY SUBSITE & SUB-CATEGORY")
        print("=" * 95)
        print(f"{'Subsite / Sub-Category Path':<40}{'Discovered Pages':<18}{'Filtered Pages':<18}{'Expected Valid Pages':<20}")
        print("-" * 95)

        total_disc = sum(subsite_discovered.values())
        total_filt = sum(subsite_filtered.values())

        for key in all_keys:
            disc = subsite_discovered[key]
            filt = subsite_filtered[key]
            valid = disc - filt
            print(f"{key:<40}{disc:<18}{filt:<18}{valid:<20}")

        print("=" * 95)
        print(f"{'TOTAL PAGES ACROSS TENANT':<40}{total_disc:<18}{total_filt:<18}{total_disc - total_filt:<20}")
        print("=" * 95)

        print("\n" + "=" * 95)
        print("📊 PRE-SYNC PAGES RECONCILIATION SUMMARY")
        print("=" * 95)
        print(f"• Total Discovered SharePoint Pages        : {total_disc} Pages")
        print(f"• Filtered / Excluded Pages (Skipped)      : {total_filt} Pages")
        print(f"• Expected Valid Pages to Sync to GCS      : {total_disc - total_filt} Pages")
        if filter_breakdown:
            print("  └─ Active Filter Rule Triggers Breakdown:")
            for reason, count in filter_breakdown.items():
                print(f"     - {reason}: {count} pages")
        print("=" * 95)
        print(f"\n💾 Report auto-saved to: {os.path.abspath(output_filename)}")

    finally:
        sys.stdout = original_stdout
        tee.close()

if __name__ == "__main__":
    main()
