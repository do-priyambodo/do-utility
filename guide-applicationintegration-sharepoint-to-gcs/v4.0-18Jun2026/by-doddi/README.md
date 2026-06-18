# Serverless SharePoint-to-GCS Synchronization Pipeline (V3.0)

A production-ready serverless pipeline utilizing a Traversal Cloud Function (Python) and Google Cloud Application Integration to recursively synchronize SharePoint documents and pre-render modern SharePoint site pages to Google Cloud Storage (GCS).

---

## Architecture Topology

The sync pipeline follows a serverless hybrid orchestrator design:

1.  **Traversal Cloud Function (`yourorg-sharepoint-list-files`)**:
    *   Recursively queries Microsoft Graph API to traverse nested folders and document libraries.
    *   Resolves site pages and pre-renders modern SharePoint canvas layouts into static HTML files.
    *   Compiles all traversed objects into a JSON file manifest.
2.  **Application Integration Parent Orchestrator (`yourorg-sharepoint-gcs-parent`)**:
    *   Receives the list of files and loops over them.
    *   Forwards loop items to the worker integration.
3.  **Application Integration Child Worker (`yourorg-sharepoint-gcs-child`)**:
    *   Downloads document streams from SharePoint connection (using SharePoint Connector V2).
    *   Streams raw uncorrupted document bytes directly to the GCS bucket connection (using GCS Connector V1).
    *   Saves site pages as HTML objects into the `pages/` path.

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
chmod +x deploy_cf.sh
./deploy_cf.sh
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

### Step 3.5: Verify Cloud Function Traversal (Diagnostic Test)
Before deploying the integrations, you can run a diagnostic test to verify that the Cloud Function successfully connects to Azure, authenticates, and traverses the SharePoint Library folders:
```bash
python3 test_cf.py
```
This script will print the total count and a sample of files/pages found in the target library without executing the Application Integration workflows.

### Step 4: Parameterize and Deploy Integration Workflows
Compile the template files (`child_workflow.json` and `parent_workflow.json`), substitute placeholders dynamically, and deploy them to GCP:
```bash
python3 deploy_workflows.py
```

---

## III. Execution & Scheduling

You can choose between running a full site crawl or synchronizing a targeted selection of files based on your operational needs:

| Goal | Command to Run | Scans SharePoint Folders? | Source List |
| :--- | :--- | :---: | :--- |
| **Lightning Fast Verification** | `python3 test-few-files-only/check_files_subset.py` | ⚡ No (Max 10 cutoff) | Live SharePoint Sample |
| **Targeted On-Demand Sync** | `python3 sync_specific_urls.py` | 🎯 No (Bypasses crawl) | `target_files.json` |
| **Full Traversal / Hourly Cron** | `python3 sync_sharepoint_to_gcs.py` | ✅ Yes (Crawls everything) | Entire SharePoint Site |

---

### 1. Execute Lightning-Fast Connectivity Verification (Max 10 Cutoff) [Recommended First Step]
To verify Microsoft Entra ID authentication, SharePoint site resolution, and GCS cache connectivity in under 3 seconds without scanning thousands of files:
```bash
cd test-few-files-only
python3 check_files_subset.py
```
This sends `"max_items": 10` to the Cloud Function, sampling 10 items and saving the report to `files-subset-result.txt`.

### 2. Execute Targeted On-Demand Sync (Selected High-Priority Pages)
To synchronize *only* specific URLs (e.g. newly published marketing pages or priority `.aspx` layouts) without crawling the rest of SharePoint:
1. Add your target URLs inside [target_files.json](target_files.json).
2. Execute the targeted orchestrator:
```bash
python3 sync_specific_urls.py
```
This bypasses Graph folder crawling entirely and schedules Application Integration batches exclusively for your curated list.

### 3. Execute Full Traversal Sync Pipeline Manually
To scan and synchronize the entire target SharePoint site collection and document library:
```bash
python3 sync_sharepoint_to_gcs.py
```

### 4. Automated Scheduling (Cloud Scheduler)
Configure a recurring Cloud Scheduler job to run the pipeline automatically.

#### Option A: Automated Runner (Recommended)
Simply run the included deployment script (configured with 30-minute deadlines and 0 retries to prevent duplicate storms):
```bash
./deploy_scheduler.sh
```

#### Option B: Manual CLI Deployment
If you prefer running manual `gcloud` commands in your terminal, export the variables from `parameters.json` first:
```bash
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'yourorg-sharepoint-sync-hourly'))")
export SITE_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Sharepoint_Sites', '').replace('sites/', ''))")
export PARENT_INTEGRATION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Parent_Integration_Name', 'yourorg-sharepoint-gcs-parent'))")

# 1. Resolve deployed Cloud Function URL dynamically
export FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(serviceConfig.uri)")

# 2. Deploy Cloud Scheduler trigger job
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --schedule="0 */6 * * *" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="{\"site_name\": \"${SITE_NAME}\", \"trigger_integration\": true, \"integration_name\": \"${PARENT_INTEGRATION_NAME}\", \"location\": \"${LOCATION}\"}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"
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

### 4. Check Sync Progress & Workflow Execution Detail
To check the real-time progress, loop iterations, and task completion status of any sync run, pass its **Execution ID** (printed by `sync_sharepoint_to_gcs.py`) to the status diagnostic tool:

```bash
# Replace 39017360-5f5c-4aa3-b0ba-2802ba2086cd with your actual execution UUID string
python3 check_execution.py "${PROJECT_ID}" "${LOCATION}" "${PARENT_INTEGRATION_NAME}" "39017360-5f5c-4aa3-b0ba-2802ba2086cd"
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
