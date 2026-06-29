# Serverless SharePoint-to-GCS Synchronization Pipeline (V6.0)

A production-ready enterprise serverless pipeline utilizing a Traversal Cloud Function (Python) and Google Cloud Application Integration to synchronize SharePoint documents and convert modern SharePoint site pages into executive high-fidelity PDF reports in Google Cloud Storage (GCS). Features dynamic micro-batching, O(1) GCS delta caching, and automated deletion of inactive SharePoint inventory.

---

## Architecture Topology

The sync pipeline follows an enterprise hybrid orchestrator design (V6.0):

1.  **Traversal Cloud Function (`yourorg-sharepoint-list-files`)**:
    *   Recursively queries Microsoft Graph API or dynamically scopes targeted URLs (`gs://bucket/config/target_urls.txt`).
    *   Resolves modern SharePoint site pages, downloads physical inline leadership images, and converts canvas layouts into executive `.pdf` documents via `xhtml2pdf`.
    *   Performs O(1) incremental delta timestamp comparisons (`gcs_cache`) to skip unchanged files and automatically deletes orphaned/inactive SharePoint files from GCS.
    *   Slices items into controlled micro-batches (`CONFIG_Batch_Size: 10`) to prevent timeout drops.
2.  **Application Integration Parent Orchestrator (`yourorg-sharepoint-gcs-parent`)**:
    *   Receives pre-sliced micro-batches and loops over the file manifest asynchronously.
    *   Forwards loop items to the worker integration and writes audit records to GCS (`gs://bucket/config/status/`).
3.  **Application Integration Child Worker (`yourorg-sharepoint-gcs-child`)**:
    *   Downloads document streams from SharePoint connection (using SharePoint Connector V2).
    *   Streams raw uncorrupted document bytes directly to the GCS bucket connection (using GCS Connector V1).
    *   Saves rendered high-fidelity executive `.pdf` page reports into the `pages/` path.

```
[Cloud Scheduler]
       │
       ▼ (OIDC Trigger)
┌──────────────────────────────────────┐
│  Traversal Cloud Function            │
│  (yourorg-sharepoint-list-files)     │
└──────────────────┬───────────────────┘
                   │
                   ▼ (Submit file manifest list)
┌──────────────────────────────────────┐
│  Parent Integration (Orchestrator)   │
│  (yourorg-sharepoint-gcs-parent)     │
└──────────────────┬───────────────────┘
                   │
                   ▼ (ForEach loop execution)
┌──────────────────────────────────────┐
│  Child Integration (Worker)          │
│  (yourorg-sharepoint-gcs-child)      │
└──────────┬───────────────────┬───────┘
           │                   │
           ▼ (Download Doc)    ▼ (Upload Object)
     [SharePoint]         [GCS Bucket]
```

---

## I. Prerequisites & IAM Setup

Verify the following GCP and Microsoft Azure details are active before deployment:

### 1. GCP Project Parameters
Verify credentials and names inside [parameters.json](parameters.json):
*   `CONFIG_ProjectId`: The target GCP Project ID.
*   `CONFIG_Location`: GCP region for deployment (e.g. `asia-southeast1`).
*   `CONFIG_Service_Account`: Service account under which the integrations and scheduler run.
*   `CONFIG_Child_Integration_Name`: Name of the child worker integration (e.g. `yourorg-sharepoint-gcs-child`).
*   `CONFIG_Parent_Integration_Name`: Name of the parent orchestrator integration (e.g. `yourorg-sharepoint-gcs-parent`).
*   `CONFIG_SharePoint_Connection`: Integration Connector resource ID for SharePoint.
*   `CONFIG_Sharepoint_Sites`: Subsite URL path (e.g. `sites/yourorg-sharepoint-to-gcs`).
*   `CONFIG_GCS_Connection`: Integration Connector resource ID for Google Cloud Storage.
*   `CONFIG_GCS_Bucket`: GCS target bucket for synchronizing files and pages.
*   `CONFIG_CloudFunction_Name`: Name of the Traversal Cloud Function (e.g. `yourorg-sharepoint-list-files`).
*   `CONFIG_M365_Tenant_Id`: Azure AD / M365 Directory Tenant ID.
*   `CONFIG_M365_Client_Id`: Azure AD Application (Client) ID.
*   `CONFIG_M365_Secret_Name`: GCP Secret Manager resource ID storing the M365 client secret.
*   `CONFIG_SharePoint_Hostname`: SharePoint tenant hostname (e.g. `yourorg.sharepoint.com`).
*   `CONFIG_Developer_Group_Or_User`: Developer user email or SSO group granted invoker rights for manual testing runs.
*   `CONFIG_Scheduler_Job_Name`: Name of the recurring Cloud Scheduler trigger job.
*   `CONFIG_Batch_Size`: Number of items sliced into each micro-batch (e.g. `10`).
*   `CONFIG_Max_Parallel_Workers`: Maximum concurrency limit for parallel thread execution (e.g. `10`).
*   `CONFIG_Sync_SharePoint_Files`: Boolean flag (`true` or `false`) to enable/disable syncing standard documents from Document Libraries.
*   `CONFIG_Sync_SharePoint_Pages`: Boolean flag (`true` or `false`) to enable/disable querying and converting Modern Site Pages (`.aspx`) into executive PDFs.

