# SharePoint-to-GCS Synchronization Pipeline (V8.0)
## Enterprise Troubleshooting, Diagnostic Logging & Active Monitoring Guide

> [!IMPORTANT]
> **Customer Reference Document — Maxis Environment Deployment**
> This guide provides comprehensive diagnostic commands, real-time sync progress monitoring mechanisms, and root-cause analysis checklists to investigate and resolve synchronization failures (such as the sync attempt on last Friday) and verify ongoing production health.

---

## 1. Executive Summary & Sync Time Estimation

When synchronizing large-scale Microsoft 365 SharePoint libraries and modern site pages (`.aspx`) to Google Cloud Storage (GCS), understanding the execution throughput and timeline is critical for operational planning.

### ⏱️ Time Estimation Calculation (4,000 Pages)

Based on baseline benchmark performance where **13 files/pages completed in 5 minutes**:

1. **Per-Item Processing Rate**:
   $$\text{Rate} = \frac{5 \text{ minutes}}{13 \text{ items}} \approx 0.3846 \text{ minutes per item} \ (23.07 \text{ seconds per item})$$

2. **Total Estimated Duration for 4,000 Pages**:
   $$\text{Total Time} = 4,000 \text{ items} \times 0.3846 \text{ minutes/item} = 1,538.46 \text{ minutes}$$
   $$\text{Total Hours} = \frac{1,538.46 \text{ minutes}}{60} \approx \mathbf{25.64 \text{ hours}} \ (\approx \mathbf{25 \text{ hours and } 38 \text{ minutes}})$$

> [!NOTE]
> **Why does an initial full sync take ~25.6 hours?**
> * **Headless Playwright Browser Rendering**: Unlike simple file copying, V8.0 queries modern SharePoint site pages (`.aspx`), launches a headless Chromium browser instance in Cloud Run, executes live JavaScript/DOM layouts, waits for external OData/thumbnail images to render, and prints high-fidelity executive `.pdf` reports.
> * **Inline Leadership & Attachment Download**: Each page requires resolving and downloading physical inline leadership images and embedded attachments.
> * **Micro-Batching Safety**: To guarantee 0% data loss and prevent gateway timeouts, Application Integration processes items in controlled chunks (configured via `CONFIG_Batch_Size` and `CONFIG_Max_Parallel_Workers` in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v8.0-01Jul2026/by-doddi/parameters.json)).

---

### 🚀 The V8.0 Delta Caching Advantage (Why this is a one-time cost)

The ~25.6-hour duration applies **ONLY to the Initial Full Baseline Synchronization**.

In pipeline version V8.0, the Traversal Cloud Function implements **O(1) GCS Delta Caching**:
* Before downloading or rendering, the Cloud Function pre-fetches the modification timestamps of all existing objects in destination bucket `gs://doddi-bucket-sharepoint-sync/`.
* It compares these against live Microsoft Graph API timestamps.
* **Unchanged files and previously rendered `.pdf` reports are instantly skipped!**
* **Subsequent hourly or daily syncs of 4,000+ items will complete in under 2 to 3 minutes**, as only newly created or modified documents are processed.

### ⚡ Performance Tuning (Speeding Up the Initial Sync)
To accelerate the initial 25.6-hour sync on customer environments, increase concurrency limits inside [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v8.0-01Jul2026/by-doddi/parameters.json):
```json
{
  "CONFIG_Batch_Size": 20,
  "CONFIG_Max_Parallel_Workers": 15
}
```
*(Note: If increasing concurrency above 15, ensure your Cloud Run function revision has at least **2 vCPUs and 4GB Memory** allocated to handle simultaneous Chromium browser tabs).*

---

## 2. Active Monitoring & Real-Time Sync Progress Mechanism

Because a full enterprise sync spans multiple hours, engineers must actively monitor progress without waiting for completion or guessing if the pipeline is frozen. Use the following three monitoring mechanisms:

### Method A: Live GCS Bucket Object Counter (Real-Time Storage Tracking)
The most reliable way to confirm active synchronization is to track the live accumulation of PDF reports and document files landing in Google Cloud Storage.

Run these commands in Google Cloud Shell or a terminal authenticated to GCP:

```bash
# 1. Check current total count of synced files and rendered PDF pages in GCS
gcloud storage ls --recursive "gs://doddi-bucket-sharepoint-sync/**" | wc -l

# 2. Check total storage size footprint consumed in the bucket
gcloud storage du -s "gs://doddi-bucket-sharepoint-sync/" --readable-sizes
```

