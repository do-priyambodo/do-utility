# Comprehensive V9.0 Application Testing Guide & Playbook

This document explains in natural language how to conduct a complete, end-to-end system test on the **V9.0 Hybrid Serverless SharePoint-to-GCS Synchronization Pipeline**. This playbook follows our standardized verification methodology to ensure all serverless components (Cloud Run, Gen2 Cloud Functions, Application Integration, and Vertex AI Discovery Engine) operate reliably under production workloads.

---

## 🧭 Testing Philosophy & Overview

Our testing strategy is divided into five sequential phases:
1. **Phase 0: Pre-Flight Diagnostic Checks** (Validating local parameters, cloud IAM permissions, Entra ID OAuth tokens, and PDF image rendering).
2. **Phase 1: Targeted Synchronization Test** (Verifying scoped, URL-specific folder and file synchronization using `target_urls.txt`).
3. **Phase 2: Full Repository Synchronization Test** (Performing a complete clean-state wipe of GCS followed by a full recursive crawl across all SharePoint subsites and libraries).
4. **Phase 3: Vertex AI Datastore Indexing Test** (Verifying document ingestion and manifest processing via our standalone `cf-datastore` microservice).
5. **Phase 4: Summary Reporting & Audit Logging** (Compiling a structured, executive-ready test report with precise execution metrics and error breakdowns).

---

## 🛠️ Phase 0: Pre-Flight Diagnostic Checks

Before executing any data movement, verify that your local configuration and cloud authentication bindings are healthy.

### Step 0.1: Validate Parameter Formats and GCP Resources
Run the parameter validation script. This checks both the syntax of `parameters.json` and performs live queries against Google Cloud to ensure your Project, Service Account, GCS Bucket, Secret Manager secrets, and Application Integration Connectors exist and are `ACTIVE`.
```bash
python3 util/validate_params.py
```
*Expected Output:* `🎉 ALL PARAMETERS AND GCP RESOURCES COMPLETED VALIDATION SUCCESSFULLY!`

### Step 0.2: Verify Microsoft Entra ID (M365) Authentication
Verify that your Azure App Registration credentials (`CONFIG_M365_Client_Id` and Secret Manager secret) successfully generate a Microsoft Graph OAuth 2.0 Bearer token and can query your SharePoint hostname.
```bash
python3 check/check_entra_id_auth.py
```
*Expected Output:* `✅ Graph API token acquired successfully!` and valid SharePoint Site ID resolution.

### Step 0.3: Test High-Fidelity PDF Image Resolution & Embedding
Test our intelligent image resolver and Playwright PDF compilation engine. This diagnostic fetches modern SharePoint site pages (`.aspx`), intercepts inline images and webpart cards, downloads the binary media from SharePoint, converts them into inline Base64 data URIs (`data:image/jpeg;base64,...`), and compiles the DOM into an A4 PDF document.
```bash
python3 test/test_image_fetch.py
```
*Expected Output:* `🎉 SUCCESS! Images were downloaded and converted to Base64 inline data URIs!`

---

## 🎯 Phase 1: Targeted Synchronization Test

The Targeted Sync mechanism allows operators to restrict synchronization to specific SharePoint folders or file URLs defined in `target_urls.txt`, avoiding a full enterprise crawl when only specific departments or folders require updates.

### Step 1.1: Prepare and Upload Target URLs
1. Open `target_urls.txt` and populate it with the SharePoint folder paths or page URLs you wish to test (one URL per line).
2. Upload the manifest to your Cloud Storage bucket (`gs://<bucket>/config/target_urls.txt`):
```bash
./sync/upload_gcs_targets.sh
```

### Step 1.2: Execute Read-Only Targeted Dry Run
Always execute a dry run first. The dry run invokes the Traversal Cloud Function (`cf-sharepoint`) in read-only mode. It queries Microsoft Graph for the specific URLs in your target list, compares them against existing GCS blob timestamps, and reports how many files would be downloaded vs. skipped without transferring any data or triggering integration workflows.
```bash
python3 check/check_sync_gcs_dynamic.py --dry-run
```
*What to observe:* Verify that the script successfully identifies the target folders, lists the internal files, and outputs a clear count of files to sync.

