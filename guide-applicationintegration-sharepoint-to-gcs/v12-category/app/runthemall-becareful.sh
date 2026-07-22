#!/bin/bash
set -e

# Change to the directory of this script to ensure absolute path safety
cd "$(dirname "$0")"

echo "=================================================="
echo "🚀 STARTING END-TO-END AUTOMATED PIPELINE (UNTIL 8A)"
echo "=================================================="

echo -e "\n➡️ [Step 1]: Authenticate Your Account to GCP"
pwd
# Ensure service account impersonation is disabled so commands run directly as your user:
gcloud config unset auth/impersonate_service_account 2>/dev/null || true

# Login to Google Cloud SDK with your user account (updates active user & ADC):
gcloud auth login --update-adc

# Set your active target GCP Project ID from parameters.json:
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
gcloud config set project "${PROJECT_ID}"

# Verify your authentication status and active project:
gcloud auth list
echo "✅ Active Project: $(gcloud config get-value project)"
echo "Testing Identity Token: $(gcloud auth print-identity-token | cut -c1-20)...✅ Valid"
echo "Testing Access Token  : $(gcloud auth print-access-token | cut -c1-20)...✅ Valid"

echo -e "\n➡️ [Step 2]: Validate Environment & IAM Prerequisites"
# SKIPPED STEP 2.1 per user instruction (Creating Service Accounts & IAM bindings)
echo "ℹ️ Skipping Step 2.1 as explicitly requested."

echo -e "\n➡️ [Step 2.2]: Validate Configuration Syntax & Completeness"
python3 config_schema.py

echo -e "\n➡️ [Step 3]: Export Shell Configuration Variables"
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'july1st-sharepoint-list-files'))")
export SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'july1st-sharepoint-sync-hourly'))")
export GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

gcloud config set project "${PROJECT_ID}"
echo "✅ Active Project: ${PROJECT_ID} | Function: ${FUNCTION_NAME} | Scheduler: ${SCHEDULER_JOB_NAME}"

echo -e "\n➡️ [Step 4]: Deploy Cloud Run High-Fidelity Playwright Job"
bash deploy/deploy_cloud_run.sh

echo -e "\n➡️ [Step 5]: Deploy Application Integration Workflows"
python3 deploy/deploy_workflows.py

echo -e "\n➡️ [Step 6]: Deploy Cloud Scheduler Automated Trigger Job"
bash deploy/deploy_scheduler.sh

echo -e "\n➡️ [Step 7]: Execute Read-Only Pre-Flight Verification"
python3 check/check_entra_id_auth.py

echo -e "\n➡️ [Step 8A]: Execute Complete Enterprise Synchronization (Direct Run)"
gcloud run jobs execute $(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'july1st-sharepoint-list-files-v12category'))") \
  --region=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))") \
  --project=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))") \
  --tasks=$(( $(python3 -c "import json; print(len(json.load(open('parameters.json')).get('CONFIG_Categories', [])))") + 1 ))

echo "=================================================="
echo "🎉 ALL DEPLOYMENTS & DISPATCH SUCCESSFUL! STOPPING."
echo "=================================================="