### 2. Azure App Registration & Microsoft Graph API Scopes
Your Azure app registration must be granted both **Delegated and Application** types for these scopes:
*   `Sites.Read.All`: Resolve subsite IDs and list site page layouts.
*   `Files.Read.All`: Retrieve standard document content streams.
*   `User.Read.All` / `User.Read`: Read user profile details.

---

## II. Deployment Guide

### Step 0: Validate Configuration Parameters
Before running any setup or deployment script, run the parameters validation tool to verify that all parameters in `parameters.json` are properly formatted and that the referenced GCP/SharePoint resources (project, service account, bucket, secret, and connector connections) are active and exist in your environment:
```bash
python3 util/validate_params.py
```
This tool will perform format verification and live resource checks. Only proceed if it completes successfully:
```
🎉 ALL PARAMETERS AND GCP RESOURCES COMPLETED VALIDATION SUCCESSFULLY!
```

For a detailed explanation of each parameter and how to create them, see the [Parameters Creation Guide](util/PARAM.md).

### (OPTIONAL!) Step 0.5: Provision Service Account and IAM Roles
Before deploying the Cloud Function or workflows, run the pre-configured role-binding script to automatically create your custom Service Account and configure both the Service Account (runtime) and your Developer User (deployment) IAM permissions:
```bash
chmod +x prereq/sa-roles.sh
./prereq/sa-roles.sh
```
This script will read `parameters.json` and execute all necessary `gcloud` commands to bind the roles.

> [!NOTE]
> If Step 0 (`validate_params.py`) failed during the live GCP resource checks because your Service Account or IAM permissions had not been created yet, run this step first to provision them. Once provisioned, execute `python3 util/validate_params.py` again to confirm all live resource checks pass.

### Step 1: Export Configuration Variables
Before executing the deployment commands, load and export the configuration parameters as environment variables in your terminal shell session. This ensures all CLI commands execute with your target configurations without hardcoding:

```bash
# 1. Export configuration variables from parameters.json
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEVELOPER_PRINCIPAL=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
export PARENT_INTEGRATION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Parent_Integration_Name', 'yourorg-sharepoint-gcs-parent'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

# 2. Extract SharePoint subsite path dynamically
export SITE_PATH=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Sharepoint_Sites', 'sites/yourorg-sharepoint-to-gcs'))")
if [[ "$SITE_PATH" == "sites/"* ]]; then
  export SITE_NAME="${SITE_PATH#sites/}"
else
  export SITE_NAME="$SITE_PATH"
fi

# 3. Extract Secret Name dynamically from parameters.json
export SECRET_PATH=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_M365_Secret_Name', ''))")
export SECRET_NAME=$(echo "$SECRET_PATH" | cut -d'/' -f4)

# 4. Extract Scheduler Job Name dynamically from parameters.json
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'yourorg-sharepoint-sync-hourly'))")
```

### Step 2: Deploy Traversal Cloud Function
1. Grant the Cloud Function service account Secret Manager Accessor role for the Azure AD Client Secret:
   ```bash
   gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
     --member="serviceAccount:${SERVICE_ACCOUNT}" \
     --role="roles/secretmanager.secretAccessor" \
     --project="${PROJECT_ID}"
   ```
2. Deploy the Cloud Function by running:
```bash
chmod +x deploy_cloud_function.sh
./deploy_cloud_function.sh
```

### Step 3: Set up Cloud Run Invoker Bindings
Since Gen2 Cloud Functions run on top of Cloud Run, grant both the Cloud Scheduler Service Account (for automated runs) and your Developer Group / User (for manual sync runs) invoker rights on the Cloud Run revision:
```bash
# 1. Grant invoker rights to Cloud Scheduler Service Account
gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

# 2. Grant invoker rights to Developer Principal (for manual testing runs)
# Auto-format member prefix (user: or group:)
if [[ "${DEVELOPER_PRINCIPAL}" == *"group"* || "${DEVELOPER_PRINCIPAL}" == *"ggrp"* || "${DEVELOPER_PRINCIPAL}" == "group:"* ]]; then
  DEV_MEMBER="group:${DEVELOPER_PRINCIPAL#group:}"
else
  DEV_MEMBER="user:${DEVELOPER_PRINCIPAL#user:}"
fi

gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --member="${DEV_MEMBER}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"
```

