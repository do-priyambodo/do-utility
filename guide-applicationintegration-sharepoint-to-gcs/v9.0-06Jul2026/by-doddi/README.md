# Serverless SharePoint-to-GCS Synchronization Pipeline (V9.0)

A production-ready enterprise serverless pipeline utilizing a Traversal Cloud Function (Python) and Google Cloud Application Integration to synchronize SharePoint documents and convert modern SharePoint site pages into executive high-fidelity PDF reports in Google Cloud Storage (GCS). Features dynamic micro-batching, O(1) GCS delta caching, automated deletion of inactive SharePoint inventory, and an **Intelligent Image URL Resolver** for enterprise OData/thumbnail endpoints.

---

## 📂 Modular Directory Architecture (V9.0)

The V9.0 codebase is organized into clean domain-specific subdirectories with automated root path resolution:
* **`deploy/`**: Infrastructure and workflow deployment scripts (`deploy_cloud_run.sh`, `deploy_workflows.py`, cron schedulers) and workflow JSON templates.
* **`sync/`**: Synchronization pipeline runners (`sync_sharepoint_to_gcs.py`, `sync_gcs_dynamic.py`, `sync_datastore.py`, `upload_gcs_targets.sh`).
* **`check/`**: Read-only pre-flight inspection and diagnostic scripts (`check_entra_id_auth.py`, discovery dry-runs).
* **`test/`**: Verification unit tests (`test_image_fetch.py`), Jupyter notebooks, and subset trial runners.
* **`util/`**: Prerequisite IAM scripts (`prereq/`), parameter validation (`validate_params.py`), and logging helpers (`log_helper.py`).
* **`docs/`**: Architecture guides (`GUIDE_GKA_Live_SharePoint_Links.md`), parameter reference (`PARAM.md`), and roadmaps.
* **Root (`by-yourorg/`)**: Retains only core configuration (`parameters.json`, `target_urls.txt`), SharePoint Traversal & PDF backend source (`cf-sharepoint/`), and dedicated Datastore import service (`cf-datastore/`).

---

## Architecture Topology

The sync pipeline follows an enterprise hybrid orchestrator design (V9.0):

1.  **Traversal Cloud Function (`yourorg-sharepoint-list-files`)**:
    *   **Modular Architecture:** Cleanly refactored from a single monolithic file into specialized modules (`graph_client.py` for resilient M365 auth/retries, `pdf_renderer.py` for multi-engine Playwright/WeasyPrint PDF conversion, `sharepoint_traversal.py` for recursive drive inventory and DOM layout harvesting, and `main.py` for HTTP orchestration).
    *   **Monolithic Revertability:** A pre-refactor backup (`cf-sharepoint/main.py.monolithic.bak`) and git tag (`v6.0-monolithic-backup`) are maintained for instant rollback if desired.
    *   Recursively queries Microsoft Graph API or dynamically scopes targeted URLs (`gs://bucket/config/target_urls.txt`).
    *   **Pre-Render Delta Cache Filter:** Performs O(1) incremental delta timestamp comparisons (`gcs_cache`) *before* browser rendering to skip unchanged files and pages instantly (<1ms).
    *   **Strict Safe Orphan Guard:** Deletes orphaned/inactive SharePoint files from GCS *only* upon completing a 100% full unconstrained traversal (`sync_files` + `sync_pages` + `max_items is None`), protecting partial/scoped runs.
    *   **Streaming Parallel Pipelined Chunk Execution:** Chunks items into blocks (`CONFIG_Batch_Size × CONFIG_Max_Parallel_Workers`) to render `.aspx` site pages via parallel Playwright worker threads (~5x speedup) and immediately dispatch micro-batches to Application Integration with automatic memory flushing.
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
*   `CONFIG_PDF_Conversion_Engine`: Selects the rendering engine for `.aspx` to PDF conversion (`playwright` vs `weasyprint`).
    *   **`playwright` (Default / Recommended)**: Launches full Headless Chromium browser automation (`playwright-python`). Executes live JavaScript, dropdowns, and dynamic widgets to capture exact desktop browser snapshots with high-definition styling. Deployed via custom Docker container (Option A) with Chromium binaries baked inside.
    *   **`weasyprint` (Fallback Engine)**: Pure Python HTML5 vector PDF generator. Used as an automatic fallback if Chromium container binaries are unavailable in standard buildpacks.

