#!/bin/bash
set -e

PROJECT_ID="your-gcp-project-id"
LOCATION="asia-southeast1"
FUNCTION_NAME="your-sharepoint-list-files"
SERVICE_ACCOUNT="your-custom-service-account@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"

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

echo "🎉 Cloud Function successfully deployed!"
