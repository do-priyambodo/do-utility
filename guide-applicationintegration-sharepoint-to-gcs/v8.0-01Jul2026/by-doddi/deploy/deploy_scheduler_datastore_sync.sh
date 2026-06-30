#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
DATASTORE_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Id', ''))")
DATASTORE_LOC=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Location', 'global'))")
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")
JOB_NAME="doddi-sharepoint-datastore-sync-12h"

if [ -z "$PROJECT_ID" ] || [ -z "$DATASTORE_ID" ] || [ -z "$BUCKET_NAME" ]; then
  echo "❌ Error: CONFIG_ProjectId, CONFIG_Datastore_Id, and CONFIG_GCS_Bucket must be set in parameters.json!"
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

IMPORT_URL="https://discoveryengine.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${DATASTORE_LOC}/collections/default_collection/dataStores/${DATASTORE_ID}/branches/0/documents:import"
PAYLOAD='{"gcsSource":{"inputUris":["gs://'${BUCKET_NAME}'/config/metadata.jsonl"]},"reconciliationMode":"INCREMENTAL"}'

if gcloud scheduler jobs describe "${JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "🗑️ Deleting existing scheduler job '${JOB_NAME}'..."
  gcloud scheduler jobs delete "${JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" --quiet
fi

echo "🚀 Creating Cloud Scheduler job '${JOB_NAME}'..."
gcloud scheduler jobs create http "${JOB_NAME}" \
  --location="${LOCATION}" \
  --schedule="${CRON_SCHEDULE}" \
  --uri="${IMPORT_URL}" \
  --http-method="POST" \
  --headers="Content-Type=application/json" \
  --message-body="${PAYLOAD}" \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --project="${PROJECT_ID}"

echo "================================================================"
echo "🎉 AUTOMATED DATASTORE SYNC SCHEDULER DEPLOYED SUCCESSFULLY!"
echo "================================================================"
echo "🌐 You can view or force-run this schedule in Cloud Console:"
echo "   https://console.cloud.google.com/cloudscheduler/jobs/edit/${LOCATION}/${JOB_NAME}?project=${PROJECT_ID}"
echo "================================================================"