### Step 3.5: Pre-Flight Interactive Diagnostics & Verification
Before deploying integration workflows (or when upgrading an existing customer environment), run our standalone interactive diagnostic checks to verify authentication and inspect live inventory counts without modifying anything:

1. **Verify Azure AD / Microsoft Graph Authentication**:
   Verify that your Client Secret and Service Account token generation work cleanly:
   ```bash
   python3 check_entra_id_auth.py
   ```
2. **Simulate SharePoint Traversal (Dry-Run)**:
   Test your connection to the deployed Cloud Function and see exactly which PDF documents and site pages are discovered in SharePoint (without triggering download batches):
   * **For Option 1 (Dynamic Remote Whitelist)**:
     ```bash
     python3 check_sync_gcs_dynamic.py --dry-run
     ```
   * **For Option 2 (Full Enterprise Traversal)**:
     ```bash
     python3 check_sync_sharepoint_to_gcs.py --dry-run
     ```
3. **Granular File-by-File Audit**:
   If you want to print out the complete itemized list of every discovered file and folder path:
   ```bash
   python3 check_sharepoint_discovery_dryrun.py
   ```

### Step 4: Parameterize and Deploy Integration Workflows
Compile the template files (`child_workflow.json` and `parent_workflow.json`), substitute placeholders dynamically, and deploy them to GCP:
```bash
python3 deploy_workflows.py
```

---

## III. How to Run This App (Execution & Scheduling)

You can execute this synchronization app using two operational models depending on whether you are targeting specific URLs or sweeping the entire repository:

| Option | Operational Model | Whitelist Source | Python On-Demand Runner | Cloud Scheduler Cron Deployer |
| :---: | :--- | :--- | :--- | :--- |
| **Option 1** | **Dynamic Remote Whitelist** *(Recommended)* | `gs://YOUR_BUCKET/config/target_urls.txt` | `python3 sync_gcs_dynamic.py` | `./deploy_scheduler_targeted_gcs_sync.sh` |
| **Option 2** | **Full Traversal Sync** | Entire SharePoint Site | `python3 sync_sharepoint_to_gcs.py` | `./deploy_scheduler_full_sharepoint_sync.sh` |

---

### Option 1: Sync specific URLs based on `target_urls.txt` in GCS bucket (RECOMMENDED)
Allow business users or administrators to maintain a dynamic list of synchronized URLs live inside Google Cloud Storage without requiring Git repository or terminal CLI access. Features micro-batching (`CONFIG_Batch_Size: 10`), delta cache filtering, and automated deletion of inactive files.

#### A. Manual On-Demand Execution (Terminal)
1. Ensure your target URLs are uploaded to GCS (e.g. `gs://YOUR_BUCKET/config/target_urls.txt`). You can populate `target_urls.txt` locally and upload it:
   ```bash
   ./upload_gcs_targets.sh
   ```
2. Run the dynamic standalone runner (displays real-time console progress per batch and file):
   ```bash
   python3 sync_gcs_dynamic.py
   ```

#### B. Automated Recurring Cron (Cloud Scheduler)
To deploy an automated hourly background trigger that reads `target_urls.txt` from GCS on every run:
```bash
./deploy_scheduler_targeted_gcs_sync.sh
```
*(Whenever users update `target_urls.txt` inside the GCP Storage Console, the recurring cron automatically picks up the new files live!)*

---

### Option 2: Sync the whole SharePoint Sites content
Crawl and synchronize **all** documents and modern site pages across the configured SharePoint subsite and library with O(1) GCS timestamp skipping.

#### A. Manual On-Demand Execution (Terminal)
```bash
python3 sync_sharepoint_to_gcs.py
```

#### B. Automated Recurring Cron (Cloud Scheduler)
To deploy an automated periodic full-crawl schedule:
```bash
./deploy_scheduler_full_sharepoint_sync.sh
```

---

### Additional Diagnostic Helpers
We provide dedicated verification tools so you can inspect your pipeline configuration, estimate runtimes, and verify SharePoint connections before transferring files:

* **Dynamic Targeted Sync Inspection**: Check target inventory breakdown (`.aspx` pages vs documents), inspect cached GCS sizes, and view performance estimates:
  ```bash
  python3 check_sync_gcs_dynamic.py
  ```
