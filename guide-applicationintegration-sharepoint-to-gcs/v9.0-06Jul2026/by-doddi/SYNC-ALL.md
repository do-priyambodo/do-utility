# 🚀 SharePoint-to-GCS Complete Synchronization Operations Guide (`SYNC-ALL.md` - V9.0)
## Enterprise Execution Runbook — Production & Manual Diagnostic Sync

> [!IMPORTANT]
> **V9.0 Operational Best Practice: DO NOT Empty Your Existing Storage Bucket!**
> Unlike earlier versions, when executing a full synchronization in **V9.0**, you **DO NOT need to delete or empty existing files, modern site pages (`pages/`), or metadata (`config/metadata.jsonl`)** in your GCS bucket.
> * **Pre-Render Delta Cache Hit**: V9.0 compares timestamps (`lastModifiedDateTime`) against existing GCS objects *before* browser rendering, skipping unchanged pages instantly (<1ms per item).
> * **Automatic Self-Healing**: V9.0 automatically detects any missing or deleted items and re-renders/uploads only what is needed while preserving existing inventory.

> [!NOTE]
> **Customer Operational Reference — YourOrg Deployment**
> This operational guide outlines the two supported methods for triggering a full Microsoft 365 SharePoint-to-Google Cloud Storage (GCS) synchronization in your environment:
> * **Option 1: Manual Execution via Virtual Machine (Compute Engine / Cloud Shell)** — Recommended for initial verification, controlled debugging, and easier real-time troubleshooting.
> * **Option 2: Automated Execution via Cloud Scheduler** — Recommended for scheduled, recurring unattended production syncs (hourly, 12-hourly, or daily).

---

## 🏗️ Prerequisites & Configuration Checklist

Before initiating either synchronization method, ensure your local environment configuration is ready:
1. **Confirm Working Directory**: Navigate to the root folder of the V9.0 application bundle:
   ```bash
   cd /path/to/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg
   ```
2. **Verify [parameters.json](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/parameters.json)**: Confirm that all configuration values (Project ID, GCS Bucket, SharePoint sites, etc.) reflect your actual target environment.
3. **Verify Python Environment**: Ensure Python 3.9+ and required libraries (`google-cloud-storage`, `msal`, `requests`) are installed:
   ```bash
   python3 -m pip install -r cf-sharepoint/requirements.txt --quiet
   ```

---

## Option 1: Manual Execution via Virtual Machine (Recommended for Troubleshooting)

Running the synchronization manually from a Virtual Machine (e.g., Google Compute Engine Linux VM, local terminal, or Google Cloud Shell) gives engineers direct interactive console streaming, real-time heartbeat monitoring, and instant access to diagnostic logs.

### Step 1: Authenticate to Google Cloud SDK
Your Virtual Machine or terminal must be authenticated with a Google Cloud user account or service account that possesses permissions to invoke Cloud Functions (`roles/run.invoker` / `roles/cloudfunctions.invoker`) and query Application Integration (`roles/integrations.integrationInvoker`).

#### Method A: Authenticate as an Admin User / Developer (Interactive Login)
If you are logged into a Linux VM or Cloud Shell as an administrative engineer:
```bash
# 1. Login to Google Cloud SDK with your user account:
gcloud auth login --update-adc

# 2. Set your active target GCP Project ID from parameters.json:
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
gcloud config set project "${PROJECT_ID}"

# 3. Verify your authentication status and active project:
gcloud auth list
echo "✅ Active Project: $(gcloud config get-value project)"
```

#### Method B: Authenticate via Service Account Key / Workload Identity (Headless VM)
If running on a dedicated Compute Engine instance using a service account key or Workload Identity:
```bash
# Authenticate using a JSON service account key:
gcloud auth activate-service-account --key-file=/path/to/credentials.json

# Export project configuration:
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
gcloud config set project "${PROJECT_ID}"
```

---

### Step 2: Validate IAM Token Generation Pre-Flight
The manual synchronization script utilizes your local SDK credentials to generate Google Cloud OAuth access and identity bearer tokens. Run this quick test to ensure token generation succeeds:
```bash
echo "Testing Identity Token: $(gcloud auth print-identity-token | cut -c1-20)...✅ Valid"
echo "Testing Access Token  : $(gcloud auth print-access-token | cut -c1-20)...✅ Valid"
```
*(If either command fails, re-run `gcloud auth login --update-adc` in Step 1).*

---

### Step 3: Run the Pre-Flight Dry-Run Diagnostic Check (Optional but Recommended)
Before triggering live document downloads and batch integration workflows, run the read-only diagnostic check to inspect SharePoint inventory vs. GCS delta cache:
```bash
python3 check/check_sync_sharepoint_to_gcs.py
```
**What to verify in output**:
* Confirm the total number of files and site pages discovered in SharePoint.
* Check how many items will be skipped due to V9.0 O(1) GCS Delta Caching.

---

### Step 4: Execute the Interactive Synchronization Runner
Launch the main synchronization runner. This script connects to the Traversal Cloud Function, initiates the recursive SharePoint crawl, and submits micro-batches to the Application Integration parent orchestrator:

```bash
python3 sync/sync_sharepoint_to_gcs.py
```

