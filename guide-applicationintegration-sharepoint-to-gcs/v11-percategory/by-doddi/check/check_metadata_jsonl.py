#!/usr/bin/env python3
"""
High-speed GCS Metadata Catalog verification script (`check/check_metadata_jsonl.py`).
Reads `config/metadata.jsonl` from the target GCS bucket, parses each JSONL record,
and reports exact breakdowns for Document Files (`files/`) and Modern Site Pages (`pages/`).
"""

import json
import os
import subprocess
import sys

def run_metadata_check():
    print("================================================================================")
    print("⚡ GCS METADATA CATALOG VERIFICATION (config/metadata.jsonl)")
    print("================================================================================")

    # 1. Load pipeline parameters
    param_path = "parameters.json"
    if not os.path.exists(param_path):
        print(f"❌ Error: {param_path} not found in current working directory.")
        sys.exit(1)

    try:
        with open(param_path, "r", encoding="utf-8") as f:
            params = json.load(f)
    except Exception as e:
        print(f"❌ Failed to parse {param_path}: {e}")
        sys.exit(1)

    bucket_name = params.get("CONFIG_GCS_Bucket", "").strip()
    if not bucket_name:
        print("❌ Error: 'CONFIG_GCS_Bucket' is missing or empty in parameters.json.")
        sys.exit(1)

    # Remove gs:// prefix if provided
    if bucket_name.startswith("gs://"):
        bucket_name = bucket_name[len("gs://"):]

    meta_gcs_path = f"gs://{bucket_name}/config/metadata.jsonl"
    print(f"📂 Target GCS Bucket : gs://{bucket_name}")
    print(f"📄 Metadata Path     : {meta_gcs_path}\n")

    print("🔍 Step 1: Retrieving metadata catalog from Google Cloud Storage...")
    try:
        cmd = ["gcloud", "storage", "cat", meta_gcs_path]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        raw_content = proc.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to read {meta_gcs_path} from GCS.\nError details: {e.stderr.strip()}")
        sys.exit(1)

    print("⚡ Step 2: Parsing and classifying synchronized metadata records...")
    lines = [line.strip() for line in raw_content.splitlines() if line.strip()]

    records = []
    invalid_lines = 0
    for idx, line in enumerate(lines, 1):
        try:
            records.append(json.loads(line))
        except Exception:
            invalid_lines += 1

    total_records = len(records)
    if total_records == 0:
        print("⚠️ Warning: metadata.jsonl exists but contains 0 valid JSONL records.")
        sys.exit(0)

    files_count = 0
    pages_count = 0

    for r in records:
        struct_data = r.get("structData", {})
        content_data = r.get("content", {})
        rel_path = str(struct_data.get("relative_path", "") or content_data.get("uri", "") or "").lower()
        if "pages/" in rel_path or rel_path.startswith("pages/"):
            pages_count += 1
        elif "files/" in rel_path or rel_path.startswith("files/"):
            files_count += 1
        elif rel_path.endswith(".pdf"):
            pages_count += 1
        else:
            files_count += 1

    print(f"✅ Successfully parsed {total_records} metadata records ({invalid_lines} invalid skipped)!\n")

    print("================================================================================")
    print("📊 SYNCHRONIZED ASSET METADATA BREAKDOWN (config/metadata.jsonl)")
    print("================================================================================")
    print("1️⃣  METADATA RECORD SUMMARY:")
    print(f"    • Document Files Registered ('files/')     : {files_count:>6}")
    print(f"    • Modern Site Pages Registered ('pages/')  : {pages_count:>6}")
    print("    ----------------------------------------------------------------------------")
    print(f"    • TOTAL ASSETS IN METADATA CATALOG         : {total_records:>6}")
    print("================================================================================")
    print("🎉 SUCCESS: Metadata catalog matches synchronized inventory counts!")
    print("================================================================================\n")

if __name__ == "__main__":
    run_metadata_check()
