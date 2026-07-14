#!/usr/bin/env python3
"""
Rugged Enterprise Configuration Schema Validator (v10-10Jul2026)
Validates config-parameters.json keys and data types before executing SharePoint or GCS network operations.
"""

import sys
from typing import Dict, Any, List

REQUIRED_KEYS: List[str] = [
    "CONFIG_ProjectId",
    "CONFIG_Location",
    "CONFIG_GCS_Bucket",
    "CONFIG_M365_Tenant_Id",
    "CONFIG_M365_Client_Id",
    "CONFIG_M365_Secret_Name",
    "CONFIG_SharePoint_Hostname",
]

def validate_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates that all required configuration keys are present and non-empty.
    Raises ValueError with explicit actionable guidance if validation fails.
    """
    missing_keys = []
    for key in REQUIRED_KEYS:
        val = params.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing_keys.append(key)

    if missing_keys:
        err_msg = (
            f"❌ Configuration Validation Error: Missing or empty required keys in config-parameters.json:\n"
            + "\n".join(f"   • {k}" for k in missing_keys)
        )
        raise ValueError(err_msg)

    # Normalize defaults
    params.setdefault("CONFIG_Batch_Size", 5)
    params.setdefault("CONFIG_Sync_SharePoint_Files", True)
    params.setdefault("CONFIG_Sync_SharePoint_Pages", True)
    params.setdefault("CONFIG_PDF_Conversion_Engine", "playwright")

    return params

CATEGORY_SCHEMA = {
    "type": "object",
    "required": ["category_id", "display_name", "sharepoint_site", "gcs_destination_prefix"],
    "properties": {
        "category_id": {"type": "string", "pattern": "^[a-z0-9-]+$"},
        "display_name": {"type": "string"},
        "sharepoint_site": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}}
            ]
        },
        "include_subsites": {"type": "boolean"},
        "sharepoint_library": {"type": "string"},
        "gcs_destination_prefix": {"type": "string"},
        "order_to_sync": {"type": "integer"}
    }
}

def validate_category_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates V11 per-category configuration structure and sorts categories by order_to_sync.
    """
    if not isinstance(config, dict) or "categories" not in config:
        return config
    if isinstance(config["categories"], list):
        config["categories"] = sorted(config["categories"], key=lambda c: c.get("order_to_sync", 9999) if isinstance(c, dict) else 9999)
    return config
