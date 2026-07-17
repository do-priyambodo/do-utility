#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

# Run log rotation and backup
python3 -c "import log_helper; log_helper.backup_old_logs()"

# Catch errors and log them to error.log
trap 'python3 -c "import log_helper; log_helper.log_error(\"deploy_cf_datastore.sh failed on line \$LINENO\")"' ERR

# Redirect stdout and stderr to setup.log while outputting to terminal
mkdir -p log
exec > >(tee -a log/setup.log) 2>&1

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Datastore_Function_Name', 'yourorg-datastore-import'))")

if [ -z "$PROJECT_ID" ] || [ -z "$LOCATION" ] || [ -z "$SERVICE_ACCOUNT" ] || [ -z "$FUNCTION_NAME" ]; then
  echo "❌ Error: Required configuration parameters missing in parameters.json!"
  exit 1
fi

echo "🚀 Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"

# Check if Cloud Function already exists
if gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "ℹ️ Cloud Function '${FUNCTION_NAME}' already exists. Proceeding with update deployment..."
fi

echo "📦 Copying parameters.json to cf-datastore for function deployment context..."
cp parameters.json cf-datastore/

echo "📦 Deploying Python Cloud Function: ${FUNCTION_NAME}..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --runtime=python310 \
  --entry-point=main \
  --trigger-http \
  --region="${LOCATION}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --no-allow-unauthenticated \
  --timeout=3600 \
  --memory=2GB \
  --cpu=1 \
  --source=./cf-datastore

echo "🧹 Cleaning up deployment context copy..."
rm cf-datastore/parameters.json

echo "🎉 Datastore Cloud Function '${FUNCTION_NAME}' successfully deployed!"
