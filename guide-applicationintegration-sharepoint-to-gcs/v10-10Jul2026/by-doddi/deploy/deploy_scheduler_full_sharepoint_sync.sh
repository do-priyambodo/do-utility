#!/bin/bash
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

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
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', 'yourorg-sharepoint-list-files'))")
SCHEDULER_JOB_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Job_Name', 'yourorg-sharepoint-sync-hourly'))")
CRON_SCHEDULE=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Scheduler_Cron_Schedule', '0 */12 * * *'))")

if [ -z "$PROJECT_ID" ] || [ -z "$LOCATION" ] || [ -z "$SERVICE_ACCOUNT" ] || [ -z "$FUNCTION_NAME" ] || [ -z "$SCHEDULER_JOB_NAME" ]; then
  echo "❌ Error: Missing required scheduler configuration parameters in parameters.json!"
  exit 1
fi

if [[ "$PROJECT_ID" == *"yourorg"* ]]; then
  echo "❌ Error: 'parameters.json' still contains sample placeholder ('$PROJECT_ID'). Please update parameters.json with your target GCP Project ID."
  exit 1
fi

CURRENT_GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -n "$CURRENT_GCLOUD_PROJECT" ] && [ "$CURRENT_GCLOUD_PROJECT" != "$PROJECT_ID" ] && [ "$PROJECT_ID" = "work-mylab-machinelearning" ]; then
  echo "❌ Error: CONFIG_ProjectId in 'parameters.json' is set to the default sample project ('work-mylab-machinelearning'), but your active gcloud project is '${CURRENT_GCLOUD_PROJECT}'."
  echo "👉 Please edit 'parameters.json' and set CONFIG_ProjectId to your target project ('${CURRENT_GCLOUD_PROJECT}') before running this script."
  exit 1
fi

# Generate JSON payload dynamically attaching environment config from parameters.json
MESSAGE_BODY=$(python3 -c "
import json
params = json.load(open('parameters.json'))
payload = {
    'site_name': params.get('CONFIG_Sharepoint_Sites', '').replace('sites/', ''),
    'library_name': params.get('CONFIG_Sharepoint_Library', 'Documents'),
    'bucket_name': params.get('CONFIG_GCS_Bucket', ''),
    'trigger_integration': True,
    'integration_name': params.get('CONFIG_Parent_Integration_Name', ''),
    'location': params.get('CONFIG_Location', ''),
    'project_id': params.get('CONFIG_ProjectId', '')
}
print(json.dumps(payload))
")

echo "🔍 Setting Cloud Run Job execution URI dynamically for '${FUNCTION_NAME}'..."
FUNCTION_URL="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${LOCATION}/jobs/${FUNCTION_NAME}:run"

echo "⏰ Creating or updating Cloud Scheduler job '${SCHEDULER_JOB_NAME}' pointing to Cloud Run Job '${FUNCTION_NAME}'..."
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "🗑️ Deleting existing scheduler job..."
  gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${LOCATION}" --project="${PROJECT_ID}" --quiet
fi

gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --schedule="${CRON_SCHEDULE}" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="${MESSAGE_BODY}" \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --attempt-deadline=1800s \
  --max-retry-attempts=0 \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}"

echo "🎉 Cloud Scheduler job '${SCHEDULER_JOB_NAME}' successfully created and active pointing to Job '${FUNCTION_NAME}' (Schedule: ${CRON_SCHEDULE})!"