### 2. Azure App Registration & Microsoft Graph API Scopes
Your Azure app registration must be granted both **Delegated and Application** types for these scopes:
*   `Sites.Read.All`: Resolve subsite IDs and list site page layouts.
*   `Files.Read.All`: Retrieve standard document content streams.
*   `User.Read.All` / `User.Read`: Read user profile details.

---

## II. Deployment Guide

### ⚡ Customer Quick-Start Checklist (Step-by-Step for Tomorrow)
If you are deploying V9.0 tomorrow in a fresh customer environment or upgrading an existing setup, follow this exact 5-step order:
1. **Validate Environment**: Fill in `parameters.json` and run `python3 util/validate_params.py` (or run `./util/prereq/sa-roles.sh` first if IAM/Service Accounts are not yet created).
2. **Export Shell Variables**: Copy and run the block in **Step 1** to export `PROJECT_ID`, `LOCATION`, `FUNCTION_NAME`, etc., into your terminal session.
3. **Deploy Cloud Run Backend**: Run `./deploy/deploy_cloud_run.sh` (**Step 2 Option A**) to deploy the high-fidelity Playwright container, then copy and paste the IAM commands in **Step 3** (which include auto-retry fallback for Google Cloud Identity groups).
4. **Deploy Application Integration Workflows**: Run `python3 deploy/deploy_workflows.py` (**Step 4**) to publish the orchestrator pipelines.
5. **Execute Verification Test**: Run `python3 sync/sync_gcs_dynamic.py --force` to test dynamic URL syncing and verify that PDFs render perfectly in your GCS bucket!

---

### Step 0: Validate Configuration Parameters
Before running any setup or deployment script, run the parameters validation tool to verify that all parameters in `parameters.json` are properly formatted and that the referenced GCP/SharePoint resources (project, service account, bucket, secret, and connector connections) are active and exist in your environment:
```bash
python3 util/validate_params.py
```
This tool will perform format verification and live resource checks. Only proceed if it completes successfully:
```
🎉 ALL PARAMETERS AND GCP RESOURCES COMPLETED VALIDATION SUCCESSFULLY!
```

For a detailed explanation of each parameter and how to create them, see the [Parameters Creation Guide](docs/PARAM.md).

### (OPTIONAL!) Step 0.5: Provision Service Account and IAM Roles
Before deploying the Cloud Function or workflows, run the pre-configured role-binding script to automatically create your custom Service Account and configure both the Service Account (runtime) and your Developer User (deployment) IAM permissions:
```bash
chmod +x util/prereq/sa-roles.sh
./util/prereq/sa-roles.sh
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
2. Choose your deployment method based on your selected PDF conversion engine:
   * **👉 Option A: Custom Docker Container (MANDATORY & RECOMMENDED FOR V9.0 DEFAULT)**:
     **Use this option!** We are currently using this deployment method because V9.0 defaults to Playwright (Headless Chromium) to solve customer feedback regarding missing visual images and complex page layouts. This script builds and deploys a custom container on Cloud Run using Microsoft's official Playwright base image (`mcr.microsoft.com/playwright/python:v1.44.0-jammy`) with Linux Chromium binaries pre-installed:
     ```bash
     chmod +x deploy/deploy_cloud_run.sh
     ./deploy/deploy_cloud_run.sh
     ```
   * **Option B: Standard Buildpacks (Alternative Fallback Only)**:
     *Skip this option unless your organization strictly bans custom Docker containers.* Deploys via standard Google Cloud Function Gen 2 buildpacks without container overhead or Chromium binaries (requires changing `parameters.json` to `"CONFIG_PDF_Conversion_Engine": "weasyprint"`):
     ```bash
     chmod +x deploy/deploy_cloud_function.sh
     ./deploy/deploy_cloud_function.sh
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
# Automatically clean user:/group: prefix and apply intelligent retry fallback
CLEAN_PRINCIPAL="${DEVELOPER_PRINCIPAL#group:}"
CLEAN_PRINCIPAL="${CLEAN_PRINCIPAL#user:}"

if [[ "${DEVELOPER_PRINCIPAL}" == "group:"* || "${DEVELOPER_PRINCIPAL}" == *"group"* || "${DEVELOPER_PRINCIPAL}" == *"ggrp"* || "${DEVELOPER_PRINCIPAL}" == *"Agentassist"* ]]; then
  DEV_MEMBER="group:${CLEAN_PRINCIPAL}"
