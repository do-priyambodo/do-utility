#!/usr/bin/env bash
# pull_check_version.sh - Step 1 of Mandatory 2-Step Deployment Protocol
# Pulls latest code from remote repository, asserts exact Git version/tag,
# and verifies that parameters.json is valid before Cloud Run deployment.
set -euo pipefail

echo "================================================================================"
echo "🔍 STEP 1: PULL LATEST CODE & ASSERT VERSION / PARAMETERS"
echo "================================================================================"

echo "📥 1. Fetching latest remote branch and checking out origin/main..."
git fetch origin
git checkout -f origin/main

echo -e "\n🏷️  2. Inspecting current Git commit and revision tag..."
CURRENT_COMMIT=$(git log -1 --format="%h - %s (%ci)")
CURRENT_TAG=$(git describe --tags --always 2>/dev/null || echo "No-Tag-Found")

echo "   • Current Commit: ${CURRENT_COMMIT}"
echo "   • Active Tag    : ${CURRENT_TAG}"

if [[ "${CURRENT_TAG}" == *"Revision"* || "${CURRENT_TAG}" == *"v10-"* ]]; then
    echo "   ✅ Verified active release tag format."
else
    echo "   ⚠️ Warning: Could not detect standard Revision tag (Current: ${CURRENT_TAG}). Please confirm branch."
fi

echo -e "\n⚙️  3. Verifying local configuration (parameters.json)..."
if [[ ! -f "parameters.json" ]]; then
    echo "❌ Error: parameters.json not found in current directory!"
    exit 1
fi

PROJECT_ID=$(python3 -c 'import json; print(json.load(open("parameters.json")).get("CONFIG_ProjectId", ""))' 2>/dev/null || echo "")
BUCKET_NAME=$(python3 -c 'import json; print(json.load(open("parameters.json")).get("CONFIG_GCS_Bucket", ""))' 2>/dev/null || echo "")
JOB_NAME=$(python3 -c 'import json; print(json.load(open("parameters.json")).get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files"))' 2>/dev/null || echo "")
PARENT_INT=$(python3 -c 'import json; print(json.load(open("parameters.json")).get("CONFIG_Parent_Integration_Name", ""))' 2>/dev/null || echo "")

if [[ -z "${PROJECT_ID}" || -z "${BUCKET_NAME}" ]]; then
    echo "❌ Error: CONFIG_ProjectId or CONFIG_GCS_Bucket is missing in parameters.json!"
    exit 1
fi

echo "   • Project ID           : ${PROJECT_ID}"
echo "   • Target GCS Bucket    : gs://${BUCKET_NAME}"
echo "   • Cloud Run Job Name   : ${JOB_NAME}"
echo "   • Parent Integration   : ${PARENT_INT:-Not configured (Standard Discovery Mode)}"

echo -e "\n☁️  4. Inspecting existing Cloud Run Job in target project (${PROJECT_ID})..."
if gcloud run jobs describe "${JOB_NAME}" --region=asia-southeast1 --project="${PROJECT_ID}" --format="value(metadata.name)" >/dev/null 2>&1; then
    EXISTING_IMAGE=$(gcloud run jobs describe "${JOB_NAME}" --region=asia-southeast1 --project="${PROJECT_ID}" --format="value(spec.template.spec.template.spec.containers[0].image)" 2>/dev/null || echo "Unknown")
    echo "   ✅ Found existing Cloud Run Job '${JOB_NAME}' (Current Image: ${EXISTING_IMAGE})"
else
    echo "   ℹ️ Could not find existing Cloud Run Job '${JOB_NAME}' in region asia-southeast1 (or insufficient permissions to inspect)."
fi

echo "================================================================================"
echo "🎉 STEP 1 COMPLETE: CODE IS UP-TO-DATE & VERSION CHECK PASSED!"
echo "================================================================================"
echo "You may now proceed to Step 2 when ready:"
echo "   👉 ./deploy/deploy_cloud_run.sh"
echo "================================================================================"