* **Full Traversal Sync Inspection**: Verify SharePoint subsite configuration, check existing GCS bucket inventory, and review runtime delta behavior:
  ```bash
  python3 check_sync_sharepoint_to_gcs.py
  ```
* **Lightning-Fast Verification (Max 10 Cutoff)**: Verify Microsoft Entra ID authentication and site folder resolution in under 3 seconds:
  ```bash
  cd test-few-files-only && python3 check_files_subset.py
  ```

---

## IV. Troubleshooting & Observability

If any step in the synchronization pipeline fails, use the following diagnostic commands.

> [!NOTE]
> To ensure the CLI commands below run seamlessly without unexpanded variable errors, export your environment variables from `parameters.json` first:
```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
export PARENT_INTEGRATION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Parent_Integration_Name', 'yourorg-sharepoint-gcs-parent'))")
export CHILD_INTEGRATION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Child_Integration_Name', 'yourorg-sharepoint-gcs-child'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'yourorg-sharepoint-sync-hourly'))")
```

### 1. Cloud Function (SharePoint Traversal) Requests & Auth Logs
To verify whether requests reached the Traversal Cloud Function or failed with authentication errors (`401 Unauthorized` / `403 Forbidden`):
```bash
gcloud logging read '(resource.type="cloud_run_revision" AND resource.labels.service_name="'"${FUNCTION_NAME}"'") OR protoPayload.serviceName="run.googleapis.com"' \
  --project="${PROJECT_ID}" \
  --limit=20 \
  --format="table(timestamp, httpRequest.status, textPayload, protoPayload.status.message)"
```

### 2. Application Integration Workflows (Parent & Child) Logs
To view runtime errors, execution failures, or connector issues inside Application Integration:
```bash
gcloud logging read 'resource.type="integrations.googleapis.com/IntegrationVersion" AND (resource.labels.integration_name="'"${PARENT_INTEGRATION_NAME}"'" OR resource.labels.integration_name="'"${CHILD_INTEGRATION_NAME}"'")' \
  --project="${PROJECT_ID}" \
  --limit=20 \
  --format="table(timestamp, severity, jsonPayload.message, textPayload)"
```

### 3. Cloud Scheduler Trigger Logs
To verify whether automated hourly scheduler runs fired successfully or encountered target trigger failures:
```bash
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="'"${SCHEDULER_JOB_NAME}"'"' \
  --project="${PROJECT_ID}" \
  --limit=15 \
  --format="table(timestamp, severity, jsonPayload.status, jsonPayload.targetType)"
```

### 4. Monitoring Real-Time Sync Progress & Audit Dashboards

When executing the sync pipeline (either manually via terminal or automated via **Cloud Scheduler**), real-time progress and status reports are automatically ingested by Google Cloud and can be monitored across five dedicated views:

#### A. Interactive Terminal Console (Manual Runs)
When executing `python3 sync_gcs_dynamic.py`, the terminal displays live item-by-item progress, delta cache hits, and prepared upload paths:
```text
================================================================================
⚡ Processing Micro-Batch 1/10 (10 URLs)...
================================================================================
   🔹 [1/10] Target: https://yourorg.sharepoint.com/sites/yoursubsite/SitePages/Executive-Briefing.aspx
   ⏳ Invoking Cloud Function to render/resolve batch...
   ✅ Cloud Function resolved Batch 1 successfully!
      • Total items scanned in batch: 10
      • Items needing upload (Delta hit/rendered): 8
      • Skipped (Unchanged in GCS / Delta cache hit): 2
      📄 Prepared item: Executive-Briefing.pdf -> gs://yourorg-bucket-sharepoint-sync/pages/Executive-Briefing.pdf
   ⏳ Submitting Batch 1 to Application Integration...
   🟢 Integration triggered successfully -> Execution ID: 9f8a7b6c-5d4e...
   🎉 Micro-Batch 1/10 COMPLETED SUCCESSFULLY!
```

#### B. Cloud Logging (Logs Explorer) — *Real-Time Live Stream*
Every print statement and status report automatically streams into **Google Cloud Logging**.
* Navigate to **Logging > Logs Explorer** in the GCP Console.
* Paste this filter query to watch automated background runs live:
  ```text
  resource.type="cloud_function"
  resource.labels.function_name="${FUNCTION_NAME}"
  ```
  *(If wrapped inside a Cloud Run job, filter by `resource.type="cloud_run_job"`).*