else
  DEV_MEMBER="user:${CLEAN_PRINCIPAL}"
fi

if ! gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --member="${DEV_MEMBER}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"; then
  echo "⚠️ Binding failed for ${DEV_MEMBER}. Automatically retrying with alternate IAM principal type..."
  if [[ "${DEV_MEMBER}" == "user:"* ]]; then
    DEV_MEMBER="group:${CLEAN_PRINCIPAL}"
  else
    DEV_MEMBER="user:${CLEAN_PRINCIPAL}"
  fi
  gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
    --region="${LOCATION}" \
    --member="${DEV_MEMBER}" \
    --role="roles/run.invoker" \
    --project="${PROJECT_ID}"
fi
```

### Step 3.5: Pre-Flight Interactive Diagnostics & Verification
Before deploying integration workflows (or when upgrading an existing customer environment), run our standalone interactive diagnostic checks to verify authentication and inspect live inventory counts without modifying anything:

1. **Verify Azure AD / Microsoft Graph Authentication**:
   Verify that your Client Secret and Service Account token generation work cleanly:
   ```bash
   python3 check/check_entra_id_auth.py
   ```
2. **Simulate SharePoint Traversal (Dry-Run)**:
   Test your connection to the deployed Cloud Function and see exactly which PDF documents and site pages are discovered in SharePoint (without triggering download batches):
   * **For Option 1 (Dynamic Remote Whitelist)**:
     ```bash
     python3 check/check_sync_gcs_dynamic.py --dry-run
     ```
   * **For Option 2 (Full Enterprise Traversal)**:
     ```bash
     python3 check/check_syncall_before.py
     ```
3. **Granular File-by-File Audit**:
   If you want to print out the complete itemized list of every discovered file and folder path:
   ```bash
   python3 check/check_sharepoint_discovery_dryrun.py
   ```

### Step 4: Parameterize and Deploy Integration Workflows
Compile the template files (`child_workflow.json` and `parent_workflow.json`), substitute placeholders dynamically, and deploy them to GCP:
```bash
python3 deploy/deploy_workflows.py
```

---

## III. How to Run This App (Execution & Scheduling)

You can execute this synchronization app using two operational models depending on whether you are targeting specific URLs or sweeping the entire repository:

| Option | Operational Model | Whitelist Source | Python On-Demand Runner | Cloud Scheduler Cron Deployer |
| :---: | :--- | :--- | :--- | :--- |
| **Option 1** | **Dynamic Remote Whitelist** *(Recommended)* | `gs://YOUR_BUCKET/config/target_urls.txt` | `python3 sync/sync_gcs_dynamic.py` | `./deploy/deploy_scheduler_targeted_gcs_sync.sh` |
| **Option 2** | **Full Traversal Sync** | Entire SharePoint Site | `python3 sync/sync_sharepoint_to_gcs.py` | `./deploy/deploy_scheduler_full_sharepoint_sync.sh` |

---

### Option 1: Sync specific URLs based on `target_urls.txt` in GCS bucket (RECOMMENDED)
Allow business users or administrators to maintain a dynamic list of synchronized URLs live inside Google Cloud Storage without requiring Git repository or terminal CLI access. Features micro-batching (`CONFIG_Batch_Size: 10`), delta cache filtering, and automated deletion of inactive files.

#### A. Manual On-Demand Execution (Terminal)
1. Ensure your target URLs are uploaded to GCS (e.g. `gs://YOUR_BUCKET/config/target_urls.txt`). You can populate `target_urls.txt` locally and upload it:
   ```bash
   ./sync/upload_gcs_targets.sh
   ```
2. Run the dynamic standalone runner (displays real-time console progress per batch and file):
   * **Default Mode (Incremental Delta Caching):** Automatically compares timestamps against existing files in your GCS bucket (`gcs_cache`). If an identical file already exists with an unchanged timestamp, it is **instantly skipped** to drop transfer volume by 99.9% and eliminate Microsoft Graph API throttling:
     ```bash
     python3 sync/sync_gcs_dynamic.py
     ```
   * **Force Full Sync Mode (`--force`):** Completely bypasses the GCS Delta Cache and forces a fresh re-download, re-render (via headless Playwright Chromium), and re-upload of **every single URL** in `target_urls.txt` regardless of timestamp. Use this during live customer demos or to force-refresh PDF layout styles:
     ```bash
     python3 sync/sync_gcs_dynamic.py --force
     ```

