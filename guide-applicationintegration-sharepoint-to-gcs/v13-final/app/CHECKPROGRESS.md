# 🔍 SharePoint-to-GCS Synchronization Progress Check Guide

Use the following step-by-step commands to authenticate, validate parameters, inspect live container execution logs, verify GCS storage footprint, and check for any synchronization errors.

All commands below dynamically read your target resources directly from your local `parameters.json` file.

---

## Step 1: Navigate to Working Directory & Authenticate

Open your Cloud Shell or terminal, navigate to your V10 working directory, and ensure your Google Cloud user credentials are active:

```bash
# 1. Navigate to your V10 working directory (where parameters.json is located)
# cd /path/to/your/sharepoint-sync/v10-10Jul2026/by-doddi

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

## Step 2: Validate Local Parameters Configuration

Run the automated parameter validation tool to verify that all required fields and Cloud resources in `parameters.json` are properly configured and accessible:

```bash
python3 util/validate_params.py
```

---

## Step 3: Export Environment Variables from `parameters.json`

Export your active resource names into shell environment variables for quick operational tracking:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'your-sharepoint-sync-hourly'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 4: Stream Live Cloud Run Job Execution Logs

Stream the last 25 live container execution heartbeats (`[Step 1/7]` to `Step 7/7`, item discovery counts, and batch dispatch notifications) directly to your terminal:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")"'" AND textPayload:*' \
  --project="$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, textPayload)"
```

---

## Step 5: Check Live GCS Ingestion Snapshot (Ad-Hoc Monitor)

Run this one-shot instant check to see exactly how many files and `.aspx` pages have successfully landed inside your destination GCS bucket along with the total storage footprint:

```bash
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))") && \
echo "=== 📊 AD-HOC SHAREPOINT -> GCS SYNC MONITOR ===" && \
echo "Timestamp    : $(date)" && \
echo "Target Bucket: gs://${GCS_BUCKET}" && \
echo "------------------------------------------------------------" && \
echo -n "Total Synced Files/Pages Landed in GCS : " && \
gcloud storage ls --recursive "gs://${GCS_BUCKET}/**" 2>/dev/null | wc -l && \
echo -n "Total Bucket Storage Footprint         : " && \
gcloud storage du -s "gs://${GCS_BUCKET}/" --readable-sizes 2>/dev/null | cut -f1 && \
echo "------------------------------------------------------------"
```

---

## Step 6: Filter Strictly for Synchronization Errors & Exceptions

Scan your Cloud Run Job container logs strictly for errors, crashes, exceptions, or rate-limiting warnings without clutter from routine progress messages:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")"'" AND severity>=ERROR' \
  --project="$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, severity, textPayload, jsonPayload.message)"
```
