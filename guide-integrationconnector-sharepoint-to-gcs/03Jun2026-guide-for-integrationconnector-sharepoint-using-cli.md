# Handbook: Deploying SharePoint Integration Connector via CLI & Direct REST API
*A comprehensive walkthrough for provisioning secure SharePoint-to-GCS integration connections under restricted IAM conditions.*

---

## Overview & Design Philosophy
In standard enterprise environments, developer accounts do not hold broad administrative permissions (such as `roles/resourcemanager.projectIamAdmin` or `roles/owner`). 

If a developer tries to deploy an Integration Connector using the GCP Console UI wizard under these conditions, the wizard will fail. This is because the Console wizard automatically attempts to bind project-level IAM permissions for Secret Manager dynamically during creation.

### The Solution
To bypass the Console's UI permission restrictions, the deployment is split into two distinct parts:
1. **Backend Provisioning & IAM Bindings:** Completed once by a GCP Project Administrator (or automated CI/CD pipeline) with sufficient IAM powers.
2. **Direct Connection Deployment via REST API:** Executed directly by the developer using standard credentials. This calls the Google Connectors REST API to bypass the Console UI's auto-binding logic entirely.
3. **One-Time Interactive OAuth Consent:** Completed once via a browser popup in the GCP console to authorize the connection.

---

## I. PRE-REQUIREMENTS CHECK

Before executing any provisioning steps, you must verify that all Microsoft Entra ID parameters are populated and that the initial Google Cloud resource boundaries are correct.

### 1. Microsoft Entra ID App Registration Parameters
Register a new **Web** application in your Microsoft Entra ID tenant and configure the Redirect URI:

*   **Redirect URI**: `https://console.cloud.google.com/connectors/oauth`
*   **Reference Sandbox Values (Working Simulation)**:
    *   **Tenant ID**: `YOUR_MICROSOFT_TENANT_ID`
    *   **Client ID**: `YOUR_MICROSOFT_CLIENT_ID`
    *   **SharePoint Subsite URL**: `https://your-tenant.sharepoint.com/sites/your-sharepoint-subsite-name`

### 2. Required Microsoft Graph API Scopes
You **must grant both Delegated and Application permissions** for the following scopes, and click **"Grant admin consent for [Tenant Name]"** in the Microsoft Entra ID portal:

| Target Resource | Required API Scope | Permission Type | Justification / Purpose |
| :--- | :--- | :--- | :--- |
| **Microsoft Graph** | **`Sites.Read.All`** | **Delegated & Application** | **Critical**. Allows traversing SharePoint site collections, folders, subfolders, and listing modern site canvas pages. |
| **Microsoft Graph** | **`Files.Read.All`** | **Delegated & Application** | **Critical**. Allows downloading document binary contents (PDFs, WebPs, log files) securely. |
| **Microsoft Graph** | **`User.Read.All`** | **Delegated & Application** | **Critical**. Resolves file owners, editors, and metadata creator profiles. Without this scope, the connector fails during metadata resolution queries. |
| **Microsoft Graph** | `User.Read` *(Default)* | Delegated | Added by default for base profile login authentication. |

> [!IMPORTANT]
> **Why are both Delegated and Application permissions required?**
> GCP's first-time integration connection setup requires browser-interactive OAuth authentication (which triggers a user login popup using **Delegated** scopes). Scheduled background synchronization runs headless (without user interaction) which relies on **Application** scopes. Both must be admin-consented.

### 3. Diagnostic Pre-flight Verification Commands (GCP CLI)
Run these diagnostic checks in your terminal to ensure the environment is fully prepared:

*   **Check Required APIs Status**:
    ```bash
    gcloud services list --enabled \
        --filter="config.name:(connectors.googleapis.com OR integrations.googleapis.com OR secretmanager.googleapis.com OR storage.googleapis.com)" \
        --format="table(config.title, config.name)"
    ```
