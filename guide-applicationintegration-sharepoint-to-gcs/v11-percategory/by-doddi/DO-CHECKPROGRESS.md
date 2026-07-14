# 🔍 SharePoint-to-GCS Synchronization Progress Check Guide

Use the following step-by-step commands to authenticate, validate parameters, inspect live container execution logs, verify GCS storage footprint, and check for any synchronization errors.

All commands below dynamically read your target resources directly from your local `config-parameters.json` file.

---

## Step 1: Navigate to Working Directory & Authenticate

Open your Cloud Shell or terminal, navigate to your V10 working directory, and ensure your Google Cloud user credentials are active:

```bash
# 1. Navigate to your V10 working directory (where config-parameters.json is located)
# cd /path/to/your/sharepoint-sync/v10-10Jul2026/by-doddi

# 2. Ensure service account impersonation is disabled so commands run directly as your user:
gcloud config unset auth/impersonate_service_account 2>/dev/null || true

# 3. Login to Google Cloud SDK with your user account (updates active user & ADC):
gcloud auth login --update-adc

# 4. Set your active target GCP Project ID from config-parameters.json:
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")
gcloud config set project "${PROJECT_ID}"

# 5. Verify your authentication status and active project:
gcloud auth list
echo "✅ Active Project: $(gcloud config get-value project)"
echo "Testing Identity Token: $(gcloud auth print-identity-token | cut -c1-20)...✅ Valid"
echo "Testing Access Token  : $(gcloud auth print-access-token | cut -c1-20)...✅ Valid"
```

---

## Step 2: Validate Local Parameters Configuration

Run the automated parameter validation tool to verify that all required fields and Cloud resources in `config-parameters.json` are properly configured and accessible:

```bash
python3 util/validate_params.py
```

---

## Step 3: Export Environment Variables from `config-parameters.json`

Export your active resource names into shell environment variables for quick operational tracking:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Scheduler_Job_Name', 'your-sharepoint-sync-hourly'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 4: Stream Live Cloud Run Job Execution Logs

Stream the last 25 live container execution heartbeats (`[Step 1/7]` to `Step 7/7`, item discovery counts, and batch dispatch notifications) directly to your terminal:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")"'" AND textPayload:*' \
  --project="$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, textPayload)"
```

---

## Step 5: Check Live GCS Ingestion Snapshot (Ad-Hoc Monitor)

Run this one-shot instant check to see exactly how many files and `.aspx` pages have successfully landed inside your destination GCS bucket along with the total storage footprint:

```bash
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_GCS_Bucket', ''))") && \
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
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'your-sharepoint-list-files'))")"'" AND severity>=ERROR' \
  --project="$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, severity, textPayload, jsonPayload.message)"
```

---

## Step 7: Interactive Timezone-Aware Log Inspector (`check_all_logging.py`)

To streamline troubleshooting across all serverless components without running individual `gcloud logging read` commands manually, use our automated diagnostic inspector script: `check/check_all_logging.py`.

This script automatically pulls your Project ID, Function Name, Scheduler Job, and GCS Bucket from `config-parameters.json`, formats all timestamps in your selected time zone, and allows you to define custom lookback windows or start timestamps:

### Method A: Interactive Mode (Recommended)
```bash
python3 check/check_all_logging.py --interactive
```

### Method B: One-Line Non-Interactive Execution
```bash
# Example 1: Look back over the last 30 minutes formatted in Singapore/Kuala Lumpur time (+08)
python3 check/check_all_logging.py --tz "Asia/Singapore" --since "30m" --limit 10

# Example 2: Query logs starting from a specific timestamp formatted in local system timezone
python3 check/check_all_logging.py --tz "LOCAL" --start-time "2026-07-07T05:00:00Z" --limit 15
```

---

## Step 8: Deep-Dive: SharePoint Throttling, DDoS Protection & Root Cause Checklist

When synchronizing thousands of SharePoint files or harvesting modern site pages (`.aspx`), Microsoft 365 monitors API request concurrency and volume. If rate limits are exceeded, Microsoft returns HTTP `429 Too Many Requests`, `503 Service Unavailable`, or `504 Gateway Timeout`.

### Diagnostic Command: Check for SharePoint Throttling & DDoS Blocks
Run this command to search your container logs specifically for throttling rejections, rate limits, and `Retry-After` headers:

```bash
gcloud logging read "(resource.type=\"cloud_run_job\" OR resource.type=\"cloud_function\" OR resource.type=\"cloud_run_revision\") AND (resource.labels.job_name=\"${FUNCTION_NAME}\" OR resource.labels.service_name=\"${FUNCTION_NAME}\") AND (textPayload=~\"429\" OR textPayload=~\"503\" OR textPayload=~\"504\" OR textPayload=~\"Too Many Requests\" OR textPayload=~\"Retry-After\" OR textPayload=~\"Server Busy\" OR textPayload=~\"ECONNRESET\")" \
    --project="${PROJECT_ID}" \
    --limit=25 \
    --order=desc \
    --format="table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz=LOCAL):label=TIMESTAMP, severity, textPayload)"
