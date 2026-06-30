#!/bin/bash
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
DATASTORE_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Id', ''))")
DATASTORE_LOC=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Location', 'global'))")
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")
JOB_NAME="doddi-sharepoint-datastore-sync-12h"

if [ -z "$PROJECT_ID" ] || [ -z "$DATASTORE_ID" ] || [ -z "$BUCKET_NAME" ] || [ -z "$FUNCTION_NAME" ]; then
  echo "❌ Error: CONFIG_ProjectId, CONFIG_Datastore_Id, CONFIG_GCS_Bucket, and CONFIG_CloudFunction_Name must be set in parameters.json!"
  exit 1
fi

echo "================================================================"
echo "🚀 DEPLOYING AUTOMATED 12-HOUR VERTEX AI DATASTORE SYNC SCHEDULER"
echo "================================================================"
echo "📌 Project ID:        ${PROJECT_ID}"
echo "📌 Scheduler Region:  ${LOCATION}"
echo "📌 Cloud Function:    ${FUNCTION_NAME}"
echo "📌 Datastore ID:      ${DATASTORE_ID} (${DATASTORE_LOC})"
echo "📌 Manifest Path:     gs://${BUCKET_NAME}/config/metadata.jsonl"
echo "⏰ Cron Schedule:     ${CRON_SCHEDULE}"
echo "🤖 Service Account:   ${SERVICE_ACCOUNT}"
echo "================================================================"

echo "🔍 Resolving Cloud Function URL dynamically for '${FUNCTION_NAME}'..."
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(serviceConfig.uri)")

if [ -z "$FUNCTION_URL" ]; then
  echo "❌ Error: Could not resolve Cloud Function URI. Is '${FUNCTION_NAME}' deployed?"
  exit 1
fi

PAYLOAD=$(python3 -c "
import json
params = json.load(open('parameters.json'))
payload = {
    'action': 'sync_datastore',
    'project_id': params.get('CONFIG_ProjectId', ''),
    'location': params.get('CONFIG_Datastore_Location', 'global'),
    'datastore_id': params.get('CONFIG_Datastore_Id', ''),
    'bucket_name': params.get('CONFIG_GCS_Bucket', '')
}
print(json.dumps(payload))
")

if gcloud scheduler jobs describe "${JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "ℹ️ Scheduler job '${JOB_NAME}' already exists. Updating..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --location="${LOCATION}" \
    --schedule="${CRON_SCHEDULE}" \
    --uri="${FUNCTION_URL}" \
    --http-method="POST" \
    --headers="Content-Type=application/json" \
    --message-body="${PAYLOAD}" \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" \
    --oidc-token-audience="${FUNCTION_URL}" \
    --attempt-deadline=1800s \
    --max-retry-attempts=0 \
    --project="${PROJECT_ID}"
else
  echo "🚀 Creating new Cloud Scheduler job '${JOB_NAME}' via OIDC Cloud Function trigger..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --location="${LOCATION}" \
    --schedule="${CRON_SCHEDULE}" \
    --uri="${FUNCTION_URL}" \
    --http-method="POST" \
    --headers="Content-Type=application/json" \
    --message-body="${PAYLOAD}" \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" \
    --oidc-token-audience="${FUNCTION_URL}" \
    --attempt-deadline=1800s \
    --max-retry-attempts=0 \
    --project="${PROJECT_ID}"
fi

echo "================================================================"
echo "🎉 AUTOMATED DATASTORE SYNC SCHEDULER DEPLOYED SUCCESSFULLY!"
echo "================================================================"
echo "🌐 You can view or force-run this schedule in Cloud Console:"
echo "   https://console.cloud.google.com/cloudscheduler/jobs/edit/${LOCATION}/${JOB_NAME}?project=${PROJECT_ID}"
echo "================================================================"
