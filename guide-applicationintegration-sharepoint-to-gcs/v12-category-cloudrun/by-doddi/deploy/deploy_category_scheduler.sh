#!/bin/bash
# deploy_category_scheduler.sh - Deploys the Option 1 Single Master Cloud Scheduler Job
# Triggers the V11 Cloud Run Job daily at midnight (0 0 * * *) to run through all categories sequentially.
cd "$(dirname "$0")/.."
set -e

if [ ! -f "config-parameters.json" ]; then
  echo "❌ Error: config-parameters.json not found in working directory."
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Service_Account', ''))")
JOB_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
SCHEDULER_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Scheduler_Job_Name', '${JOB_NAME}-daily-master'))")

echo "================================================================================"
echo "⏰ V11 CLOUD SCHEDULER DEPLOYMENT (OPTION 1 MASTER SEQUENTIAL LOOP)"
echo "================================================================================"
echo " • Project ID       : ${PROJECT_ID}"
echo " • Region           : ${LOCATION}"
echo " • Cloud Run Job    : ${JOB_NAME}"
echo " • Scheduler Job    : ${SCHEDULER_NAME}"
echo " • Cron Schedule    : '0 0 * * *' (Daily at Midnight)"
echo " • Service Account  : ${SERVICE_ACCOUNT}"
echo "================================================================================\n"

gcloud config set project "${PROJECT_ID}"

# Construct Cloud Run Job execution API endpoint (v2 API requiring valid RunJobRequest payload)
RUN_JOB_URI="https://${LOCATION}-run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${LOCATION}/jobs/${JOB_NAME}:run"

echo "🔐 Ensuring Cloud Scheduler Service Agent is authorized to mint tokens..."
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "")
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Use Compute SA for Scheduler trigger to bypass Org Policy/VPC-SC custom SA token creation restrictions on Run API v2
SCHEDULER_CALLER_SA="${COMPUTE_SA:-$SERVICE_ACCOUNT}"

if [ -n "${PROJECT_NUMBER}" ]; then
  SCHEDULER_AGENT="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
  gcloud iam service-accounts add-iam-policy-binding "${SCHEDULER_CALLER_SA}" \
    --member="${SCHEDULER_AGENT}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
  gcloud iam service-accounts add-iam-policy-binding "${SCHEDULER_CALLER_SA}" \
    --member="${SCHEDULER_AGENT}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
fi

echo "🚀 Creating or updating Cloud Scheduler job '${SCHEDULER_NAME}'..."
gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
  --location="${LOCATION}" \
  --schedule="0 0 * * *" \
  --uri="${RUN_JOB_URI}" \
  --http-method=POST \
  --message-body='{"overrides": {}}' \
  --oauth-service-account-email="${SCHEDULER_CALLER_SA}" \
  --time-zone="Asia/Kuala_Lumpur" \
  --description="V11 Option 1 Daily Master SharePoint-to-GCS Sequential Category Sync" || \
gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
  --location="${LOCATION}" \
  --schedule="0 0 * * *" \
  --uri="${RUN_JOB_URI}" \
  --http-method=POST \
  --message-body='{"overrides": {}}' \
  --oauth-service-account-email="${SCHEDULER_CALLER_SA}" \
  --time-zone="Asia/Kuala_Lumpur" \
  --description="V11 Option 1 Daily Master SharePoint-to-GCS Sequential Category Sync"

echo "\n✅ Successfully configured Cloud Scheduler Job '${SCHEDULER_NAME}'!"
echo "💡 To trigger an on-demand manual test run right now, execute:"
echo "   gcloud run jobs execute ${JOB_NAME} --region=${LOCATION}"
