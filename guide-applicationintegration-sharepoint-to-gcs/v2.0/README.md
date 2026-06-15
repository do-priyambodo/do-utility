# Serverless SharePoint-to-GCS Synchronization Pipeline (V2.0)

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
*   `CONFIG_Service_Account`: Service account under which the integrations run.
*   `CONFIG_Child_Integration_Name`: `yourorg-sharepoint-gcs-child`
*   `CONFIG_Parent_Integration_Name`: `yourorg-sharepoint-gcs-parent`
*   `CONFIG_Sharepoint_Sites`: Subsite url path (e.g. `sites/yourorg-sharepoint-to-gcs`).
*   `CONFIG_GCS_Bucket`: GCS target bucket.

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

### Step 0.5: Provision Service Account and IAM Roles
Before deploying the Cloud Function or workflows, run the pre-configured role-binding script to automatically create your custom Service Account and configure both the Service Account (runtime) and your Developer User (deployment) IAM permissions:
```bash
chmod +x prereq/sa-roles.sh
./prereq/sa-roles.sh
```
This script will read `parameters.json` and execute all necessary `gcloud` commands to bind the roles.

### Step 1: Export Configuration Variables
Before executing the deployment commands, load and export the configuration parameters as environment variables in your terminal shell session. This ensures all CLI commands execute with your target configurations without hardcoding:

```bash
# 1. Export configuration variables from parameters.json
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
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
Since Gen2 Cloud Functions run on top of Cloud Run, grant the Scheduler's Service Account invoker rights on the Cloud Run revision:
```bash
gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
  --region="${LOCATION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
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

### 1. Execute Sync Pipeline Manually
Run the manual orchestrator runner to traverse SharePoint and trigger the integration immediately:
```bash
python3 sync_sharepoint_to_gcs.py
```
This script will:
*   Invoke the traversal Cloud Function to compile the file list.
*   Directly submit the file list to the Parent Integration (`yourorg-sharepoint-gcs-parent`) and output the Execution ID.

### 2. Automated Scheduling (Cloud Scheduler)
Configure a recurring Cloud Scheduler job to run the pipeline automatically:
```bash
# 1. Resolve deployed Cloud Function URL dynamically
export FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(serviceConfig.uri)")

# 2. Deploy Cloud Scheduler trigger job
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --schedule="0 * * * *" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="{\"site_name\": \"${SITE_NAME}\", \"trigger_integration\": true, \"integration_name\": \"${PARENT_INTEGRATION_NAME}\", \"location\": \"${LOCATION}\"}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"
```
