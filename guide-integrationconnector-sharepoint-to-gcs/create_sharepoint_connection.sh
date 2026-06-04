#!/bin/bash
# ==================================================================================
# Deploy SharePoint Integration Connector via Direct REST API
# ==================================================================================
# Justification: Bypasses the Google Cloud Console UI's automatic project-level 
# IAM binding checks, which usually fail for restricted developer accounts.
# ==================================================================================

set -e

# ==================================================================================
# 🛠️ 1. CONFIGURATION PARAMETERS (Your Team: Edit these values)
# ==================================================================================
PROJECT_ID="your-gcp-project-id"
LOCATION="asia-southeast1"
CONNECTION_NAME="your-sharepoint-connection"
SERVICE_ACCOUNT="your-custom-service-account@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="your-secret-sharepoint-clientsecret"
SECRET_VERSION="1"

# Microsoft Azure AD / SharePoint credentials
TENANT_ID="YOUR_MICROSOFT_TENANT_ID"
CLIENT_ID="YOUR_MICROSOFT_CLIENT_ID"
SHAREPOINT_SITE_URL="https://your-tenant.sharepoint.com/sites/your-sharepoint-subsite-name"

# ==================================================================================
# 🚀 2. PRE-FLIGHT CHECKS & RUNTIME EXECUTION
# ==================================================================================
echo "=================================================================="
echo "🤖 DEPLOYING SHAREPOINT INTEGRATION CONNECTOR VIA DIRECT REST API"
echo "=================================================================="
echo "👉 Project ID: ${PROJECT_ID}"
echo "👉 Location:   ${LOCATION}"
echo "👉 Connection: ${CONNECTION_NAME}"
echo "👉 Target Site: ${SHAREPOINT_SITE_URL}"
echo "=================================================================="

# 1. Retrieve active developer session token
echo "🔒 Step 1: Authenticating and generating GCP OAuth Access Token..."
AUTH_TOKEN=$(gcloud auth print-access-token)

if [ -z "${AUTH_TOKEN}" ]; then
  echo "❌ Error: Failed to retrieve active access token. Please run 'gcloud auth login' first."
  exit 1
fi

SECRET_VERSION_PATH="projects/${PROJECT_ID}/secrets/${SECRET_NAME}/versions/${SECRET_VERSION}"

# 2. Post connection payload to Connectors REST API
echo "📤 Step 2: Sending POST request to Google Cloud Connectors API..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "connectorVersion": "projects/'"${PROJECT_ID}"'/locations/global/providers/microsoft/connectors/sharepoint/versions/2",
    "serviceAccount": "'"${SERVICE_ACCOUNT}"'",
    "description": "SharePoint Connection for GCS Sync Flow under restricted IAM",
    "nodeConfig": {
      "minNodeCount": 1,
      "maxNodeCount": 2
    },
    "configVariables": [
      {
        "key": "azure_environment",
        "stringValue": "GLOBAL"
      },
      {
        "key": "base_web_url",
        "stringValue": "'"${SHAREPOINT_SITE_URL}"'"
      },
      {
        "key": "proxy_enabled",
        "boolValue": false
      }
    ],
    "authConfig": {
      "authType": "OAUTH2_AUTH_CODE_FLOW",
      "oauth2AuthCodeFlow": {
        "clientId": "'"${CLIENT_ID}"'",
        "clientSecret": {
          "secretVersion": "'"${SECRET_VERSION_PATH}"'"
        },
        "scopes": [
          "Sites.Read.All",
          "Files.Read.All",
          "User.Read.All"
        ],
        "authUri": "https://login.microsoftonline.com/'"${TENANT_ID}"'/oauth2/v2.0/authorize?prompt=consent"
      },
      "authKey": "oauth"
    },
    "destinationConfigs": [
      {
        "key": "url",
        "destinations": [
          {
            "host": "'"${SHAREPOINT_SITE_URL}"'",
            "port": 443
          }
        ]
      }
    ]
  }' \
  "https://connectors.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/connections?connectionId=${CONNECTION_NAME}")

# 3. Parse HTTP status code
HTTP_STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "${HTTP_STATUS}" -eq 200 ] || [ "${HTTP_STATUS}" -eq 201 ]; then
  echo "=================================================================="
  echo "🎉 SUCCESS: SharePoint Connection Resource Created Successfully!"
  echo "=================================================================="
  echo "👉 Connection state: Provisioning (In Progress)"
  echo "👉 Next Step: Log into GCP Console and complete Step 5 (OAuth consent authorization popup)."
  echo "=================================================================="
else
  echo "❌ Error: Connection creation failed with HTTP status code ${HTTP_STATUS}"
  echo "Response details:"
  echo "${BODY}"
  exit 1
fi
