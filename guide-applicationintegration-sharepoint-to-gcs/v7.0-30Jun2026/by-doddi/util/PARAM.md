# Parameters Validation & Creation Guide

This guide details how to validate the integration parameters and provides step-by-step instructions on how to set up each resource in Google Cloud and SharePoint.

---

## 🔍 Section 1: Parameters Validator Utility (`validate_params.py`)

The validator script [validate_params.py](file:///usr/local/google/home/yourorg/Coding/DO-PRIYAMBODO/customer-maxis/do-applicationintegration/app/v2.0/util/validate_params.py) is a diagnostic tool designed to verify your configuration file `parameters.json` before deploying any Cloud Functions or Application Integration workflows.

### What it checks:
1. **Local Format Validation**:
   * Ensures that all expected keys exist in `parameters.json`.
   * Detects and warns about unconfigured placeholder values (e.g., values starting with `your-` or `yourorg`).
   * Validates parameter values against strict regular expressions (e.g., confirming project IDs contain valid characters, service accounts match email structures, M365 IDs are valid UUIDs, and connection paths follow the GCP Resource model).
2. **Live GCP Resource Existence Checks**:
   * Uses your active `gcloud` identity credentials to query Google Cloud live endpoints.
   * Confirms the existence of:
     * GCP Project ID
     * Scoped IAM Service Account
     * Cloud Storage (GCS) Bucket
     * Secret Manager secret version
     * Integration Connector SharePoint Connection status (must be `ACTIVE`)
     * Integration Connector GCS Connection status (must be `ACTIVE`)

### How to Run:
Run the script from the `util/` directory:
```bash
python3 validate_params.py
```
Outputs and exceptions are logged into the standard setup logs directory `log/setup.log` (with any failures mirrored to `log/error.log`).

---

## 🛠️ Section 2: Step-by-Step Creation Guide for Parameters

### 1. `CONFIG_ProjectId` (Google Cloud Project)
* **Goal**: The GCP Project hosting the synchronization infrastructure.
* **Creation Step**:

  #### Option 1: Using Google Cloud Console
  1. Open the [Google Cloud Console](https://console.cloud.google.com/).
  2. Click the project dropdown in the top bar and select **New Project**.
  3. Enter a Project Name. Note the generated **Project ID** (e.g., `work-mylab-machinelearning`).
  4. Ensure billing is enabled for this project.

  #### Option 2: Using Command Line Interface (CLI)
  Run the following `gcloud` command in your terminal:
  ```bash
  gcloud projects create "YOUR_PROJECT_ID" --name="YOUR_PROJECT_NAME"
  ```
  *Note: Make sure to link your billing account to the newly created project.*

### 2. `CONFIG_Location` (GCP Region)
* **Goal**: The region where your integrations, connections, and functions will be deployed.
* **Creation Step**:
  * Select a region that supports both **Application Integration** and **Integration Connectors**. Recommended: `asia-southeast1` (Singapore) or `us-central1` (Iowa).

### 3. `CONFIG_Service_Account` (IAM Service Account)
* **Goal**: The identity used to execute the Cloud Function and run the integrations with appropriate permissions.
* **Creation Step**:

  #### Option 1: Using Google Cloud Console
  1. Go to **IAM & Admin** > **Service Accounts** in the GCP Console.
  2. Click **Create Service Account**.
  3. Enter a name (e.g., `yourorg-sa-sharepoint-gcs`) and click **Create and Continue**.
  4. (Optional) Assign temporary roles or configure them later using `check_permissions.py` recommendations.
  5. Click **Done**.
  6. Copy the fully qualified email address: `yourorg-sa-sharepoint-gcs@<project-id>.iam.gserviceaccount.com`.

  #### Option 2: Using Command Line Interface (CLI)
  Run the following `gcloud` command in your terminal:
  ```bash
  gcloud iam service-accounts create "yourorg-sa-sharepoint-gcs" \
      --description="Identity used to execute the Cloud Function and run the integrations" \
      --display-name="yourorg-sa-sharepoint-gcs" \
      --project="<project-id>"
  ```
  The fully qualified service account email will be: `yourorg-sa-sharepoint-gcs@<project-id>.iam.gserviceaccount.com`.

### 4. `CONFIG_M365_Tenant_Id` & `CONFIG_M365_Client_Id` (Microsoft 365 Azure side)
* **Goal**: Authenticate the SharePoint reader client via Microsoft Graph API.
* **Creation Step**:
  1. Log into the [Microsoft Entra ID Admin Center](https://entra.microsoft.com/) or the Azure Portal.
  2. Under **Overview**, copy the **Tenant ID** (Directory ID).
  3. Go to **Identity** > **Applications** > **App registrations** > **New registration**.
  4. Name your application (e.g., `SharePoint GCS Sync Daemon`), select **Accounts in this organizational directory only**, and click **Register**.
  5. Copy the **Application (client) ID**.
  6. Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Application permissions**:
     * Add `Sites.Read.All` (or `Sites.ReadWrite.All`).
     * Click **Grant admin consent** for your tenant so the daemon app can read sites without user interaction.

### 5. `CONFIG_M365_Secret_Name` (Secret Manager client secret)
* **Goal**: Securely store the M365 client secret inside GCP.
* **Creation Step**:
  1. In the Azure App Registration for your app, navigate to **Certificates & secrets** > **Client secrets** > **New client secret**.
  2. Copy the secret **Value** (not Secret ID) immediately.
  
  #### Option 1: Using Google Cloud Console
  1. In GCP Console, go to **Security** > **Secret Manager**.
  2. Click **Create Secret**. Name it (e.g., `yourorg-secret-sharepoint-clientsecret`).
  3. Paste the Azure Client Secret value as the secret value and click **Create**.
  4. Copy the resource ID path of version 1:
     `projects/<project-number>/secrets/yourorg-secret-sharepoint-clientsecret/versions/1`

  #### Option 2: Using Command Line Interface (CLI)
  Run the following `gcloud` commands in your terminal:
  ```bash
  # 1. Create the Secret Manager container
  gcloud secrets create "yourorg-secret-sharepoint-clientsecret" \
      --replication-policy="automatic" \
      --project="<project-id>"

  # 2. Add the M365 client secret value as version 1
  echo -n "YOUR_AZURE_CLIENT_SECRET_VALUE" | gcloud secrets versions add "yourorg-secret-sharepoint-clientsecret" \
      --data-file=- \
      --project="<project-id>"
  ```
  The secret resource path will be: `projects/<project-number>/secrets/yourorg-secret-sharepoint-clientsecret/versions/1`.

### 6. `CONFIG_GCS_Bucket` (Target Storage Bucket)
* **Goal**: GCS bucket where files and pre-rendered site pages are synchronized.
* **Creation Step**:

  #### Option 1: Using Google Cloud Console
  1. Go to **Cloud Storage** > **Buckets** in GCP Console.
  2. Click **Create**.
  3. Set a globally unique name (e.g., `yourorg-bucket-sharepoint-sync`).
  4. Select your region (matching `CONFIG_Location`) and choose **Standard** storage class.
  5. Click **Create**.

  #### Option 2: Using Command Line Interface (CLI)
  Run the following `gcloud` command in your terminal:
  ```bash
  gcloud storage buckets create gs://yourorg-bucket-sharepoint-sync \
      --location="<location>" \
      --project="<project-id>"
  ```

### 7. `CONFIG_GCS_Connection` (Integration GCS Connection)
* **Goal**: Connect Application Integration to GCS.
* **Creation Step**:
  1. Go to **Application Integration** > **Connectors** in the GCP Console.
  2. Click **Create New**.
  3. **Connector**: Google Cloud Storage.
  4. **Connection Name**: `yourorg-connection-gcs-sync`.
  5. **Location**: Same as `CONFIG_Location`.
  6. **Authentication**: Choose **Service Account** (binds to the default connectors service agent).
  7. Click **Create** and wait for status to become `ACTIVE`.
  8. Path: `projects/<project-id>/locations/<location>/connections/yourorg-connection-gcs-sync`.

### 8. `CONFIG_SharePoint_Connection` (Integration SharePoint Connection)
* **Goal**: Connect Application Integration to SharePoint.
* **Creation Step**:
  1. Go to **Application Integration** > **Connectors** in the GCP Console.
  2. Click **Create New**.
  3. **Connector**: SharePoint.
  4. **Connection Name**: `yourorg-connection-sharepoint-sync`.
  5. **Location**: Same as `CONFIG_Location`.
  6. **Tenant ID**: Paste `CONFIG_M365_Tenant_Id`.
  7. **Client ID**: Paste `CONFIG_M365_Client_Id`.
  8. **Client Secret**: Select your Secret Manager secret name.
  9. Click **Create** and wait for status to become `ACTIVE`.
  10. Path: `projects/<project-id>/locations/<location>/connections/yourorg-connection-sharepoint-sync`.

### 9. `CONFIG_SharePoint_Hostname`, `CONFIG_Sharepoint_Sites` & `CONFIG_Sharepoint_Library`
* **Goal**: SharePoint domain, subsite target, and document library name.
* **Creation Step**:
  1. Open your SharePoint Online site.
  2. Hostname is the main domain (e.g., `yourorg.sharepoint.com`).
  3. Subsite path is the subsite folder name (e.g., `sites/yourorg-sharepoint-to-gcs`). Create this subsite inside your SharePoint Admin dashboard if it does not exist yet.
  4. `CONFIG_Sharepoint_Library` is the Microsoft Graph API Drive name for the target document library (typically `"Documents"` for the default library shown as "Shared Documents" in the Web UI).

### 10. `CONFIG_CloudFunction_Name`
* **Goal**: Name of the deployed traversal Cloud Function.
* **Creation Step**:
  * Set this string parameter (e.g., `yourorg-sharepoint-list-files`). Running `./deploy_cf.sh` will deploy it.

### 11. `CONFIG_Parent_Integration_Name` & `CONFIG_Child_Integration_Name`
* **Goal**: Names of the deployed Application Integration workflows.
* **Creation Step**:
  * Set these strings (e.g., `yourorg-sharepoint-gcs-parent` and `yourorg-sharepoint-gcs-child`). Running `deploy_workflows.py` will deploy and link them.
