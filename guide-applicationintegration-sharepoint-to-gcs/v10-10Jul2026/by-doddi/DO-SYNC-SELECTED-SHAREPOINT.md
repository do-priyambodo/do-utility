# 🎯 Version 10 (`v10-10Jul2026`) Enterprise Targeted Selected-URL SharePoint Synchronization Guide (`DO-SYNC-SELECTED-SHAREPOINT.md`)

This detailed copy-paste runbook walks you through authenticating your account to GCP, validating your environment, deploying the Playwright backend, deploying workflows and Cloud Scheduler, and synchronizing **specific selected SharePoint files or modern `.aspx` site pages** defined in your remote whitelist (`gs://bucket/config/target_urls.txt`).

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
export SCHEDULER_TARGETED_JOB="doddi-sharepoint-sync-targeted"
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Location: ${LOCATION}"
```

---

## Step 4: Deploy Cloud Run High-Fidelity Playwright Backend (`8 GiB / 4 vCPUs`)

Deploy the containerized high-fidelity Playwright (`headless Chromium`) backend service and apply Enterprise Hardware Sizing (**8 GiB RAM**, **4 vCPUs**, **900s timeout**):

```bash
# 1. Build & Deploy the high-fidelity Playwright container service
./deploy/deploy_cloud_run.sh

# 2. Apply Enterprise 8 GiB Memory / 4 vCPUs / 15-Minute Timeout / Startup CPU Boost Sizing
gcloud run services update "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --memory=8192Mi \
  --cpu=4 \
  --timeout=900 \
  --cpu-boost

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

Publish the orchestrator pipelines (`child_workflow.json` and `parent_workflow.json`) to Google Cloud Application Integration:

```bash
python3 deploy/deploy_workflows.py
```

---

## Step 6: Deploy Cloud Scheduler Targeted Trigger Job

Deploy the automated Cloud Scheduler targeted job (`doddi-sharepoint-sync-targeted`) that links to the deployed Cloud Run service configured for targeted URL synchronization (`trigger_integration=true`):

```bash
./deploy/deploy_scheduler_targeted_gcs_sync.sh
```

---

## Step 7: Upload Whitelist (`target_urls.txt`) & Execute Dry-Run Verification

Upload your list of target SharePoint URLs (`target_urls.txt`) to GCS and run a read-only dry-run verification:

```bash
# 1. Upload or update target_urls.txt to your GCS configuration bucket
gsutil cp target_urls.txt "gs://${GCS_BUCKET}/config/target_urls.txt"

# 2. Simulate Targeted Synchronization (Dry-Run without downloading files)
python3 check/check_sync_gcs_dynamic.py --dry-run
```

---

## Step 8: Execute Targeted Selected Synchronization

Initiate the synchronization for your selected URLs:

### Option A: Cloud Scheduler Targeted Job (Recommended Unattended Production Execution)
```bash
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))")
PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")

gcloud scheduler jobs run doddi-sharepoint-sync-targeted \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"
```

### Option B: Interactive Python Dynamic Orchestrator (Manual Debug & Console Tracking)
```bash
python3 sync/sync_gcs_dynamic.py --force
```

---

## Step 9: Post-Sync Verification

Verify that your targeted files and rendered high-fidelity Playwright PDFs have landed in GCS:

```bash
gsutil ls -lh "gs://${GCS_BUCKET}/files/"
gsutil ls -lh "gs://${GCS_BUCKET}/pages/"
```
