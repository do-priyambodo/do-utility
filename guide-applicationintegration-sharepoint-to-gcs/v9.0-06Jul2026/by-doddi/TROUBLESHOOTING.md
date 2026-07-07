# SharePoint-to-GCS Synchronization Pipeline (V9.0)
## Enterprise Troubleshooting, Diagnostic Logging & Active Monitoring Guide

> [!IMPORTANT]
> **Customer Reference Document — YourOrg Environment Deployment**
> This guide provides comprehensive diagnostic commands, real-time sync progress monitoring mechanisms, and root-cause analysis checklists to investigate and resolve synchronization failures (such as the sync attempt on last Friday) and verify ongoing production health. All CLI commands automatically export and utilize configuration variables from your local [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json).

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
> * **Headless Playwright Browser Rendering**: Unlike simple file copying, V9.0 queries modern SharePoint site pages (`.aspx`), launches a headless Chromium browser instance in Cloud Run, executes live JavaScript/DOM layouts, waits for external OData/thumbnail images to render, and prints high-fidelity executive `.pdf` reports.
> * **Inline Leadership & Attachment Download**: Each page requires resolving and downloading physical inline leadership images and embedded attachments.
> * **Micro-Batching Safety**: To guarantee 0% data loss and prevent gateway timeouts, Application Integration processes items in controlled chunks (configured via `CONFIG_Batch_Size` and `CONFIG_Max_Parallel_Workers` in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json)).

---

### 🚀 The V9.0 Delta Caching Advantage (Why this is a one-time cost)

The ~25.6-hour duration applies **ONLY to the Initial Full Baseline Synchronization**.

In pipeline version V9.0, the Traversal Cloud Function implements **O(1) GCS Delta Caching**:
* Before downloading or rendering, the Cloud Function pre-fetches the modification timestamps of all existing objects in your destination GCS bucket.
* It compares these against live Microsoft Graph API timestamps.
* **Unchanged files and previously rendered `.pdf` reports are instantly skipped!**
* **Subsequent hourly or daily syncs of 4,000+ items will complete in under 2 to 3 minutes**, as only newly created or modified documents are processed.

### ⚡ Performance Tuning (Speeding Up the Initial Sync)
To accelerate the initial 25.6-hour sync in your customer environment, increase concurrency limits inside [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json):
```json
{
  "CONFIG_Batch_Size": 20,
  "CONFIG_Max_Parallel_Workers": 15
}
```
*(Note: If increasing concurrency above 15, ensure your Cloud Run function revision has at least **2 vCPUs and 4GB Memory** allocated to handle simultaneous Chromium browser tabs).*

---

## 2. Active Monitoring & Real-Time Sync Progress Mechanism

Because a full enterprise sync spans multiple hours, engineers must actively monitor progress without waiting for completion or guessing if the pipeline is frozen. Before running monitoring checks, export your destination bucket from your local configuration:

```bash
# Export the target bucket name from parameters.json into your current shell:
export GCS_BUCKET=$(jq -r '.CONFIG_GCS_Bucket' parameters.json)
```

### Method A: Live GCS Bucket Object Counter (Real-Time Storage Tracking)
The most reliable way to confirm active synchronization is to track the live accumulation of PDF reports and document files landing in Google Cloud Storage.

Run these commands in Google Cloud Shell or a terminal authenticated to GCP:

```bash
# 1. Check current total count of synced files and rendered PDF pages in GCS
gcloud storage ls --recursive "gs://${GCS_BUCKET}/**" | wc -l

# 2. Check total storage size footprint consumed in the bucket
gcloud storage du -s "gs://${GCS_BUCKET}/" --readable-sizes
```

> [!WARNING]
> **Getting an `ERROR: 404 not found`?**
> If you receive an error like `ERROR: (gcloud.storage.ls) gs://yourorg-bucket-sharepoint-sync not found: 404`, it means either:
> 1. **You have not updated `parameters.json` yet**: The configuration file currently contains a default sample bucket name (`yourorg-bucket-sharepoint-sync`). Open [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json) and update `"CONFIG_GCS_Bucket"` to your actual production bucket name.

> [!WARNING]
> **Getting an `ERROR: PERMISSION_DENIED: Failed to impersonate service account`?**
> If your `gcloud` commands fail with `WARNING: This command is using service account impersonation` and `PERMISSION_DENIED: Failed to impersonate [sa@project.iam.gserviceaccount.com]`, it means your gcloud SDK has service account impersonation enabled in its config. Run this command to disable impersonation so commands authenticate directly as your user account:
> ```bash
> gcloud config unset auth/impersonate_service_account 2>/dev/null || true
> unset CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT 2>/dev/null || true
> ```
> 2. **The bucket has not been created yet in GCP**: If this is a new environment deployment and the bucket does not exist yet, create it first by running:
>    ```bash
>    gcloud storage buckets create "gs://${GCS_BUCKET}" --location=$(jq -r '.CONFIG_Location' parameters.json)
>    ```