#### C. Cloud Scheduler Dashboard — *Cron Trigger History*
* Navigate to **Cloud Scheduler** in the GCP Console.
* Locate your automated job (`yourorg-sharepoint-sync-hourly`).
* Check the **Result** column (`Success` or `Failed`) and timestamp of the last execution.
* Click the **"View Logs"** button on the far right of the row to instantly open the filtered log stream for that specific cron run.

#### D. Application Integration Console — *Visual Workflow Graph*
* Navigate to **Application Integration > Executions**.
* Click on any generated `Execution ID` (or paste the clickable URL outputted by the terminal).
* Inspect the node-by-node visual graph showing exactly which micro-batch succeeded and how many documents transferred. You can also run the CLI helper:
  ```bash
  python3 check_application_integration_execution.py "${PROJECT_ID}" "${LOCATION}" "${PARENT_INTEGRATION_NAME}" "<EXECUTION_ID>"
  ```

#### E. GCS Audit Manifests — *Permanent Historical File Log*
At the conclusion of every 10-item micro-batch, the orchestrator deposits a structured completion audit manifest into your bucket:
`gs://yourorg-bucket-sharepoint-sync/config/status/`

Inspect these audit records anytime via terminal or UI:
```bash
gcloud storage ls gs://${GCS_BUCKET}/config/status/
```

### 5. Inspect Local Setup & Cloud Diagnostic Logs
Local helper scripts automatically record setup trajectories and cloud responses into **timestamped** log files inside the `log/` folder:
```bash
# List all generated log files
ls -la log/

# View the latest setup log
tail -n 50 log/setup.log.*

# View the latest Cloud Function response payload
tail -n 50 log/cloud.log.*
```

---

## 🧠 6. Vertex AI Search Datastore Ingestion & Manual Purging (Future Roadmap / Phase 4b)

When files and pages are synchronized to Google Cloud Storage (`gs://yourorg-bucket-sharepoint-sync/`), our Traversal Cloud Function automatically deposits a structured JSONL manifest at `gs://yourorg-bucket-sharepoint-sync/config/metadata.jsonl`. Each record attaches custom schema attributes (`sharepoint_url`, `title`, `_id`, and `content.uri`) so frontend Contact Center AI / GKA widgets redirect citation clicks directly to live SharePoint pages.

### ⚙️ Future Ingestion Setup Guide
When you are ready to connect Vertex AI Search Datastore to your synchronized bucket:
1. **Create Datastore as JSONL**: In the Google Cloud Console, select **Cloud Storage > JSON lines (JSONL) with custom metadata** and enter `gs://yourorg-bucket-sharepoint-sync/config/metadata.jsonl`. Because each JSON line contains `"content": {"uri": "gs://..."}`, Discovery Engine automatically locates and indexes the PDF files!
2. **Automated Trigger**: You can deploy a Cloud Function and Cloud Scheduler job to periodically hit the Discovery Engine `importDocuments` API with `"reconciliationMode": "INCREMENTAL"` to automatically refresh the Datastore index whenever new files arrive.

---

## 🏗️ 7. Preparing for Vertex AI Search Datastore from Synced GCS

To ensure that your Contact Center AI (CCAI) / Generative Knowledge Assist (GKA) agents always receive custom metadata attributes (`sharepoint_url`) and avoid random hash IDs, follow these step-by-step best practices when configuring your Data Store in Google Cloud Console:

### Step 1: Remove Unstructured Raw Bucket Scanners
If your Datastore was originally created using **Unstructured documents (HTML, PDF, TXT)** pointing to the bucket root:
1. Navigate to **Google Cloud Console > Vertex AI Search > Data Stores** and select your Datastore.
2. Click the **Data Sources** tab on the left menu.
3. Click the three dots (`⋮`) next to the existing unstructured Cloud Storage data source and select **Delete / Remove Data Source**.

### Step 2: Add Custom JSONL Metadata Data Source
1. Click **+ Add Data Source > Cloud Storage**.
2. When prompted for data format, select **JSON lines (JSONL) with custom metadata** (or **Custom Schema**).
3. Enter the exact manifest path generated by our synchronization pipeline:
   ```text
   gs://yourorg-bucket-sharepoint-sync/config/metadata.jsonl
   ```

### Step 3: Configure Ingestion Synchronization
Once your data source points to `config/metadata.jsonl`:
* Even when Google Cloud's built-in console schedule runs (e.g., Daily, 3 Days, or 5 Days), it will cleanly ingest `metadata.jsonl`, attaching the correct `"sharepoint_url"` and `"title"` to every document automatically.
* You can safely upload manual files into GCS alongside your synchronized SharePoint content without them being overwritten or losing metadata formatting!
