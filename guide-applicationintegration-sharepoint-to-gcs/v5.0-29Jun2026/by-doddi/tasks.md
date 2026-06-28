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

- [x] **Task 2.2: Verify Targeted Sync via GCS Config List (`target_urls.txt`)**
  - *Completed*: Verified targeted sync workflow (`sync_gcs_dynamic.py`). Enhanced engine to dynamically read `gs://bucket/config/target_urls.txt`, convert targeted `.aspx` pages to high-fidelity executive `.pdf` reports (with embedded Rich Text, clickable SharePoint Source citations, and physical inline Base64 leadership photos), and upload them reliably to GCS (`1.38 MiB`).

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

#### 📊 Customer Executive Briefing: Root Cause Analysis & Justification for Rejection Errors
*Why previous legacy sync architectures failed when traversing enterprise-scale repositories (17.00 GB+ / 3,695+ items):*

1. **Microsoft Graph API Multi-Tenant Throttling (`HTTP 429 / 503`)**:
   - *The Problem*: When legacy synchronous scripts attempt to traverse 3,695 items in a single uninterrupted execution loop—specifically firing rapid `$expand=canvasLayout` API requests for 1,952 modern site pages while simultaneously downloading 1,743 binary files—Microsoft 365's tenant protection monitors identify the traffic pattern as an automated burst spike or Denial of Service (DoS) attempt.
   - *The Rejection*: Microsoft Graph responds by rejecting further connections with `HTTP 429 Too Many Requests` or `HTTP 503 Service Unavailable` and injects a mandatory `Retry-After` cooldown timer. Because previous scripts did not implement asynchronous queuing or respect `Retry-After` headers, repeated immediate retries caused Microsoft to temporarily ban the OAuth Service Principal token.

2. **Synchronous Execution & Cloud Function HTTP Gateway Timeouts (`HTTP 504`)**:
   - *The Problem*: Legacy architectures coupled folder traversal and file downloading into a single monolithic HTTP Cloud Function request.
   - *The Timeout*: While Cloud Functions (2nd Gen) can run up to 60 minutes internally, downstream calling clients (such as Application Integration connectors or API Gateways) enforce hard synchronous HTTP connection drops (typically between 60 to 300 seconds). Attempting to stream 17.00 GB of binary data synchronously over a single HTTP socket guarantees a `504 Gateway Timeout` or container out-of-memory crash before the loop can finish.

3. **Absence of Delta State Tracking (Redundant Daily Transfer)**:
   - *The Problem*: Legacy pipelines executed a brute-force full scan every day, re-downloading all 17.00 GB even if 99.9% of files were unchanged.
   - *The Solution*: Transitioning to Microsoft Graph **Delta Queries (`$delta`)** and **GCS timestamp caching** ensures the pipeline only requests items created or edited since the previous run, dropping daily data movement from 17.00 GB down to a few megabytes and completely eliminating throttling risks.

---
#### 🛠️ Phase 5 Implementation Tasks

- [ ] **Task 5.1: Enhance Resilient HTTP Session & Throttling Backoff (`cf-source/main.py`)**
  - *How to execute*: Update `get_resilient_session()` to respect Graph's `Retry-After` header (`respect_retry_after_header=True`), expand retries to 5 across status codes `[429, 500, 502, 503, 504]`, and add micro-jitter between API calls.

- [ ] **Task 5.2: Implement GCS Delta Cache Filter (Skip Unchanged Files)**
  - *How to execute*: Compare each item's SharePoint `lastModifiedDateTime` against GCS cached timestamps. Skip downloading unchanged items to reduce daily transfer volume from 17.00 GB down to modified megabytes.

- [ ] **Task 5.3: Chunked Batch Execution for Application Integration**
  - *How to execute*: Group items into controlled batches (e.g., 50 items per payload) before triggering Application Integration workflows to prevent flooding connectors.

---
*Status: Roadmap updated with Executive Briefing justifying legacy sync failures. Ready for Task 2.1.*
