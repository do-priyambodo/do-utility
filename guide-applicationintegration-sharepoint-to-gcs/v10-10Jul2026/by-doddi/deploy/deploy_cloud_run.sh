#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

# Run log rotation and backup
python3 -c "import log_helper; log_helper.backup_old_logs()"

# Catch errors and log them to error.log
trap 'python3 -c "import log_helper; log_helper.log_error(\"deploy_cloud_run.sh failed on line \$LINENO\")"' ERR

# Redirect stdout and stderr to setup.log while outputting to terminal
exec > >(tee -a log/setup.log) 2>&1

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
SERVICE_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")

if [ -z "$PROJECT_ID" ] || [ -z "$LOCATION" ] || [ -z "$SERVICE_ACCOUNT" ] || [ -z "$SERVICE_NAME" ]; then
  echo "❌ Error: Required configuration parameters missing in parameters.json!"
  exit 1
fi

echo "🚀 Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"

echo "📦 Copying parameters.json to cf-sharepoint for Docker build context..."
cp parameters.json cf-sharepoint/

echo "🐳 Building and Deploying Custom Docker Cloud Run Service: ${SERVICE_NAME}..."
gcloud run deploy "${SERVICE_NAME}" \
  --source=./cf-sharepoint \
  --region="${LOCATION}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --no-allow-unauthenticated \
  --timeout=3600 \
  --memory=8Gi \
  --cpu=4 \
  --clear-base-image

echo "🔐 Granting Cloud Run Invoker role (roles/run.invoker) to ${SERVICE_ACCOUNT}..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${LOCATION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

echo "🧹 Cleaning up deployment context copy..."
rm cf-sharepoint/parameters.json

echo "🎉 Cloud Run service successfully deployed with custom Docker container!"