```

### Root Cause Analysis Checklist

| Check | Potential Root Cause | Component to Inspect | How to Diagnose & Resolve |
| :---: | :--- | :--- | :--- |
| 🔲 1 | **SharePoint Throttling / Anti-DDoS Rejection** | Microsoft Graph API / SharePoint | **Diagnose**: Check logs above for HTTP `429 Too Many Requests`, `503 Server Busy`, or `504 Gateway Timeout`.<br>**Resolve**: Reduce `CONFIG_Max_Parallel_Workers` to `5` or `8` in `config-parameters.json`, and ensure exponential backoff with jitter is active. |
| 🔲 2 | **Entra ID Conditional Access Block / Expired Secret** | Azure AD / M365 Graph API | **Diagnose**: Check logs for HTTP `401`/`403`.<br>**Resolve**: Verify in Azure Portal that `CONFIG_M365_Secret_Name` has not expired and that no Conditional Access policy requires interactive MFA for headless client-credentials flows. |
| 🔲 3 | **Playwright Chromium Out-of-Memory (OOM)** | Cloud Run Container | **Diagnose**: Check logs for `Memory limit exceeded` or container crash code `500` during `.aspx` page conversion.<br>**Resolve**: In `config-parameters.json` / deployment flags, verify Cloud Run memory allocation is set to **8GiB (`8192Mi`)**. |
| 🔲 4 | **VPC Service Controls (VPC-SC) Egress Block** | Network Security / Connectors | **Diagnose**: Check audit logs for `VpcServiceControlAuditMetadata` violation.<br>**Resolve**: Add an egress rule in perimeter settings allowing traffic to `connectors.googleapis.com` and `*.sharepoint.com`. |
| 🔲 5 | **Missing IAM Invoker or Storage Creator Roles** | IAM & Admin | **Diagnose**: Check logs for `PERMISSION_DENIED`.<br>**Resolve**: Ensure service account `CONFIG_Service_Account` has `roles/run.invoker`, `roles/storage.objectAdmin`, and `roles/secretmanager.secretAccessor`. |
| 🔲 6 | **Micro-Batch Payload Serialization Timeout** | Batch Processing | **Diagnose**: Check logs for execution timeouts or payload size errors.<br>**Resolve**: Ensure `CONFIG_Batch_Size` in `config-parameters.json` is set appropriately (`100` for files, `5` for `.aspx` pages). |

---

## Step 9: Exporting Diagnostic Support Bundles (`If Errors Occur`)

If you encounter any synchronization failures, container timeouts, or OData rate-limiting (`HTTP 429 / 500 / 504`) during the pipeline run, export your diagnostic logs and send them to your support engineer using **either of these two options**:

### Option 1: Export Logs from GCP Console (`JSON Format`)
1. Navigate to **Logging > Logs Explorer** in the Google Cloud Console (`https://console.cloud.google.com/logs/query`).
2. Run this quick command in your terminal to print your exact error query dynamically:
   ```bash
   python3 -c 'import json; fn = json.load(open("config-parameters.json")).get("CONFIG_CloudFunction_Name", "your-service-name"); print(f"\n📋 Paste this query into GCP Logs Explorer:\n\n(resource.type=\"cloud_run_job\" OR resource.type=\"cloud_run_revision\")\n(resource.labels.job_name=\"{fn}\" OR resource.labels.service_name=\"{fn}\")\nseverity>=ERROR\n")'
   ```
3. Paste the generated query into the Logs Explorer search bar and click **Run Query**.
4. Click the **Download / Export** icon (top right above the log results pane) and select **Download JSON**.
5. Save the `.json` file and attach it to your support ticket.

### Option 2: Create a Complete Diagnostic Log Bundle via Command Line (`Tar/Gz Bundle`)
Run this single automated command inside your Cloud Shell or terminal. It collects all local execution logs (`log/*.log`), fetches the last 500 Cloud Run container error logs from GCP directly in JSON format, includes a copy of both `config-parameters.json` and `config-category.json`, and compresses everything into a timestamped `.tar.gz` diagnostic bundle ready for sharing:

```bash
export BUNDLE_NAME="sharepoint_sync_diagnostic_bundle_$(date +%Y%m%d_%H%M%S).tar.gz"
mkdir -p log/diagnostic_export && \
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))") && \
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))") && \
echo "📥 Fetching recent Cloud Run error logs from GCP Logs Explorer..." && \
gcloud logging read "(resource.type=\"cloud_run_job\" OR resource.type=\"cloud_run_revision\") AND (resource.labels.job_name=\"${FUNCTION_NAME}\" OR resource.labels.service_name=\"${FUNCTION_NAME}\") AND severity>=ERROR" \
  --project="${PROJECT_ID}" --limit=500 --format=json > log/diagnostic_export/cloud_run_errors.json 2>/dev/null || true && \
cp -r log/*.log log/diagnostic_export/ 2>/dev/null || true && \
cp config-parameters.json log/diagnostic_export/config-parameters.json.copy 2>/dev/null || true && \
[ -f config-category.json ] && cp config-category.json log/diagnostic_export/config-category.json.copy 2>/dev/null || true && \
tar -czf "${BUNDLE_NAME}" -C log diagnostic_export && \
rm -rf log/diagnostic_export && \
echo "✅ Complete diagnostic log bundle successfully created: ${BUNDLE_NAME}" && \
echo "📧 Please attach ${BUNDLE_NAME} and send it to your support engineer for immediate analysis!"
```