*   **Verify Secret Manager Key Presence**:
    ```bash
    gcloud secrets list --filter="name:your-secret-sharepoint-clientsecret"
    ```
*   **Verify IAM Secret Accessor Binding**:
    ```bash
    gcloud secrets get-iam-policy your-secret-sharepoint-clientsecret \
        --format="table(bindings.role, bindings.members)"
    ```
    *👉 Expected Output: You must see `serviceAccount:your-custom-service-account@your-gcp-project-id.iam.gserviceaccount.com` bound to `roles/secretmanager.secretAccessor`.*
*   **Verify Service Account Impersonation Binding**:
    ```bash
    gcloud iam service-accounts get-iam-policy your-custom-service-account@your-gcp-project-id.iam.gserviceaccount.com \
        --format="table(bindings.role, bindings.members)"
    ```
    *👉 Expected Output: You must see `serviceAccount:service-[PROJECT_NUMBER]@gcp-sa-connectors.iam.gserviceaccount.com` associated with `roles/iam.serviceAccountUser`.*

---

## II. EXECUTION

Follow these step-by-step instructions to provision the backend components and deploy the connection.

### Step 1: Define Environment Variables
Configure your terminal session using the working simulation settings:
```bash
export PROJECT_ID="your-gcp-project-id"
export LOCATION="asia-southeast1"
export BUCKET_NAME="your-gcs-sync-bucket-name"
export SERVICE_ACCOUNT_NAME="your-custom-service-account"
export SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export SECRET_NAME="your-secret-sharepoint-clientsecret"
export CONNECTION_NAME="your-sharepoint-connection"

# Microsoft Credentials
export TENANT_ID="YOUR_MICROSOFT_TENANT_ID"
export CLIENT_ID="YOUR_MICROSOFT_CLIENT_ID"
export SHAREPOINT_SITE_URL="https://your-tenant.sharepoint.com/sites/your-sharepoint-subsite-name"
```

### Step 2: Create Core Infrastructure Resources
```bash
# 1. Create GCS bucket
gcloud storage buckets create gs://${BUCKET_NAME} --location=${LOCATION}

# 2. Create the Secret Manager secret
gcloud secrets create ${SECRET_NAME} --replication-policy="automatic"

# 3. Inject your Microsoft App Client Secret as version 1
echo -n "YOUR_MICROSOFT_CLIENT_SECRET_HERE" | gcloud secrets versions add ${SECRET_NAME} --data-file=-
```

### Step 3: Bind Least-Privilege IAM Policies
Apply the exact role permissions required for secure serverless operation:
```bash
# 1. GCS Storage Object Admin (least-privilege read/write on bucket objects)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/storage.objectAdmin"

# 2. Secret Manager Viewer role
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/secretmanager.viewer"

# 3. Secret Manager Secret Accessor role (restricted to this specific secret only)
gcloud secrets add-iam-policy-binding ${SECRET_NAME} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

# 4. Connector Invoker & Viewer roles
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/connectors.invoker"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/connectors.viewer"

# 5. Application Integration Runner & Invoker roles
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/integrations.integrationRunner"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/integrations.integrationInvoker"
```

### Step 4: Authorize Connectors Service Agent (System Impersonation)
```bash
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT_EMAIL} \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-connectors.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser"
```

### Step 5: Deploy Connection Resource via REST API Script
Navigate to the folder and execute the direct REST creation script we prepared:
```bash
./create_sharepoint_connection.sh
```
*👉 Note: This script targets the Google Cloud Connectors REST API directly, completely bypassing the Console UI's dynamic project-level IAM-binding checks.*

### Step 6: Complete One-Time Interactive OAuth Consent
1. Log into the GCP Console and navigate to **Integration Connectors** > **Connections**.
2. Select `your-sharepoint-connection`.
3. You will see a banner displaying `Connection requires authorization`. Click the **"Authorize"** button.
4. Log in using your Microsoft Entra ID credentials in the interactive popup to consent to the scopes.
5. The connection state will instantly transition to **`🟢 Active`**.

