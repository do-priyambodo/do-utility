#!/usr/bin/env python3
"""
Unified SharePoint Discovery Engine (v10-10Jul2026)
Single Source of Truth for Enterprise 4-Strategy Discovery across both Local CLI Audits and Cloud Run Container services.
Guarantees zero counting drift between local diagnostic runs and production container executions.
"""

from typing import List, Dict, Any, Set, Tuple
from collections import deque

def classify_drive_item(item: Dict[str, Any], parent_path: str, subsite_name: str) -> Tuple[Dict[str, Any], bool]:
    """
    Classifies a Graph API drive item into a standardized item dictionary.
    Returns (item_obj, is_page) where is_page=True if the item is a Modern Site Page (.aspx -> .pdf).
    """
    item_name = item.get("name", "")
    if item_name.lower().endswith(".aspx"):
        pdf_name = item_name.replace(".aspx", ".pdf")
        rel_page_path = f"pages/{parent_path}{pdf_name}"
        return {
            "Name": pdf_name,
            "RelativePath": rel_page_path,
            "IsPage": True,
            "Subsite": subsite_name,
            "Modified": item.get("lastModifiedDateTime")
        }, True
    else:
        rel_path = f"{parent_path}{item_name}"
        return {
            "Name": item_name,
            "RelativePath": rel_path,
            "IsPage": False,
            "Subsite": subsite_name,
            "Modified": item.get("lastModifiedDateTime")
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
