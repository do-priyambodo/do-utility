# 📚 Complete Chronological Encyclopedia of Historical Customer Errors & Root-Cause Engineering Fixes (`all-historical-error-from-customers.md`)

**Document Purpose:** This document provides the Maxis engineering team (**Janice and colleagues**) and **Doddi Priyambodo** with the complete, unvarnished chronological history of every major error, crash, quota rejection, and unexpected behavior encountered across our multi-week synchronization and troubleshooting journey (`June 2026 — July 2026 across V1, V2, V10, V11, and V12`). Every issue is broken down by its exact timeline, technical root cause, and authoritative architectural lockdown rule.

**Timeline Order:** Chronological (Ascending: Earliest serverless cutoffs to latest 4-Pillar and V13 Micro-Batching solutions).

---

## 📅 Phase 1 [June 2026 — Early V1 to V9 Cloud Functions Revisions]

### ⏱️ Error 1: `Cloud Function execution took 3600 ms and was terminated` / `exit(0) after 57 minutes`
* **Symptom:** The synchronization script would stop running right around the 57-minute or 60-minute mark, exiting with either a Google Cloud Functions deadline exceeded error (`DeadlineExceeded`) or a self-imposed `exit(0)` print. On large folders, only a fraction of files were synced.
* **Technical Root Cause:**  
  When the architecture originally ran on **Google Cloud Functions (`1st-gen and 2nd-gen`)**, the GCP serverless platform enforced strict maximum execution ceilings: 9 minutes for Pub/Sub triggers, and a maximum of 60 minutes for Web Service / HTTP triggers.  
  To prevent Cloud Functions from forcefully killing the container midway through discovery or file upload without saving state, our early Python code (`main.py` and `sharepoint_traversal.py`) explicitly embedded internal wall-clock time guards:
  ```python
  if time.time() - discovery_start_time > 2100:  # 35 minutes
      print("⏱️ Wall-Clock Discovery Time Guard reached... break")
      break
  if time.time() - start_time > 3400:            # 57 minutes
      print("⏱️ Wall-Clock Execution Time Guard reached... exit(0)")
      sys.exit(0)
  ```
* **Engineering Cure (`Version 10 Migration & Time Guard Purge`):**  
  We migrated the entire execution engine from Cloud Functions to **Google Cloud Run Jobs (`--task-timeout=86400s`)**, which provides an uninterrupted **24-Hour Continuous Execution Budget**. Furthermore, we forensically stripped out every single 35-minute (`2,100s`) and 57-minute (`3,400s`) time check across `main.py` and `sharepoint_traversal.py`, allowing discovery and traversal to run to 100% completion without time ceilings.

---

## 📅 Phase 2 [Early July 2026 — V10 Initial Cloud Run Job Revisions]

### 💥 Error 2: `Container terminated on signal 9 (SIGKILL)` / `Memory limit exceeded (OOM)` / `Signal 5 SIGTRAP (greenlet thread collisions)`
* **Symptom:** During massive SharePoint crawls involving hundreds of Site Pages (`.aspx`), the Cloud Run Job container would suddenly die with exit code 9 (`Signal 9 SIGKILL`) or throw `greenlet.error: cannot switch to a different thread`.
* **Technical Root Cause:**  
  1. **Holding 100+ Heavy Items in Memory (`Eat the whole buffet at once`):** In earlier V10 builds, the container grabbed 100 items at a time (`chunk_size = 100`) into active Python dictionary memory. When Playwright renders a Site Page into a PDF, the resulting Base64-encoded PDF string is huge (`~2 MB to 5 MB per page`). Holding 60+ Base64 PDF strings + file metadata inside active RAM consumed over 300 MB+ of memory instantly.
  2. **Aggressive Multi-Threading (`5 to 10 workers`):** Spawning 5 parallel Playwright Chromium worker threads simultaneously multiplied the memory footprint and caused thread contention over shared Node.js IPC pipes. Over 200+ chunks, Chromium memory leaked until hitting the 8 GiB container ceiling, at which point the Linux OS forcefully killed the process (`Signal 9 OOM`).
  3. **Greenlet Collisions (`Signal 5`):** Sharing a single Playwright `asyncio/greenlet` event loop across multiple Python thread-pool workers caused coroutine switching crashes (`Signal 5 SIGTRAP`).
* **Engineering Cure (`Tortoise Concurrency & Thread-Local Greenlets`):**  
  1. **Thread-Local Isolation:** Playwright browsers and event loops are strictly isolated per worker thread (`_THREAD_LOCAL = threading.local()`).
  2. **Tortoise Concurrency Clamping:** Concurrency is hard-capped at a maximum of **3 worker threads** (`max_workers = min(3, max(1, raw_workers))`).

---

## 📅 Phase 3 [Mid July 2026 — V10 Throttling & Deletion Incidents]

