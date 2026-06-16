#!/bin/bash
set -e

# Run log rotation and backup
python3 -c "import log_helper; log_helper.backup_old_logs()"

# Catch errors and log them to error.log
trap 'python3 -c "import log_helper; log_helper.log_error(\"deploy_cf.sh failed on line \$LINENO\")"' ERR

# Redirect stdout and stderr to setup.log while outputting to terminal
exec > >(tee -a log/setup.log) 2>&1

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")

if [ -z "$PROJECT_ID" ] || [ -z "$LOCATION" ] || [ -z "$SERVICE_ACCOUNT" ] || [ -z "$FUNCTION_NAME" ]; then
  echo "❌ Error: CONFIG_ProjectId, CONFIG_Location, CONFIG_Service_Account, or CONFIG_CloudFunction_Name missing in parameters.json!"
  exit 1
fi


echo "🚀 Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"

if gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "⚠️ Cloud Function '${FUNCTION_NAME}' already exists in region '${LOCATION}'."
  read -p "Do you want to delete the existing function first? (y/N): " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    echo "🗑️ Deleting existing function..."
    gcloud functions delete "${FUNCTION_NAME}" --gen2 --region="${LOCATION}" --project="${PROJECT_ID}" --quiet
  else
    echo "⏭️ Proceeding with update deployment..."
  fi
fi

echo "📦 Copying parameters.json to cf-source for function deployment context..."
cp parameters.json cf-source/

echo "📦 Deploying Python Cloud Function: ${FUNCTION_NAME}..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --runtime=python310 \
  --entry-point=main \
  --trigger-http \
  --region="${LOCATION}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --no-allow-unauthenticated \
  --source=./cf-source

echo "🧹 Cleaning up deployment context copy..."
rm cf-source/parameters.json

echo "🎉 Cloud Function successfully deployed!"
