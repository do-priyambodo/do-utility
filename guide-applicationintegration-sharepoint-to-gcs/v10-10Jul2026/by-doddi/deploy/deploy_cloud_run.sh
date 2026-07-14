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

echo "📦 Copying parameters.json and dependencies to cf-sharepoint for Docker build context..."
cp parameters.json cf-sharepoint/
[ -f config_schema.py ] && cp config_schema.py cf-sharepoint/ || true
[ -d sharepoint_engine ] && cp -r sharepoint_engine cf-sharepoint/ || true

echo "🐳 Building and Deploying Custom Docker Cloud Run Job: ${SERVICE_NAME}..."
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
echo "📦 Submitting source to Cloud Build (${IMAGE_NAME})..."
gcloud builds submit ./cf-sharepoint --tag="${IMAGE_NAME}" --project="${PROJECT_ID}"

echo "🚀 Creating or updating Cloud Run Job (${SERVICE_NAME}) with image ${IMAGE_NAME}..."
gcloud run jobs create "${SERVICE_NAME}" \
  --image="${IMAGE_NAME}" \
  --region="${LOCATION}" \
  --tasks=1 \
  --max-retries=0 \
  --task-timeout=86400s \
  --memory=8192Mi \
  --cpu=4 \
  --service-account="${SERVICE_ACCOUNT}" \
  --project="${PROJECT_ID}" || \
gcloud run jobs update "${SERVICE_NAME}" \
  --image="${IMAGE_NAME}" \
  --region="${LOCATION}" \
  --tasks=1 \
  --max-retries=0 \
  --task-timeout=86400s \
  --memory=8192Mi \
  --cpu=4 \
  --service-account="${SERVICE_ACCOUNT}" \
  --project="${PROJECT_ID}"

echo "🔐 Granting Cloud Run Job Invoker role (roles/run.invoker) to ${SERVICE_ACCOUNT}..."
gcloud run jobs add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${LOCATION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

DEV_MEMBER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))" 2>/dev/null || true)
if [ -n "$DEV_MEMBER" ]; then
  echo "🔐 Granting Cloud Run Job Invoker role (roles/run.invoker) to developer ${DEV_MEMBER}..."
  if [[ "${DEV_MEMBER}" == "group:"* ]]; then
    gcloud run jobs add-iam-policy-binding "${SERVICE_NAME}" \
      --region="${LOCATION}" \
      --member="${DEV_MEMBER}" \
      --role="roles/run.invoker" \
      --project="${PROJECT_ID}" || \
    gcloud run jobs add-iam-policy-binding "${SERVICE_NAME}" \
      --region="${LOCATION}" \
      --member="user:${DEV_MEMBER#group:}" \
      --role="roles/run.invoker" \
      --project="${PROJECT_ID}" || true
  else
    gcloud run jobs add-iam-policy-binding "${SERVICE_NAME}" \
      --region="${LOCATION}" \
      --member="${DEV_MEMBER}" \
      --role="roles/run.invoker" \
      --project="${PROJECT_ID}" || true
  fi
fi

echo "🧹 Cleaning up deployment context copy..."
rm -f cf-sharepoint/parameters.json
[ -f config_schema.py ] && rm -f cf-sharepoint/config_schema.py || true
[ -d sharepoint_engine ] && rm -rf cf-sharepoint/sharepoint_engine || true

echo "🎉 Cloud Run Job successfully deployed with custom 24-hour continuous Docker container!"