---

## III. TEST

To confirm the connection and entire synchronization pipeline are fully active:

### 1. Standalone Connection Status Check
Run this CLI command to verify the connection state:
```bash
gcloud connectors connections describe ${CONNECTION_NAME} \
    --location=${LOCATION} \
    --format="value(connectionStatus.state)"
```
*👉 Expected Output: `ACTIVE`*

### 2. End-to-End Sync Test Execution
Create a new test file inside the SharePoint subsite directory (`/sites/your-sharepoint-subsite-name/Shared Documents`). Then, run the sync pipeline from the terminal:
```bash
python3 sync_sharepoint_to_gcs.py
```
Verify the console output returns `🎉 SYNC JOB SUBMITTED SUCCESSFULLY`. Finally, list your GCS bucket objects to ensure the new file has synced with perfect byte integrity:
```bash
gcloud storage objects list gs://${BUCKET_NAME}/**
```

---

## IV. TROUBLESHOOTING & FAQS

### 1. Real-Time CLI Troubleshooting Commands

If you encounter connection failures or sync issues, run these specific `gcloud logging read` commands:

*   **Check Connection Lifecycle & Deployment Errors**:
    ```bash
    gcloud logging read 'resource.type="connectors.googleapis.com/Connection" AND severity>=INFO' \
        --project="${PROJECT_ID}" --limit=10 --format="table(timestamp, severity, jsonPayload.message)"
    ```
*   **Monitor OAuth Token Exchange & Refresh Failures**:
    ```bash
    gcloud logging read 'resource.type="connectors.googleapis.com/Connection" AND (jsonPayload.status.code!=0 OR "auth" OR "token")' \
        --project="${PROJECT_ID}" --limit=10 --format="json(timestamp, jsonPayload.status, jsonPayload.message)"
    ```
*   **Identify Secret Access Denied Errors**:
    ```bash
    gcloud logging read 'protoPayload.serviceName="secretmanager.googleapis.com" AND protoPayload.status.code!=0' \
        --project="${PROJECT_ID}" --limit=5 --format="table(timestamp, protoPayload.authenticationInfo.principalEmail, protoPayload.status.message)"
    ```

---

### 2. Frequently Asked Questions

#### **Q1: Why does the GCP Console display a warning asking me to "Please grant Cloud IAM role(s) 'roles/secretmanager.viewer, roles/secretmanager.secretAccessor'" when I edit the connection?**
*   **Answer**: This is a **false-positive client-side UI warning** and can be safely ignored.
*   **Cause**: Because your developer account is restricted and lacks project-level IAM administrative rights (`resourcemanager.projects.getIamPolicy`), the Google Cloud Console frontend in your browser is **forbidden** from viewing the project's active IAM permissions. Since the UI is "blind" to whether the roles are present or not, it displays a warning banner to play it safe.
*   **Verification**: As long as the permissions were successfully bound on the backend (as verified via `gcloud secrets get-iam-policy ${SECRET_NAME}`), the backend runtime will access the secret flawlessly and run your sync tasks without issues.

#### **Q2: What if our security policies prevent developers from receiving the `roles/connectors.connectionAdmin` role required for the Step-6 browser authorization?**
If corporate security refuses to grant even this focused, non-sensitive developer role to the engineer, you can utilize **Admin-Led One-Time Activation**:
1. The developer carries out all CLI deployment up to Step 5 using standard credentials.
2. A Project Administrator (e.g., Cloud Administrator) who already has broad administrative roles logs into the GCP Console once.
3. The administrator clicks the **"Authorize"** button, logs in via the Microsoft popup, and transitions the connection to **`🟢 Active`**.
4. Once authorized, the developer can instantly use the connection in their integration pipelines without needing any special connector roles.
