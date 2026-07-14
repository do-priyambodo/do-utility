#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

if [ ! -f "config-parameters.json" ]; then
  echo "❌ Error: config-parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Service_Account', ''))")
DATASTORE_ID=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Datastore_Id', ''))")
DATASTORE_LOC=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Datastore_Location', 'global'))")
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_GCS_Bucket', ''))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")
JOB_NAME="yourorg-sharepoint-datastore-sync-12h"

if [ -z "$PROJECT_ID" ] || [ -z "$DATASTORE_ID" ] || [ -z "$BUCKET_NAME" ]; then
  echo "❌ Error: CONFIG_ProjectId, CONFIG_Datastore_Id, and CONFIG_GCS_Bucket must be set in config-parameters.json!"
  exit 1
fi

echo "================================================================"
echo "🚀 DEPLOYING AUTOMATED 12-HOUR VERTEX AI DATASTORE SYNC SCHEDULER"
echo "================================================================"
echo "📌 Project ID:        ${PROJECT_ID}"
echo "📌 Scheduler Region:  ${LOCATION}"
echo "📌 Datastore ID:      ${DATASTORE_ID} (${DATASTORE_LOC})"
echo "📌 Manifest Path:     gs://${BUCKET_NAME}/config/metadata.jsonl"
echo "⏰ Cron Schedule:     ${CRON_SCHEDULE}"
echo "🤖 Service Account:   ${SERVICE_ACCOUNT}"
echo "================================================================"

FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('config-parameters.json')).get('CONFIG_Datastore_Function_Name', 'yourorg-datastore-import'))")

echo "🔍 Resolving Cloud Run Service / Cloud Function URL dynamically for '${FUNCTION_NAME}'..."
FUNCTION_URL=$(gcloud run services describe "${FUNCTION_NAME}" --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(status.url)" 2>/dev/null || true)
if [ -z "$FUNCTION_URL" ]; then
  FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(serviceConfig.uri)" 2>/dev/null || true)
fi

if [ -z "$FUNCTION_URL" ]; then
  echo "❌ Error: Could not resolve Cloud Run Service or Cloud Function URI for '${FUNCTION_NAME}'. Is the datastore function deployed? Try running ./deploy/deploy_cf_datastore.sh first."
  exit 1
fi

PAYLOAD='{"reconciliation_mode":"INCREMENTAL"}'

if gcloud scheduler jobs describe "${JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "🗑️ Deleting existing scheduler job '${JOB_NAME}'..."
  gcloud scheduler jobs delete "${JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" --quiet
fi

echo "🚀 Creating Cloud Scheduler job '${JOB_NAME}' targeting ${FUNCTION_URL}..."
gcloud scheduler jobs create http "${JOB_NAME}" \
  --location="${LOCATION}" \
  --schedule="${CRON_SCHEDULE}" \
  --uri="${FUNCTION_URL}" \
  --http-method="POST" \
  --headers="Content-Type=application/json" \
  --message-body="${PAYLOAD}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --attempt-deadline=600s \
  --max-retry-attempts=1 \
  --project="${PROJECT_ID}"

echo "================================================================"
echo "🎉 AUTOMATED DATASTORE SYNC SCHEDULER DEPLOYED SUCCESSFULLY!"
echo "================================================================"
echo "🌐 You can view or force-run this schedule in Cloud Console:"
echo "   https://console.cloud.google.com/cloudscheduler/jobs/edit/${LOCATION}/${JOB_NAME}?project=${PROJECT_ID}"
echo "================================================================"
