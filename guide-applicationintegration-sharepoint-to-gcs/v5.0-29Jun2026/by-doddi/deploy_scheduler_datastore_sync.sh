#!/usr/bin/env bash
set -e

echo "================================================================"
echo "⏰ DEPLOYING DATASTORE INGESTION CLOUD SCHEDULER JOB (OPTION A)"
echo "================================================================"

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")
DATASTORE_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Id', ''))")
DATASTORE_LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Location', 'global'))")
GCS_BUCKET=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

SCHEDULER_JOB_NAME="doddi-sharepoint-datastore-sync-hourly"

if [ -z "$PROJECT_ID" ] || [ -z "$SERVICE_ACCOUNT" ] || [ -z "$DATASTORE_ID" ] || [ -z "$GCS_BUCKET" ]; then
  echo "❌ Error: Missing required parameters in parameters.json!"
  exit 1
fi

TARGET_URI="https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/${DATASTORE_LOCATION}/collections/default_collection/dataStores/${DATASTORE_ID}/branches/0/documents:import"
MANIFEST_URI="gs://${GCS_BUCKET}/config/metadata.jsonl"

MESSAGE_BODY=$(python3 -c "import json; print(json.dumps({'gcsSource': {'inputUris': ['$MANIFEST_URI'], 'dataSchema': 'custom'}, 'reconciliationMode': 'INCREMENTAL'}))")

echo "👉 Job Name          : ${SCHEDULER_JOB_NAME}"
echo "👉 Schedule          : ${CRON_SCHEDULE}"
echo "👉 Target Endpoint   : ${TARGET_URI}"
echo "👉 Manifest URI      : ${MANIFEST_URI}"
echo "👉 OAuth Account     : ${SERVICE_ACCOUNT}"
echo "----------------------------------------------------------------"

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "🗑️ Deleting existing Datastore scheduler job..."
  gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" --quiet
fi

echo "⏰ Creating direct Discovery Engine Cloud Scheduler job..."
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --schedule="${CRON_SCHEDULE}" \
  --uri="${TARGET_URI}" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Goog-User-Project=${PROJECT_ID}" \
  --message-body="${MESSAGE_BODY}" \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --attempt-deadline=1800s \
  --max-retry-attempts=0 \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"

echo "================================================================"
echo "🎉 DATASTORE CLOUD SCHEDULER JOB CREATED SUCCESSFULLY!"
echo "================================================================"
echo "👉 Job Name: ${SCHEDULER_JOB_NAME} (Schedule: ${CRON_SCHEDULE})"
echo "👉 Every 12 hours, Cloud Scheduler directly instructs Discovery Engine to re-index your GCS bucket!"
echo "================================================================"
