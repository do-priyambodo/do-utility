#!/bin/bash
# ==============================================================================
# CLI Commands to Create and Configure Custom Service Account & Developer Permissions
# ==============================================================================

# Ensure parameters.json exists
if [ ! -f "parameters.json" ]; then
  # Try to find it in parent directory if run from prereq/
  if [ -f "../parameters.json" ]; then
    cd ..
  else
    echo "❌ Error: parameters.json not found! Please run from the directory containing parameters.json"
    exit 1
  fi
fi

# Load variables dynamically from parameters.json
export PROJECT_ID=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_ProjectId', ''))")
export LOCATION=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Location', ''))")
export SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Service_Account', ''))")
export FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_CloudFunction_Name', ''))")
export BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")
export DEV_USER=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_Developer_Group_Or_User', ''))")

# Extract SA name/ID from the email (e.g. name@project.iam.gserviceaccount.com -> name)
export SA_NAME=$(echo "$SERVICE_ACCOUNT" | cut -d'@' -f1)

# Extract Secret Name from M365 secret version resource ID
# (e.g., projects/123/secrets/secret-name/versions/1 -> secret-name)
export SECRET_PATH=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_M365_Secret_Name', ''))")
export SECRET_NAME=$(echo "$SECRET_PATH" | cut -d'/' -f4)

# Resolve GCP Project Number
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

# Helper to format member prefix (user: or group:)
format_member() {
  local member="$1"
  if [[ "$member" == "user:"* || "$member" == "group:"* || "$member" == "serviceAccount:"* ]]; then
    echo "$member"
  elif [[ "$member" == *"group"* || "$member" == *"ggrp"* ]]; then
    echo "group:$member"
  else
    echo "user:$member"
  fi
}

export DEV_MEMBER=$(format_member "$DEV_USER")

echo "=================================================="
echo "RESOLVED CONFIGURATION DETAILS"
echo "=================================================="
echo "Project ID:          $PROJECT_ID"
echo "Project Number:      $PROJECT_NUMBER"
echo "Location:            $LOCATION"
echo "SA Name:             $SA_NAME"
echo "SA Email:            $SERVICE_ACCOUNT"
echo "Bucket Name:         $BUCKET_NAME"
echo "Secret Name:         $SECRET_NAME"
echo "Function Name:       $FUNCTION_NAME"
echo "Developer Member:    $DEV_MEMBER"
echo "=================================================="
echo ""

# ------------------------------------------------------------------------------
# Part 1: Service Account Setup (Runtime Permissions)
# ------------------------------------------------------------------------------
echo "🤖 [Part 1/2] Setting up Custom Service Account & Runtime Roles..."

# 1. Create the Custom Service Account
echo "👉 Creating service account: $SA_NAME..."
gcloud iam service-accounts create "$SA_NAME" \
    --description="Identity used to execute the Cloud Function and run the integrations" \
    --display-name="$SA_NAME" \
    --project="$PROJECT_ID" || echo "⚠️ Service account might already exist, proceeding..."

# 2. Project-Level Role Bindings
echo "👉 Granting logging.logWriter role to Custom SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/logging.logWriter" \
    --condition=None

echo "👉 Granting integrations.integrationInvoker role to Custom SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/integrations.integrationInvoker" \
    --condition=None

echo "👉 Granting storage.admin role to Custom SA (required for GCS Connector)..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.admin" \
    --condition=None

echo "👉 Granting connectors.viewer role to Custom SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/connectors.viewer" \
    --condition=None

echo "👉 Granting connectors.invoker role to Custom SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/connectors.invoker" \
    --condition=None

# 3. Resource-Level / Scoped Role Bindings
echo "👉 Granting secretmanager.secretAccessor role on secret '$SECRET_NAME' to Custom SA..."
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID"

echo "👉 Granting secretmanager.viewer role on secret '$SECRET_NAME' to Custom SA..."
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.viewer" \
    --project="$PROJECT_ID"

echo "👉 Granting storage.objectAdmin role on bucket 'gs://$BUCKET_NAME' to Custom SA..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectAdmin"

echo "👉 Granting run.invoker role on Cloud Run service '$FUNCTION_NAME' to Custom SA..."
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --region="$LOCATION" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --project="$PROJECT_ID"

# 4. Service Agent Impersonation Bindings (Allow GCP service agents to act as the Custom SA)
echo "👉 Authorizing Connectors Service Agent to impersonate Custom SA..."
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-connectors.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser" \
    --project="$PROJECT_ID"

echo "👉 Authorizing Cloud Scheduler Service Agent to impersonate Custom SA..."
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser" \
    --project="$PROJECT_ID"

# ------------------------------------------------------------------------------
# Part 2: Developer/SSO Account Setup (Deployment Permissions)
# ------------------------------------------------------------------------------
if [ -n "$DEV_USER" ]; then
  echo ""
  echo "👤 [Part 2/2] Configuring Setup/Deployment Roles for Developer: $DEV_MEMBER..."
  
  # A. Project-Level Setup Roles
  echo "👉 Granting cloudfunctions.developer role to $DEV_MEMBER..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$DEV_MEMBER" \
      --role="roles/cloudfunctions.developer" \
      --condition=None

  echo "👉 Granting run.admin role to $DEV_MEMBER..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$DEV_MEMBER" \
      --role="roles/run.admin" \
      --condition=None

  echo "👉 Granting integrations.integrationAdmin role to $DEV_MEMBER..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$DEV_MEMBER" \
      --role="roles/integrations.integrationAdmin" \
      --condition=None

  echo "👉 Granting connectors.admin role to $DEV_MEMBER..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$DEV_MEMBER" \
      --role="roles/connectors.admin" \
      --condition=None

  # B. Scoped Secret Admin (required to manage/update the SharePoint client credentials secret)
  echo "👉 Granting secretmanager.admin role on secret '$SECRET_NAME' to $DEV_MEMBER..."
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
      --member="$DEV_MEMBER" \
      --role="roles/secretmanager.admin" \
      --project="$PROJECT_ID"

  # C. Scoped Service Account User (required to deploy Cloud Functions/Workflows running as the Custom SA)
  echo "👉 Granting iam.serviceAccountUser role on Custom SA to $DEV_MEMBER..."
  gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
      --member="$DEV_MEMBER" \
      --role="roles/iam.serviceAccountUser" \
      --project="$PROJECT_ID"
else
  echo ""
  echo "⏭️ [Part 2/2] Skipping Developer Setup Roles configuration (CONFIG_Developer_Group_Or_User is empty in parameters.json)."
fi

echo ""
echo "🎉 Setup Completed Successfully!"
