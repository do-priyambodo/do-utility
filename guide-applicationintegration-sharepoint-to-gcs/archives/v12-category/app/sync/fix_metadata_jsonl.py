#!/usr/bin/env python3
"""
fix_metadata_jsonl.py - Instant GCS Manifest Fixer

Repairs an existing gs://<bucket_name>/config/metadata.jsonl manifest file in Google Cloud Storage
without requiring any re-sync or re-download of files from SharePoint.

What it does:
  1. Reads the existing config/metadata.jsonl directly from GCS.
  2. Inspects every document record. If a document URI is missing the 'files/' or 'pages/' prefix,
     it automatically prepends 'files/' to format a valid GCS unstructured document URI.
  3. Re-uploads the corrected config/metadata.jsonl to GCS instantly.
"""

import os
import sys
import json
import subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
try:
    os.chdir(ROOT_DIR)
except Exception:
    pass

def main():
    print("================================================================================")
    print("🛠️ INSTANT GCS MANIFEST FIXER (config/metadata.jsonl)")
    print("================================================================================")

    if not os.path.exists("parameters.json"):
        print("❌ Error: parameters.json not found in working directory.")
        sys.exit(1)

    with open("parameters.json", "r") as f:
        params = json.load(f)

    bucket_name = params.get("CONFIG_GCS_Bucket", "")
    if not bucket_name:
        print("❌ Error: CONFIG_GCS_Bucket not found in parameters.json.")
        sys.exit(1)

    manifest_gcs_path = f"gs://{bucket_name}/config/metadata.jsonl"
    print(f"📂 Step 1: Downloading existing manifest from {manifest_gcs_path}...")

    try:
        raw_content = subprocess.check_output(
            ["gcloud", "storage", "cat", manifest_gcs_path],
            stderr=subprocess.DEVNULL
        ).decode("utf-8")
    except Exception as e:
        print(f"❌ Could not read {manifest_gcs_path}: {e}")
        sys.exit(1)

    lines = raw_content.splitlines()
    print(f"   🟢 Loaded {len(lines)} existing records.")

    print("⚡ Step 2: Repairing document URIs, relative paths, and MIME types...")
    fixed_lines = []
    fixed_uri_count = 0
    fixed_mime_count = 0

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

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            record = json.loads(line_str)
            content_obj = record.get("content", {})
            uri = content_obj.get("uri", "")

            prefix_root = f"gs://{bucket_name}/"
            if uri.startswith(prefix_root):
                rel = uri[len(prefix_root):]
                if not rel.startswith("pages/") and not rel.startswith("files/"):
                    new_rel = f"files/{rel}"
                    new_uri = f"gs://{bucket_name}/{new_rel}"
                    content_obj["uri"] = new_uri
                    record["content"] = content_obj

                    struct_data = record.get("structData", {})
                    if "relative_path" in struct_data and not struct_data["relative_path"].startswith("files/"):
                        struct_data["relative_path"] = new_rel
                        record["structData"] = struct_data

                    fixed_uri_count += 1

            # Fix MIME type if application/octet-stream or missing
            curr_mime = content_obj.get("mimeType", "")
            ext = uri.rsplit('.', 1)[-1].lower() if '.' in uri else ''
            if curr_mime == "application/octet-stream" or not curr_mime:
                new_mime = mime_map.get(ext, "application/pdf" if "/pages/" in uri else curr_mime)
                if new_mime and new_mime != curr_mime:
                    content_obj["mimeType"] = new_mime
                    record["content"] = content_obj
                    fixed_mime_count += 1

            fixed_lines.append(json.dumps(record))
        except Exception:
            fixed_lines.append(line_str)

    print(f"   🔧 Corrected {fixed_uri_count} document URI(s) and {fixed_mime_count} MIME type(s).")

    print("📤 Step 3: Re-uploading corrected manifest back to GCS...")
    fixed_payload = "\n".join(fixed_lines) + "\n"

    tmp_path = "/tmp/fixed_metadata.jsonl"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(fixed_payload)

    subprocess.check_call(
        ["gcloud", "storage", "cp", tmp_path, manifest_gcs_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    print(f"✅ Successfully updated {manifest_gcs_path}!")
    print("================================================================================")
    print("🎉 MANIFEST REPAIR COMPLETE! You can now run Vertex AI Datastore import cleanly.")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