#### B. Automated Recurring Cron (Cloud Scheduler)
To deploy an automated hourly background trigger that reads `target_urls.txt` from GCS on every run:
```bash
./deploy/deploy_scheduler_targeted_gcs_sync.sh
```
*(Whenever users update `target_urls.txt` inside the GCP Storage Console, the recurring cron automatically picks up the new files live!)*

---

### Option 2: Sync the whole SharePoint Sites content (`SYNC-ALL.md`)
Crawl and synchronize **all** documents and modern site pages across the configured SharePoint subsite and library with O(1) GCS timestamp skipping and streaming parallel pipelined chunk execution.

> [!IMPORTANT]
> **V9.0 Operational Note: DO NOT Empty Your Storage Bucket Before Syncing!**
> When executing a full enterprise synchronization in **V9.0**, **DO NOT delete or empty existing files, pages (`pages/`), or metadata (`config/metadata.jsonl`)** in your GCS bucket.
> * **Pre-Render Delta Cache Hit**: V9.0 checks SharePoint timestamps (`lastModifiedDateTime`) against existing GCS objects *before* browser rendering, skipping unchanged pages instantly (<1ms).
> * **Automatic Self-Healing**: V9.0 detects missing or deleted files and restores only what is missing without re-rendering existing valid inventory.
> * For the complete end-to-end enterprise runbook, see [SYNC-ALL.md](SYNC-ALL.md).

#### A. Manual On-Demand Execution (Terminal)
For detailed step-by-step diagnostic execution instructions, consult the complete runbook in **[SYNC-ALL.md](SYNC-ALL.md)**:
```bash
python3 sync/sync_sharepoint_to_gcs.py
```

#### B. Automated Recurring Cron (Cloud Scheduler)
To deploy an automated periodic full-crawl schedule:
```bash
./deploy/deploy_scheduler_full_sharepoint_sync.sh
```

#### C. Step-by-Step Playbook: Start Sync for Whole Contents (~Thousands of Pages)
When initiating an enterprise synchronization across thousands of documents and site pages, follow this execution playbook (see **[SYNC-ALL.md](SYNC-ALL.md)** for full reference):

##### Step 1: Trigger the Sync in Cloud Scheduler (No Bucket Reset Needed)
Navigate to **Google Cloud Console ➔ Cloud Scheduler**, locate your full SharePoint synchronization job (e.g., `yourorg-sharepoint-sync-hourly`), and click **Force run**. Unchanged pages will be skipped via delta cache, and missing pages will be automatically self-healed.
Navigate to **Google Cloud Console ➔ Cloud Scheduler**, locate your full SharePoint synchronization job (e.g., `yourorg-sharepoint-sync-hourly`), and click **Force run**.

##### Step 3: Live Progress Monitoring Command
Run this command repeatedly (every 2–3 minutes) to monitor real-time worker batch executions and watch GCS file/page counts grow:
```bash
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")
echo "========================================================"
echo "📂 1a. Documents currently in GCS (files/**):"
gcloud storage ls gs://${BUCKET_NAME}/files/** 2>/dev/null | wc -l
echo "📄 1b. Site Pages currently in GCS (pages/**):"
gcloud storage ls gs://${BUCKET_NAME}/pages/** 2>/dev/null | wc -l
echo "========================================================"
echo "⚙️ 2. Checking Application Integration Executions..."
python3 -c "
import json, urllib.request, subprocess
params = json.load(open('parameters.json'))
proj, loc = params['CONFIG_ProjectId'], params['CONFIG_Location']
parent, child = params['CONFIG_Parent_Integration_Name'], params['CONFIG_Child_Integration_Name']
token = subprocess.check_output(['gcloud', 'auth', 'print-access-token']).decode().strip()

for name, label in [(parent, 'PARENT (Orchestrator)'), (child, 'CHILD (Workers)')]:
    url = f'https://{loc}-integrations.googleapis.com/v1/projects/{proj}/locations/{loc}/integrations/{name}/executions?pageSize=5'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        data = json.loads(urllib.request.urlopen(req).read().decode())
        print(f'=== {label} ({name}) ===')
        execs = data.get('executions', [])
        if not execs:
            print('   (No executions found yet)')
        for i, ex in enumerate(execs):
            state = ex.get('state') or ex.get('executionDetails', {}).get('state') or ex.get('eventExecutionDetails', {}).get('eventExecutionState', 'UNKNOWN')
            id_str = ex.get('name', '').split('/')[-1]
            print(f'   Batch {i+1} [ID: {id_str}]: {state}')
            err = ex.get('executionDetails', {}).get('failureReason') or ex.get('error')
            if err: print(f'      ❌ Error: {err}')
    except Exception as e:
        print(f'   Could not check {label}: {e}')
"
echo "========================================================"
```

