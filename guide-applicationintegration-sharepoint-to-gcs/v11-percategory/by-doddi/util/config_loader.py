#!/usr/bin/env python3
"""
Rugged Configuration Loader Utility (v11-percategory)
Loads parameters.json (Static Infra & Auth) and sites-sync.json (Dynamic Category Matrix).
Supports reading sites-sync.json from local disk OR directly from Google Cloud Storage (gs://<bucket>/config/sites-sync.json).
"""

import os
import json
from typing import Dict, Any, Optional

def load_sites_sync_config(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Loads sites-sync.json category configuration.
    1. Checks local paths ('sites-sync.json', 'config/sites-sync.json', '../sites-sync.json').
    2. If running inside Cloud Run or GCS override specified, attempts to download from GCS bucket.
    """
    local_paths = [
        "sites-sync.json",
        "config/sites-sync.json",
        os.path.join(os.path.dirname(__file__), "../sites-sync.json"),
        os.path.join(os.path.dirname(__file__), "../config/sites-sync.json"),
        os.path.join(os.path.dirname(__file__), "sites-sync.json"),
        os.path.join(os.path.dirname(__file__), "config/sites-sync.json")
    ]

    for p in local_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "categories" in data:
                        return data
            except Exception as e:
                print(f"Warning: Could not parse local {p}: {e}")

    # Fallback to GCS if params provided and bucket available
    if params and isinstance(params, dict):
        bucket_name = params.get("CONFIG_GCS_Bucket")
        if bucket_name:
            try:
                from google.cloud import storage
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                for gcs_path in ["sites-sync.json", "config/sites-sync.json"]:
                    blob = bucket.blob(gcs_path)
                    if blob.exists():
                        content = blob.download_as_text()
                        data = json.loads(content)
                        print(f"✅ Loaded sites-sync.json from gs://{bucket_name}/{gcs_path}")
                        return data
            except Exception as e:
                print(f"Warning: Could not fetch sites-sync.json from GCS bucket {bucket_name}: {e}")

    # Return default empty structure if none found
    print("Warning: sites-sync.json not found locally or in GCS. Returning empty category matrix.")
    return {"root_portal_site": "sites/DEN", "categories": []}