#### 🔄 Automated Real-Time Watch Loop (Live Dashboard in Terminal)
Execute this command to monitor sync speed in real time (refreshing automatically every 30 seconds):
```bash
watch -n 30 'echo "=== 📊 LIVE SHAREPOINT -> GCS SYNC MONITOR ===" && \
echo "Timestamp: $(date)" && \
echo "------------------------------------------------------------" && \
echo -n "Total Synced Files/Pages Landed in GCS : " && \
gcloud storage ls --recursive "gs://doddi-bucket-sharepoint-sync/**" 2>/dev/null | wc -l && \
echo -n "Total Bucket Storage Footprint         : " && \
gcloud storage du -s "gs://doddi-bucket-sharepoint-sync/" --readable-sizes 2>/dev/null | cut -f1 && \
echo "------------------------------------------------------------"'
```
*(If the object count increments steadily every minute, the synchronization is healthy and progressing normally).*

---

### Method B: V8.0 Diagnostic Dry-Run & Delta Cache Analyzer
The V8.0 codebase includes a dedicated diagnostic check tool that directly crawls Microsoft Graph API and checks GCS cache inventory without triggering integration workflows.

Run the diagnostic script from the root project directory:
```bash
python3 check/check_sync_sharepoint_to_gcs.py
```

**What this script reveals**:
1. **Total SharePoint Inventory**: Exactly how many files and `.aspx` pages exist in the M365 library.
2. **Delta Cache Hits**: How many items are already safely cached in GCS.
3. **Remaining Work**: Exactly how many items need to be processed in the current run.

---

### Method C: Application Integration Execution Loop Tracking
When the Traversal Cloud Function submits batches, the Parent Integration (`doddi-sharepoint-gcs-parent`) iterates through the manifest. You can inspect the live loop execution status using the built-in checker:

```bash
# Usage: python3 check/check_application_integration_execution.py <project_id> <location> <integration_name> <execution_id>

python3 check/check_application_integration_execution.py work-mylab-machinelearning asia-southeast1 doddi-sharepoint-gcs-parent <INSERT_EXECUTION_ID>
```
*(Retrieve the `<INSERT_EXECUTION_ID>` from Cloud Function logs or the GCP Console under **Application Integration > Executions**).*

---

## 3. Component-by-Component Diagnostic Logging Commands

To identify the root cause of sync failures (such as last Friday's incident), execute the following targeted `gcloud logging read` CLI commands or use the corresponding query strings in the GCP Console **Log Explorer**.

> [!TIP]
> **Parameter Customization Note**
> The commands below use the default parameters defined in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v8.0-01Jul2026/by-doddi/parameters.json) (`work-mylab-machinelearning`, `doddi-sharepoint-list-files`, etc.). If running in Maxis's production GCP project, replace `--project="work-mylab-machinelearning"` and resource names with Maxis's specific identifiers.

---

### 3.1 Cloud Scheduler Logs (Job Trigger & Cron Health)
**Purpose**: Verify whether the recurring cron trigger successfully invoked the Traversal Cloud Function or failed during OIDC token authentication.

#### 🖥️ CLI Command
```bash
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id:"doddi-sharepoint-sync-hourly"' \
    --project="work-mylab-machinelearning" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp, severity, jsonPayload.status.message, textPayload)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="cloud_scheduler_job"
resource.labels.job_id:"doddi-sharepoint-sync-hourly"
```

* **What to look for**: 
  * HTTP `403 Forbidden`: The Cloud Scheduler service account (`CONFIG_Service_Account`) lacks the `roles/run.invoker` or `roles/cloudfunctions.invoker` IAM permission.
  * HTTP `504 Gateway Timeout`: The function execution exceeded the HTTP response window (ensure micro-batching is active so the function responds quickly after submitting batches).

---

### 3.2 Traversal Cloud Function / Cloud Run Logs (Graph API Crawl & Playwright Rendering)
**Purpose**: Diagnose Microsoft Graph API authentication failures, folder traversal crashes, `.aspx` page harvesting errors, and Playwright Chromium container rendering faults. *(Note: Gen2 Cloud Functions run on underlying Cloud Run revisions).*

#### 🖥️ CLI Command
```bash
gcloud logging read '(resource.type="cloud_function" OR resource.type="cloud_run_revision") AND resource.labels.service_name:"doddi-sharepoint-list-files" AND severity>=WARNING' \
    --project="work-mylab-machinelearning" \
    --limit=30 \
    --order=desc \
    --format="table(timestamp, severity, textPayload, jsonPayload.message)"
```