##### Step 4: Final Count & Inventory Verification
Once all worker batches transition to `SUCCEEDED`, execute this final audit block to confirm total ingestion:
```bash
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")
echo "========================================================"
echo "🎉 FINAL SYNCHRONIZATION RESULTS:"
echo "========================================================"
echo -n "📂 Total Documents Downloaded: "
gcloud storage ls gs://${BUCKET_NAME}/files/** 2>/dev/null | wc -l

echo -n "📄 Total Site Pages Rendered to PDF: "
gcloud storage ls gs://${BUCKET_NAME}/pages/** 2>/dev/null | wc -l

echo -n "🧠 Total Items Indexed in Metadata Manifest: "
gcloud storage cat gs://${BUCKET_NAME}/config/metadata.jsonl 2>/dev/null | wc -l
echo "========================================================"
```

#### D. How to Abort Running Executions & Cleanly Redo a Massive Sync (~Thousands of Pages)
When synchronizing thousands of items (~9,000+ pages and documents), deleting or redeploying Cloud Scheduler does **not** terminate worker tasks that are already executing in the background, because Cloud Scheduler only acts as the trigger alarm.

If you need to instantly abort an ongoing enterprise synchronization and redo everything from scratch, use one of the two bulk abort methods below before running Step 1 of the clean reset playbook above:

##### Method 1: The UI Kill Switch (Fastest — 10 Seconds)
1. In Google Cloud Console, navigate to **Application Integration ➔ Integrations**.
2. Locate your child worker integration (e.g., `yourorg-sharepoint-gcs-child`).
3. Click the **three dots (⋮)** on the right side of the integration row ➔ click **Unpublish** (or **Archive / Disable**). This instantly drops all queued batches and halts running workers.
4. Wait 10 seconds, then click the **three dots (⋮)** again ➔ click **Publish** (or **Restore**) to re-enable the engine for a clean reset.

##### Method 2: Automated Bulk Cancel Script (via Cloud Shell)
If you prefer not to touch the UI and want to programmatically find every single active or queued batch among the thousands of items and abort them via the Google Cloud API, copy and paste this command block into Cloud Shell:
```bash
python3 -c "
import json, urllib.request, subprocess
params = json.load(open('parameters.json'))
proj, loc = params['CONFIG_ProjectId'], params['CONFIG_Location']
parent, child = params['CONFIG_Parent_Integration_Name'], params['CONFIG_Child_Integration_Name']
token = subprocess.check_output(['gcloud', 'auth', 'print-access-token']).decode().strip()

for name, label in [(parent, 'PARENT (Orchestrator)'), (child, 'CHILD (Workers)')]:
    print(f'🛑 Scanning for active executions in {label} ({name})...')
    url = f'https://{loc}-integrations.googleapis.com/v1/projects/{proj}/locations/{loc}/integrations/{name}/executions?pageSize=200'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        data = json.loads(urllib.request.urlopen(req).read().decode())
        execs = data.get('executions', [])
        cancelled_count = 0
        for ex in execs:
            state = ex.get('eventExecutionDetails', {}).get('eventExecutionState', '')
            if state in ['IN_PROGRESS', 'QUEUED', 'ON_HOLD', 'PENDING']:
                exec_name = ex['name']
                cancel_url = f'https://{loc}-integrations.googleapis.com/v1/{exec_name}:cancel'
                c_req = urllib.request.Request(cancel_url, data=b'{}', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, method='POST')
                try:
                    urllib.request.urlopen(c_req)
                    cancelled_count += 1
                except Exception:
                    pass
        print(f'   ✅ Successfully aborted {cancelled_count} active/queued batch(es) in {label}!')
    except Exception as e:
        print(f'   ❌ Could not query {label}: {e}')
"
```

