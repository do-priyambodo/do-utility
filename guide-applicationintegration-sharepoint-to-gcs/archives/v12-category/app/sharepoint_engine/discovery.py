#!/usr/bin/env python3
"""
Unified SharePoint Discovery Engine (v10-10Jul2026)
Single Source of Truth for Enterprise 4-Strategy Discovery across both Local CLI Audits and Cloud Run Container services.
Guarantees zero counting drift between local diagnostic runs and production container executions.
"""

from typing import List, Dict, Any, Set, Tuple
from collections import deque
import hashlib

def classify_drive_item(item: Dict[str, Any], parent_path: str, subsite_name: str) -> Tuple[Dict[str, Any], bool]:
    """
    Classifies a Graph API drive item into a standardized item dictionary.
    Returns (item_obj, is_page) where is_page=True if the item is a Modern Site Page (.aspx -> .pdf).
    Applies Option 2 Flattened SHA-256 Hash Suffixing (_hash[:8]) while preserving human-readable Name.
    """
    item_name = item.get("name", "")
    item_id = str(item.get("id") or item.get("webUrl") or item_name)
    path_hash = hashlib.sha256(item_id.encode('utf-8')).hexdigest()[:8]

    if item_name.lower().endswith(".aspx"):
        page_base = item_name[:-5]
        pdf_name = f"{page_base}_{path_hash}.pdf"
        rel_page_path = f"pages/{pdf_name}"
        return {
            "Name": item_name.replace(".aspx", ".pdf"),
            "RelativePath": rel_page_path,
            "IsPage": True,
            "Subsite": subsite_name,
            "Modified": item.get("lastModifiedDateTime"),
            "_filename": pdf_name,
            "_folder_path": parent_path.rstrip("/")
        }, True
    else:
        if "." in item_name:
            file_base = item_name.rsplit(".", 1)[0]
            ext = item_name.rsplit(".", 1)[-1]
            hashed_filename = f"{file_base}_{path_hash}.{ext}"
        else:
            hashed_filename = f"{item_name}_{path_hash}"
        return {
            "Name": item_name,
            "RelativePath": hashed_filename,
            "IsPage": False,
            "Subsite": subsite_name,
            "Modified": item.get("lastModifiedDateTime"),
            "_filename": hashed_filename,
            "_folder_path": parent_path.rstrip("/")
        }, False

def deduplicate_discovered_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates discovered assets by RelativePath while preserving order.
    """
    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for itm in items:
        rel = itm.get("RelativePath", "")
        if rel and rel not in seen:
            seen.add(rel)
            deduped.append(itm)
    return deduped