#### 🔍 GCP Console Log Explorer Query
```query
(resource.type="cloud_function" OR resource.type="cloud_run_revision")
resource.labels.service_name:"doddi-sharepoint-list-files"
severity>=INFO
```

* **What to look for**:
  * `401 Unauthorized` / `403 Forbidden`: Azure AD / M365 Client Secret is invalid, expired, or corporate Entra ID Conditional Access policies are blocking system-to-system client-credentials authentication.
  * `429 Too Many Requests`: Microsoft Graph API throttling (check if automated exponential backoff is kicking in inside `graph_client.py`).
  * `Memory limit exceeded` or `500 Internal Server Error`: Playwright Headless Chromium ran out of memory while rendering complex `.aspx` pages with large inline image attachments. **Fix**: Upgrade Cloud Run memory from 1GB to 2GB or 4GB.

---

### 3.3 Integration Connector Logs (SharePoint & GCS Connectivity)
**Purpose**: Inspect connection handshake health, SSL certificate validation, and data streaming throughput between Google Cloud Connectors and Microsoft 365 / GCS endpoints.

#### 🖥️ CLI Command
```bash
gcloud logging read 'resource.type="connectors.googleapis.com/Connection" AND severity>=WARNING' \
    --project="work-mylab-machinelearning" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp, severity, jsonPayload.status.message, jsonPayload.message)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="connectors.googleapis.com/Connection"
(resource.labels.connection_id:"doddi-connection-sharepoint-sync" OR resource.labels.connection_id:"doddi-connection-gcs-sync")
```

* **What to look for**:
  * OAuth Refresh Token Expired: SharePoint Connector V2 authentication connection needs re-authorization.
  * SSL / Handshake Termination or Network Timeout: Corporate firewall or VPC egress rules blocking connectivity to `https://*.sharepoint.com`.

---

### 3.4 Application Integration Logs (Parent Orchestrator & Child Worker)
**Purpose**: Track batch orchestration loops (`doddi-sharepoint-gcs-parent`) and isolate document binary download/upload streaming failures (`doddi-sharepoint-gcs-child`).

#### 🖥️ CLI Command
```bash
gcloud logging read 'resource.type="integrations.googleapis.com/IntegrationVersion" AND (resource.labels.integration_name:"doddi-sharepoint-gcs-parent" OR resource.labels.integration_name:"doddi-sharepoint-gcs-child") AND severity>=WARNING' \
    --project="work-mylab-machinelearning" \
    --limit=25 \
    --order=desc \
    --format="table(timestamp, severity, jsonPayload.errorMessage, jsonPayload.integrationVersionId)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="integrations.googleapis.com/IntegrationVersion"
(resource.labels.integration_name="doddi-sharepoint-gcs-parent" OR resource.labels.integration_name="doddi-sharepoint-gcs-child")
```

* **What to look for**:
  * `FAILED` or `CANCELLED` execution state: Look at `jsonPayload.errorMessage` for exact failure task names.
  * Payload Serialization Error: Occurs if a single micro-batch contains too many large metadata objects. Ensure `CONFIG_Batch_Size` is set between `5` and `15`.
  * `PERMISSION_DENIED`: Service account missing `roles/integrations.integrationInvoker`.

---

### 3.5 GCS Bucket & Cloud Storage Audit Logs (Destination Write Verification)
**Purpose**: Verify object creation events (`storage.objects.create`) and catch IAM permission denials when writing files or executive PDFs to the target bucket.

#### 🖥️ CLI Command
```bash
gcloud logging read 'resource.type="gcs_bucket" AND resource.labels.bucket_name:"doddi-bucket-sharepoint-sync" AND severity>=WARNING' \
    --project="work-mylab-machinelearning" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp, severity, protoPayload.status.message, protoPayload.authenticationInfo.principalEmail)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="gcs_bucket"
resource.labels.bucket_name="doddi-bucket-sharepoint-sync"
```

* **What to look for**:
  * `403 Permission Denied`: The child integration service account (`doddi-sa-sharepoint-gcs@...`) lacks the `roles/storage.objectAdmin` or `roles/storage.objectCreator` role on target bucket `doddi-bucket-sharepoint-sync`.
  * VPC-SC Ingress Rejection: Bucket protected by perimeter rules preventing external integration connector writes.