#### 🔄 Automated Real-Time Watch Loop (Live Dashboard in Terminal)
Execute this command to monitor sync speed in real time (refreshing automatically every 30 seconds):
```bash
watch -n 30 'export GCS_BUCKET=$(jq -r ".CONFIG_GCS_Bucket" parameters.json) && \
echo "=== 📊 LIVE SHAREPOINT -> GCS SYNC MONITOR ===" && \
echo "Timestamp    : $(date)" && \
echo "Target Bucket: gs://${GCS_BUCKET}" && \
echo "------------------------------------------------------------" && \
echo -n "Total Synced Files/Pages Landed in GCS : " && \
gcloud storage ls --recursive "gs://${GCS_BUCKET}/**" 2>/dev/null | wc -l && \
echo -n "Total Bucket Storage Footprint         : " && \
gcloud storage du -s "gs://${GCS_BUCKET}/" --readable-sizes 2>/dev/null | cut -f1 && \
echo "------------------------------------------------------------"'
```
*(If the object count increments steadily every minute, the synchronization is healthy and progressing normally).*

---

### Method B: V9.0 Diagnostic Dry-Run & Delta Cache Analyzer
The V9.0 codebase includes a dedicated diagnostic check tool that directly crawls Microsoft Graph API and checks GCS cache inventory without triggering integration workflows.

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
When the Traversal Cloud Function submits batches, the Parent Integration iterates through the manifest. You can inspect the live loop execution status using the built-in checker by exporting your environment variables first:

```bash
# Export required project parameters:
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
export LOCATION=$(jq -r '.CONFIG_Location' parameters.json)
export PARENT_INTEGRATION=$(jq -r '.CONFIG_Parent_Integration_Name' parameters.json)

# Usage: python3 check/check_application_integration_execution.py <project_id> <location> <integration_name> <execution_id>
python3 check/check_application_integration_execution.py "${PROJECT_ID}" "${LOCATION}" "${PARENT_INTEGRATION}" <INSERT_EXECUTION_ID>
```
*(Retrieve the `<INSERT_EXECUTION_ID>` from Cloud Function logs or the GCP Console under **Application Integration > Executions**).*

---

## 3. Component-by-Component Diagnostic Logging Commands

To identify the root cause of sync failures, execute the following targeted `gcloud logging read` CLI commands or use the corresponding query strings in the GCP Console **Log Explorer**.

### 🛠️ Step 0: Load Your Customer Environment Parameters
Run this block in your Cloud Shell or terminal first. It reads your local [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json) and exports all relevant names as shell environment variables:

```bash
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
export SCHEDULER_JOB=$(jq -r '.CONFIG_Scheduler_Job_Name' parameters.json)
export FUNCTION_NAME=$(jq -r '.CONFIG_CloudFunction_Name' parameters.json)
export PARENT_INTEGRATION=$(jq -r '.CONFIG_Parent_Integration_Name' parameters.json)
export CHILD_INTEGRATION=$(jq -r '.CONFIG_Child_Integration_Name' parameters.json)
export GCS_BUCKET=$(jq -r '.CONFIG_GCS_Bucket' parameters.json)
export SHAREPOINT_CONN=$(jq -r '.CONFIG_SharePoint_Connection' parameters.json | awk -F/ '{print $NF}')
export GCS_CONN=$(jq -r '.CONFIG_GCS_Connection' parameters.json | awk -F/ '{print $NF}')

# Verify parameters are loaded:
echo "✅ Loaded Config for Project: ${PROJECT_ID} | Bucket: gs://${GCS_BUCKET} | Function: ${FUNCTION_NAME}"
```

---

### 3.1 Cloud Scheduler Logs (Job Trigger & Cron Health)
**Purpose**: Verify whether the recurring cron trigger successfully invoked the Traversal Cloud Function or failed during OIDC token authentication.

#### 🖥️ CLI Command
```bash
gcloud logging read "resource.type=\"cloud_scheduler_job\" AND resource.labels.job_id:\"${SCHEDULER_JOB}\"" \
    --project="${PROJECT_ID}" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, jsonPayload.status.message, textPayload)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="cloud_scheduler_job"
resource.labels.job_id="${SCHEDULER_JOB}"
```
*(Note: When pasting into Log Explorer in GCP Console, substitute `${SCHEDULER_JOB}` with your actual job name from parameters.json).*

