# 🔮 Architectural Considerations & Hardened Baseline Porting Guide for Version 11 (`consideration-for-v11.md`)

**Date Recorded:** 15 July 2026 at 15:00 MYT / 07:00 UTC  
**Target Architecture:** Version 11 Per-Category Distributed Engine (`app/v11-percategory/by-doddi/`)  
**Source Hardened Baseline:** Version 10 Continuous Engine (`Revision 00050+` in `app/v10-10Jul2026/by-doddi/`)

---

## 🎯 Executive Summary & Architectural Porting Mandate

When we eventually begin implementation on **Version 11 (`v11-percategory`)**, the system will partition the master SharePoint repository (`sites/System-Procedure`, `sites/Quicklinks`, `sites/Hotlink`, `sites/FAQ`, and `sites/DEN`) across **multiple independent, isolated Cloud Run Jobs**, each responsible for a specific subsite category or tenant scope.

To guarantee that **Version 11 NEVER experiences the Out-of-Memory (`Signal 9`) crashes, discovery cutoffs, API quota rejections, or accidental GCS object purges** that we fought and cured in Version 10, **every single V11 worker container MUST strictly inherit the 4-Pillar Hardened Ultra-Conservative Architecture** documented below. 

Under no circumstances should a V11 worker revert to aggressive concurrency, unmanaged memory loops, or unchecked Phase 1 time cutoffs.

---

## 🏛️ The 4 Hardened V10 Pillars That Must Be Ported into V11

### Pillar 1: 100% Full Phase 1 Discovery (`0% Cutoffs & Universal $top=25 Paging`)
* **V10 Problem & Lesson:** In earlier V10 builds, `_strat1_pages` through `_strat4_pages` inside `main.py` enforced artificial 35-minute and 30-minute discovery cutoffs (`if time.time() - discovery_start_time > 2100: break`), and queried Graph API with `$top=100/200`. On massive subfolders, Graph API timed out or throttled, causing Phase 1 to abort early and dropping page counts from `5,412` down to `1,544`.
* **Required V11 Implementation (`main.py`, `sharepoint_traversal.py`, & `graph_client.py` in `v11-percategory/`):**
  1. **Zero Time Cutoffs:** Remove all `time.time() - discovery_start_time > ...` checks from every discovery routine inside V11's category crawlers. Each category worker must traverse its assigned root subsite to **100% completion** without time ceilings.
  2. **Standardized Page Size:** All OData folder and child listing queries across `graph_client.py` in V11 must use a uniform **`$top=25`** parameter (`.../children?$top=25`).
  3. **Resilient Graph Paging (`graph_get_paginated`):** Set `max_retries=5, timeout=30` and enforce strict **`Retry-After` HTTP header compliance** (`HTTP 429, 502, 503, 504`) so the crawler peacefully pauses when Microsoft 365 throttles during peak hours.

### Pillar 2: Locked-Down Orphaned Item Cleanup (`Step 7b Circuit Breaker`)
* **V10 Problem & Lesson:** When Graph API returned a partial discovery scan due to network delays, `Step 7b` compared that partial list against `gcs_cache` and deleted all "missing" historical PDFs from GCS (`stale_blob.delete()`), wiping out 3,868 valid pages.
* **Required V11 Implementation (`main.py` inside each V11 worker):**
  1. **Disabled by Default:** Require an explicit boolean flag (`parse_bool_flag(params.get("CONFIG_Enable_Orphan_Cleanup", False), default=False)`) before ever executing GCS object deletions.
  2. **80% Inventory Circuit Breaker:** Add the exact safety check:
     ```python
     if len(all_list) < len(gcs_cache) * 0.8:
         print(f"🛑 Safety Circuit Breaker: Discovered items ({len(all_list)}) significantly smaller than cached GCS inventory ({len(gcs_cache)}). Aborting orphan cleanup to prevent accidental data loss from partial scans/timeouts!")
     ```
  3. **Scoped Partitioning Protection:** Because V11 runs on specific subsite categories (e.g., *only* `sites/DEN` or *only* `sites/FAQ`), the `active_gcs_paths` verification loop **must only compare and clean up GCS objects whose relative paths match the active worker's assigned subsite prefix**. Never allow the `sites/DEN` worker to delete `sites/FAQ` objects from a shared GCS bucket!

