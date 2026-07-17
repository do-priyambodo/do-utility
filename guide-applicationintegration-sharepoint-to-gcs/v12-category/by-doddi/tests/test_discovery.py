#!/usr/bin/env python3
"""
Unit tests for cf-sharepoint/sharepoint_engine/discovery.py (Option 2 Flattened SHA-256 Hash Suffixing)
Verifies correct item classification (.aspx -> .pdf Modern Site Pages vs regular document files), hash suffix derivation, human-readable titles, and deduplication.
"""

import sys
import os
import unittest
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cf-sharepoint")))
from sharepoint_engine.discovery import classify_drive_item, deduplicate_discovered_items

class TestDiscoveryEngine(unittest.TestCase):
    def test_classify_aspx_page(self):
        raw_item = {"name": "Welcome.aspx", "lastModifiedDateTime": "2026-07-10T10:00:00Z"}
        obj, is_page = classify_drive_item(raw_item, "SitePages/", "Home")
        self.assertTrue(is_page)
        self.assertTrue(obj["IsPage"])
        self.assertEqual(obj["Name"], "Welcome.pdf")  # Clean human-readable title!
        expected_hash = hashlib.sha256(b"Welcome.aspx").hexdigest()[:8]
        self.assertEqual(obj["RelativePath"], f"pages/Welcome_{expected_hash}.pdf")
        self.assertEqual(obj["_filename"], f"Welcome_{expected_hash}.pdf")
        self.assertEqual(obj["_folder_path"], "SitePages")  # Preserved breadcrumb!

    def test_classify_regular_file(self):
        raw_item = {"name": "Report.docx", "lastModifiedDateTime": "2026-07-10T10:00:00Z"}
        obj, is_page = classify_drive_item(raw_item, "Finance/Q3/", "Business")
        self.assertFalse(is_page)
        self.assertFalse(obj["IsPage"])
        self.assertEqual(obj["Name"], "Report.docx")  # Clean human-readable title!
        expected_hash = hashlib.sha256(b"Report.docx").hexdigest()[:8]
        self.assertEqual(obj["RelativePath"], f"Report_{expected_hash}.docx")  # Strictly flattened!
        self.assertEqual(obj["_filename"], f"Report_{expected_hash}.docx")
        self.assertEqual(obj["_folder_path"], "Finance/Q3")  # Preserved breadcrumb!

    def test_deduplicate_discovered_items(self):
        items = [
            {"Name": "Welcome.pdf", "RelativePath": "pages/Welcome_3fad7a44.pdf", "IsPage": True},
            {"Name": "Welcome.pdf", "RelativePath": "pages/Welcome_3fad7a44.pdf", "IsPage": True}, # duplicate
            {"Name": "Report.docx", "RelativePath": "Report_d2b6796a.docx", "IsPage": False}
        ]
        deduped = deduplicate_discovered_items(items)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["RelativePath"], "pages/Welcome_3fad7a44.pdf")
        self.assertEqual(deduped[1]["RelativePath"], "Report_d2b6796a.docx")

if __name__ == "__main__":
    unittest.main()