#### 🖥️ What You Will See on Console (Real-Time Terminal Output):
```
================================================================================
🚀 STARTING SHAREPOINT TO GCS FULL SYNCHRONIZATION (V9.0)
================================================================================

🔍 Resolving Cloud Function URI dynamically...
✅ Resolved Cloud Function URI: https://yourorg-sharepoint-list-files-00009-8sz.asia-southeast1.run.app
   ⏳ Crawling SharePoint inventory & submitting batches to Application Integration (Elapsed time: 14s)... 
   ✅ Completed in 14s!                                    

================================================================================
🎉 ALL SYNC BATCHES SCHEDULED SUCCESSFULLY!
================================================================================
ℹ️ Executions Triggered: 12 batches
ℹ️ Batch 1 Execution ID : 39017360-1234-5678-9abc-def012345678
ℹ️ Batch 2 Execution ID : 39017360-8765-4321-cba9-876543210fed
...
```

---

### Step 5: Live Progress Monitoring & Troubleshooting
While the synchronization runs in the background across Application Integration workers, open a second terminal window on your VM to track live progress and troubleshoot any errors:

1. **Watch Live GCS Bucket Accumulation**:
   ```bash
   watch -n 30 'export GCS_BUCKET=$(jq -r ".CONFIG_GCS_Bucket" parameters.json) && \
   echo "=== 📊 LIVE SYNC MONITOR ===" && \
   echo "Total Synced Files/Pages in GCS: $(gcloud storage ls --recursive gs://${GCS_BUCKET}/** 2>/dev/null | wc -l)" && \
   echo "Total Storage Footprint        : $(gcloud storage du -s gs://${GCS_BUCKET}/ --readable-sizes 2>/dev/null | cut -f1)"'
   ```
2. **Inspect Individual Micro-Batch Execution Status**:
   ```bash
   # Substitute <EXECUTION_ID> with an ID printed in Step 4:
   export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
   export LOCATION=$(jq -r '.CONFIG_Location' parameters.json)
   export PARENT_INTEGRATION=$(jq -r '.CONFIG_Parent_Integration_Name' parameters.json)

   python3 check/check_application_integration_execution.py "${PROJECT_ID}" "${LOCATION}" "${PARENT_INTEGRATION}" <EXECUTION_ID>
   ```
3. **Troubleshoot Errors**: For in-depth diagnostic logging commands (Cloud Run logs, Connector errors, SharePoint throttling/DDoS blocks, and 404 troubleshooting), refer directly to [TROUBLSHOOTING.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/TROUBLSHOOTING.md).

---

## Option 2: Automated Execution via Google Cloud Scheduler (Production Mode)

In automated production environments, synchronization is managed entirely by Google Cloud Scheduler, which triggers the Traversal Cloud Function on a recurring cron schedule (e.g., `0 */12 * * *` for every 12 hours) via secure OpenID Connect (OIDC) authentication.

### Step 1: Verify Cloud Scheduler Job Status
Check if your configured Cloud Scheduler job is active and enabled in your GCP project:

```bash
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
export SCHEDULER_JOB=$(jq -r '.CONFIG_Scheduler_Job_Name' parameters.json)
export LOCATION=$(jq -r '.CONFIG_Location' parameters.json)

# List job details and schedule:
gcloud scheduler jobs describe "${SCHEDULER_JOB}" --location="${LOCATION}" --project="${PROJECT_ID}"
```

---

### Step 2: Trigger an Immediate Unattended Sync (Force Run)
You do not need to wait for the next scheduled cron interval to execute an automated sync. You can manually force Cloud Scheduler to trigger an immediate run from your terminal:

```bash
export PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
export SCHEDULER_JOB=$(jq -r '.CONFIG_Scheduler_Job_Name' parameters.json)
export LOCATION=$(jq -r '.CONFIG_Location' parameters.json)

echo "⚡ Force-triggering Cloud Scheduler Job: ${SCHEDULER_JOB}..."
gcloud scheduler jobs run "${SCHEDULER_JOB}" --location="${LOCATION}" --project="${PROJECT_ID}"
echo "✅ Job triggered successfully! The Traversal Cloud Function is now processing in the background."
```

---

### Step 3: Monitor Automated Execution & Diagnose Failures
Because automated Cloud Scheduler runs execute asynchronously without an interactive terminal stream, you must monitor progress and diagnose any errors using Google Cloud Logging and our comprehensive diagnostic runbook:

1. **Verify Scheduler Execution Result**:
   ```bash
   gcloud logging read "resource.type=\"cloud_scheduler_job\" AND resource.labels.job_id:\"${SCHEDULER_JOB}\"" \
       --project="${PROJECT_ID}" --limit=5 --order=desc --format="table(timestamp, severity, jsonPayload.status.message)"
   ```
2. **Refer to the Enterprise Troubleshooting Guide**:
   For complete end-to-end monitoring, error tracing, and root-cause resolution across all serverless components (Cloud Scheduler, Cloud Run/Functions, Integration Connectors, Application Integration, Secret Manager, VPC Service Controls, and SharePoint Throttling), **consult the official diagnostic document**:
   
   👉 **[📖 Enterprise Troubleshooting, Diagnostic Logging & Active Monitoring Guide (TROUBLSHOOTING.md)](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-yourorg/do-applicationintegration/app/v9.0-06Jul2026/by-yourorg/TROUBLSHOOTING.md)**

---
*Generated for YourOrg Enterprise Support — Application Integration V9.0 Pipeline.*