### Pillar 3: Ultra-Conservative Batching & Polite Pacing (`The Tortoise vs. Hare Strategy`)
* **V10 Problem & Lesson:** Spawning 5 parallel worker threads (`raw_workers = 5`) while firing back-to-back `requests.post()` payloads at Google Cloud Application Integration saturated API quotas (`HTTP 429 / 503`) and triggered CPU starvation across concurrent Playwright browser instances.
* **Required V11 Implementation (`main.py` lines 610–730 equivalent in V11):**
  1. **Hard-Capped Concurrency:** Even if `parameters.json` requests 5 or 10 parallel workers (`"CONFIG_Max_Parallel_Workers": 5`), V11 worker code must hard-cap concurrency using:
     ```python
     max_workers = min(3, max(1, raw_workers))
     ```
  2. **Adaptive API Payload Sizing:** Continue using `CONFIG_File_Batch_Size: 10` and `CONFIG_Batch_Size: 10` for `Parent_Files_List` JSON payloads sent to Application Integration, keeping individual HTTP requests lightweight (~100 KB for files, ~2 MB for Base64 PDFs).
  3. **Connection Pooling & Inter-Batch Sleep:** Use a persistent `requests.Session()` mounted with `HTTPAdapter(max_retries=sched_retries, pool_connections=max_workers, pool_maxsize=max_workers * 2)`. After every `200 OK` batch scheduled, enforce a **polite 300ms breather (`time.sleep(0.3)`)** before sending the next batch.

### Pillar 4: Hardened Playwright & Node IPC Memory Management (`0% Signal 9 OOM Guarantee`)
* **V10 Problem & Lesson:** In earlier revisions, `_render_lazy_page` ran via `ThreadPoolExecutor(max_workers=5)` across 100-item chunks. Storing 100 heavy Base64 PDF strings in RAM while Playwright and Node IPC pipes accumulated memory over 215 chunks gradually hit the 8 GiB container ceiling, terminating the process with `Container terminated on signal 9 (SIGKILL)`.
* **Required V11 Implementation (`pdf_renderer.py` & `main.py` in `v11-percategory/`):**
  1. **Thread-Local Greenlet Isolation:** Initialize Playwright browsers and `asyncio` event loops on a per-thread basis (`_THREAD_LOCAL = threading.local()`) to eliminate `greenlet.error: cannot switch to a different thread` (`Signal 5 SIGTRAP`).
  2. **Aggressive Chromium Context Recycling:** Inside `pdf_renderer.py`, force Chromium context and Node IPC recycling every **15 pages** per worker thread:
     ```python
     if _THREAD_LOCAL.render_count >= 15:
         # Close and re-launch persistent browser context to flush Chromium/Node memory
     ```
  3. **Bite-Sized Pipelined Chunks (`20–30 items max`):** Hard-cap memory processing loop chunks:
     ```python
     chunk_size = min(30, max(20, file_batch_size * max_workers))
     ```
  4. **Targeted Thread-Pool Rendering:** Only run `ThreadPoolExecutor(max_workers=max_workers)` on `[item for item in chunk if item.get("IsPage") and not item.get("VirtualContent")]`. Do not waste thread-pool overhead on regular files (`.docx`, `.png`, `.xlsx`) that do not require Playwright conversion.
  5. **Immediate Memory Eviction & GC:** Right after dispatching a chunk of batches to Application Integration, evict Base64 strings from active RAM, sleep for `500ms`, and trigger garbage collection:
     ```python
     for item in chunk:
         item.pop("VirtualContent", None)
     time.sleep(0.5)
     gc.collect()
     ```

---

## 📋 Exact Checklist When Starting Version 11 Implementation

When Doddi authorizes work on `Version 11 (`v11-percategory`)`, run through this exact validation checklist before deploying any V11 worker container:

- [ ] **Verify `max_execution_seconds = 86400`** is hardcoded in V11's `main.py` (no 1-hour cutoffs).
- [ ] **Verify `discovery_start_time > 2100` cutoffs are absent** in V11's `sharepoint_traversal.py` and `main.py`.
- [ ] **Verify `$top=25` and `max_retries=5, timeout=30` with `Retry-After` backoff** are active in V11's `graph_client.py`.
- [ ] **Verify `max_workers = min(3, max(1, raw_workers))`** is active in V11's `main.py`.
- [ ] **Verify `chunk_size = min(30, max(20, file_batch_size * max_workers))`** and `gc.collect()` are active in V11's chunk processing loops.
- [ ] **Verify `_THREAD_LOCAL.render_count >= 15`** auto-recycling is active inside V11's `pdf_renderer.py`.
- [ ] **Verify `Step 7b Orphan Cleanup` has the 80% circuit breaker AND prefix-matching protection** so category workers don't delete each other's files from the shared GCS bucket.
- [ ] **Verify `deploy/deploy_cloud_run.sh` in V11 uses `--async` and REST API polling** to bypass VPC-SC log streaming blocks in Cloud Shell.

By adhering strictly to this transition checklist, **Version 11 will achieve multi-category distributed scalability while inheriting 100% of the rock-solid, crash-proof stability we achieved in Version 10.**
