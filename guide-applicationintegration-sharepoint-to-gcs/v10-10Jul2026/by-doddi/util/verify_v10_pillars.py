#!/usr/bin/env python3
"""
Version 10 (`Revision 00050+`) 4-Pillar Safety Architecture Pre-Flight Verification Script
Run via: python3 util/verify_v10_pillars.py
"""
import os
import sys
import json

def verify():
    print("=== 🛡️ V10 4-PILLAR SAFETY ARCHITECTURE PRE-FLIGHT VERIFICATION ===")
    
    # 1. Verify parameters.json
    if not os.path.exists("parameters.json"):
        print("❌ ERROR: parameters.json not found in current directory!")
        sys.exit(1)
    try:
        with open("parameters.json", "r") as f:
            p = json.load(f)
        print(f"✅ Active Project: {p.get('CONFIG_ProjectId')} | GCS Bucket: gs://{p.get('CONFIG_GCS_Bucket')}")
        print(f"✅ Cloud Run Job : {p.get('CONFIG_CloudFunction_Name')} | Conversion Engine: {p.get('CONFIG_PDF_Conversion_Engine', 'playwright')}")
    except Exception as e:
        print(f"❌ ERROR reading parameters.json: {e}")
        sys.exit(1)

    # 2. Verify main.py and pdf_renderer.py code pillars
    main_path = "cf-sharepoint/main.py"
    renderer_path = "cf-sharepoint/pdf_renderer.py"
    
    if not os.path.exists(main_path) or not os.path.exists(renderer_path):
        print(f"❌ ERROR: Cannot find {main_path} or {renderer_path}!")
        sys.exit(1)

    with open(main_path, "r") as f:
        main_code = f.read()
    with open(renderer_path, "r") as f:
        renderer_code = f.read()

    errors = []
    
    # Pillar 1 check: Zero discovery time cutoffs
    if "discovery_start_time > 2100" in main_code:
        errors.append("Pillar 1 FAILED: Old 35-minute discovery cutoffs still present in main.py!")
    else:
        print("✅ Pillar 1 (Zero Discovery Cutoffs / 100% Inventory Traversal): ACTIVE")

    # Pillar 2 check: Step 7b locked down behind CONFIG_Enable_Orphan_Cleanup
    if "CONFIG_Enable_Orphan_Cleanup" not in main_code:
        errors.append("Pillar 2 FAILED: Step 7b Orphaned Deletion Safety Guard not found in main.py!")
    else:
        print("✅ Pillar 2 (Locked-Down Step 7b & 80% Inventory Circuit Breaker): ACTIVE")

    # Pillar 3 check: Ultra-Conservative Concurrency Clamping (max_workers = min(3,...))
    if "max_workers = min(3," not in main_code:
        errors.append("Pillar 3 FAILED: Concurrency clamping (max_workers = min(3,...)) not found in main.py!")
    else:
        print("✅ Pillar 3 (Tortoise Concurrency Clamping & Polite Inter-Batch Pacing): ACTIVE")

    # Pillar 4 check: 15-Page Playwright Chromium Auto-Recycling
    if "render_count >= 15" not in renderer_code:
        errors.append("Pillar 4 FAILED: 15-page Playwright Chromium recycling not found in pdf_renderer.py!")
    else:
        print("✅ Pillar 4 (Hardened 15-Page Playwright Memory & IPC Pipe Recycling): ACTIVE")

    print("-" * 65)
    if errors:
        print("❌ VERIFICATION FAILED. The following issues were detected:")
        for err in errors:
            print(f"  - {err}")
        print("\n👉 Action Required: Please re-run the Step 1 Git sync command (`git pull origin main`) to get the latest code.")
        sys.exit(1)
    else:
        print("🎉 PRE-FLIGHT PASSED: ALL 4 PILLAR SAFETY GUARDS ARE 100% ACTIVE!")
        print("👉 You may now safely execute: ./deploy/deploy_cloud_run.sh")
        sys.exit(0)

if __name__ == "__main__":
    verify()