Once aborted via Method 1 or Method 2, proceed to **Step 1 (Empty the Storage Bucket)** and **Step 2 (Trigger the Sync)** in Section C above!

---

### Additional Diagnostic Helpers
We provide dedicated verification tools so you can inspect your pipeline configuration, estimate runtimes, and verify SharePoint connections before transferring files:

* **Dynamic Targeted Sync Inspection**: Check target inventory breakdown (`.aspx` pages vs documents), inspect cached GCS sizes, and view performance estimates:
  ```bash
  python3 check/check_sync_gcs_dynamic.py
  ```
* **Full Traversal Sync Inspection**: Verify SharePoint subsite configuration, check existing GCS bucket inventory, and review runtime delta behavior:
  ```bash
  python3 check/check_sync_sharepoint_to_gcs.py
  ```
* **Lightning-Fast Verification (Max 10 Cutoff)**: Verify Microsoft Entra ID authentication and site folder resolution in under 3 seconds:
  ```bash
  python3 test/few-files/check_files_subset.py
  ```

---

## IV. Datastore Incremental Indexing Scheduler (12-Hour Cron)

To ensure that newly synchronized SharePoint files and converted `.aspx` PDFs in GCS are automatically ingested and indexed into Vertex AI Agent Assist without manual intervention, deploy an automated 12-hour Datastore sync schedule.

### Step 1: Verify Datastore Configuration in `parameters.json`
Before creating the scheduler or running manual tests, open `parameters.json` and verify that your Discovery Engine Datastore credentials and location are configured:
*   `CONFIG_Datastore_Id`: The ID of your Vertex AI Search / Agent Assist Datastore (e.g. `yourorg-sharepoint-gcs-datastore_1782668342491_gcs_store`).
*   `CONFIG_Datastore_Location`: The location of your Datastore (e.g. `global` or `us`, `eu`, `asia-southeast1`).
*   `CONFIG_GCS_Bucket`: Your sync bucket where `config/metadata.jsonl` is written.
*   `CONFIG_Scheduler_Cron_Schedule`: The recurrence interval (default: `0 */12 * * *` for every 12 hours; or use `0 3,9,15,21 * * *` for 4x daily runs).

### Step 2: Ensure Service Account IAM Role (`roles/discoveryengine.editor`)
Before running any Datastore sync commands or cron schedulers, verify whether your sync Service Account (`CONFIG_Service_Account`) already has the **Discovery Engine Editor** (`roles/discoveryengine.editor`) role:
```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")

# 1. Check existing IAM roles assigned to your Service Account
gcloud projects get-iam-policy ${PROJECT_ID} \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:${SERVICE_ACCOUNT}"
```
If `roles/discoveryengine.editor` (or `roles/discoveryengine.admin`) is missing from the list above, grant it now:
```bash
# 2. Grant Discovery Engine Editor role to your Service Account
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/discoveryengine.editor"
```
*(If your security governance team prefers zero new IAM roles, you can rely on Google Cloud's built-in automated background pull instead!)*

### Step 3: Test Datastore Indexing Manually (Terminal)
We provide a standalone helper script (`sync/sync_datastore.py`) that triggers an immediate `importDocuments` call in `INCREMENTAL` reconciliation mode pointing to `gs://YOUR_BUCKET/config/metadata.jsonl`:
```bash
python3 sync/sync_datastore.py
```
*(This confirms your Service Account IAM role is active and that your Datastore accepts the metadata manifest!)*

### Step 4: Deploy Automated 12-Hour Cron Scheduler
Deploy the automated Cloud Scheduler job (`yourorg-sharepoint-datastore-sync-12h`) to run every 12 hours in the background:
```bash
./deploy/deploy_scheduler_datastore_sync.sh
```
*(You can also trigger this job on-demand in the Google Cloud Console under **Cloud Scheduler** by clicking **Force Run**.)*

---

## V. Troubleshooting & Observability

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
When executing `python3 sync/sync_gcs_dynamic.py`, the terminal displays live item-by-item progress, delta cache hits, and prepared upload paths:
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
  python3 check/check_application_integration_execution.py "${PROJECT_ID}" "${LOCATION}" "${PARENT_INTEGRATION_NAME}" "<EXECUTION_ID>"
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


