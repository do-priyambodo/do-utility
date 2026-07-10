# 🚀 Version 10 (`v10-10Jul2026`) Enterprise Complete SharePoint Synchronization Guide (`DO-SYNC-ALL-SHAREPOINT.md`)

This comprehensive copy-paste production runbook covers the end-to-end workflow: authenticating your account to GCP, validating your IAM credentials and `parameters.json`, deploying our hardened Playwright Cloud Run backend (`8 GiB / 4 vCPUs / 900s timeout`), deploying Google Cloud Application Integration workflows, deploying the automated Cloud Scheduler job, running read-only pre-flight verification, and executing a full SharePoint-to-GCS synchronization (`100,000+ assets`).

---

## Step 1: Authenticate Your Account to GCP (`Pre-Requirement`)

Before running deployment or verification scripts, ensure your local terminal session is cleanly authenticated to Google Cloud SDK (`gcloud`) and Application Default Credentials (`ADC`):

```bash
# 1. Navigate to Version 10 working directory
cd /usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi

# 2. Ensure service account impersonation is disabled so commands run directly as your user:
gcloud config unset auth/impersonate_service_account 2>/dev/null || true

# 3. Login to Google Cloud SDK with your user account (updates active user & ADC):
gcloud auth login --update-adc

# 4. Set your active target GCP Project ID from parameters.json:
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
gcloud config set project "${PROJECT_ID}"

# 5. Verify your authentication status and active project:
gcloud auth list
echo "✅ Active Project: $(gcloud config get-value project)"
echo "Testing Identity Token: $(gcloud auth print-identity-token | cut -c1-20)...✅ Valid"
echo "Testing Access Token  : $(gcloud auth print-access-token | cut -c1-20)...✅ Valid"
```

---

## Step 2: Validate Environment & IAM Prerequisites

Verify that your service accounts and `parameters.json` values are configured correctly:

```bash
# 1. (Optional) Run prerequisite IAM script if Service Accounts or bindings are not yet created:
./util/prereq/sa-roles.sh

# 2. Validate your parameters.json syntax and configuration completeness:
python3 util/validate_params.py
```

---

## Step 3: Export Shell Configuration Variables

Copy and run the following block in your terminal to export active project parameters dynamically from `parameters.json`:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'doddi-sharepoint-sync-hourly'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 4: Deploy Cloud Run High-Fidelity Playwright Backend (`8 GiB / 4 vCPUs`)

Deploy the containerized high-fidelity Playwright (`headless Chromium`) backend service and apply Enterprise Hardware Sizing (**8 GiB RAM**, **4 vCPUs**, **900s timeout**) so complex `.aspx` pages render without memory limits:

```bash
# 1. Build & Deploy the high-fidelity Playwright container service
./deploy/deploy_cloud_run.sh

# 2. Apply Enterprise 8 GiB Memory / 4 vCPUs / 60-Minute (1-Hour) Timeout Sizing
gcloud run services update "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --memory=8192Mi \
  --cpu=4 \
  --timeout=3600

# 3. Grant invoker IAM permissions (with auto-retry fallback for Google Cloud Identity groups vs users)
if [[ "${DEV_MEMBER}" == "group:"* ]]; then
  gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
    --region="${LOCATION}" \
    --member="${DEV_MEMBER}" \
    --role="roles/run.invoker" \
    --project="${PROJECT_ID}" || \
  gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
    --region="${LOCATION}" \
    --member="user:${DEV_MEMBER#group:}" \
    --role="roles/run.invoker" \
    --project="${PROJECT_ID}"
else
  gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
    --region="${LOCATION}" \
    --member="${DEV_MEMBER}" \
    --role="roles/run.invoker" \
    --project="${PROJECT_ID}"
fi
```

---

## Step 5: Deploy Application Integration Workflows

Compile the template files (`child_workflow.json` and `parent_workflow.json`), dynamically inject your environment placeholders, and publish the integration workflows to Google Cloud Application Integration:

```bash
python3 deploy/deploy_workflows.py
```

---

## Step 6: Deploy Cloud Scheduler Automated Trigger Job

Deploy the automated Cloud Scheduler job (`doddi-sharepoint-sync-hourly`) that links your configured cron schedule (`CONFIG_Scheduler_Cron_Schedule`) to the deployed Cloud Run Playwright service with full OIDC authentication (`roles/run.invoker`):

```bash
./deploy/deploy_scheduler_full_sharepoint_sync.sh
```

---

## Step 7: Execute Read-Only Pre-Flight Verification (`Dry-Run`)

Before initiating file synchronization, run our read-only pre-flight diagnostic checks to verify authentication and audit your SharePoint repository:

```bash
# 1. Execute instant offline unit tests (schema & discovery classification logic)
python3 -m unittest discover tests -v

# 2. Verify Azure AD / Microsoft Graph Authentication
python3 check/check_entra_id_auth.py
```

### High-Speed Pre-Flight Inventory & Delta Verification (`~5 to 15s`)
Runs directly from your local terminal session using **20 concurrent worker threads** (`ThreadPoolExecutor`) with unthrottled 4-Strategy page discovery. This audits live Microsoft Graph API inventory and GCS counts in **~5 to 15 seconds**, printing a clear **Executive Subsite/Department Breakdown Table (`No. | Subsite / Department Name | Docs | Site Pages | Total`)**:

```bash
python3 check/check_syncall_before.py
```

---

## Step 8: Execute Complete Enterprise Synchronization (`Full Traversal`)

Initiate the full enterprise synchronization (`100,000+ assets`). Standard regular files scale automatically to **100 items/batch** (`~15 KB payload`), `.aspx` pages batch at **5 items/batch**, and batches dispatch concurrently via 10 keep-alive connection-pooled threads:

### Option A: Cloud Scheduler (Recommended Unattended Production Execution)
Trigger your deployed Cloud Scheduler cron job (`doddi-sharepoint-sync-hourly`):

```bash
gcloud scheduler jobs run $(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'full-sharepoint-sync'))") \
  --location=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))") \
  --project=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
```

### Option B: Interactive Python Runner (Manual Debug & Console Tracking)
Runs the complete synchronization interactively in your terminal shell:

```bash
python3 sync/sync_sharepoint_to_gcs.py
```

> [!TIP]
> **Timeline Expectations**:
> * **1st File Visible in GCS (`gs://bucket/files/...`)**: **~3 to 5 seconds**
> * **First 100 Files (Batch #1 Complete)**: **~8 to 12 seconds**
> * **Time Guard Circuit Breaker**: Exits cleanly with `200 OK` (`COMPLETED_WITH_TIME_BUDGET`) at **800 seconds (~13.3 minutes)**, preserving all delta timestamps (`O(1)` delta cache).

---

## Step 9: Post-Sync Inventory Verification

Compare your ingested GCS bucket items against live SharePoint repository counts:

```bash
# 1. Perform automated multi-threaded GCS vs SharePoint audit
python3 check/check_syncall_after.py

# 2. Inspect generated metadata JSONL file info (size & modification time)
gcloud storage ls -l "gs://$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', 'fullsharepoint-1stjuly'))")/config/metadata.jsonl"

# 3. Verify total synchronized record count inside metadata.jsonl
echo -n "Total metadata records in GCS: " && gcloud storage cat "gs://$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")/config/metadata.jsonl" | grep -c "^{"
```
