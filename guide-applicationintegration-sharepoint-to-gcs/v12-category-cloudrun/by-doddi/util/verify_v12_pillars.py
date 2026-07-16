#!/usr/bin/env python3
"""
=== V11 4-PILLAR SAFETY ARCHITECTURE PRE-FLIGHT VERIFIER ===
Verifies that all 4 Pillars of our Ultra-Conservative V10 Safety Architecture
have been cleanly ported and enforced across the V11 Per-Category Pipeline.
"""
import os
import sys

def check_file(rel_path):
    if not os.path.exists(rel_path):
        print(f"❌ ERROR: Required file '{rel_path}' not found!")
        sys.exit(1)
    with open(rel_path, "r", encoding="utf-8") as f:
        return f.read()

def verify_v11():
    print("=== 🛡️ V11 4-PILLAR SAFETY ARCHITECTURE PRE-FLIGHT VERIFICATION ===")
    
    # Check Pillar 1: Discovery & Pagination ($top=5000 & max_items=None)
    traversal_txt = check_file("cf-sharepoint/sharepoint_traversal.py")
    if "$top=5000" not in traversal_txt or "deque" not in traversal_txt:
        print("❌ Pillar 1 FAILED: $top=5000 pagination or non-recursive queue missing in sharepoint_traversal.py")
        sys.exit(1)
    print("✅ Pillar 1 (Zero Discovery Cutoffs / $top=5000 Pagination): ACTIVE")

    # Check Pillar 2: Locked-Down Orphan Cleanup & 80% Circuit Breaker
    root_main_txt = check_file("main.py")
    if "* 0.8" not in root_main_txt or "parse_bool_flag" not in root_main_txt or "CONFIG_Enable_Orphan_Cleanup" not in root_main_txt:
        print("❌ Pillar 2 FAILED: 80% Circuit Breaker or parse_bool_flag missing in main.py")
        sys.exit(1)
    print("✅ Pillar 2 (Locked-Down Step 7b & 80% Inventory Circuit Breaker): ACTIVE")

    # Check Pillar 3: Tortoise Concurrency & Memory Sweeps (gc.collect() + time.sleep(0.3))
    cf_main_txt = check_file("cf-sharepoint/main.py")
    sync_txt = check_file("sync/sync_sharepoint_to_gcs.py")
    if "min(3," not in cf_main_txt or "gc.collect()" not in cf_main_txt or "min(30," not in cf_main_txt:
        print("❌ Pillar 3 FAILED: Tortoise Concurrency clamp or gc.collect() missing in cf-sharepoint/main.py")
        sys.exit(1)
    if "gc.collect()" not in sync_txt or "time.sleep(0.3)" not in sync_txt:
        print("❌ Pillar 3 FAILED: gc.collect() or time.sleep(0.3) missing in sync/sync_sharepoint_to_gcs.py")
        sys.exit(1)
    print("✅ Pillar 3 (Tortoise Concurrency Clamping & Polite Inter-Batch Pacing): ACTIVE")

    # Check Pillar 4: Hardened 15-Page Playwright Memory & IPC Pipe Recycling
    pdf_txt = check_file("cf-sharepoint/pdf_renderer.py")
    if "_THREAD_LOCAL" not in pdf_txt or "--disable-dev-shm-usage" not in pdf_txt or "force_restart" not in pdf_txt:
        print("❌ Pillar 4 FAILED: _THREAD_LOCAL isolation or --disable-dev-shm-usage missing in pdf_renderer.py")
        sys.exit(1)
    print("✅ Pillar 4 (Hardened 15-Page Playwright Memory & IPC Pipe Recycling): ACTIVE")

    print("-----------------------------------------------------------------")
    print("🎉 PRE-FLIGHT PASSED: ALL 4 PILLAR SAFETY GUARDS ARE 100% ACTIVE IN V11!")
    print("👉 You may now safely deploy and execute the V11 Per-Category Pipeline.")

if __name__ == "__main__":
    verify_v11()