* **What to look for**: 
  * HTTP `403 Forbidden`: The Cloud Scheduler service account (`CONFIG_Service_Account`) lacks the `roles/run.invoker` or `roles/cloudfunctions.invoker` IAM permission.
  * HTTP `504 Gateway Timeout`: The function execution exceeded the HTTP response window (ensure micro-batching is active so the function responds quickly after submitting batches).

---

### 3.2 Traversal Cloud Function / Cloud Run Logs (Graph API Crawl & Playwright Rendering)
**Purpose**: Diagnose Microsoft Graph API authentication failures, folder traversal crashes, `.aspx` page harvesting errors, and Playwright Chromium container rendering faults. *(Note: Gen2 Cloud Functions run on underlying Cloud Run revisions).*

#### 🖥️ CLI Command (View All Live Execution & Status Logs)
Standard Python `print()` statements log at `INFO`/`DEFAULT` severity. Run this command to view live progress outputs (`✅ Status Log`, `⏭️ Skipping...`, `🟢 Batch scheduled`):
```bash
gcloud logging read "(resource.type=\"cloud_function\" OR resource.type=\"cloud_run_revision\") AND resource.labels.service_name:\"${FUNCTION_NAME}\"" \
    --project="${PROJECT_ID}" \
    --limit=30 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, textPayload, jsonPayload.message)"
```

*(Tip: To filter strictly for crashes or exceptions, append `AND severity>=WARNING` to the query string.)*

#### 🔍 GCP Console Log Explorer Query
```query
(resource.type="cloud_function" OR resource.type="cloud_run_revision")
resource.labels.service_name="${FUNCTION_NAME}"
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
gcloud logging read "resource.type=\"connectors.googleapis.com/Connection\" AND (resource.labels.connection_id:\"${SHAREPOINT_CONN}\" OR resource.labels.connection_id:\"${GCS_CONN}\")" \
    --project="${PROJECT_ID}" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, jsonPayload.status.message, jsonPayload.message)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="connectors.googleapis.com/Connection"
(resource.labels.connection_id="${SHAREPOINT_CONN}" OR resource.labels.connection_id="${GCS_CONN}")
```

* **What to look for**:
  * OAuth Refresh Token Expired: SharePoint Connector V2 authentication connection needs re-authorization.
  * SSL / Handshake Termination or Network Timeout: Corporate firewall or VPC egress rules blocking connectivity to `https://*.sharepoint.com`.

---

### 3.4 Application Integration Logs (Parent Orchestrator & Child Worker)
**Purpose**: Track batch orchestration loops (`${PARENT_INTEGRATION}`) and isolate document binary download/upload streaming failures (`${CHILD_INTEGRATION}`).

#### 🖥️ CLI Command
```bash
gcloud logging read "resource.type=\"integrations.googleapis.com/IntegrationVersion\" AND (resource.labels.integration_name:\"${PARENT_INTEGRATION}\" OR resource.labels.integration_name:\"${CHILD_INTEGRATION}\")" \
    --project="${PROJECT_ID}" \
    --limit=25 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, jsonPayload.errorMessage, jsonPayload.integrationVersionId)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="integrations.googleapis.com/IntegrationVersion"
(resource.labels.integration_name="${PARENT_INTEGRATION}" OR resource.labels.integration_name="${CHILD_INTEGRATION}")
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
gcloud logging read "resource.type=\"gcs_bucket\" AND resource.labels.bucket_name:\"${GCS_BUCKET}\"" \
    --project="${PROJECT_ID}" \
    --limit=20 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, protoPayload.status.message, protoPayload.authenticationInfo.principalEmail)"
```

#### 🔍 GCP Console Log Explorer Query
```query
resource.type="gcs_bucket"
resource.labels.bucket_name="${GCS_BUCKET}"
```

* **What to look for**:
  * `403 Permission Denied`: The child integration service account lacks the `roles/storage.objectAdmin` or `roles/storage.objectCreator` role on target bucket `${GCS_BUCKET}`.
  * VPC-SC Ingress Rejection: Bucket protected by perimeter rules preventing external integration connector writes.

---

### 3.6 Secret Manager & IAM Authentication Logs (M365 Credentials Access)
**Purpose**: Confirm that the Traversal Cloud Function can successfully decrypt and access the Microsoft 365 Client Secret (`CONFIG_M365_Secret_Name`).

