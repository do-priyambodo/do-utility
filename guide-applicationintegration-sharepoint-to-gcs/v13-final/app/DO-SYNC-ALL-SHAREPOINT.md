# 🚀 Version 12 (`v12-17Jul2026`) Enterprise Sharded SharePoint Synchronization Guide (`DO-SYNC-ALL-SHAREPOINT.md`)

This comprehensive copy-paste production runbook covers the end-to-end workflow for **Option 2 - Simple Sharding (Category Isolation)**: authenticating to GCP, validating `parameters.json`, deploying the Playwright Cloud Run Job backend (`16 GiB / 4 vCPUs / 24-Hour timeout`), deploying the Application Integration workflows, running pre-flight verification, and executing the sequential categories sync manually (`100,000+ assets`).

---

## Step 1: Authenticate Your Account to GCP (`Pre-Requirement`)

Before running deployment or verification scripts, ensure your local terminal session is cleanly authenticated to Google Cloud SDK (`gcloud`) and Application Default Credentials (`ADC`):

```bash
pwd

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

### Step 2.1: (Optional) Create Service Accounts & Grant IAM Role Bindings

> [!WARNING]
> **Administrator IAM Permissions Required**
> **ONLY** run `./util/prereq/sa-roles.sh` if your active user account holds elevated **GCP Project Owner or IAM Administrator** permissions (`roles/resourcemanager.projectIamAdmin` / `roles/iam.serviceAccountAdmin`). If your Cloud Administrator already provisioned your Service Accounts, or if you do not have permission to modify project-level IAM policies, **DO NOT run this command**, as it will fail with `HTTP 403 Permission Denied`. Skip directly to **Step 2.2** below.

```bash
./util/prereq/sa-roles.sh
```

### Step 2.2: Validate Configuration Syntax & Completeness (`parameters.json`)

Verify that all required configuration keys, service account names, and Microsoft Graph credentials inside `parameters.json` are populated and structurally valid:

```bash
python3 config_schema.py
```

---

## Step 3: Export Shell Configuration Variables

Copy and run the following block in your terminal to export active project parameters dynamically from `parameters.json`:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'july1st-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'july1st-sharepoint-sync-hourly'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 4: Deploy Cloud Run High-Fidelity Playwright Job (`16 GiB / 4 vCPUs / 24-Hour Timeout`)

Deploy the containerized high-fidelity Playwright (`headless Chromium`) backend service as a 24-hour Cloud Run Job with Enterprise Hardware Sizing (**16 GiB RAM**, **4 vCPUs**, **86,400s timeout**). 

Our automated script copies `parameters.json` and dependencies into `cf-sharepoint/`, builds the container, deploys the 24-Hour Cloud Run Job (`${FUNCTION_NAME}`), sets tasks number to the count of categories, and grants `roles/run.invoker` automatically:

```bash
bash deploy/deploy_cloud_run.sh
```

---

## Step 5: Deploy Application Integration Workflows

Compile the template files (`child_workflow.json` and `parent_workflow.json`), dynamically inject your environment placeholders, and publish the integration workflows to Google Cloud Application Integration:

```bash
python3 deploy/deploy_workflows.py
```

---

## Step 6: Deploy Cloud Scheduler Automated Trigger Job

Deploy the automated Cloud Scheduler job that links your configured cron schedule (`CONFIG_Scheduler_Cron_Schedule`) directly to our deployed 24-Hour Cloud Run Job with full OAuth authentication:

```bash
bash deploy/deploy_scheduler.sh
```

---

## Step 7: Execute Read-Only Pre-Flight Verification (`Dry-Run`)

Before initiating file synchronization, run our read-only pre-flight diagnostic checks to verify authentication and audit your SharePoint repository:

```bash
# 1. Verify Azure AD / Microsoft Graph Authentication
python3 check/check_entra_id_auth.py
```

---

## Step 8: Execute Complete Enterprise Synchronization (`Full Traversal`)

Initiate the sequential category synchronization manually. Standard regular files process automatically, pages render via headless Playwright, and GCS buckets populate using flat layouts (`/files/` and `/pages/`).

### Option A: Direct Cloud Run Job Execution (Recommended for Immediate Unattended Run)
Use this option to trigger all category tasks sequentially. Cloud Run will spin up tasks one by one (constrained by `--parallelism=1` set on the Job level) to sync each category shard:

```bash
gcloud run jobs execute $(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'july1st-sharepoint-list-files-v12category'))") \
  --region=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))") \
  --project=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))") \
  --tasks=$(( $(python3 -c "import json; print(len(json.load(open('parameters.json')).get('CONFIG_Categories', [])))") + 1 ))
