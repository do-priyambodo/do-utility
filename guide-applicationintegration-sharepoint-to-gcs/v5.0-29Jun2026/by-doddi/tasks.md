# 🎯 Enterprise SharePoint to GCS Sync & Agent Assist Roadmap

This document outlines the execution roadmap for synchronizing Microsoft SharePoint repositories into Google Cloud Storage (GCS) and indexing them into Vertex AI Agent Builder. It is divided into **TODAY'S SCOPE** (Option 1: Targeted Sync & Cloud Run Migration) and **FUTURE SCOPE** (Option 2: Full Enterprise Repository Traversal).

---

# 📅 TODAY'S SCOPE (Option 1: Targeted Sync)

### ✅ Phase 1: Output Formatting (Completed)
- [x] **Task 1: Change SharePoint Page Sync Output from HTML to PDF**
  - *Completed*: Converted SharePoint `.aspx` site pages into clean executive `.pdf` documents using `xhtml2pdf` with Fluent UI styling.

---

### 🎯 Phase 2: Targeted Sync & Cloud Run Migration
*Goal*: Synchronize a curated list of specific SharePoint URLs/files defined in a GCS config file (`gs://bucket/config/target_urls.txt`). Migrate from Cloud Functions to **Cloud Run** for improved stability, larger memory allocation, and longer execution timeout limits.

- [ ] **Task 2.1: Migrate Execution Engine to Cloud Run (Job/Service)**
  - *How to execute*: Create deployment scripts (`deploy_cloud_run.sh`) and containerize or wrap `cf-source/main.py` so it runs stably on Cloud Run with increased timeouts (up to 24 hours) and memory limits, avoiding 2nd Gen Cloud Function HTTP dropouts.

- [ ] **Task 2.2: Verify Targeted Sync via GCS Config List (`target_urls.txt`)**
  - *How to execute*: Test and verify the targeted sync workflow (`sync_gcs_dynamic.py` / `sync_specific_urls.py`). Ensure the engine dynamically reads `gs://bucket/config/target_urls.txt`, converts targeted `.aspx` pages to `.pdf`, downloads files, and uploads them reliably to GCS.

---

### ⏰ Phase 3: Automated Scheduling
*Goal*: Automate periodic execution of the targeted synchronization pipeline.

- [ ] **Task 3: Create or Replace Cloud Scheduler Jobs**
  - *How to execute*: Update scheduler deployment scripts (`deploy_scheduler_gcs_dynamic.sh`, `deploy_scheduler.sh`) to point to the new Cloud Run URI with automated CRON schedules (e.g., nightly `0 2 * * *`) and OIDC authentication.

---

### 🧠 Phase 4: Datastore Indexing & GKA Live SharePoint Link Maintenance
*Goal*: Ensure contact center agents using Generative Knowledge Assist (GKA) are directed to the live SharePoint web page when clicking citation links, rather than opening the raw GCS storage blob.

- [ ] **Task 4.1: Generate `metadata.jsonl` Manifest during GCS Sync**
  - *How to execute*: Update `cf-source/main.py` so during sync, a `metadata.jsonl` file is uploaded to GCS mapping each object URI (`gs://bucket/pages/Page.pdf`) to structured custom metadata: `"sharepoint_url": item["Url"]` and `"title": item["Name"]`.

- [ ] **Task 4.2: Create or Replace Datastore Sync Execution Function**
  - *How to execute*: Create or replace the Cloud Function/Run job responsible for triggering Vertex AI Datastore synchronization. Configure the `ImportDocumentsRequest` API payload to use **JSONL with metadata** pointing to `gs://bucket/metadata.jsonl`.

- [ ] **Task 4.3: Configure Frontend Agent Assist Widget (`linkMetadataKey`)**
  - *How to execute*: In the contact center UI configuration (`<agent-assist-ui-modules>` in `app.js`), set `articleLinkConfig: { linkMetadataKey: "sharepoint_url", target: "blank" }`.

---
---

# 🚀 FUTURE SCOPE (Option 2: Full Enterprise Traversal)

### 🏢 Phase 5: Full Enterprise Repository Resilient Traversal
*Goal*: Synchronize entire enterprise subsite repositories (`Sites/DEN/Consumer` - 1,743 files, 1,952 pages, 17.00 GB) without encountering Microsoft Graph API throttling rejections (`HTTP 429 / 503`).

- [ ] **Task 5.1: Enhance Resilient HTTP Session & Throttling Backoff (`cf-source/main.py`)**
  - *How to execute*: Update `get_resilient_session()` to respect Graph's `Retry-After` header (`respect_retry_after_header=True`), expand retries to 5 across status codes `[429, 500, 502, 503, 504]`, and add micro-jitter between API calls.

- [ ] **Task 5.2: Implement GCS Delta Cache Filter (Skip Unchanged Files)**
  - *How to execute*: Compare each item's SharePoint `lastModifiedDateTime` against GCS cached timestamps. Skip downloading unchanged items to reduce daily transfer volume from 17.00 GB down to modified megabytes.

- [ ] **Task 5.3: Chunked Batch Execution for Application Integration**
  - *How to execute*: Group items into controlled batches (e.g., 50 items per payload) before triggering Application Integration workflows to prevent flooding connectors.

---
*Status: Roadmap divided into TODAY'S SCOPE and FUTURE SCOPE (Option 2 as last section). Ready for Task 2.1.*
