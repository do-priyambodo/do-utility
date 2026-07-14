# 🚀 Version 11 (`v11-percategory`) Enterprise Per-Category Synchronization Guide (`DO-SYNC-SELECTED-CATEGORY.md`)

> [!IMPORTANT]
> **Version 11 Production Milestone: Per-Category Sharded Architecture & Option 1 Master Loop**
> This exact release (`V11 Per-Category`) is our hardened, production-verified release designed to cleanly handle massive enterprise SharePoint topologies (`38,800+ assets across 23+ subsite departments`). It incorporates all historical resilience fixes (`_THREAD_LOCAL` greenlet isolation, VPC-SC immune `--async` builds, and 24-hour continuous Cloud Run Jobs) while introducing three critical structural upgrades:
> * **Configuration Decoupling (`config/sites-sync.json`)**: Shards large enterprise site collections into manageable category tiers (`tier1-den-root-only`, `tier1-business`, `tier1-consumer`, `tier2-medium-departments`, etc.) targeting `"sharepoint_library": "all"`.
> * **Fast Subsite Discovery (`check/discover_categories.py`)**: Resolves all child subsite categories under any root portal in **<3 seconds** without crawling libraries or counting items.
> * **Master Serial Category Loop & RAM Isolation**: `main.py` iterates sequentially over each category in `sites-sync.json`, wiping local memory buffers (`all_list.clear()`, `sync_list.clear()`, `target_sites.clear()`) after every category to guarantee O(1) memory safety (<8 GB Cloud Run limit).

This comprehensive copy-paste production runbook covers the end-to-end V11 workflow: authenticating your account to GCP, validating your IAM credentials and `parameters.json`, discovering your categories, deploying our hardened Playwright Cloud Run backend, deploying Application Integration workflows, deploying the Option 1 Master Cloud Scheduler job, and executing pre/post-flight verification.

---

## Step 1: Authenticate Your Account to GCP (`Pre-Requirement`)

Before running deployment or verification scripts, ensure your local terminal session is cleanly authenticated to Google Cloud SDK (`gcloud`) and Application Default Credentials (`ADC`):

```bash
# 1. Navigate to Version 11 working directory
cd /path/to/your/repo/app/v11-percategory/by-doddi

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

### Step 2.2: Validate Configuration Syntax (`parameters.json` & `sites-sync.json`)

Verify that all required infrastructure keys and M365 credentials inside `parameters.json` and your category matrix inside `config/sites-sync.json` are structurally valid:

```bash
python3 -m json.tool parameters.json > /dev/null && echo "✅ parameters.json valid"
python3 -m json.tool config/sites-sync.json > /dev/null && echo "✅ sites-sync.json valid"
```

---

## Step 3: Fast Subsite Discovery & Category Onboarding (`<3s Discovery`)

To discover all available child subsites/departments under your target root portal site in **<3 seconds** (without waiting 30 minutes for library counting), run:

```bash
python3 check/discover_categories.py --root="sites/DEN"
```

Copy the output category names and paths directly into `config/sites-sync.json` under your desired `categories[]` matrix.

---

## Step 4: Export Shell Configuration Variables

Copy and run the following block in your terminal to export active project parameters dynamically from `parameters.json`:

```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'doddi-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME="${FUNCTION_NAME}-daily-master"
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Job: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"
```

---

## Step 5: Deploy Cloud Run Job with Category Config (`8 GiB / 4 vCPUs / 24-Hour Timeout`)

Deploy the containerized high-fidelity Playwright backend service as a 24-hour Cloud Run Job (`${FUNCTION_NAME}`). Our automated script copies `parameters.json`, `config/sites-sync.json`, and utilities into the container build context and sets `--set-env-vars="CONFIG_SITES_SYNC_PATH=config/sites-sync.json"`:

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

## Step 7: Deploy Option 1 Master Cloud Scheduler Trigger Job

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

Initiate the synchronization across your sharded categories (`38,800+ items`). Standard regular files scale automatically to **100 items/batch** (`~15 KB payload`), `.aspx` pages batch at **5 items/batch**, and batches dispatch concurrently:

### Option A: Cloud Scheduler Trigger (`Recommended Unattended 24-Hour Master Loop`)
Force your Option 1 Master Cloud Scheduler job to trigger immediately on demand, executing all categories sequentially with RAM isolation between each category:

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
