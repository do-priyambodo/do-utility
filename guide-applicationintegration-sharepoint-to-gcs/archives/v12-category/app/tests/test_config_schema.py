#!/usr/bin/env python3
"""
Unit tests for cf-sharepoint/config_schema.py
Verifies fail-fast behavior and default parameter normalization.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cf-sharepoint")))
from config_schema import validate_parameters

class TestConfigSchema(unittest.TestCase):
    def test_valid_parameters(self):
        valid_params = {
            "CONFIG_ProjectId": "test-project",
            "CONFIG_Location": "asia-southeast1",
            "CONFIG_GCS_Bucket": "test-bucket",
            "CONFIG_M365_Tenant_Id": "tenant-123",
            "CONFIG_M365_Client_Id": "client-123",
            "CONFIG_M365_Secret_Name": "secret-123",
            "CONFIG_SharePoint_Hostname": "test.sharepoint.com",
            "CONFIG_Sharepoint_Sites": "sites/test",
            "CONFIG_Sharepoint_Library": "Documents",
        }
        validated = validate_parameters(valid_params)
        self.assertEqual(validated["CONFIG_Batch_Size"], 5)
        self.assertTrue(validated["CONFIG_Sync_SharePoint_Files"])
        self.assertTrue(validated["CONFIG_Sync_SharePoint_Pages"])

    def test_missing_required_keys_raises_error(self):
        invalid_params = {
            "CONFIG_ProjectId": "test-project",
            # Missing required keys
        }
        with self.assertRaises(ValueError) as ctx:
            validate_parameters(invalid_params)
        self.assertIn("Configuration Validation Error", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