#### 🖥️ CLI Command
```bash
gcloud logging read "protoPayload.serviceName=\"secretmanager.googleapis.com\"" \
    --project="${PROJECT_ID}" \
    --limit=15 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, protoPayload.authenticationInfo.principalEmail, protoPayload.status.message)"
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
**Purpose**: In enterprise customer environments (like YourOrg), VPC Service Controls (VPC-SC) or firewall egress rules often silently drop external traffic to Microsoft cloud endpoints.

#### 🖥️ CLI Command (VPC Service Control Denials)
```bash
gcloud logging read "protoPayload.metadata.@type=\"type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata\" AND protoPayload.metadata.violationReason!=\"REASON_UNSPECIFIED\"" \
    --project="${PROJECT_ID}" \
    --limit=15 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, protoPayload.metadata.violationReason, protoPayload.authenticationInfo.principalEmail)"
```

#### 🔍 GCP Console Log Explorer Query (VPC-SC & Firewall Rules)
```query
(protoPayload.metadata.@type="type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata" OR resource.type="firewall_rule")
severity>=WARNING
```

---

## 4. Deep-Dive: SharePoint Throttling & DDoS Protection (Rate Limits, Timeouts & Error Codes)

When synchronizing thousands of SharePoint files or harvesting modern site pages (`.aspx`), Microsoft 365 monitors API request concurrency and volume. If a client application sends too many simultaneous requests within a short timeframe, **SharePoint's automated security defenses flag the traffic as an automated Denial-of-Service (DDoS) attack or abusive bot scraping**.

### ⚠️ How SharePoint Rejects Traffic (Symptoms & Error Codes)
When anti-DDoS or Service Throttling defenses are triggered, Microsoft Graph API and SharePoint Online respond with specific failure signatures:
1. **HTTP `429 Too Many Requests`**: Standard Microsoft throttling rejection indicating your tenant/client API rate limit has been exceeded.
2. **HTTP `503 Service Unavailable` / `Server Busy`**: The SharePoint server is actively rejecting connections to safeguard backend capacity under heavy load or suspected flood attacks.
3. **HTTP `504 Gateway Timeout` / Connection Reset (`ECONNRESET` / `ETIMEDOUT`)**: Microsoft's edge firewalls (Azure Front Door or cloud DDoS protection) forcibly terminate TCP sessions without returning an HTTP response when an IP or App Registration exceeds burst concurrency thresholds.

### ⏱️ The Critical `Retry-After` HTTP Header
When returning a `429` or `503` error, Microsoft includes an HTTP `Retry-After` header specifying the exact number of seconds (typically between **30s and 300s+**) the client **MUST** pause before sending another request.
> [!CAUTION]
> **Do Not Hammer the API During a Throttling Block!**
> If your pipeline ignores the `Retry-After` header and immediately re-attempts requests during an active block, Microsoft's security layer will escalate the throttling severity. This can lead to **multi-hour tenant API blackouts or temporary IP / Service Principal bans**!

### 🔍 Diagnostic Command: Check for SharePoint Throttling & DDoS Blocks
Run this CLI command to search your Cloud Function / Cloud Run logs specifically for throttling rejections, rate limits, and `Retry-After` headers:

```bash
gcloud logging read "(resource.type=\"cloud_function\" OR resource.type=\"cloud_run_revision\") AND resource.labels.service_name:\"${FUNCTION_NAME}\" AND (textPayload=~\"429\" OR textPayload=~\"503\" OR textPayload=~\"504\" OR textPayload=~\"Too Many Requests\" OR textPayload=~\"Retry-After\" OR textPayload=~\"Server Busy\" OR textPayload=~\"ECONNRESET\")" \
    --project="${PROJECT_ID}" \
    --limit=25 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, textPayload)"
