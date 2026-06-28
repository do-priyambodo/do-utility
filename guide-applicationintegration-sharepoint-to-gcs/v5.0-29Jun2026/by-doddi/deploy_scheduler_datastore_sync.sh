#!/usr/bin/env bash
set -e

echo "================================================================"
echo "⏰ DEPLOYING DATASTORE INGESTION CLOUD SCHEDULER JOB (OPTION B)"
echo "================================================================"

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")
FUNCTION_NAME="doddi-datastore-sync-trigger"
SCHEDULER_JOB_NAME="doddi-sharepoint-datastore-sync-hourly"

if [ -z "$PROJECT_ID" ] || [ -z "$SERVICE_ACCOUNT" ]; then
  echo "❌ Error: Missing required parameters in parameters.json!"
  exit 1
fi

echo "🔍 Resolving Cloud Function URL dynamically for '${FUNCTION_NAME}'..."
FUNCTION_URL=$(gcloud run services describe "${FUNCTION_NAME}" --region="${LOCATION}" --project="${PROJECT_ID}" --format="value(status.url)" 2>/dev/null || true)

if [ -z "$FUNCTION_URL" ]; then
  echo "❌ Error: Could not resolve Cloud Function URI. Is '${FUNCTION_NAME}' deployed via ./deploy_datastore_sync_function.sh?"
  exit 1
fi

echo "👉 Job Name          : ${SCHEDULER_JOB_NAME}"
echo "👉 Schedule          : ${CRON_SCHEDULE}"
echo "👉 Target Function   : ${FUNCTION_URL}"
echo "👉 OIDC Account      : ${SERVICE_ACCOUNT}"
echo "----------------------------------------------------------------"

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "🗑️ Deleting existing Datastore scheduler job..."
  gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" --quiet
fi

echo "⏰ Creating Cloud Scheduler job targeting Cloud Function..."
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --schedule="${CRON_SCHEDULE}" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"trigger": "scheduled_cron"}' \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --attempt-deadline=600s \
  --max-retry-attempts=0 \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"

echo "================================================================"
echo "�� DATASTORE CLOUD SCHEDULER JOB CREATED SUCCESSFULLY!"
echo "================================================================"
echo "👉 Job Name: ${SCHEDULER_JOB_NAME} (Schedule: ${CRON_SCHEDULE})"
echo "👉 Every 12 hours, Cloud Scheduler wakes up Cloud Function '${FUNCTION_NAME}' with structured logging!"
echo "================================================================"