---

### 3.6 Secret Manager & IAM Authentication Logs (M365 Credentials Access)
**Purpose**: Confirm that the Traversal Cloud Function can successfully decrypt and access the Microsoft 365 Client Secret (`CONFIG_M365_Secret_Name`).

#### 🖥️ CLI Command
```bash
gcloud logging read 'protoPayload.serviceName="secretmanager.googleapis.com" AND (protoPayload.status.code!=0 OR severity>=WARNING)' \
    --project="work-mylab-machinelearning" \
    --limit=15 \
    --order=desc \
    --format="table(timestamp, protoPayload.authenticationInfo.principalEmail, protoPayload.status.message)"
```

#### 🔍 GCP Console Log Explorer Query
```query
protoPayload.serviceName="secretmanager.googleapis.com"
protoPayload.status.code!=0
```

* **What to look for**:
  * `PERMISSION_DENIED`: The Cloud Function runtime service account is missing the `roles/secretmanager.secretAccessor` IAM role on the M365 secret.

---

### 3.7 VPC Service Controls, Firewall & Network Egress Logs (Enterprise Security Audit)
**Purpose**: In enterprise customer environments (like Maxis), VPC Service Controls (VPC-SC) or firewall egress rules often silently drop external traffic to Microsoft cloud endpoints.

#### 🖥️ CLI Command (VPC Service Control Denials)
```bash
gcloud logging read 'protoPayload.metadata.@type="type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata" AND protoPayload.metadata.violationReason!="REASON_UNSPECIFIED"' \
    --project="work-mylab-machinelearning" \
    --limit=15 \
    --order=desc \
    --format="table(timestamp, protoPayload.metadata.violationReason, protoPayload.authenticationInfo.principalEmail)"
```

#### 🔍 GCP Console Log Explorer Query (VPC-SC & Firewall Rules)
```query
(protoPayload.metadata.@type="type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata" OR resource.type="firewall_rule")
severity>=WARNING
```

---

## 4. Root Cause Analysis Checklist (Why Friday's Sync May Have Failed)

Use this structured checklist to evaluate the top 5 most common enterprise root causes for synchronization failures in customer environments:

| Check | Potential Root Cause | Component to Inspect | How to Diagnose & Resolve |
| :---: | :--- | :--- | :--- |
| 🔲 1 | **Entra ID Conditional Access Block / Expired Secret** | Azure AD / M365 Graph API | **Diagnose**: Check **Section 3.2** logs for HTTP `401`/`403`.<br>**Resolve**: Verify in Azure Portal that `CONFIG_M365_Secret_Name` has not expired and that no Conditional Access policy requires interactive MFA for headless client-credentials flows. |
| 🔲 2 | **Playwright Chromium Out-of-Memory (OOM)** | Traversal Cloud Function (Gen2) | **Diagnose**: Check **Section 3.2** logs for `Memory limit exceeded` or container crash code `500` during `.aspx` page conversion.<br>**Resolve**: In GCP Console > Cloud Run > Revisions, increase memory allocation from 1GB to **2GB or 4GB**. |
| 🔲 3 | **VPC Service Controls (VPC-SC) Egress Block** | Network Security / Connectors | **Diagnose**: Check **Section 3.7** logs for `VpcServiceControlAuditMetadata` violation.<br>**Resolve**: Add an egress rule in perimeter settings allowing traffic to `connectors.googleapis.com` and `*.sharepoint.com`. |
| 🔲 4 | **Missing IAM Invoker or Storage Creator Roles** | IAM & Admin | **Diagnose**: Check **Section 3.4** and **Section 3.5** for `PERMISSION_DENIED`.<br>**Resolve**: Ensure service account `CONFIG_Service_Account` has `roles/integrations.integrationInvoker`, `roles/storage.objectAdmin`, and `roles/secretmanager.secretAccessor`. |
| 🔲 5 | **Micro-Batch Timeout / Throttling (`429`)** | Application Integration / Graph API | **Diagnose**: Check **Section 3.4** for workflow timeout errors or Graph API `429 Too Many Requests`.<br>**Resolve**: Reduce `CONFIG_Batch_Size` to `5` or `10` in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v8.0-01Jul2026/by-doddi/parameters.json) to ensure smoother streaming without hitting Graph API concurrency caps. |

---
*Generated for Maxis Enterprise Support — Application Integration V8.0 Pipeline.*
