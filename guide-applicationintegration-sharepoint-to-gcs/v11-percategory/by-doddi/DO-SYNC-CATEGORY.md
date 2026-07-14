# 🚀 Version 11 (`v11-percategory`) Enterprise Per-Category Synchronization Guide (`DO-SYNC-CATEGORY.md`)

## Step 1: Authenticate Your Account to GCP (`Pre-Requirement`)

Before running deployment or verification scripts, ensure your local terminal session is cleanly authenticated to Google Cloud SDK (`gcloud`) and Application Default Credentials (`ADC`):

```bash
# 1. Navigate to Version 11 working directory
# cd /path/to/your/repo/app/v11-percategory/by-doddi

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

## Step 2: Validate Environment & IAM Prerequisites

### Step 2.1: (Optional) Create Service Accounts & Grant IAM Role Bindings

> [!WARNING]
> **Administrator IAM Permissions Required**
> **ONLY** run `./util/prereq/sa-roles.sh` if your active user account holds elevated **GCP Project Owner or IAM Administrator** permissions (`roles/resourcemanager.projectIamAdmin` / `roles/iam.serviceAccountAdmin`). If your Cloud Administrator already provisioned your Service Accounts, or if you do not have permission to modify project-level IAM policies, **DO NOT run this command**, as it will fail with `HTTP 403 Permission Denied`. Skip directly to **Step 2.2** below.

```bash
./util/prereq/sa-roles.sh
```

### Step 2.2: Validate Configuration Syntax (`config-parameters.json` & `config-category.json`)

Verify that all required infrastructure keys and M365 credentials inside `config-parameters.json` and your category matrix inside `config-category.json` are structurally valid:

```bash
python3 -m json.tool config-parameters.json > /dev/null && echo "✅ config-parameters.json valid"
python3 -m json.tool config-category.json > /dev/null && echo "✅ config-category.json valid"
```

---

## Step 3: Fast Subsite Discovery & Category Onboarding (`<3s Discovery`)

To discover all available child subsites/departments under your target root portal site in **<3 seconds** (without waiting 30 minutes for library counting), run:

```bash
python3 check/discover_categories.py --root="sites/CHANGETHISTOYOURROOTSITE"
```

Copy the output category names and paths directly into `config-category.json` under your desired `categories[]` matrix.

---

## Step 4: Export Shell Configuration Variables

Copy and run the following block in your terminal to export active project parameters dynamically from `config-parameters.json`:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME="${FUNCTION_NAME}-daily-master"
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Job: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 5: Deploy Cloud Run Job with Category Config (`8 GiB / 4 vCPUs / 24-Hour Timeout`)

Deploy the containerized high-fidelity Playwright backend service as a 24-hour Cloud Run Job (`${FUNCTION_NAME}`). Our automated script copies `config-parameters.json`, `config-category.json`, and utilities into the container build context and sets `--set-env-vars="CONFIG_SITES_SYNC_PATH=config-category.json"`:

```bash
./deploy/deploy_cloud_run.sh
```

---

## Step 6: Deploy Application Integration Workflows

Compile the template files (`child_workflow.json` and `parent_workflow.json`), dynamically inject your environment placeholders, and publish the integration workflows to Google Cloud Application Integration:

```bash
python3 deploy/deploy_workflows.py
```

---

## Step 7: Deploy Cloud Scheduler Trigger Job

Deploy the single automated Cloud Scheduler job (`${FUNCTION_NAME}-daily-master`) that triggers our Cloud Run Job daily at midnight (`0 0 * * *`) to iterate sequentially across all categories:

```bash
./deploy/deploy_category_scheduler.sh
```

---

## Step 8: Execute Read-Only Pre-Flight Verification (`Dry-Run`)

Before initiating file synchronization, run our read-only pre-flight diagnostic checks to audit your per-category SharePoint repository:

```bash
# 1. Verify Azure AD / Microsoft Graph Authentication
python3 check/check_entra_id_auth.py

# 2. Execute High-Speed Per-Category Pre-Sync Delta Audit (Mode B - Master Serial Loop)
python3 check/check_syncall_before.py

