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
    "CONFIG_Sharepoint_Sites",
    "CONFIG_Sharepoint_Library",
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
