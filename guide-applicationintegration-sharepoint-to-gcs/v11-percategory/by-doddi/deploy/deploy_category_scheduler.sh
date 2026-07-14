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
SCHEDULER_NAME="${JOB_NAME}-daily-master"

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

# Construct Cloud Run Job execution API endpoint
RUN_JOB_URI="https://${LOCATION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

echo "🚀 Creating or updating Cloud Scheduler job '${SCHEDULER_NAME}'..."
gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
  --location="${LOCATION}" \
  --schedule="0 0 * * *" \
  --uri="${RUN_JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --time-zone="Asia/Kuala_Lumpur" \
  --description="V11 Option 1 Daily Master SharePoint-to-GCS Sequential Category Sync" || \
gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
  --location="${LOCATION}" \
  --schedule="0 0 * * *" \
  --uri="${RUN_JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --time-zone="Asia/Kuala_Lumpur" \
  --description="V11 Option 1 Daily Master SharePoint-to-GCS Sequential Category Sync"

echo "\n✅ Successfully configured Cloud Scheduler Job '${SCHEDULER_NAME}'!"
echo "💡 To trigger an on-demand manual test run right now, execute:"
echo "   gcloud run jobs execute ${JOB_NAME} --region=${LOCATION}"