# 3. (Optional) Execute Targeted Pre-Sync Audit on one specific category (Mode A - Fast <15s Audit)
python3 check/check_syncall_before.py --category=tier1-business
```

---

## Step 9: Execute Per-Category Synchronization

Initiate the synchronization across your categories. Standard regular files scale automatically to **100 items/batch**, `.aspx` pages batch at **5 items/batch**, and batches dispatch concurrently:

### Option A: Cloud Scheduler Trigger (`Recommended Unattended 24-Hour Master Loop`)
Cloud Scheduler job to trigger immediately on demand, executing all categories sequentially with RAM isolation between each category:

```bash
gcloud scheduler jobs run "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}"
```
> [!TIP]
> **💻 Laptop / Terminal Closure Safety: SAFE TO CLOSE IMMEDIATELY**  
> This command sends an asynchronous trigger and exits in `~2 seconds`. The 24-hour traversal runs unattended inside Google Cloud's infrastructure. **You can safely close your terminal or shut down your laptop right after running this command!**

### Option B: On-Demand Single-Category Emergency Override (`Targeted Sync`)
If a specific department (e.g. `tier1-business`) needs immediate synchronization without running all other categories, set `TARGET_CATEGORY_ID` via `--update-env-vars`:

```bash
gcloud run jobs execute "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --update-env-vars="TARGET_CATEGORY_ID=tier1-business"
```
> [!IMPORTANT]
> When the single-category sync completes, remember to remove the override environment variable before the next nightly master run:
> ```bash
> gcloud run jobs update "${FUNCTION_NAME}" \
>   --region="${LOCATION}" \
>   --remove-env-vars="TARGET_CATEGORY_ID"
> ```

---

## Step 9.5: Active Real-Time Monitoring While Running (`During Step 9 Sync`)

Because a full per-category synchronization runs asynchronously over multiple hours via Cloud Scheduler and Application Integration, use either of these **2 real-time monitoring options** to track progress and verify health while the sync is running (or see our complete dedicated monitoring guide 👉 **[DO-CHECKPROGRESS.md](DO-CHECKPROGRESS.md)**):

### Option 1: Log Explorer (GCP Console UI)
Monitor live pipeline chunking, Graph API traversal, and Playwright rendering in real time from the **Google Cloud Console**:
1. Navigate to **Logging > Logs Explorer** (`https://console.cloud.google.com/logs/query`).
2. **Set Time Range Filter (IMPORTANT):** In the top-right time picker of Logs Explorer, filter the start time to the **exact timestamp when you executed the Cloud Scheduler job in Step 9**. This ensures you only see active logs from the current execution without noise from prior runs.
3. Paste the following universal query into the search bar (replace `your-service-name` with your actual service name from `config-parameters.json`, e.g., `doddi-sharepoint-list-files`):
   ```text
   (resource.type="cloud_run_job" OR resource.type="cloud_run_revision" OR resource.type="cloud_function")
   (resource.labels.job_name="your-service-name" OR resource.labels.service_name="your-service-name" OR resource.labels.function_name="your-service-name")
   ```
   *(Optional)* To generate this exact query dynamically with your `config-parameters.json` service name already inserted, run:
   ```bash
   python3 -c 'import json; fn = json.load(open("config-parameters.json")).get("CONFIG_CloudFunction_Name", "your-service-name"); print(f"\n📋 Paste this exact query into GCP Logs Explorer:\n\n(resource.type=\"cloud_run_job\" OR resource.type=\"cloud_run_revision\" OR resource.type=\"cloud_function\")\n(resource.labels.job_name=\"{fn}\" OR resource.labels.service_name=\"{fn}\" OR resource.labels.function_name=\"{fn}\")\n")'
   ```
4. Click **Stream Logs** (top right) to watch live batch processing and Playwright rendering in real time.

### Option 2: Command Line (Real-Time Storage & Log Tracking)
Run these commands in your Cloud Shell or local terminal to track live objects landing in Google Cloud Storage or stream Cloud Run logs directly:

**A. Ad-Hoc GCS Bucket Snapshot (One-Shot Instant Check):**
Check exactly how many files and `.aspx` pages have landed in your destination GCS bucket without locking up your terminal in a watch loop:
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

**B. Live Cloud Run Terminal Log Stream:**
Stream live container heartbeats directly from your terminal session without opening the browser:
```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")"'" AND textPayload:*' \
  --project="$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, textPayload)"
```

To filter strictly for **Errors & Exceptions only**, append `AND severity>=ERROR`:
```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="'"$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")"'" AND severity>=ERROR' \
  --project="$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")" \
  --limit=25 \
  --format="table(timestamp, severity, textPayload, jsonPayload.message)"
```

---

## Step 10: Post-Sync Completeness Verification & Shard Aggregation

After the sync completes, verify that 100% of your category assets landed inside their exact GCS sharded prefixes (`gs://<bucket>/<prefix>/...`):

```bash
# 1. Perform automated per-category completeness audit against GCS shards
python3 check/check_syncall_after.py

# 2. Inspect the combined Vertex AI master metadata manifest (config/metadata.jsonl)
python3 check/check_metadata_jsonl.py
```

---

## 🎯 Mode 3: Selective Target URLs Bypass (`target_urls.txt`)
If you need to bypass category traversal entirely and instantly sync only a specific list of URL files or `.aspx` pages in `<15 seconds`, see the dedicated operator runbook:
👉 **[DO-SYNC-TARGET-URLS.md](DO-SYNC-TARGET-URLS.md)**