### Step 1.3: Execute Live Targeted Synchronization
Run the live targeted sync to initiate actual data movement:
```bash
python3 sync/sync_gcs_dynamic.py
```
*What to observe:*
- The script invokes the Traversal service, which dispatches micro-batches (`CONFIG_Batch_Size: 50`) to Google Cloud Application Integration.
- In Google Cloud Console under **Cloud Storage > Buckets**, navigate to `files/` and verify that the target documents and converted `.pdf` site pages appear with correct folder hierarchies.

---

## 🚀 Phase 2: Full Repository Synchronization Test

This phase tests the core enterprise crawler: recursively inventorying all SharePoint subsites, document libraries, and site pages across the entire tenant.

### Step 2.1: CRITICAL PRE-CONDITION — Clean State GCS Wipe
> [!CAUTION]
> **Why we wipe GCS prior to full testing**: To genuinely prove that the full sync crawler discovers 100% of SharePoint assets, renders all `.aspx` pages to PDF, and generates an uncorrupted metadata manifest from scratch, we must remove existing cache artifacts. If we do not delete prior assets, O(1) delta caching will skip existing files, masking potential download or rendering issues during baseline testing.

Purge all previously synced files and metadata manifests from your Cloud Storage bucket using the GCP CLI:
```bash
# Extract bucket name from parameters.json
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

echo "🧹 Wiping existing synced assets from gs://${BUCKET_NAME}/files/..."
gcloud storage rm -r "gs://${BUCKET_NAME}/files/**" 2>/dev/null || echo "ℹ️ No existing files to remove."

echo "🧹 Removing previous metadata manifest..."
gcloud storage rm "gs://${BUCKET_NAME}/config/metadata.jsonl" 2>/dev/null || echo "ℹ️ No existing manifest to remove."

echo "✨ Clean state pre-condition established! Ready for baseline full sync test."
```

### Step 2.2: Execute Read-Only Full Discovery Dry Run
Run the repository-wide discovery dry run. This queries the Microsoft Graph API across all configured sites, counts every physical document and site page, checks in-memory delta cache timestamps (which will now show 0% hits due to our clean wipe), and estimates total transfer volume.
```bash
python3 check/check_sync_sharepoint_to_gcs.py --dry-run
```
*What to observe:* Ensure the discovered item count matches your expected SharePoint asset inventory (e.g., verifying all ~9,000 enterprise assets are discovered cleanly without rate-limiting).

### Step 2.3: Execute Live Full Synchronization
Initiate the full enterprise crawl and ingestion pipeline:
```bash
python3 sync/sync_sharepoint_to_gcs.py
```
*What happens during execution:*
1. **Inventory & Harvesting**: The `cf-sharepoint` service traverses drive hierarchies and harvests site page layouts.
2. **Batch Orchestration**: Discovered items are sliced into batches of 50 and dispatched in parallel across worker threads to Application Integration.
3. **Data Ingestion**: Application Integration Connectors stream file bytes directly from SharePoint into GCS `files/`.
4. **Manifest Compilation**: Upon completion, the container automatically builds a comprehensive JSONL manifest and uploads it directly to `gs://<bucket>/config/metadata.jsonl`, formatting every item with `"id"`, `"structData"`, `"title"`, and clickable `"sharepoint_url"` citation links for Generative Knowledge Assist (GKA).
5. **Orphan Cleanup**: Any deleted or inactive SharePoint files found in GCS are automatically removed.

### Step 2.4: Verify Downstream Integration Execution
While the sync is running (or after completion), check the real-time execution status of your Application Integration child workflows:
```bash
python3 check/check_application_integration_execution.py
```
*What to observe:* Verify that all batch executions complete with status `SUCCEEDED` and that no worker failed due to memory exhaustion or API timeouts.

---

## 🧠 Phase 3: Vertex AI Datastore Indexing Test

Once files and the `metadata.jsonl` manifest reside in GCS, test document ingestion into Vertex AI Search / Discovery Engine using our standalone microservice (`cf-datastore`).

### Step 3.1: Trigger Datastore Indexing
Invoke the Datastore synchronization runner:
```bash
python3 sync/sync_datastore.py
```
*(Alternatively, trigger the deployed Cloud Scheduler job directly via CLI)*:
```bash
gcloud scheduler jobs run yourorg-sharepoint-datastore-sync-12h --location=$(python3 -c "import json; print(json.load(open('parameters.json'))['CONFIG_Location'])")
```

### Step 3.2: Verify Ingestion Status
1. Check the terminal output for: `✅ Vertex AI Datastore import operation initiated successfully!`.
2. In Google Cloud Console, navigate to **Vertex AI Search & Conversation > Data Stores > [Your Datastore] > Activity** and confirm that the incremental document import job completes without schema or formatting rejection errors.

