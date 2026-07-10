# 🚀 Version 10 (`v10-10Jul2026`) Enterprise Complete SharePoint Synchronization Guide (`DO-SYNC-ALL-SHAREPOINT.md`)

This comprehensive copy-paste production runbook covers the end-to-end workflow: validating your IAM credentials and `parameters.json`, deploying our hardened Playwright Cloud Run backend (`8 GiB / 4 vCPUs / 900s timeout`), deploying Google Cloud Application Integration orchestrator workflows, running read-only pre-flight verification, and executing a full SharePoint-to-GCS synchronization (`100,000+ assets`).

---

## Step 1: Validate Environment & IAM Prerequisites

Before deploying services, verify that your service accounts and `parameters.json` values are configured correctly:

```bash
# 1. Navigate to Version 10 working directory
cd /usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi

# 2. (Optional) Run prerequisite IAM script if Service Accounts or bindings are not yet created:
./util/prereq/sa-roles.sh

# 3. Validate your parameters.json syntax and configuration completeness:
python3 util/validate_params.py
```

---

## Step 2: Export Shell Configuration Variables

Copy and run the following block in your terminal to export active project parameters dynamically from `parameters.json`:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Location: ${LOCATION}"
```

---

## Step 3: Deploy Cloud Run High-Fidelity Playwright Backend (`8 GiB / 4 vCPUs`)

Deploy the containerized high-fidelity Playwright (`headless Chromium`) backend service and apply Enterprise Hardware Sizing (**8 GiB RAM**, **4 vCPUs**, **900s timeout**) so complex `.aspx` pages render without memory limits:

```bash
# 1. Build & Deploy the high-fidelity Playwright container service
./deploy/deploy_cloud_run.sh

# 2. Apply Enterprise 8 GiB Memory / 4 vCPUs / 15-Minute Timeout Sizing
gcloud run services update "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --memory=8192Mi \
  --cpu=4 \
  --timeout=900

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

## Step 4: Deploy Application Integration Workflows

Compile the template files (`child_workflow.json` and `parent_workflow.json`), dynamically inject your environment placeholders, and publish the integration workflows to Google Cloud Application Integration:

```bash
python3 deploy/deploy_workflows.py
```

---

## Step 5: Execute Read-Only Pre-Flight Verification (`Dry-Run`)

Before triggering file downloads, run our read-only diagnostic checks to verify Microsoft Entra ID authentication and simulate full SharePoint discovery (`$top=999` + iterative BFS queue, completes in ~3 to 5 seconds):

```bash
# 1. Verify Azure AD / Microsoft Graph Authentication
python3 check/check_entra_id_auth.py

# 2. Simulate Full SharePoint Traversal (Dry-Run without triggering download batches)
python3 check/check_sync_sharepoint_to_gcs.py --dry-run
```

---

## Step 6: Execute Complete Enterprise Synchronization (`Full Traversal`)

Initiate the full enterprise synchronization (`100,000+ assets`). Standard regular files scale automatically to **100 items/batch** (`~15 KB payload`), `.aspx` pages batch at **5 items/batch**, and batches dispatch concurrently via 10 keep-alive connection-pooled threads:

### Option A: Run Directly via Python Orchestrator (Recommended for Console Tracking)
```bash
python3 sync/sync_sharepoint_to_gcs.py
```

### Option B: Trigger Existing Cloud Scheduler Job
```bash
gcloud scheduler jobs run doddi-sharepoint-sync-hourly \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"
```

> [!TIP]
> **Timeline Expectations**:
> * **1st File Visible in GCS (`gs://bucket/files/...`)**: **~3 to 5 seconds**
> * **First 100 Files (Batch #1 Complete)**: **~8 to 12 seconds**
> * **Time Guard Circuit Breaker**: Exits cleanly with `200 OK` (`COMPLETED_WITH_TIME_BUDGET`) at **800 seconds (~13.3 minutes)**, preserving all delta timestamps (`O(1)` delta cache).

---

## Step 7: Post-Sync Inventory Verification

Compare your ingested GCS bucket items against live SharePoint repository counts:

```bash
# 1. Perform automated multi-threaded GCS vs SharePoint audit
python3 check/check_syncall_after.py

# 2. Inspect generated metadata JSONL record
gsutil ls -lh "gs://${GCS_BUCKET}/config/metadata.jsonl"
```
