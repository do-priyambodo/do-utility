#!/usr/bin/env python3
"""
Unit tests for cf-sharepoint/sharepoint_engine/discovery.py
Verifies correct item classification (.aspx -> .pdf Modern Site Pages vs regular document files) and deduplication.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cf-sharepoint")))
from sharepoint_engine.discovery import classify_drive_item, deduplicate_discovered_items

class TestDiscoveryEngine(unittest.TestCase):
    def test_classify_aspx_page(self):
        raw_item = {"name": "Welcome.aspx", "lastModifiedDateTime": "2026-07-10T10:00:00Z"}
        obj, is_page = classify_drive_item(raw_item, "", "Home")
        self.assertTrue(is_page)
        self.assertTrue(obj["IsPage"])
        self.assertEqual(obj["Name"], "Welcome.pdf")
        self.assertEqual(obj["RelativePath"], "pages/Welcome.pdf")

    def test_classify_regular_file(self):
        raw_item = {"name": "Report.docx", "lastModifiedDateTime": "2026-07-10T10:00:00Z"}
        obj, is_page = classify_drive_item(raw_item, "Finance/", "Business")
        self.assertFalse(is_page)
        self.assertFalse(obj["IsPage"])
        self.assertEqual(obj["Name"], "Report.docx")
        self.assertEqual(obj["RelativePath"], "Finance/Report.docx")

    def test_deduplicate_discovered_items(self):
        items = [
            {"Name": "Welcome.pdf", "RelativePath": "pages/Welcome.pdf", "IsPage": True},
            {"Name": "Welcome.pdf", "RelativePath": "pages/Welcome.pdf", "IsPage": True}, # duplicate
            {"Name": "Report.docx", "RelativePath": "Report.docx", "IsPage": False}
        ]
        deduped = deduplicate_discovered_items(items)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["RelativePath"], "pages/Welcome.pdf")
        self.assertEqual(deduped[1]["RelativePath"], "Report.docx")

if __name__ == "__main__":
    unittest.main()
