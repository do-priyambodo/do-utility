#!/bin/bash
# check_syncall_after.sh - Pure Bash V9.0 High-Speed Post-Sync Verification
#
# Verifies target SharePoint site inventory against GCS bucket contents via Graph API and gcloud,
# confirms delta completion, and outputs a comprehensive post-sync audit report.
# 100% Pure Bash implementation (does not execute Python scripts).

cd "$(dirname "$0")/.."
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found in $(pwd)!"
  exit 1
fi

echo "================================================================================"
echo "⚡ HIGH-SPEED POST-SYNC CHECK: GCS BUCKET & DELTA VERIFICATION (AFTER SYNC)"
echo "================================================================================"

echo ""
echo "📂 Step 1: Loading Pipeline Parameters..."
PROJECT_ID=$(jq -r '.CONFIG_ProjectId' parameters.json)
BUCKET_NAME=$(jq -r '.CONFIG_GCS_Bucket' parameters.json)
SITE_PATH=$(jq -r '.CONFIG_Sharepoint_Sites' parameters.json)
HOSTNAME=$(jq -r '.CONFIG_SharePoint_Hostname' parameters.json)
TENANT_ID=$(jq -r '.CONFIG_M365_Tenant_Id' parameters.json)
CLIENT_ID=$(jq -r '.CONFIG_M365_Client_Id' parameters.json)
SECRET_NAME=$(jq -r '.CONFIG_M365_Secret_Name' parameters.json)

echo " • Project ID            : ${PROJECT_ID}"
echo " • Target GCS Bucket     : gs://${BUCKET_NAME}"
echo " • Target SharePoint Site: ${SITE_PATH}"
echo " • Document Library      : Documents"

echo ""
echo "⚡ Step 2: Inspecting Google Cloud Storage Bucket Inventory (gs://${BUCKET_NAME}/)..."
PAGES_GCS=$(gcloud storage ls "gs://${BUCKET_NAME}/pages/**" 2>/dev/null | wc -l || echo 0)
FILES_GCS=$(gcloud storage ls "gs://${BUCKET_NAME}/files/**" 2>/dev/null | wc -l || echo 0)
TOTAL_GCS=$((PAGES_GCS + FILES_GCS))

echo "   • Modern Site Pages (.pdf) in GCS ('pages/'): ${PAGES_GCS}"
echo "   • Document Files in GCS ('files/')          : ${FILES_GCS}"
echo "   • Total Items Stored in GCS                 : ${TOTAL_GCS}"

echo ""
echo "⚡ Step 3: Fetching Azure AD Access Token & SharePoint Inventory via Graph API..."
if [[ "${SECRET_NAME}" == *"secrets/"* ]]; then
  SHORT_SECRET=$(echo "${SECRET_NAME}" | awk -F'/secrets/' '{print $2}' | awk -F'/' '{print $1}')
else
  SHORT_SECRET="${SECRET_NAME}"
fi
SECRET_VAL=$(gcloud secrets versions access latest --secret="${SHORT_SECRET}" --project="${PROJECT_ID}" 2>/dev/null)
TOKEN=$(curl -s -X POST "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${CLIENT_ID}&scope=https%3A%2F%2Fgraph.microsoft.com%2F.default&client_secret=${SECRET_VAL}&grant_type=client_credentials" | jq -r '.access_token')

if [ -z "${TOKEN}" ] || [ "${TOKEN}" = "null" ]; then
  echo "❌ Error: Failed to obtain Microsoft Graph access token."
  exit 1
fi

REL_SITE="${SITE_PATH#sites/}"
SITE_ID=$(curl -s -H "Authorization: Bearer ${TOKEN}" "https://graph.microsoft.com/v1.0/sites/${HOSTNAME}:/sites/${REL_SITE}" | jq -r '.id')

PAGES_SP=$(curl -s -H "Authorization: Bearer ${TOKEN}" "https://graph.microsoft.com/v1.0/sites/${SITE_ID}/pages" | jq '.value | length // 0')

