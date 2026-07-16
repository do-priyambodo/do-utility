#!/usr/bin/env python3
"""
=== CONFIGURATION PARAMETERS STRUCTURAL VERIFIER ===
Validates that config-parameters.json contains all mandatory GCP infrastructure,
M365 Graph API credentials, and safe execution tuning boundaries.
"""
import json
import os
import sys

def verify_parameters_structure(file_path="config-parameters.json"):
    print(f"🔍 Inspecting structural integrity of '{file_path}'...")
    if not os.path.exists(file_path):
        # Fallback check inside cf-sharepoint if run from root or subdirectory
        fallback = os.path.join("cf-sharepoint", file_path)
        if os.path.exists(fallback):
            file_path = fallback
        else:
            print(f"❌ ERROR: Configuration file '{file_path}' not found!")
            sys.exit(1)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: '{file_path}' contains invalid JSON syntax: {e}")
        sys.exit(1)

    # Required string parameters
    required_strings = [
        "CONFIG_ProjectId",
        "CONFIG_Location",
        "CONFIG_Service_Account",
        "CONFIG_GCS_Bucket",
        "CONFIG_M365_Tenant_Id",
        "CONFIG_M365_Client_Id",
        "CONFIG_M365_Secret_Name",
        "CONFIG_SharePoint_Hostname"
    ]

    missing = []
    for key in required_strings:
        val = data.get(key)
        if not val or not isinstance(val, str) or val.strip() == "":
            missing.append(key)

    if missing:
        print(f"❌ ERROR: Missing or empty mandatory string fields in '{file_path}': {missing}")
        sys.exit(1)

    # Numeric safety boundaries
    batch_size = data.get("CONFIG_Batch_Size", 5)
    file_batch = data.get("CONFIG_File_Batch_Size", batch_size * 20)
    page_batch = data.get("CONFIG_Page_Batch_Size", batch_size)
    workers = data.get("CONFIG_Max_Parallel_Workers", 5)

    if not (1 <= workers <= 10):
        print(f"⚠️ WARNING: CONFIG_Max_Parallel_Workers ({workers}) is outside safe boundaries (1..10). This may cause Graph API 429 throttling.")
    if file_batch > 200:
        print(f"⚠️ WARNING: CONFIG_File_Batch_Size ({file_batch}) > 200. This may exceed Application Integration 10 MB payload limits.")

    print("-----------------------------------------------------------------")
    print(f"✅ STRUCTURAL VALIDATION PASSED: '{file_path}' is 100% compliant!")
    print(f"   • GCP Project: {data.get('CONFIG_ProjectId')} ({data.get('CONFIG_Location')})")
    print(f"   • GCS Destination Bucket: gs://{data.get('CONFIG_GCS_Bucket')}")
    print(f"   • M365 Hostname: {data.get('CONFIG_SharePoint_Hostname')}")
    print(f"   • Concurrency & Batches: {workers} workers | File Batch: {file_batch} | Page Batch: {page_batch}")
    print("-----------------------------------------------------------------")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "config-parameters.json"
    verify_parameters_structure(target)