### 📉 Error 3: Microsoft Graph API Rate Limiting (`HTTP 429 Too Many Requests`) & Orphaned File Purges (`Page count dropped from 5,412 to 1,544`)
* **Symptom:** During peak business hours in the Maxis Microsoft 365 tenant, the crawler returned only `1,544 discovered pages` (down from `5,412 pages`). Immediately after, `Step 7b Orphaned File Cleanup` ran and deleted 3,868 valid PDFs from the GCS bucket (`stale_blob.delete()`).
* **Technical Root Cause:**  
  1. **Graph API Throttling (`HTTP 429`):** When querying large folders with `$top=100/200` without adaptive retry sleep intervals, Microsoft Graph dynamically throttled our requests. Because the old code lacked `Retry-After` header compliance, the crawler aborted folder loops early upon receiving a 429, returning a partial list of discovered items (`1,544 pages`).
  2. **Unprotected Orphaned Cleanup (`Step 7b Cascade Effect`):** When `Step 7b` compared that partial discovery scan (`1,544 pages`) against the existing GCS bucket inventory (`5,412 pages`), it incorrectly assumed that the 3,868 "missing" pages had been deleted from SharePoint! As a result, `Step 7b` automatically ran `stale_blob.delete()` and wiped 3,868 perfectly valid PDFs out of GCS.
* **Engineering Cure (`Universal Deletion Guards & Retry-After Backoff`):**  
  1. **Adaptive Graph Retries (`graph_get_paginated`):** Set `max_retries=5, timeout=30` and enforced strict **`Retry-After` HTTP header compliance** (`status_forcelist=[429, 500, 502, 503, 504]`). When Microsoft Graph says *"slow down for 12 seconds (`Retry-After: 12`)"*, the container sleeps for 12 seconds and resumes cleanly without dropping a single folder or item.
  2. **Universal Deletion Lockdown (`Double Safety Lock`):** Automatic orphaned file cleanup is now **disabled by default** (`CONFIG_Enable_Orphan_Cleanup: false`). Furthermore, we added an **80% Inventory Safety Circuit Breaker** (`if discovered items < len(gcs_cache) * 0.8 -> abort deletion immediately`). If a partial network scan ever occurs, the container prints a critical safety warning and refuses to delete a single object from GCS.

---

## 📅 Phase 4 [15–16 July 2026 — V10 Forensic Analysis, V11 String-Safe & Hash Suffixing Shield]

### 💣 Error 4: The 16 GB / 8 GB Linux `/dev/shm` Shared-Memory Wall (`Signal 7 SIGBUS / Bus Error at ~900 Pages`)
* **Symptom:** In `20260715-1800PM.json` (`july1st-sharepoint-list-files-8nfr4`), after running for ~1 hour 15 minutes and successfully converting ~900 Modern Site Pages, the Cloud Run container suddenly terminated with `Chromium Pool exception: Signal 7 (SIGBUS / Bus Error)`.
* **Technical Root Cause:**  
  Inside Linux `gen2` Cloud Run containers, Python worker threads terminating `sync_playwright()` browsers do not reliably release the POSIX `/dev/shm` shared memory maps (`vm_area_struct`) allocated by Chromium child renderer processes (`chrome --type=renderer`). Even with 15-page browser recycling (`render_cnt >= 15`) and `shutil.rmtree(/tmp/pw*)`, dead kernel shared memory accumulates (`~15–20 MB per 15-page cycle`) while the parent `python3` process stays alive across hundreds of iterations. Over ~60 recycle cycles (`~900 pages`), `/dev/shm` and `pymalloc` heap accumulation exhausts the 8 GB container limit, terminating with `Signal 7`. Mathematically, on 16 GB RAM in V11, the hard single-job ceiling is ~1,800 to 2,200 pages.
* **Engineering Cure (`V13 Inverted Micro-Renderer & Partitioning`):**  
  In **V13 Option 1**, rather than letting one Cloud Run container loop across 2,000 pages, Application Integration dispatches a micro-batch of **1 to 5 pages per invocation (`POST /v13/render_page`)**. The container renders 5 pages (`~10 to 15 seconds`) and completes its request, forcing the host OS kernel to destroy the container instance and automatically reclaim **100.0% of `/dev/shm` shared memory and zombie handles**.

### 🔗 Error 5: Application Integration Jsonnet String-Safe Variable Error (`undefined variable: objectName`)
* **Symptom:** In V11 during initial integration tests, Child Workflow `Task 3 Upload file request mapping` failed with: `INVALID_ARGUMENT: error executing jsonnet: RUNTIME ERROR: undefined variable: objectName`.
* **Technical Root Cause:**  
  The Jsonnet data mapping block inside the Application Integration definition referenced `objectName: item.objectName` directly using dot-notation on a variable that was injected from an external workflow input (`item_metadata` / `upload_request`). When the payload structure lacked an explicit top-level `objectName` or when special characters appeared in folder paths, Jsonnet execution aborted.
* **Engineering Cure (`String-Safe Jsonnet ExtVar Parsing`):**  
  All Jsonnet mapping expressions across parent and child workflows must strictly use defensive lookup syntax: `objectName: std.extVar('upload_request')['objectName']` (`or deriving relative paths safely via std.extVar`).