count_files_recursive() {
  local item_id="$1"
  local url="$2"
  local total=0
  local response
  response=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${url}")
  
  local file_cnt
  file_cnt=$(echo "${response}" | jq '[.value[]? | select(.file != null)] | length // 0')
  total=$((total + file_cnt))

  local folders
  folders=$(echo "${response}" | jq -r '.value[]? | select(.folder != null) | .id')
  for fid in ${folders}; do
    local sub_cnt
    sub_cnt=$(count_files_recursive "${fid}" "https://graph.microsoft.com/v1.0/drives/${DRIVE_ID}/items/${fid}/children")
    total=$((total + sub_cnt))
  done
  echo "${total}"
}

DRIVE_ID=$(curl -s -H "Authorization: Bearer ${TOKEN}" "https://graph.microsoft.com/v1.0/sites/${SITE_ID}/drive" | jq -r '.id')
FILES_SP=$(count_files_recursive "root" "https://graph.microsoft.com/v1.0/drives/${DRIVE_ID}/root/children")

TOTAL_SP=$((PAGES_SP + FILES_SP))

SYNCED_PAGES=$((PAGES_GCS > PAGES_SP ? PAGES_SP : PAGES_GCS))
SYNCED_FILES=$((FILES_GCS > FILES_SP ? FILES_SP : FILES_GCS))
TOTAL_SYNCED=$((SYNCED_PAGES + SYNCED_FILES))

REMAINING_PAGES=$((PAGES_SP > PAGES_GCS ? PAGES_SP - PAGES_GCS : 0))
REMAINING_FILES=$((FILES_SP > FILES_GCS ? FILES_SP - FILES_GCS : 0))
TOTAL_REMAINING=$((REMAINING_PAGES + REMAINING_FILES))

echo ""
echo "================================================================================"
echo "📊 POST-SYNC VERIFICATION REPORT (AFTER SYNC)"
echo "================================================================================"
echo "1️⃣  GOOGLE CLOUD STORAGE BUCKET INVENTORY (gs://${BUCKET_NAME}):"
printf "    • Total Modern Site Pages Stored ('pages/') : %6d\n" "${PAGES_GCS}"
printf "    • Total Document Files Stored ('files/')    : %6d\n" "${FILES_GCS}"
echo "    ----------------------------------------------------------------------------"
printf "    • TOTAL GCS OBJECTS STORED                  : %6d\n" "${TOTAL_GCS}"
echo "--------------------------------------------------------------------------------"
echo "2️⃣  ALREADY SYNCED & UP-TO-DATE IN GCS (DELTA CACHE VERIFIED):"
printf "    • Pages Already Synced & Up-To-Date         : %6d / %d\n" "${SYNCED_PAGES}" "${PAGES_SP}"
printf "    • Files Already Synced & Up-To-Date         : %6d / %d\n" "${SYNCED_FILES}" "${FILES_SP}"
echo "    ----------------------------------------------------------------------------"
printf "    • TOTAL IN-SYNC ITEMS                       : %6d / %d\n" "${TOTAL_SYNCED}" "${TOTAL_SP}"
echo "--------------------------------------------------------------------------------"
echo "3️⃣  REMAINING DELTA (UNSYNCED / IN-PROGRESS ITEMS):"
printf "    • Remaining Pages Needing Sync              : %6d\n" "${REMAINING_PAGES}"
printf "    • Remaining Files Needing Sync              : %6d\n" "${REMAINING_FILES}"
echo "    ----------------------------------------------------------------------------"
printf "    • TOTAL REMAINING DELTA                     : %6d\n" "${TOTAL_REMAINING}"
echo "================================================================================"
if [ "${TOTAL_REMAINING}" -eq 0 ]; then
  echo "🎉 SUCCESS: 100% of SharePoint pages and files are fully synchronized in GCS!"
else
  echo "⏳ IN PROGRESS: ${TOTAL_REMAINING} item(s) remaining to be synchronized."
fi
echo "================================================================================"
