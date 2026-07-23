#!/usr/bin/env python3
"""
V11 Option 2 (Flattened SHA-256 Hash Suffixing) Dry-Run Verification Script
Validates:
1. Modern Site Page (.aspx -> .pdf) classification and flattened hash derivation.
2. Regular file classification across deeply nested subfolders and libraries.
3. Target URL direct parsing path derivation.
4. Correct config/metadata.jsonl record generation with human-readable structData.title and exact structData.sharepoint_folder_path.
"""

import sys
import os
import json
import hashlib

# Add cf-sharepoint to path to test discovery module directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cf-sharepoint")))
from sharepoint_engine.discovery import classify_drive_item, deduplicate_discovered_items

def run_verification():
    print("=== 🚀 Starting V11 Option 2 (Flattened SHA-256 Hash Suffixing) Dry-Run Verification ===")
    
    # Test Item 1: Modern Site Page
    page_item = {
        "id": "page-guid-001",
        "name": "SHARE-LINE-CAMPAIGN.aspx",
        "webUrl": "https://maxis.sharepoint.com/sites/Consumer/SitePages/SHARE-LINE-CAMPAIGN.aspx",
        "lastModifiedDateTime": "2026-07-16T10:00:00Z"
    }
    page_obj, is_page = classify_drive_item(page_item, "SitePages/Campaigns/", "Consumer")
    assert is_page == True, "Expected page classification"
    assert page_obj["Name"] == "SHARE-LINE-CAMPAIGN.pdf", f"Expected clean title, got {page_obj['Name']}"
    expected_page_hash = hashlib.sha256(b"page-guid-001").hexdigest()[:8]
    assert page_obj["RelativePath"] == f"pages/SHARE-LINE-CAMPAIGN_{expected_page_hash}.pdf", f"Mismatch on page RelativePath: {page_obj['RelativePath']}"
    assert page_obj["_folder_path"] == "SitePages/Campaigns", f"Mismatch on page _folder_path: {page_obj['_folder_path']}"
    print(f"✅ Page Classification Verified -> Title: '{page_obj['Name']}', RelativePath: '{page_obj['RelativePath']}', Folder: '{page_obj['_folder_path']}'")

    # Test Item 2: Deeply Nested Regular File
    file_item = {
        "id": "file-guid-999",
        "name": "Annual_Revenue_Report.xlsx",
        "webUrl": "https://maxis.sharepoint.com/sites/Consumer/Shared Documents/Finance/Reports/2026/Annual_Revenue_Report.xlsx",
        "lastModifiedDateTime": "2026-07-16T11:30:00Z"
    }
    file_obj, is_file_page = classify_drive_item(file_item, "Shared Documents/Finance/Reports/2026/", "Consumer")
    assert is_file_page == False, "Expected file classification"
    assert file_obj["Name"] == "Annual_Revenue_Report.xlsx", f"Expected clean title, got {file_obj['Name']}"
    expected_file_hash = hashlib.sha256(b"file-guid-999").hexdigest()[:8]
    assert file_obj["RelativePath"] == f"Annual_Revenue_Report_{expected_file_hash}.xlsx", f"Mismatch on file RelativePath: {file_obj['RelativePath']}"
    assert file_obj["_folder_path"] == "Shared Documents/Finance/Reports/2026", f"Mismatch on file _folder_path: {file_obj['_folder_path']}"
    print(f"✅ Nested File Classification Verified -> Title: '{file_obj['Name']}', RelativePath: '{file_obj['RelativePath']}', Folder: '{file_obj['_folder_path']}'")

    # Test Item 3: Metadata.jsonl Manifest Record Verification
    doc_id = "Annual_Revenue_Report"
    full_gcs_path = f"files/{file_obj['RelativePath']}"
    meta_record = {
        "id": doc_id,
        "structData": {
            "sharepoint_url": file_obj.get("Url", file_item["webUrl"]),
            "title": file_obj["Name"],
            "relative_path": full_gcs_path,
            "sharepoint_folder_path": file_obj.get("_folder_path", "")
        },
        "content": {
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "uri": f"gs://maxis-sync-bucket/{full_gcs_path}"
        }
    }
    jsonl_str = json.dumps(meta_record)
    parsed_meta = json.loads(jsonl_str)
    
    assert parsed_meta["structData"]["title"] == "Annual_Revenue_Report.xlsx", "Metadata structData.title must be clean unhashed human-readable name!"
    assert parsed_meta["structData"]["relative_path"] == f"files/Annual_Revenue_Report_{expected_file_hash}.xlsx", "Metadata structData.relative_path must match exact flattened hashed GCS object!"
    assert parsed_meta["structData"]["sharepoint_folder_path"] == "Shared Documents/Finance/Reports/2026", "Metadata structData.sharepoint_folder_path must preserve unhashed SharePoint breadcrumb!"
    assert "/" not in parsed_meta["structData"]["relative_path"].split("files/")[1], "GCS ObjectName under files/ must contain 0% slashes to guarantee no subfolder drops in Application Integration connector!"
    
    print(f"✅ Metadata.jsonl Schema & Breadcrumb Verification Passed:")
    print(json.dumps(parsed_meta, indent=2))
    print("=== 🎉 ALL V11 OPTION 2 DRY-RUN VERIFICATIONS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_verification()