```

### 🛡️ How to Resolve & Prevent Throttling in V9.0
1. **Tune Down Concurrency & Batch Size**: In your local [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json), lower `CONFIG_Max_Parallel_Workers` (e.g., to `5` or `8`) and `CONFIG_Batch_Size` (e.g., to `5` or `10`). This spreads the request footprint over time and avoids triggering Microsoft's DDoS heuristics.
2. **Exponential Backoff with Randomized Jitter**: The V9.0 Microsoft Graph API client (`graph_client.py`) is engineered to automatically intercept `429`/`503` responses, read the `Retry-After` header, and apply exponential backoff with randomized jitter. Verify in your logs that these retry pauses are executing rather than failing immediately.
3. **Enterprise M365 `User-Agent` Header**: Ensure your Microsoft Graph API requests include an enterprise-compliant, descriptive `User-Agent` header (e.g., `ISV|YourOrg|SharePointToGCSSync/8.0`). Microsoft strictly throttles or rejects traffic from generic or default scripting user-agents (such as `python-requests` or empty headers).

---

## 5. Root Cause Analysis Checklist (Why Sync May Have Failed)

Use this structured checklist to evaluate the top 6 most common enterprise root causes for synchronization failures in customer environments:

| Check | Potential Root Cause | Component to Inspect | How to Diagnose & Resolve |
| :---: | :--- | :--- | :--- |
| 🔲 1 | **SharePoint Throttling / Anti-DDoS Rejection** | Microsoft Graph API / SharePoint | **Diagnose**: Check **Section 4** logs for HTTP `429 Too Many Requests`, `503 Server Busy`, or `504 Gateway Timeout`.<br>**Resolve**: Reduce `CONFIG_Max_Parallel_Workers` to `5` or `8` in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json), ensure backoff jitter is enabled in `graph_client.py`, and obey `Retry-After` headers. |
| 🔲 2 | **Entra ID Conditional Access Block / Expired Secret** | Azure AD / M365 Graph API | **Diagnose**: Check **Section 3.2** logs for HTTP `401`/`403`.<br>**Resolve**: Verify in Azure Portal that `CONFIG_M365_Secret_Name` has not expired and that no Conditional Access policy requires interactive MFA for headless client-credentials flows. |
| 🔲 3 | **Playwright Chromium Out-of-Memory (OOM)** | Traversal Cloud Function (Gen2) | **Diagnose**: Check **Section 3.2** logs for `Memory limit exceeded` or container crash code `500` during `.aspx` page conversion.<br>**Resolve**: In GCP Console > Cloud Run > Revisions, increase memory allocation from 1GB to **2GB or 4GB**. |
| 🔲 4 | **VPC Service Controls (VPC-SC) Egress Block** | Network Security / Connectors | **Diagnose**: Check **Section 3.7** logs for `VpcServiceControlAuditMetadata` violation.<br>**Resolve**: Add an egress rule in perimeter settings allowing traffic to `connectors.googleapis.com` and `*.sharepoint.com`. |
| 🔲 5 | **Missing IAM Invoker or Storage Creator Roles** | IAM & Admin | **Diagnose**: Check **Section 3.4** and **Section 3.5** for `PERMISSION_DENIED`.<br>**Resolve**: Ensure service account `CONFIG_Service_Account` has `roles/integrations.integrationInvoker`, `roles/storage.objectAdmin`, and `roles/secretmanager.secretAccessor`. |
| 🔲 6 | **Micro-Batch Payload Serialization Timeout** | Application Integration | **Diagnose**: Check **Section 3.4** for workflow execution timeouts or payload size errors.<br>**Resolve**: Reduce `CONFIG_Batch_Size` to `5` or `10` in [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json) to ensure smooth streaming without exceeding integration message limits. |

---

## 6. Unified Diagnostic Log Inspector (Interactive & Timezone/Timeframe Aware)

To streamline troubleshooting across all serverless components without running individual `gcloud logging read` commands manually, use our automated diagnostic inspector script: [`check/check_all_logging.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/check/check_all_logging.py).

This script automatically pulls your Project ID, Function Name, Scheduler Job, and GCS Bucket from `parameters.json`, formats all timestamps in your selected time zone, and allows you to define custom lookback windows or start timestamps.

### Method A: Interactive Mode (Recommended)
Run the script interactively to select your time zone and enter a lookback duration or RFC3339 start timestamp:

```bash
python3 check/check_all_logging.py --interactive
```

**Interactive Prompts:**
1. **Enter target Time Zone**: Type your desired display timezone (e.g., `Asia/Singapore`, `Asia/Kuala_Lumpur`, `LOCAL`, or `UTC`).
2. **Select log timeframe filter**:
   * **Option 1 (Relative Lookback Duration)**: Enter a duration like `15m`, `30m`, `1h`, `6h`, or `24h`.
   * **Option 2 (Specific Start Timestamp)**: Enter an exact RFC3339 timestamp (e.g., `2026-07-07T05:00:00Z`).

### Method B: One-Line Non-Interactive Execution
You can also invoke the script directly with command-line arguments:

```bash
# Example 1: Look back over the last 30 minutes formatted in Singapore/Kuala Lumpur time (+08)
python3 check/check_all_logging.py --tz "Asia/Singapore" --since "30m" --limit 10

# Example 2: Query logs starting from a specific timestamp formatted in local system timezone
python3 check/check_all_logging.py --tz "LOCAL" --start-time "2026-07-07T05:00:00Z" --limit 15
```

---
*Generated for YourOrg Enterprise Support — Application Integration V9.0 Pipeline.*
