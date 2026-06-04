# Security & IAM Permissions Architecture Handoff Guide
*An enterprise-grade security blueprint detailing all GCP IAM Roles, Azure AD App Registration API Scopes, and SharePoint Directory permissions required to run, deploy, and maintain the hybrid SharePoint-to-GCS synchronization pipeline.*

---

## 1. Core Execution Identity (GCP Service Account)

To implement strict **least-privilege access**, a single custom Google Cloud Service Account must be created to act as the execution principal across all serverless runtime components.

*   **Recommended Name**: `your-custom-service-account@<your-gcp-project-id>.iam.gserviceaccount.com`
*   **Justification**: This service account provides a single, auditable security boundary that binds the Cloud Scheduler, Cloud Function runtime, and Integration Connector executions together, eliminating the need for multiple keys or administrative permissions.

---

## 2. GCP Permission Matrix (Service Account Roles)

The table below lists every specific role that must be bound to the execution service account (`your-custom-service-account@...`) inside the Google Cloud Console.

| GCP Component | Role Required | Target Resource / Scope | Justification |
| :--- | :--- | :--- | :--- |
| **Cloud Function Runtime** | `Secret Manager Secret Accessor`<br>(`roles/secretmanager.secretAccessor`) | Specific Secret:<br>`projects/<project-id>/secrets/your-secret-sharepoint-clientsecret` | Allows the Cloud Function to securely retrieve the Microsoft Azure Client Secret at runtime without hardcoding credentials. |
| **Cloud Function Runtime** | `Application Integration Runner`<br>(`roles/integrations.integrationRunner`) | Project-Level or specific integration | Allows the Cloud Function to authenticate and securely trigger the parent integration `:execute` API endpoint. |
| **Cloud Scheduler** | `Cloud Run Invoker`<br>(`roles/run.invoker`) | Cloud Run Service:<br>`your-sharepoint-list-files` | Essential for Gen2 Cloud Functions. Allows Cloud Scheduler to securely invoke the HTTP endpoint using a signed Google OIDC token. |
| **Cloud Scheduler** | `Cloud Functions Invoker`<br>(`roles/cloudfunctions.invoker`) | Cloud Function:<br>`your-sharepoint-list-files` | Connects Scheduler authorization directly to the Cloud Function invocation interface. |
| **GCS Connection** | `Storage Object Creator` / `Storage Object Admin`<br>(`roles/storage.objectAdmin`) | Target GCS Bucket:<br>`gs://your-gcs-sync-bucket-name` | Allows the GCS connector task inside the integration flow to upload standard files and pre-rendered HTML pages. |

---

## 3. Google Application Integration System Agent Permissions

The GCP Application Integration engine uses an automated **Service Agent** to perform background resource calls (such as invoking the traversal Cloud Function).

*   **Service Agent Principal**: `service-<your-gcp-project-number>@gcp-sa-integrations.iam.gserviceaccount.com`
*   **Roles Required**:
    *   **`Cloud Run Invoker` (`roles/run.invoker`)** on the `your-sharepoint-list-files` Cloud Run revision.
    *   **`Cloud Functions Invoker` (`roles/cloudfunctions.invoker`)** on the Cloud Function.
*   **Justification**: Allows the integration flow engine's background loop thread to safely and securely call out to the traversal Cloud Function.

---

## 4. Microsoft Azure AD App Registration & SharePoint Permissions

To enable safe Graph API queries, an **App Registration** must be created in the customer's Microsoft Entra ID (Azure AD) tenant.

### A. Azure AD App Credentials
*   **App ID / Client ID**: A unique GUID representing the sync pipeline client.
*   **Client Secret**: Generated inside the App Registration and saved securely inside the **GCP Secret Manager** (referenced in Section 2).

### B. Microsoft Graph API Scopes
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

### C. SharePoint Subsite Directory Scoping (Restricted Alternative)
In highly restricted corporate environments (like your company), administrators may refuse to grant tenant-wide `Sites.Read.All` or `Files.Read.All` application scopes, as they permit reading *all* corporate site collections:

1. **`Sites.Selected` (Application Role)**: Request the SharePoint Administrator to grant the `Sites.Selected` (Application) permission to your registered App instead of tenant-wide read scopes.
2. **Administrator Site Binding (PowerShell or Graph API)**: The SharePoint Administrator must then explicitly run a PowerShell PnP command or make a Graph API `POST` request to assign the **`Read`** role to your App's `CLIENT_ID` specifically for the target subsite collection `/sites/your-sharepoint-subsite-name`.
3. **Result**: Without this explicit subsite-level assignment, Microsoft will block all sync worker attempts to access or download files with a `403 Forbidden` error.


---

## 5. GCP Secret Manager Setup

To secure the connection between Google Cloud and Microsoft Azure:
*   **Secret Name**: `your-secret-sharepoint-clientsecret`
*   **Content**: The plaintext Azure AD App client secret.
*   **Justification**: Prevents accidental exposure of M365 keys in code repository histories, deployment configurations, or execution logs.

---

## 6. Developer/Deployment Permissions (For Admin Deploying)

The GCP Administrator or Devops Engineer who is executing the setup scripts (`deploy_cf.sh` and `deploy_v4_workflows.py`) needs the following administrative permissions on their own GCP user principal:

*   `roles/cloudfunctions.developer` (To compile and deploy Cloud Functions)
*   `roles/run.admin` (To manage Gen2 Cloud Run backing resources)
*   `roles/integrations.integrationAdmin` (To import, configure, and publish Parent/Child integration workflows)
*   `roles/iam.serviceAccountUser` (To bind the execution service account to the Cloud Function and Cloud Run instances)
*   `roles/secretmanager.admin` (To configure the Azure AD Client Secret resource)

---

> [!IMPORTANT]
> **Enterprise Security Summary**: This hybrid serverless sync architecture is 100% locked-down. It relies on standard Google OIDC service-account authentication at all HTTP endpoints, stores Microsoft Graph secrets securely inside Secret Manager, and accesses GCS using IAM rather than permanent access keys.
