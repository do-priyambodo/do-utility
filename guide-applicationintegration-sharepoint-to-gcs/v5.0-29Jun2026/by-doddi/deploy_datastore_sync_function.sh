#!/usr/bin/env bash
set -e

echo "================================================================"
echo "🚀 DEPLOYING DATASTORE INGESTION TRIGGER CLOUD FUNCTION"
echo "================================================================"

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', 'asia-southeast1'))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
FUNCTION_NAME="doddi-datastore-sync-trigger"

if [ -z "$PROJECT_ID" ] || [ -z "$SERVICE_ACCOUNT" ]; then
  echo "❌ Error: Missing required parameters in parameters.json!"
  exit 1
fi

gcloud config set project "${PROJECT_ID}" --quiet >/dev/null

echo "📦 Copying parameters.json into cf-datastore-sync container context..."
cp parameters.json cf-datastore-sync/parameters.json

echo "📦 Deploying Gen 2 Cloud Function: ${FUNCTION_NAME}..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --runtime=python310 \
  --region="${LOCATION}" \
  --source=./cf-datastore-sync \
  --entry-point=main \
  --trigger-http \
  --service-account="${SERVICE_ACCOUNT}" \
  --memory=512MB \
  --timeout=300s \
  --no-allow-unauthenticated \
  --quiet

rm -f cf-datastore-sync/parameters.json

FUNCTION_URL=$(gcloud run services describe "${FUNCTION_NAME}" --region="${LOCATION}" --format="value(status.url)")
echo "================================================================"
echo "🎉 DATASTORE SYNC CLOUD FUNCTION DEPLOYED SUCCESSFULLY!"
echo "================================================================"
echo "👉 Function Name : ${FUNCTION_NAME}"
echo "👉 Function URL  : ${FUNCTION_URL}"
echo "================================================================"