---

## 📊 Phase 4: Summary Reporting & Audit Logging

After concluding all testing phases, compile a comprehensive execution summary report. This provides stakeholders (such as customer engineering leads or project managers) with complete transparency into system reliability, performance metrics, and data integrity.

### Step 4.1: Inspect Audit Logs
Review the generated local and cloud log archives to ensure no silent failures occurred:
- **`log/setup.log`**: Contains stdout/stderr transcripts of all deployment and execution commands.
- **`log/cloud.log`**: Contains structured operational logs, timestamped execution traces, and GCS file deletion notices.
- **`log/error.log`**: Captures any trapped script errors or HTTP stack traces.
```bash
# Check for any recorded errors during the test run
cat log/error.log 2>/dev/null || echo "✅ No errors recorded in log/error.log!"
```

### Step 4.2: Stakeholder Test Execution Report Template
When reporting back to stakeholders or customers after a full test run, complete and submit the following structured executive summary:

```markdown
# 📋 V9.0 SharePoint-to-GCS Synchronization: Full Test Execution Report

**Date of Execution:** [e.g., 01 July 2026]
**Environment / Customer:** [e.g., Customer YourOrg - Production / Staging Tenant]
**Operator / Engineer:** [e.g., YourOrg Priyambodo]
**Pipeline Version:** V9.0 (Modular Serverless Architecture)

---

### 🟢 1. Executive Summary & Status
* **Overall Test Status:** **PASSED / SUCCEEDED**
* **Total Elapsed Runtime:** [e.g., 4 minutes 12 seconds]
* **GCS Clean State Reset Performed:** Yes (All prior blobs and manifests purged prior to baseline crawl)
* **API Throttling / Rate-Limit Events Encountered:** 0 (Handled seamlessly by 5x exponential backoff adapter)

---

### 📈 2. Synchronization & Inventory Metrics

| Metric Description | Count / Value | Notes & Verification |
| :--- | :---: | :--- |
| **Total SharePoint Assets Discovered** | `9,000` | Verified across all subsites and document libraries via Graph API |
| **Files Successfully Downloaded to GCS** | `8,985` | Streamed cleanly via Application Integration workers into `files/` |
| **Site Pages Rendered to PDF (`.aspx`)** | `15` | Converted via Playwright Chromium with inline Base64 images embedded |
| **O(1) Delta Cache Hits (Skipped Files)** | `0` | Expected 0 due to baseline clean-state GCS wipe |
| **Inactive / Orphaned Assets Deleted** | `0` | Verified zero orphaned blobs in GCS |
| **Total Manifest Records Generated** | `9,000` | Compiled into `gs://<bucket>/config/metadata.jsonl` with citation URLs |

---

### 🔍 3. Subsystem Verification Breakdown

#### A. High-Fidelity PDF Conversion Engine
* **Engine Used:** Playwright (Headless Chromium)
* **Image Resolution Status:** 100% of inline images, webpart banners, and leadership profile cards were successfully authenticated via Graph OAuth, converted to Base64 data URIs, and embedded inside exported PDF reports without layout loss.

#### B. Application Integration Orchestration
* **Batch Slicing Configuration:** `50` items per batch across `10` parallel workers (Total Batches: `180`).
* **Execution Results:** All 180 child workflow executions completed with status `SUCCEEDED`. Zero timeout drops or memory limit exceeded events recorded on Cloud Run.

#### C. Vertex AI Discovery Engine Indexing (`cf-datastore`)
* **Service Endpoint:** `yourorg-datastore-import` Cloud Function triggered via OIDC authentication.
* **Ingestion Status:** Manifest `metadata.jsonl` successfully imported into Vertex AI Datastore. All 9,000 documents indexed and available for Generative Knowledge Assist (GKA) citation querying.

---

### 📝 4. Additional Observations & Next Steps
* **Observations:** The pipeline operated smoothly within Google Cloud quotas and Microsoft Entra ID rate limits. Memory utilization on the `cf-sharepoint` Cloud Run container remained steady under ~450 MB per instance.
* **Next Operational Step:** The system is certified for live production operation. Automated Cloud Scheduler cron jobs (`yourorg-sharepoint-full-sync-24h` and `yourorg-sharepoint-datastore-sync-12h`) have been enabled for ongoing automated delta synchronization.
```
