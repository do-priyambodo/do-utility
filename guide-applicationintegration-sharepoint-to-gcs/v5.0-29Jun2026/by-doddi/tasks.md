# 🎯 Enterprise SharePoint to GCS Sync & Agent Assist Roadmap

This document outlines the end-to-end execution plan to synchronize enterprise Microsoft SharePoint repositories (17 GB+ / ~3,700 items) into Google Cloud Storage (GCS) and index them into Vertex AI Agent Builder without encountering Microsoft Graph API rejection errors or Cloud Function timeouts.

---

## 📅 Execution Roadmap & Task List

### ✅ Phase 1: Output Formatting (Completed)
- [x] **Task 1: Change SharePoint Page Sync Output from HTML to PDF**
  - *Completed*: Modified `cf-source/main.py` and `child_workflow.json` to inject Fluent UI styling, convert SharePoint `.aspx` site pages into clean executive `.pdf` documents using `xhtml2pdf`, and upload them to GCS without double encoding.

---

### 🚀 Phase 2: Enterprise Resilient Sync & Throttling Defense
*Goal*: Overcome Microsoft Graph API rejection errors (`HTTP 429 / 503`) and pipeline timeouts when synchronizing large subsite repositories (`Sites/DEN/Consumer` - 1,743 files, 1,952 pages, 17.00 GB). Execute these step-by-step:

- [ ] **Task 2.1: Enhance Resilient HTTP Session & Throttling Backoff (`cf-source/main.py`)**
  - *How to execute*: Update `get_resilient_session()` in `cf-source/main.py` to configure `urllib3.Retry` with `respect_retry_after_header=True`, expand `status_forcelist=[429, 500, 502, 503, 504]`, increase max backoff retries to `5`, and add micro-jitter (`time.sleep(uniform(0.1, 0.4))`) between consecutive Graph calls to prevent burst rate-limiting.

- [ ] **Task 2.2: Implement GCS Delta Cache Filter (Skip Unchanged Files)**
  - *How to execute*: Ensure the traversal logic checks each item's `lastModifiedDateTime` against the cached object timestamp in GCS (`gcs_cache` / `metadata.jsonl`). If an item has not been modified since the last sync run, mark `needs_sync = False`. This drops daily transfer volume from 17.00 GB down to just modified megabytes.

- [ ] **Task 2.3: Chunked Batch Execution for Application Integration**
  - *How to execute*: When triggering downstream Application Integration workflows (`sync_sharepoint_to_gcs.py`), group sync items into controlled batches (e.g., 50 items per payload). This prevents flooding integration connectors with thousands of concurrent HTTP invocations.

- [ ] **Task 2.4: Cloud Run Job Migration Script (For 24-Hour Timeout Support)**
  - *How to execute*: Provide a deployment script (`deploy_cloud_run_job.sh`) to run the sync engine as a **Cloud Run Job** (up to 32 GB RAM and 24-hour execution limits) as an enterprise failover if 2nd Gen Cloud Function HTTP timeouts (60 mins) are ever reached during massive initial sync runs.

---

### ⏰ Phase 3: Automated Scheduling
*Goal*: Automate the periodic execution of the resilient synchronization pipeline.

- [ ] **Task 3: Create or Replace Cloud Scheduler Jobs**
  - *How to execute*: Execute or update `deploy_scheduler.sh` and `deploy_scheduler_targeted.sh` to provision automated Google Cloud Scheduler jobs configured with CRON expressions (e.g., nightly `0 2 * * *`) and OIDC Service Account authentication to reliably trigger the sync engine.

---

### 🧠 Phase 4: Datastore Indexing & GKA Live SharePoint Link Maintenance
*Goal*: Ensure contact center agents using Generative Knowledge Assist (GKA) are directed to the live SharePoint web page when clicking citation links, rather than opening the raw GCS storage blob.

- [ ] **Task 4.1: Generate `metadata.jsonl` Manifest during GCS Sync**
  - *How to execute*: Update `cf-source/main.py` so that during synchronization, a `metadata.jsonl` file is generated and uploaded to the GCS bucket root. Each line maps the GCS object URI (`gs://bucket/pages/Page.pdf`) to structured custom metadata: `"sharepoint_url": item["Url"]` (the original live web link) and `"title": item["Name"]`.

- [ ] **Task 4.2: Create or Replace Datastore Sync Execution Function**
  - *How to execute*: Create or replace the Cloud Function responsible for triggering Vertex AI Agent Builder Datastore synchronization. Configure the `ImportDocumentsRequest` API payload to use **JSONL with metadata** pointing to `gs://bucket/metadata.jsonl`. This indexes both the document content and its associated `sharepoint_url`.

- [ ] **Task 4.3: Configure Frontend Agent Assist Widget (`linkMetadataKey`)**
  - *How to execute*: In the frontend contact center UI configuration (`<agent-assist-ui-modules>` / V2 config in `app.js`), set `articleLinkConfig: { linkMetadataKey: "sharepoint_url", target: "blank" }`. When an agent clicks a citation card, the UI component extracts `sharepoint_url` from the document metadata and launches the live SharePoint page in a new tab.

---
*Status: Roadmap reorganized into sequential phases. Ready to begin Phase 2 (Task 2.1).*