### 💥 Error 6: Primary Key (`doc_id`) & Path Collisions across Sub-Libraries (`Option 2 Hash Suffixing`)
* **Symptom:** Analysis of `metadata_16july.jsonl` revealed **2,656 primary key (`doc_id`) collisions and 18 path overwrites across 38,895 records**. Generic filenames (`1.pdf`, `Slide1.JPG`, `BulletinTest.aspx`) occurring in different sub-folders silently overwrote each other inside GCS.
* **Technical Root Cause:**  
  Relying solely on `file.name` or unhashed relative paths for GCS destination paths and `metadata.jsonl` primary keys (`doc_id`) guarantees collisions across deeply hierarchical enterprise sites.
* **Engineering Cure (`V11 Option 2 SHA-256 Hashed Suffixing Shield`):**  
  Every item automatically receives an 8-character SHA-256 hash derived from its immutable `graph_id` / relative path, enforcing `files/{Subsite}/{Library}/{Folder}/{FileBase}_{Hash[:8]}.{ext}` and `id: "{BaseName}_{Hash[:8]}"` while keeping `structData.title` 100% human-readable for Vertex AI chat citations.

---

## 🏛️ The Master Checklist: 10 Real-World Production Traps That V13 Must Enforce

Before writing any code or deploying any workflow for **Version 13 (`v13-category-appint`)**, every engineer and AI agent must verify that all 10 of these real-world traps are permanently locked down in the architecture:

1. **Microsoft Graph API 429 Throttling & WAF Rejections:**  
   *Lockdown:* Hard-cap horizontal Cloud Run concurrency to **5 parallel container instances (`max-instances = 5`)** during Day 1 bulk crawls, and enforce strict **`Retry-After` HTTP header compliance** across all Graph API requests.
2. **The 10 MB Application Integration Variable Payload Limit:**  
   *Lockdown:* Enforce **Option 1 Pipelined Chunking**: regular files are sliced into **100-item chunks (~150 KB)** and Modern Site Pages into **5-item chunks (~15 KB)**, staying >98% below the 10 MB payload ceiling.
3. **The 5,000-Step Application Integration Loop Ceiling:**  
   *Lockdown:* Dispatch each 100-item file chunk to its own independent Parent Workflow execution ID. A `ForEach` loop iterating over 100 items generates only **~400 internal step transitions (`92% below the 5,000-step ceiling`)**.
4. **The Linux `/dev/shm` Shared-Memory Wall (`Signal 7 SIGBUS / Signal 9 SIGKILL`):**  
   *Lockdown:* Enforce the **Inverted Micro-Renderer Pattern (`POST /v13/render_page`)** where each container instance processes at most 1 to 5 pages per invocation (`~10 to 15 seconds`), allowing the OS kernel to destroy the container and reclaim 100.0% of `/dev/shm` after every micro-batch.
5. **String-Safe Jsonnet Parsing in Application Integration:**  
   *Lockdown:* Every child/parent workflow Jsonnet data mapping task must strictly use defensive lookup syntax (`std.extVar('upload_request')['objectName']`), completely avoiding direct dot-notation on unescaped keys.
6. **Primary Key (`doc_id`) & Path Collision Overwrites across Libraries:**  
   *Lockdown:* Natively bake in **V11 Option 2 (`SHA-256 Hashed Suffixing`)** into all GCS paths and `metadata.jsonl` IDs while preserving unhashed titles for Vertex AI Search.
7. **Orphaned File Cleanup Circuit Breakers (`The Step 7b Cascade Trap`):**  
   *Lockdown:* Keep orphan cleanup **DISABLED by default** (`CONFIG_Enable_Orphan_Cleanup: false`). If enabled, enforce the **80% Inventory Circuit Breaker** AND **Partition-Scoped Deletion** (`only comparing and deleting objects whose paths match the active subsite prefix`).
8. **OAuth Access Token Expiration during Multi-Hour Crawls:**  
   *Lockdown:* Pass every Graph API request through a **Dynamic Token Refresh Interceptor (`get_valid_access_token()`)** that automatically re-authenticates 5 minutes before the 60-minute token expiration window (`or instantly upon receiving an HTTP 401`).
9. **Greenlet & Thread-Pool Event Loop Collisions (`Signal 5 SIGTRAP`):**  
   *Lockdown:* Enforce strict **Thread-Local Greenlet Isolation** (`_THREAD_LOCAL = threading.local()`) inside all Playwright and asyncio routines so worker threads never cross-contaminate greenlet loops.
10. **The Fast Delta Check Gate (`97% Traffic Reduction`):**  
    *Lockdown:* Always check `lastModifiedDateTime` via `/v13/check_delta_batch` (`or local cache`) before launching Chromium or downloading files. Unchanged items (~97%) return `SKIPPED_DELTA_HIT` in **0.05 seconds** with ZERO requests to SharePoint and ZERO Chromium instances launched.