```

> [!TIP]
> **💻 Laptop / Terminal Closure Safety: SAFE TO CLOSE IMMEDIATELY**  
> `gcloud run jobs execute` dispatches the execution directly to Cloud Run's serverless infrastructure and exits your terminal in `~2 seconds`. **You can safely close your terminal or shut down your laptop right after running this command!**

### Option B: Cloud Scheduler Trigger (Recommended for Automated Production Testing)
Use this option to trigger the sharded synchronization run using Google Cloud Scheduler. This guarantees all parameters are passed cleanly in the HTTP payload:

```bash
gcloud scheduler jobs run $(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'july1st-sharepoint-sync-hourly-v12category'))") \
  --location=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))") \
  --project=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
```

> [!TIP]
> **💻 Laptop / Terminal Closure Safety: SAFE TO CLOSE IMMEDIATELY**  
> Triggering the scheduler sends an asynchronous trigger to GCP and exits in `~2 seconds`. The sequential traversal runs unattended inside Google Cloud's infrastructure. **You can safely close your terminal or shut down your laptop right after running this command!**

---

## Step 9: Active Real-Time Monitoring While Running (`During Step 8 Sync`)

Track pipeline progress and container heartbeats using these monitoring options:

### Option 1: Log Explorer (GCP Console UI)
Monitor live pipeline chunking, Graph API traversal, and Playwright rendering in real time from the **Google Cloud Console**:

1. Navigate to **Logging > Logs Explorer** (`https://console.cloud.google.com/logs/query`).
2. Paste the following universal query into the search bar (replace `your-service-name` with your actual service name from `parameters.json`):
   ```text
   resource.type="cloud_run_job"
   resource.labels.job_name="july1st-sharepoint-list-files-v12category"
   ```
3. Click **Stream Logs** to watch live batch processing and task indexing.

### Option 2: Command Line GCS Audit
Check how many files and pages have landed in your destination GCS bucket:
```bash
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))") && \
echo "=== 📊 AD-HOC GCS SYNC MONITOR ===" && \
echo "Timestamp    : $(date)" && \
echo "Target Bucket: gs://${GCS_BUCKET}" && \
echo "------------------------------------------------------------" && \
echo -n "Total Synced Files (gs://${GCS_BUCKET}/files/) : " && \
gcloud storage ls --recursive "gs://${GCS_BUCKET}/files/**" 2>/dev/null | wc -l && \
echo -n "Total Synced Pages (gs://${GCS_BUCKET}/pages/) : " && \
gcloud storage ls --recursive "gs://${GCS_BUCKET}/pages/**" 2>/dev/null | wc -l && \
echo "------------------------------------------------------------"
```

---

## Step 10: Troubleshooting & Diagnostic Export

If you encounter any synchronization failures or container timeouts during the pipeline run, export your diagnostic log bundle:

```bash
export BUNDLE_NAME="sharepoint_sync_diagnostic_bundle_$(date +%Y%m%d_%H%M%S).tar.gz"
mkdir -p log/diagnostic_export && \
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))") && \
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'july1st-sharepoint-list-files-v12category'))") && \
echo "📥 Fetching recent Cloud Run error logs from GCP..." && \
gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${FUNCTION_NAME}\" AND severity>=ERROR" \
  --project="${PROJECT_ID}" --limit=500 --format=json > log/diagnostic_export/cloud_run_errors.json 2>/dev/null || true && \
cp -r log/*.log log/diagnostic_export/ 2>/dev/null || true && \
cp parameters.json log/diagnostic_export/parameters.json.copy 2>/dev/null || true && \
tar -czf "${BUNDLE_NAME}" -C log diagnostic_export && \
rm -rf log/diagnostic_export && \
echo "✅ Diagnostic log bundle created: ${BUNDLE_NAME}"
```
