#!/usr/bin/env python3
"""
=== CATEGORY MATRIX STRUCTURAL VERIFIER ===
Validates that config-category.json conforms to the V12 Category Sharding schema,
ensuring zero duplicate IDs, valid boolean flags, and clean subsite isolation.
"""
import json
import os
import sys

def verify_category_structure(file_path="config-category.json"):
    print(f"🔍 Inspecting structural integrity of category matrix '{file_path}'...")
    if not os.path.exists(file_path):
        fallback = os.path.join("cf-sharepoint", file_path)
        if os.path.exists(fallback):
            file_path = fallback
        else:
            print(f"❌ ERROR: Category file '{file_path}' not found!")
            sys.exit(1)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: '{file_path}' contains invalid JSON syntax: {e}")
        sys.exit(1)

    root_portal = data.get("root_portal_site")
    if not root_portal or not isinstance(root_portal, str):
        print(f"❌ ERROR: Missing required top-level string property 'root_portal_site' in '{file_path}'!")
        sys.exit(1)

    categories = data.get("categories")
    if not categories or not isinstance(categories, list) or len(categories) == 0:
        print(f"❌ ERROR: Property 'categories' must be a non-empty list of category objects!")
        sys.exit(1)

    seen_ids = set()
    seen_prefixes = set()
    active_count = 0

    print(f"\n📊 Scanning {len(categories)} defined category tiers under Root Portal: '{root_portal}':")
    print(f"-----------------------------------------------------------------------------------------")
    print(f"{'Order':<6} {'Category ID':<26} {'Active':<8} {'Subsites?':<10} {'GCS Prefix':<26}")
    print(f"-----------------------------------------------------------------------------------------")

    for idx, cat in enumerate(categories):
        cat_id = cat.get("category_id")
        if not cat_id or not isinstance(cat_id, str):
            print(f"❌ ERROR: Category at index {idx} is missing valid string 'category_id'!")
            sys.exit(1)

        if cat_id in seen_ids:
            print(f"❌ ERROR: Duplicate 'category_id' detected: '{cat_id}' at index {idx}!")
            sys.exit(1)
        seen_ids.add(cat_id)

        sp_site = cat.get("sharepoint_site")
        if not sp_site or (not isinstance(sp_site, str) and not isinstance(sp_site, list)):
            print(f"❌ ERROR: Category '{cat_id}' must define 'sharepoint_site' as a string URL or list of URLs!")
            sys.exit(1)

        inc_sub = cat.get("include_subsites")
        if not isinstance(inc_sub, bool):
            print(f"❌ ERROR: Category '{cat_id}' must define boolean 'include_subsites' (true/false) without quotes!")
            sys.exit(1)

        gcs_prefix = cat.get("gcs_destination_prefix")
        if not gcs_prefix or not isinstance(gcs_prefix, str):
            print(f"❌ ERROR: Category '{cat_id}' must define valid 'gcs_destination_prefix' string!")
            sys.exit(1)

        if gcs_prefix in seen_prefixes:
            print(f"⚠️ WARNING: Category '{cat_id}' shares GCS prefix '{gcs_prefix}' with another category. This may cause orphan cleanup collisions!")
        seen_prefixes.add(gcs_prefix)

        is_active = str(cat.get("active", "yes")).lower() in ("yes", "true", "1")
        if is_active:
            active_count += 1

        order = cat.get("order_to_sync", idx + 1)
        sub_str = "Yes (True)" if inc_sub else "No (Root)"
        act_str = "✅ Yes" if is_active else "⏸️ No"
        print(f"{order:<6} {cat_id:<26} {act_str:<8} {sub_str:<10} {gcs_prefix:<26}")

    print(f"-----------------------------------------------------------------------------------------")
    print(f"✅ CATEGORY MATRIX VALIDATION PASSED: {active_count}/{len(categories)} active categories configured cleanly!")
    print(f"-----------------------------------------------------------------------------------------\n")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "config-category.json"
    verify_category_structure(target)
